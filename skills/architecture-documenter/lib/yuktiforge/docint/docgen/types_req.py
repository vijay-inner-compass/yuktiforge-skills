"""Requirement-style documents and code explanation. Reconstructions from code are drafts; business intent comes only from what a person supplied."""
from __future__ import annotations

import re

from yuktiforge.docint.docgen.helpers import NSV, Q, SB, labels_of, sha8
from yuktiforge.docint.docgen.spi import DocumentType, EvidenceRules, GenContext, OutputProfile, SectionSpec
from yuktiforge.docint.knowledge.schema import Entity

RECON = EvidenceRules(reconstructed=True)
_NOT_NULL = re.compile(r"\bNOT\s+NULL\b", re.I)
_PKUQ = re.compile(r"\b(PRIMARY\s+KEY|UNIQUE|CHECK\s*\(.*?\)|REFERENCES\s+[\w\".]+|DEFAULT\s+\S+)", re.I)


def tests_for(ctx: GenContext, q: Q, module_id: str) -> list[Entity]:
    """Test modules that import the module: a static, import-based hint, not coverage."""
    return sorted({e.id: e for t, e in q.inc(module_id, "imports") if e.type == "module" and e.subtype == "test"}.values(), key=lambda e: e.name)


def module_of(q: Q, sym: Entity) -> Entity | None:
    cur, seen = sym, set()
    while cur and cur.id not in seen:
        seen.add(cur.id)
        if cur.type == "module":
            return cur
        up = [e for t, e in q.inc(cur.id, "owns") if e.type in ("module", "symbol", "interface")]
        cur = up[0] if up else None
    return None


def api_flow(ctx: GenContext, q: Q, api: Entity):
    t = ctx.graph.trace_request(api.id, 6)
    return t


