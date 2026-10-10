"""`docs audit`: measurable correctness, coverage, freshness and consistency of a generated documentation set against its knowledge model (and the repository, when given).
Measurements are reported separately and never combined into one 'quality score'. Each GATE is PASS, FAIL or NOT_TESTED, with the reason."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from yuktiforge.docint import safety as S
from yuktiforge.docint.audit import states as ST
from yuktiforge.docint.docgen import registry
from yuktiforge.docint.docgen import validate as DV
from yuktiforge.docint.docgen.doc import Claim, Document, Table
from yuktiforge.docint.knowledge import ids
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import KnowledgeModel
from yuktiforge.docint.knowledge.validate import check_evidence_against_repo

ROUTE = re.compile(r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|ANY)\s+(\S+)$")
TICKS = re.compile(r"`([^`\n]+)`")
MODAL = re.compile(r"\b(shall|must|is required to|are required to|will be required|needs? to be implemented)\b", re.I)
ABS_PATH = re.compile(r"(?<![\w.])(/Users/|/home/[a-z]|/private/var/|/var/folders/|[A-Z]:\\Users\\)")
SCOPE_TYPES = ("component", "api", "database_entity", "event", "module")


def items(doc: Document):
    for s in doc.sections:
        for b in s.blocks:
            if isinstance(b, Claim):
                yield s.id, b.id, b.text, b.labels, b.evidence_ids, b.entity_ids, b
            elif isinstance(b, Table):
                for r in b.rows:
                    yield s.id, r.id, " | ".join(r.cells), r.labels, r.evidence_ids, r.entity_ids, r


class Names:
    """Every name the model knows, in the forms a document may legitimately quote them."""

    def __init__(self, m: KnowledgeModel):
        self.routes: set[tuple[str, str]] = set()
        self.all: set[str] = set()
        for e in m.entities:
            self.all.add(e.name.lower())
            mm = ROUTE.match(e.name)
            if mm:
                self.routes.add((mm.group(1), ids.norm_route(mm.group(2)) if mm.group(2).startswith("/") else mm.group(2)))
            for k in ("path", "url", "root", "defined_in"):
                v = e.attrs.get(k)
                if isinstance(v, str):
                    self.all.add(v.lower())
            if e.type == "field":
                self.all.add(e.name.split(".", 1)[-1].lower())
            self.all.add(e.name.rsplit(".", 1)[-1].lower())
            for part in re.split(r"[./]", e.name):
                if len(part) > 2:
                    self.all.add(part.lower())
        for e in m.evidence:
            if e.path:
                self.all.add(e.path.lower())
        self.paths = {e.path.lower() for e in m.evidence if e.path}

    def known(self, token: str) -> bool:
        t = token.strip()
        mm = ROUTE.match(t)
        if mm:
            path = mm.group(2)
            key = (mm.group(1), ids.norm_route(path) if path.startswith("/") else path)
            return key in self.routes or (mm.group(1) == "HTTP" and any(r[1] == key[1] for r in self.routes))
        low = t.lower()
        return low in self.all or any(low.endswith(a) or a.endswith(low) for a in self.all if len(a) > 6 and len(low) > 6)


GENERIC = {"repo", "true", "false", "none", "null", "unknown", "verified", "inferred", "user_supplied", "needs_stakeholder_validation", "docs model assert", "page"}


def unsupported_identifiers(doc: Document, names: Names) -> list[dict[str, str]]:
    out = []
    for sid, iid, text, labels, _, _, _ in items(doc):
        for tok in TICKS.findall(text):
            t = tok.strip()
            if not t or t.lower() in GENERIC or len(t) < 3 or " " in t and not ROUTE.match(t):
                continue
            if t.startswith(("[", "docs ", "yuktiforge", "doc:", "type ", "--")) or re.match(r"^(api|module|symbol|component|event|database_entity|technology|deployment_boundary|interface|field|rel|ev|conflict|gap|requirement_candidate)[:-]", t):
                continue
            if not names.known(t):
                out.append({"document": doc.doc_type, "section": sid, "statement": iid, "identifier": t[:80]})
    return out


def fabricated_requirements(doc: Document, model: KnowledgeModel) -> list[dict[str, str]]:
    ents = {e.id: e for e in model.entities}
    evs = {e.id: e for e in model.evidence}
    out = []
    for sid, iid, text, labels, _, entity_ids, _ in items(doc):
        cited = [ents[i] for i in entity_ids if i in ents]
        user_backed = any(e.cls == "user-supplied" or any(evs[x].cls == "user-supplied" for x in e.evidence_ids if x in evs) for e in cited)
        for e in cited:
            if e.type in ("requirement_candidate", "business_rule_candidate") and not user_backed:
                out.append({"document": doc.doc_type, "section": sid, "statement": iid, "reason": f"{e.type} '{e.name}' is not backed by a user-supplied statement"})
        if MODAL.search(text) and not text.rstrip().endswith("?") and not ("USER_SUPPLIED" in labels and user_backed) and not _explains_modal(text):
            out.append({"document": doc.doc_type, "section": sid, "statement": iid, "reason": "obligation language ('shall', 'must') that no person supplied"})
        if "USER_SUPPLIED" in labels and not user_backed:
            out.append({"document": doc.doc_type, "section": sid, "statement": iid, "reason": "labelled USER_SUPPLIED but cites no user-supplied entity"})
    return out


def _explains_modal(text: str) -> bool:
    """Generated boilerplate that mentions modality while saying there is none (for example 'requirement ids are not approved requirements')."""
    t = text.lower()
    return any(p in t for p in ("not approved", "needs a data owner", "must be confirmed", "stakeholder must", "needs people", "must confirm", "need review", "confirm or reject", "must answer"))


def privacy(doc: Document, text_blobs: list[str]) -> list[dict[str, str]]:
    out = []
    for blob in text_blobs:
        if S.scrub_text(blob) != blob:
            out.append({"document": doc.doc_type, "issue": "text matches a credential pattern"})
        if ABS_PATH.search(blob):
            out.append({"document": doc.doc_type, "issue": "absolute local path"})
    return out


def doc_blobs(doc: Document) -> list[str]:
    return [t for _, _, t, _, _, _, _ in items(doc)] + list(doc.banner)


# ----------------------------------------------------------------------------- cross-document consistency
def consistency(docs: list[Document], model: KnowledgeModel, glossary: dict) -> list[dict[str, Any]]:
    g = Graph(model)
    ents = g.ent
    find: list[dict[str, Any]] = []

    def add(check: str, severity: str, detail: str, documents: list[str]) -> None:
        find.append({"check": check, "severity": severity, "detail": detail, "documents": sorted(set(documents))})

    scans = {d.scan_id for d in docs}
    if scans != {model.scan_id}:
        add("snapshot", "warning", f"documents carry scan id(s) {sorted(scans)} while the model is {model.scan_id}: current only if the document-vs-model check below finds no drift", [d.doc_type for d in docs])
    for d in docs:
        for sid, iid, text, labels, evs, cited, _ in items(d):
            for i in cited:
                if i not in ents:
                    add("dangling-entity", "error", f"{d.doc_type}/{sid}: cites entity {i} which is not in the model", [d.doc_type])
                elif ents[i].status == "retired":
                    add("retired-entity", "error", f"{d.doc_type}/{sid}: describes '{ents[i].name}', which the current model has retired", [d.doc_type])
    # document-vs-model: regenerate each document from the model; a section whose input facts differ is out of date (renamed, changed, removed or added things all show up here)
    from yuktiforge.docint.docgen import engine
    for d in docs:
        try:
            fresh = engine.generate(d.doc_type, model, audience=d.audience, depth=d.depth, scope=d.scope)
        except Exception as e:                                                         # a document type that is no longer registered, or a scope that no longer exists
            add("regeneration", "error", f"{d.doc_type} cannot be regenerated from the model ({type(e).__name__})", [d.doc_type])
            continue
        old = {s.id: s.input_hash for s in d.sections}
        new = {s.id: s.input_hash for s in fresh.sections}
        for sid in sorted(set(old) | set(new)):
            if sid not in new:
                add("document-vs-model", "error", f"{d.doc_type}/{sid}: the section no longer exists in a fresh generation", [d.doc_type])
            elif sid not in old:
                add("document-vs-model", "error", f"{d.doc_type}/{sid}: a fresh generation has a section the document lacks", [d.doc_type])
            elif old[sid] != new[sid]:
                add("document-vs-model", "error", f"{d.doc_type}/{sid}: the facts this section was built from have changed; regenerate it", [d.doc_type])
    active = lambda t: {e.name for e in model.entities if e.type == t and e.status == "active"}
    # technology stack: facts keyed lang|X
    for d in docs:
        for s in d.sections:
            for b in s.blocks:
                if isinstance(b, Claim) and b.fact_key and b.fact_key.startswith("lang|"):
                    lang = b.fact_key.split("|", 1)[1]
                    truth = sum(1 for e in model.entities if e.type == "module" and e.attrs.get("language") == lang)
                    if str(truth) != b.fact_value:
                        add("technology-stack", "error", f"{d.doc_type} says {b.fact_value} {lang} module(s), the model has {truth}", [d.doc_type])
    # endpoints: the catalog lists exactly the model's implemented APIs; every document's endpoints exist
    api_names = {e.name for e in model.entities if e.type == "api" and not e.external and e.subtype in ("route", "grpc", "graphql") and e.status == "active"}
    for d in docs:
        mentioned = {ents[i].name for _, _, _, _, _, cited, _ in items(d) for i in cited if i in ents and ents[i].type == "api" and not ents[i].external and ents[i].subtype in ("route", "grpc", "graphql")}
        for n in sorted(mentioned - api_names):
            add("endpoint", "error", f"{d.doc_type} documents endpoint '{n}' which is not an implemented API in the model", [d.doc_type])
        if d.doc_type == "api-catalog":
            listed = {ents[i].name for s, _, _, _, _, cited, _ in items(d) if s == "inbound" for i in cited if i in ents and ents[i].type == "api"}
            for n in sorted(api_names - listed):
                add("endpoint", "warning", f"the API catalog omits implemented endpoint '{n}'", ["api-catalog"])
    # data entities
    tables = active("database_entity")
    for d in docs:
        if d.doc_type in ("data-dictionary", "database-doc"):
            listed = {ents[i].name for _, _, _, _, _, cited, _ in items(d) for i in cited if i in ents and ents[i].type == "database_entity" and ents[i].subtype == "table"}
            for n in sorted(({e.name for e in model.entities if e.type == "database_entity" and e.subtype == "table" and e.status == "active"}) - listed):
                add("data-entity", "warning", f"{d.doc_type} omits table '{n}'", [d.doc_type])
            for n in sorted(listed - tables):
                add("data-entity", "error", f"{d.doc_type} lists table '{n}' that the model does not have", [d.doc_type])
    # components named in documents exist
    comps = active("component")
    for d in docs:
        for s, _, _, _, _, cited, _ in items(d):
            for i in cited:
                if i in ents and ents[i].type == "component" and ents[i].name not in comps:
                    add("component", "error", f"{d.doc_type} mentions component '{ents[i].name}' not in the model", [d.doc_type])
    # glossary
    terms = {t["id"]: t for t in glossary.get("terms", [])}
    for d in docs:
        for tid in d.glossary_terms:
            if tid not in ents:
                add("glossary", "error", f"{d.doc_type} lists term {tid} which is not in the model", [d.doc_type])
            elif terms and tid not in terms:
                add("glossary", "warning", f"term '{ents[tid].name}' used by {d.doc_type} is missing from glossary.json", [d.doc_type])
            elif terms and terms[tid].get("cls") != ents[tid].cls:
                add("glossary", "error", f"glossary says '{ents[tid].name}' is {terms[tid].get('cls')} but the model says {ents[tid].cls}", [d.doc_type])
    # flows: chains in HLD / functional spec must equal the model's request path
    for d in docs:
        for sid, iid, text, labels, evs, cited, b in items(d):
            m = re.match(r"^`([A-Z]+ [^`]+)`: (.+?)(?: \(the path may continue.*)?$", text) if d.doc_type == "hld" else None
            api = next((ents[i] for i in cited if i in ents and ents[i].type == "api" and not ents[i].external), None)
            chain = None
            if m and api:
                chain = [x.strip() for x in m.group(2).split("->")]
            elif d.doc_type == "functional-spec" and text.startswith("Processing: ") and api:
                chain = [x.strip() for x in text[len("Processing: "):].split(";")[0].rstrip(".").split("->")]
            if chain == ["no handler found"]:
                chain = []
            if (chain is not None) and api and api.id in ents:
                truth = [s["symbol"] for s in g.trace_request(api.id, 6)["steps"][:6]]
                if chain[:len(truth)] != truth[:len(chain)] or bool(chain) != bool(truth):
                    add("flow", "error", f"{d.doc_type}: the flow of '{api.name}' reads {' -> '.join(chain)} but the model says {' -> '.join(truth)}", [d.doc_type])
    return find


# ----------------------------------------------------------------------------- the audit
def evaluate(docs: list[Document], model: KnowledgeModel, *, repo: Path | None = None, review_db: dict | None = None, glossary: dict | None = None, audience_hint: str | None = None) -> dict[str, Any]:
    registry.load_builtin()
    ev = {e.id: e for e in model.evidence}
    ents = {e.id: e for e in model.entities}
    names = Names(model)
    review_db = review_db or {}
    # --- evidence completeness
    total = cited = resolvable = verified = verified_ok = 0
    labels: Counter[str] = Counter()
    per_doc = []
    for d in docs:
        t = c = r = v = vo = 0
        lab: Counter[str] = Counter()
        for _, _, _, labs, evs, cited_ents, _ in items(d):
            t += 1
            lab.update(labs)
            if evs:
                c += 1
            if evs and all(i in ev for i in evs):
                r += 1
            if "VERIFIED" in labs:
                v += 1
                if (evs and all(i in ev for i in evs)) or (not evs and any(i in ents for i in cited_ents)):
                    vo += 1
        per_doc.append({"document": d.doc_type, "audience": d.audience, "depth": d.depth, "statements": t, "with_evidence": c, "with_resolvable_evidence": r, "verified": v, "verified_with_valid_pointer": vo,
                        "labels": dict(sorted(lab.items()))})
        total, cited, resolvable, verified, verified_ok = total + t, cited + c, resolvable + r, verified + v, verified_ok + vo
        labels.update(lab)
    evidence = {"statements": total, "with_evidence": cited, "with_resolvable_evidence": resolvable, "verified": verified, "verified_with_valid_pointer": verified_ok, "labels": dict(sorted(labels.items())),
                "by_document": per_doc,
                "note": "statements without evidence are labelled UNKNOWN, NEEDS_STAKEHOLDER_VALIDATION or cite a model entity; the counts are reported separately and are not merged into a score"}
    # --- freshness
    stale_ev: set[str] = set()
    fresh: dict[str, Any] = {"checked": False, "reason": "no --repo given: the cited text was not compared with the repository"}
    if repo is not None:
        findings = check_evidence_against_repo(model, Path(repo))
        stale_ev = {f.ref for f in findings}
        by_code = Counter(f.code for f in findings)
        affected = defaultdict(set)
        for d in docs:
            secev = ST.section_evidence(d)
            for sid, e_ in secev.items():
                if e_ & stale_ev:
                    affected[d.doc_type].add(sid)
        fresh = {"checked": True, "evidence_checked": len([e for e in model.evidence if e.path]), "stale_or_missing": len(stale_ev), "by_kind": dict(sorted(by_code.items())),
                 "sections_affected": {k: sorted(v) for k, v in sorted(affected.items())}}
    # --- coverage
    offered = {t.id for t in registry.all_types() if (audience_hint is None or audience_hint in t.audiences)}
    present = {d.doc_type for d in docs}
    scope = {}
    mentioned = {i for d in docs for _, _, _, _, _, cited_ents, _ in items(d) for i in cited_ents}
    for t in SCOPE_TYPES:
        total_t = [e for e in model.entities if e.type == t and e.status == "active" and not e.external and (t != "module" or e.subtype == "source")]
        covered = [e for e in total_t if e.id in mentioned]
        scope[t] = {"total": len(total_t), "documented": len(covered), "undocumented": sorted(e.name for e in total_t if e.id not in mentioned)[:25]}
    coverage = {"document_types": {"present": sorted(present), "offered": sorted(offered), "missing": sorted(offered - present)}, "scope": scope}
    # --- integrity, invention, privacy
    defects, gaps = [], Counter()
    for d in docs:
        rep = DV.validate_document(d, model)
        defects += [f"{d.doc_type}: {x}" for x in rep.defects]
        for g_ in d.gaps:
            gaps[g_.code] += 1
    unsupported = [x for d in docs for x in unsupported_identifiers(d, names)]
    fabricated = [x for d in docs for x in fabricated_requirements(d, model)]
    priv = [x for d in docs for x in privacy(d, doc_blobs(d))]
    cons = consistency(docs, model, glossary or {"terms": []})
    # --- review states
    states = {}
    counts: Counter[str] = Counter()
    for d in docs:
        sec = ST.section_states(d, review_db, stale_ev)
        states[d.doc_id] = {"document": d.doc_type, "state": ST.document_state(sec), "sections": sec}
        counts.update(sec.values())
    approved_recon = [d.doc_type for d in docs if d.reconstruction and states[d.doc_id]["state"] == ST.APPROVED]
    dishonest = [d.doc_type for d in docs if states[d.doc_id]["state"] != ST.APPROVED and (d.status.upper().startswith("REVIEWED") or re.search(r"(?<!NOT )(?<!NOT AN )\bAPPROVED\b", d.status.upper()))]
    gates = {
        "evidence-pointers": _gate(verified == verified_ok and resolvable == cited, "every VERIFIED statement has a valid pointer and every cited evidence id resolves", f"{verified - verified_ok} VERIFIED statement(s) without a valid pointer; {cited - resolvable} unresolvable evidence reference(s)"),
        "labels-and-profiles": _gate(not defects, "all documents satisfy their label and reconstruction rules", f"{len(defects)} defect(s)"),
        "no-invented-identifiers": _gate(not unsupported, "every quoted route, path and name exists in the model", f"{len(unsupported)} quoted identifier(s) not in the model"),
        "no-fabricated-requirements": _gate(not fabricated, "no requirement, rule or obligation without a person behind it", f"{len(fabricated)} fabricated requirement(s)"),
        "consistency": _gate(not [c for c in cons if c["severity"] == "error"], "documents agree with the model and each other", f"{len([c for c in cons if c['severity'] == 'error'])} inconsistency(ies)"),
        "freshness": ({"status": "NOT_TESTED", "detail": fresh["reason"]} if not fresh["checked"] else _gate(not stale_ev, "no cited text has changed or disappeared", f"{len(stale_ev)} stale or missing evidence record(s)")),
        "privacy": _gate(not priv, "no credential pattern or absolute local path in any document", f"{len(priv)} issue(s)"),
        "approval-honesty": _gate(not dishonest, "no document presents itself as approved without a recorded decision", f"{len(dishonest)} document(s) present themselves as approved without a recorded decision: {', '.join(dishonest)}"),
    }
    return {"format": "yuktiforge-evaluation/1", "model_scan_id": model.scan_id, "repository": model.repository, "documents": [{"id": d.doc_id, "type": d.doc_type, "audience": d.audience, "depth": d.depth, "scan_id": d.scan_id, "status": d.status} for d in docs],
            "evidence": evidence, "freshness": fresh, "coverage": coverage, "integrity": {"defects": defects, "gaps_by_code": dict(sorted(gaps.items()))},
            "invention": {"unsupported_identifiers": unsupported[:200], "fabricated_requirements": fabricated[:200]}, "privacy": priv, "consistency": cons,
            "review": {"documents": states, "section_counts": dict(sorted(counts.items())), "reconstructions_fully_approved": approved_recon,
                       "note": "a fully approved reconstruction is approved as a description of the implementation, not as a business requirement"},
            "gates": gates, "verdict": {"passed": all(g["status"] in ("PASS", "NOT_TESTED") for g in gates.values()), "failed": sorted(k for k, g in gates.items() if g["status"] == "FAIL"),
                                        "not_tested": sorted(k for k, g in gates.items() if g["status"] == "NOT_TESTED"), "note": "no single quality number is computed: it would hide which gate failed"}}


def _gate(ok: bool, passed: str, failed: str) -> dict[str, str]:
    return {"status": "PASS", "detail": passed} if ok else {"status": "FAIL", "detail": failed}