class BRDDraft(DocumentType):
    id, title, version = "brd-draft", "Business Requirements Document — RECONSTRUCTION DRAFT", "1.0"
    template_id = "requirements/brd"
    input_dependencies = ("requirement_candidate", "actor", "document", "workflow", "api", "database_entity")
    sections = (SectionSpec("context", "Business context"), SectionSpec("stakeholders", "Stakeholders and actors"), SectionSpec("objectives", "Business objectives"), SectionSpec("capabilities", "Observed capabilities"),
                SectionSpec("rules", "Business rule candidates"), SectionSpec("constraints", "Constraints and assumptions"), SectionSpec("questions", "Open questions for stakeholders"))
    evidence_rules = RECON
    validation_profile = "reconstruction"
    audiences = ("executive", "ba", "architect", "onboarding")
    output_profile = OutputProfile(file_stem="brd-draft")
    banner = ("RECONSTRUCTED FROM SOURCE CODE. THIS IS A DRAFT, NOT AN APPROVED BUSINESS REQUIREMENTS DOCUMENT.",
              "Code shows what the system does, not why. Business objectives, stakeholders and success criteria appear below only if a named person supplied them; everything else is marked UNKNOWN or NEEDS_STAKEHOLDER_VALIDATION.")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "context", "Business context")
        docs = q.user_entities("document")
        for d in docs:
            s.about(f"{d.name}: {d.attrs.get('statement', '')}", d)
        if not docs:
            s.gap("missing-business-context", "No business context was supplied (why the system exists, the problem it solves, the organisation it serves).", "error")
        out.append(s.build())
        s = SB(ctx, "stakeholders", "Stakeholders and actors")
        actors = q.user_entities("actor")
        for a in actors:
            s.about(f"{a.name}: {a.attrs.get('statement', '')}", a)
        if not actors:
            s.gap("missing-stakeholders", "No stakeholders or actors were supplied. Who uses or owns the system is not in the code.", "error")
        out.append(s.build())
        s = SB(ctx, "objectives", "Business objectives")
        reqs = q.user_entities("requirement_candidate")
        for r in reqs:
            s.about(f"{r.name}: {r.attrs.get('statement', '')} [approval: {r.approval}]", r, NSV if r.approval == "unapproved" else "USER_SUPPLIED")
        if not reqs:
            s.gap("missing-business-intent", "No business objectives or requirements were supplied. None are invented here: the code cannot say what the business wants.", "error")
        out.append(s.build())
        s = SB(ctx, "capabilities", "Observed capabilities")
        s.note("These are things the software demonstrably does. Their business purpose is not stated in the code.")
        rows = []
        for a in q.of("api", external=False):
            if a.subtype in ("route", "grpc", "graphql"):
                rows.append(((f"Exposes `{a.name}`", "UNKNOWN - what business need does it serve?", ctx.cite(a.evidence_ids)), (*labels_of(a), NSV), a.evidence_ids, (a.id,)))
        for t in q.of("database_entity"):
            if t.subtype == "table":
                rows.append(((f"Stores data in `{t.name}`", "UNKNOWN - what business information is this?", ctx.cite(t.evidence_ids)), (*labels_of(t), NSV), t.evidence_ids, (t.id,)))
        for e in q.of("event"):
            rows.append(((f"Uses messaging topic `{e.name}`", "UNKNOWN - which business event does it represent?", ctx.cite(e.evidence_ids)), (*labels_of(e), NSV), e.evidence_ids, (e.id,)))
        for a in q.of("api", external=True)[:30]:
            rows.append(((f"Depends on external service call `{a.name}`", "UNKNOWN - which partner or system is this?", ctx.cite(a.evidence_ids)), (*labels_of(a), NSV), a.evidence_ids, (a.id,)))
        if rows:
            s.table("cap", ("Observed capability", "Business meaning", "Source"), rows)
        else:
            s.empty("observable capabilities", "no-capabilities")
        out.append(s.build())
        s = SB(ctx, "rules", "Business rule candidates", audiences=("ba", "architect", "executive"))
        n = sum(1 for e in ctx.model.entities if e.type == "business_rule_candidate")
        s.claim(f"{n} business rule candidate(s) are recorded in the model. See the Business Rule Catalog for their evidence and approval state.", ("VERIFIED",), entities=q.repo_ids, evidence=q.repo_ev) if n else s.claim("No business rule candidates are recorded in the model.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "constraints", "Constraints and assumptions")
        for fw in q.of("technology", subtype="framework")[:12]:
            s.about(f"Technology constraint (inferred from dependencies): {fw.name}.", fw)
        s.claim("Regulatory, contractual and budget constraints are not in the code.", ("UNKNOWN", NSV))
        out.append(s.build())
        s = SB(ctx, "questions", "Open questions for stakeholders")
        qs = ["Who owns this system and who are its users?", "Which business problem does it solve, and how is success measured?", "Which of the observed capabilities are still required, and which are legacy?",
              "Which data is regulated, and what must be retained or deleted?"]
        for t in qs:
            s.claim(t, ("UNKNOWN", NSV), key=f"question|{t}")
        for g in s.ctx.model.gaps:
            if g.kind in ("spec-only-route", "code-only-route"):
                s.claim(f"Question: {g.detail}. Which is correct?", ("UNKNOWN", NSV), evidence=g.evidence_ids, entities=g.entity_ids)
        out.append(s.build())
        return out


class SRSDraft(DocumentType):
    id, title, version = "srs-draft", "Software Requirements Specification — AS-IMPLEMENTED DRAFT", "1.0"
    template_id = "requirements/srs"
    input_dependencies = ("api", "event", "database_entity", "component", "symbol", "module", "requirement_candidate")
    sections = (SectionSpec("intro", "Introduction and scope"), SectionSpec("overall", "Overall description"), SectionSpec("functional", "Functional behaviour as implemented"), SectionSpec("interfaces", "External interfaces"),
                SectionSpec("data", "Data requirements"), SectionSpec("nfr", "Non-functional observations"), SectionSpec("trace", "Traceability"), SectionSpec("open", "Open issues"))
    evidence_rules = RECON
    validation_profile = "reconstruction"
    audiences = ("ba", "architect", "developer", "qa", "onboarding")
    output_profile = OutputProfile(file_stem="srs-draft")
    banner = ("AS-IMPLEMENTED DRAFT RECONSTRUCTED FROM SOURCE CODE. IT DESCRIBES WHAT THE SOFTWARE DOES, NOT WHAT THE BUSINESS HAS APPROVED IT TO DO.",
              "Requirement identifiers (SRS-FR-...) are stable labels for observed behaviour. They are not approved requirements; approval needs stakeholders.")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "intro", "Introduction and scope")
        s.claim("Scope: the behaviour that can be observed in the analyzed source files of this repository.", ("VERIFIED",), entities=q.repo_ids, evidence=q.repo_ev)
        s.claim("Out of scope of this evidence: run-time behaviour, deployed configuration, data contents, other repositories, and anything in languages without an analyzer.", ("UNKNOWN",))
        for u in ctx.model.coverage.get("unsupported_languages", []):
            s.claim(f"{u['files']} {u['language']} file(s) were not analyzed at all.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "overall", "Overall description")
        rows = [((c.name, ", ".join(str(x) for x in c.attrs.get("languages", []) or []) or "?", len(q.modules_of(c)), ctx.cite(c.evidence_ids)), labels_of(c), c.evidence_ids, (c.id,)) for c in q.comps()]
        if rows:
            s.table("comps", ("Component", "Languages", "Modules", "Source"), rows)
        else:
            s.empty("components", "no-components")
        s.claim("Users, user classes and operating environment are not stated in the code.", ("UNKNOWN", NSV))
        out.append(s.build())
        s = SB(ctx, "functional", "Functional behaviour as implemented")
        n = 0
        for a in q.of("api", external=False):
            if a.subtype not in ("route", "grpc", "graphql"):
                continue
            n += 1
            rid = f"SRS-FR-{sha8(a.id).upper()}"
            hs = q.handlers(a)
            t = api_flow(ctx, q, a)
            touches = sorted({f"{x['rel']} {x['target']}" for x in t["touches"]})
            text = (f"{rid}: As implemented, the system exposes `{a.name}`" + (f", handled by `{hs[0].name}`" if hs else " (no handler found)") + (". During handling it " + "; ".join(touches) if touches else "") + ".")
            s.claim(text, (*labels_of(a), NSV), evidence=[*a.evidence_ids, *[i for h in hs for i in h.evidence_ids]], entities=(a.id, *[h.id for h in hs]), key=f"{a.id}|fr")
            if t["uncertain_hops"]:
                s.claim(f"{rid}: further behaviour after unresolved calls in {', '.join(u['symbol'] for u in t['uncertain_hops'])} is UNKNOWN.", ("UNKNOWN",), entities=(a.id,))
        if not n:
            s.empty("implemented entry points", "no-functional-behaviour")
        out.append(s.build())
        s = SB(ctx, "interfaces", "External interfaces")
        rows = [((a.name, "outbound HTTP", ctx.cite(a.evidence_ids)), labels_of(a), a.evidence_ids, (a.id,)) for a in q.of("api", external=True)]
        rows += [((e.name, "messaging", ctx.cite(e.evidence_ids)), labels_of(e), e.evidence_ids, (e.id,)) for e in q.of("event")]
        if rows:
            s.table("ifc", ("Interface", "Kind", "Source"), rows)
        else:
            s.claim("No external interfaces with literal addresses were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "data", "Data requirements")
        rows = [((t.name, len(q.fields_of(t)) or "unknown", ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)) for t in q.of("database_entity") if t.subtype == "table"]
        if rows:
            s.table("tbl", ("Table", "Columns known", "Source"), rows)
        else:
            s.claim("No persistent data structures were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "nfr", "Non-functional observations")
        from yuktiforge.docint.docgen.types_arch import security_observations
        security_observations(ctx, s, q)
        s.claim("Performance, capacity, availability, usability and maintainability requirements are not in the code.", ("UNKNOWN", NSV))
        out.append(s.build())
        s = SB(ctx, "trace", "Traceability")
        rows = []
        for a in q.of("api", external=False):
            if a.subtype not in ("route", "grpc", "graphql"):
                continue
            for h in q.handlers(a):
                m = module_of(q, h)
                tests = tests_for(ctx, q, m.id) if m else []
                rows.append(((f"SRS-FR-{sha8(a.id).upper()}", a.name, h.name, ", ".join(t.name for t in tests) or "NONE FOUND (no test module imports this module)"), ("VERIFIED",) if tests else ("VERIFIED", "UNKNOWN"),
                            (*a.evidence_ids, *h.evidence_ids), (a.id, h.id)))
        if rows:
            s.table("trace", ("Requirement id", "Observed behaviour", "Implemented in", "Test modules importing it"), rows)
            s.note("'Test modules importing it' is an import-based hint, not test coverage and not proof a test exercises the behaviour.")
        else:
            s.claim("No requirement-to-code links could be built.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "open", "Open issues")
        for g in ctx.model.gaps:
            s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        for c in ctx.model.conflicts:
            s.claim(f"Conflict: {c.detail}", ("VERIFIED", NSV), evidence=c.evidence_ids, entities=c.entity_ids)
        out.append(s.build())
        return out


class FunctionalSpec(DocumentType):
    id, title, version = "functional-spec", "Functional Specification (as implemented)", "1.0"
    template_id = "requirements/functional"
    input_dependencies = ("api", "symbol", "database_entity", "event")
    sections = (SectionSpec("features", "Features"),)
    evidence_rules = RECON
    validation_profile = "reconstruction"
    audiences = ("ba", "developer", "qa", "support", "onboarding")
    output_profile = OutputProfile(file_stem="functional-spec")
    banner = ("AS-IMPLEMENTED DRAFT RECONSTRUCTED FROM SOURCE CODE. NOT AN APPROVED SPECIFICATION.",)

    def build(self, ctx: GenContext):
        q = Q(ctx)
        s = SB(ctx, "features", "Features")
        n = 0
        for a in q.of("api", external=False):
            if a.subtype not in ("route", "grpc", "graphql"):
                continue
            n += 1
            t = api_flow(ctx, q, a)
            params = re.findall(r"[{:<]([A-Za-z_]\w*)", str(a.attrs.get("path", a.name)))
            s.claim(f"Feature `{a.name}`: entry point of kind {a.subtype} ({a.attrs.get('framework', '')}).", (*labels_of(a),), evidence=a.evidence_ids, entities=(a.id,))
            s.claim("Inputs: " + (", ".join(f"path parameter `{p}`" for p in params) if params else "no path parameters; request body and query parameters are UNKNOWN") + ".", ("INFERRED", NSV) if params else ("UNKNOWN",), evidence=a.evidence_ids, entities=(a.id,))
            s.claim("Processing: " + (" -> ".join(x["symbol"] for x in t["steps"][:6]) if t["steps"] else "no handler found") + ("; calls beyond this point could not be resolved" if t["uncertain_hops"] else "") + ".",
                    ("VERIFIED",) if t["steps"] and not t["uncertain_hops"] else ("VERIFIED", "UNKNOWN") if t["steps"] else ("UNKNOWN",), evidence=a.evidence_ids, entities=(a.id,))
            tt = t["touches"]
            if tt:
                s.table(f"io-{sha8(a.id)}", ("From", "Action", "Target", "Source"), [((x["from"], x["rel"], x["target"], "; ".join(x["evidence"][:1])), ("VERIFIED",) if x["cls"] == "verified" else ("INFERRED",), x["evidence_ids"], (x["from_id"], x["target_id"])) for x in tt], caption=f"Data and integrations touched by {a.name}")
            s.claim("Outputs, error responses, validation and business rules applied: UNKNOWN (not extracted).", ("UNKNOWN", NSV), entities=(a.id,))
        if not n:
            s.empty("features (entry points)", "no-features")
        return [s.build()]


class BusinessRuleCatalog(DocumentType):
    id, title, version = "business-rule-catalog", "Business Rule Catalog — CANDIDATES", "1.1"
    template_id = "requirements/rules"
    input_dependencies = ("business_rule_candidate", "field", "database_entity", "symbol")
    sections = (SectionSpec("supplied", "Rules supplied by people"), SectionSpec("integrity", "Data-integrity rule candidates"), SectionSpec("states", "Enumerated values"), SectionSpec("implementations", "Code that probably implements rules"), SectionSpec("gaps", "What cannot be derived"))
    evidence_rules = RECON
    validation_profile = "reconstruction"
    audiences = ("ba", "architect", "developer", "qa")
    output_profile = OutputProfile(file_stem="business-rules")
    banner = ("DRAFT - RULE CANDIDATES, NOT APPROVED BUSINESS RULES. Only rules supplied by a named person carry an approval state; the rest are observations from code that a stakeholder must confirm or reject.",)

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "supplied", "Rules supplied by people")
        rules = [e for e in ctx.model.entities if e.type == "business_rule_candidate"]
        if rules:
            s.table("rules", ("Id", "Rule", "Supplied by", "Approval"), [((f"BR-{sha8(r.id).upper()}", r.attrs.get("statement", r.name), r.attrs.get("asserted_by", "?"), r.approval or "unapproved"), ("USER_SUPPLIED",) if r.approval != "unapproved" else ("USER_SUPPLIED", NSV), r.evidence_ids, (r.id,)) for r in rules])
        else:
            s.gap("no-supplied-rules", "No business rules were supplied by a person.", "warning")
        out.append(s.build())
        s = SB(ctx, "integrity", "Data-integrity rule candidates")
        rows = []
        for t in q.of("database_entity"):
            if t.subtype != "table":
                continue
            for f in q.fields_of(t):
                d = str(f.attrs.get("definition", ""))
                col = f.name.split(".", 1)[-1]
                if _NOT_NULL.search(d):
                    rows.append(((f"BR-{sha8(f.id, 'nn').upper()}", f"`{t.name}.{col}` is declared NOT NULL: the schema requires a value", f"NOT NULL constraint", ctx.cite(f.evidence_ids)), ("VERIFIED", NSV), f.evidence_ids, (f.id, t.id)))
                for m in _PKUQ.finditer(d):
                    rows.append(((f"BR-{sha8(f.id, m.group(1)).upper()}", f"`{t.name}.{col}`: {m.group(1).lower()}", "column constraint as written", ctx.cite(f.evidence_ids)), ("VERIFIED", NSV), f.evidence_ids, (f.id, t.id)))
            for c in t.attrs.get("constraints") or []:
                rows.append(((f"BR-{sha8(t.id, str(c)).upper()}", f"`{t.name}`: {c}", "table constraint as written", ctx.cite(t.evidence_ids)), ("VERIFIED", NSV), t.evidence_ids, (t.id,)))
        if rows:
            s.table("integ", ("Id", "Candidate rule", "Basis", "Source"), rows)
            s.note("The constraint is observed; that it reflects a business rule (rather than a technical convenience) is not established.")
        else:
            s.claim("No column or table constraints were found in analyzed schema files.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "states", "Enumerated values")
        rows = []
        for e in q.of("symbol"):
            if e.subtype == "enum":
                vals = [k.name.rsplit(".", 1)[-1] for k in q.children(e.id)]
                rows.append(((f"BR-{sha8(e.id, 'enum').upper()}", e.name, ", ".join(vals) or "(no values read)", ctx.cite(e.evidence_ids)), ("VERIFIED", NSV), e.evidence_ids, (e.id,)))
        if rows:
            s.table("enums", ("Id", "Enumeration", "Allowed values as declared", "Source"), rows)
            s.note("Which transitions between values are legal is not recoverable from declarations.")
        else:
            s.claim("No enumerations were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "implementations", "Code that probably implements rules", audiences=("developer", "ba", "qa"))
        hits = [e for e in q.of("symbol") if e.subtype in ("function", "method") and re.search(r"valid|check|verify|ensure|assert|authori|calculate|compute|apply|enforce", e.name.rsplit(".", 1)[-1], re.I)]
        rows = [((f"BR-{sha8(e.id, 'impl').upper()}", e.name, "name suggests a rule or calculation (content not analyzed)", ctx.cite(e.evidence_ids)), ("INFERRED", NSV), e.evidence_ids, (e.id,)) for e in hits[:200]]
        if rows:
            s.table("impl", ("Id", "Function", "Basis", "Source"), rows)
        else:
            s.claim("No functions with rule-like names were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "gaps", "What cannot be derived")
        s.gap("rule-logic-not-extracted", "Conditions, thresholds, calculations, workflows and exceptions inside function bodies are not extracted. A rule catalog of real business rules needs people who know the business.", "warning")
        out.append(s.build())
        return out


class UseCases(DocumentType):
    id, title, version = "use-cases", "Use Cases (reconstruction draft)", "1.0"
    template_id = "requirements/usecases"
    input_dependencies = ("workflow", "actor", "requirement_candidate", "api", "symbol")
    sections = (SectionSpec("supplied", "Use cases supplied by people"), SectionSpec("system", "System operations observed in code"))
    evidence_rules = RECON
    validation_profile = "reconstruction"
    audiences = ("ba", "qa", "developer", "support", "onboarding")
    output_profile = OutputProfile(file_stem="use-cases")
    banner = ("RECONSTRUCTION DRAFT. Actors, goals and alternative flows are not in the code; system operations below are the only observable part.",)

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "supplied", "Use cases supplied by people")
        ws = q.user_entities("workflow")
        for w in ws:
            s.about(f"{w.name}: {w.attrs.get('statement', '')}", w, NSV if w.approval in (None, "unapproved") else "USER_SUPPLIED")
        if not ws:
            s.gap("missing-use-cases", "No use cases or workflows were supplied; actors, goals and alternative flows are UNKNOWN.", "error")
        out.append(s.build())
        s = SB(ctx, "system", "System operations observed in code")
        n = 0
        for a in q.of("api", external=False):
            if a.subtype not in ("route", "grpc", "graphql"):
                continue
            n += 1
            t = api_flow(ctx, q, a)
            s.claim(f"UC-{sha8(a.id).upper()}: Invoke `{a.name}`. Primary actor: UNKNOWN. Goal: UNKNOWN.", (*labels_of(a), NSV), evidence=a.evidence_ids, entities=(a.id,), key=f"{a.id}|uc")
            s.claim("Main flow (observed): " + (" -> ".join(x["symbol"] for x in t["steps"][:8]) if t["steps"] else "UNKNOWN") + ("; flow continues beyond unresolved calls" if t["uncertain_hops"] else "") + ".",
                    ("VERIFIED",) if t["steps"] and not t["uncertain_hops"] else ("VERIFIED", "UNKNOWN") if t["steps"] else ("UNKNOWN",), entities=(a.id,))
            s.claim("Alternative and exception flows, preconditions and postconditions: UNKNOWN.", ("UNKNOWN", NSV), entities=(a.id,))
        if not n:
            s.empty("system operations", "no-operations")
        out.append(s.build())
        return out


class CodeExplanation(DocumentType):
    id, title, version = "code-explanation", "Code Explanation", "1.0"
    template_id = "code/explanation"
    input_dependencies = ("module", "symbol", "interface", "api", "technology")
    sections = (SectionSpec("overview", "Overview"), SectionSpec("entry", "Entry points and call paths"), SectionSpec("modules", "Modules and symbols"), SectionSpec("boundaries", "What the code talks to"), SectionSpec("limits", "Limits of this explanation"))
    output_profile = OutputProfile(file_stem="code-explanation")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        scope = ctx.scope or "repo"
        mods = q.of("module", subtype="source")
        if scope.startswith("module:"):
            mods = [m for m in mods if m.name == scope[7:]]
        elif scope.startswith("symbol:"):
            names = scope[7:]
            mods = [m for m in mods if any(names == s.name for s in q.children(m.id)) or any(k.name == names for c in q.children(m.id) for k in q.children(c.id))]
        out = []
        s = SB(ctx, "overview", "Overview")
        ids = {m.id for m in mods}
        syms = [e for e in q.of("symbol", "interface") if any(e.id in {x.id for x in q.children(m.id)} or e.attrs.get("path") == m.name for m in mods)]
        s.claim(f"Scope `{scope}`: {len(mods)} module(s) and {len(syms)} symbol(s) analyzed.", ("VERIFIED",), entities=tuple(sorted(ids)))
        if not mods:
            s.gap("scope-not-found", f"scope `{scope}` matched no analyzed module", "error")
        out.append(s.build())
        s = SB(ctx, "entry", "Entry points and call paths")
        paths = 0
        for a in q.of("api", external=False):
            if a.subtype not in ("route", "grpc", "graphql"):
                continue
            hs = [h for h in q.handlers(a) if h.attrs.get("path") in {m.name for m in mods}]
            if mods and not hs:
                continue
            t = api_flow(ctx, q, a)
            if t["steps"]:
                paths += 1
                s.claim(f"`{a.name}` runs " + " -> ".join(f"`{x['symbol']}` ({x['at']})" for x in t["steps"][:8]) + ("; the path continues past unresolved calls" if t["uncertain_hops"] else "."), ("VERIFIED",) if not t["uncertain_hops"] else ("VERIFIED", "UNKNOWN"),
                        evidence=[i for st in t["steps"] for i in ctx.graph.ent[st["id"]].evidence_ids][:8], entities=(a.id,))
        for e in q.of("symbol"):
            if e.attrs.get("entry_point") and e.attrs.get("path") in {m.name for m in mods}:
                s.about(f"`{e.name}` is a program entry point.", e)
                paths += 1
        if not paths:
            s.claim("No entry points or request paths in this scope.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "modules", "Modules and symbols", depth="summary")
        for m in mods:
            kids = q.children(m.id)
            s.claim(f"`{m.name}` ({m.attrs.get('language', '')}) declares " + (", ".join(f"{k.subtype} `{k.name.rsplit('.', 1)[-1]}`" for k in kids[:15]) + (" ..." if len(kids) > 15 else "") if kids else "nothing recognised") + ".", ("VERIFIED",), evidence=m.evidence_ids, entities=(m.id,))
        if mods:
            imps = sorted({e.name for m in mods for t, e in q.out(m.id, "imports")})
            if imps:
                s.claim("Imports from other modules in the repository: " + ", ".join(f"`{i}`" for i in imps[:20]) + ".", ("VERIFIED",), entities=tuple(sorted(ids)))
        out.append(s.build())
        s = SB(ctx, "boundaries", "What the code talks to")
        rows = []
        for e in syms:
            for t, es in q.touches(e).items():
                for x in es:
                    rows.append(((e.name, t, x.name, ctx.cite(x.evidence_ids)), labels_of(e, x), x.evidence_ids, (e.id, x.id)))
        if rows:
            s.table("touch", ("Code", "Action", "Target", "Source"), rows[:300])
        else:
            s.claim("No database, messaging, configuration or outbound HTTP access was recognised in this scope.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "limits", "Limits of this explanation")
        s.claim("This explains structure and observed connections. It does not explain algorithms, business meaning or run-time behaviour; comments in the source are untrusted text and are not quoted here.", ("UNKNOWN",))
        for g in ctx.model.gaps:
            if g.kind in ("unresolved-calls", "no-call-graph", "unsupported-language", "parse-failure"):
                s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        out.append(s.build())
        return out
