"""`docs update --since <revision>`: find what changed in the repository, map it to knowledge-model entities, to the documents' sections and to the diagrams it affects, and
(with --apply) regenerate only what changed. Sections and approvals that did not change stay exactly as they were; a changed section's earlier approval is shown as STALE."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yuktiforge.docint.audit import loader
from yuktiforge.docint.docgen import engine
from yuktiforge.docint.docgen.doc import Document
from yuktiforge.docint.docgen.outputs import canon, write_documents
from yuktiforge.docint.docgen.regen import regenerate
from yuktiforge.docint.knowledge import outputs as KO
from yuktiforge.docint.knowledge.build import build_model
from yuktiforge.docint.knowledge.schema import KnowledgeModel
from yuktiforge.docint.knowledge.store import Store, merge
from yuktiforge.docint.publish import diagrams as D
from yuktiforge.docint.publish import tools
from yuktiforge.docint.scan import ScanConfig, scan, write_outputs
from yuktiforge.errors import YuktiForgeError
from yuktiforge.visualizer.model import canonical_json

_REV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^@{}-]{0,99}$")


@dataclass
class UpdatePlan:
    since: str | None
    git: dict[str, Any]
    old_model: KnowledgeModel
    new_model: KnowledgeModel
    entities: dict[str, list[dict[str, str]]]
    relationships: dict[str, int]
    documents: list[dict[str, Any]]
    diagrams: dict[str, list[str]]
    new_documents: list[Document] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)

    @property
    def unchanged(self) -> bool:
        return not any(self.entities.values()) and not any(self.relationships.values()) and not any(d["changed_sections"] or d["added_sections"] or d["removed_sections"] for d in self.documents) and not any(self.diagrams.values())


def git_changes(repo: Path, since: str | None) -> dict[str, Any]:
    """Files changed between `since` and the working tree (read-only git). Returns {'available': bool, 'files': {path: status}, 'reason'}."""
    info: dict[str, Any] = {"available": False, "files": {}, "since": since}
    if since is None:
        info["reason"] = "no revision given and the model records none"
        return info
    if not _REV.match(since):
        raise YuktiForgeError(f"'{since}' is not an acceptable revision name")
    if not tools.which("git"):
        info["reason"] = "git not found"
        return info
    ok = tools.git(repo, "rev-parse", "--verify", "--quiet", since + "^{commit}")
    if ok.returncode != 0:
        info["reason"] = f"revision {since} was not found in the repository"
        return info
    d = tools.git(repo, "diff", "--name-status", "-z", since)
    if d.returncode != 0:
        info["reason"] = "git diff failed"
        return info
    parts = d.stdout.split("\0")
    i, files = 0, {}
    while i < len(parts) and parts[i]:
        st = parts[i]
        if st.startswith(("R", "C")):
            files[parts[i + 2]] = "R"
            files[parts[i + 1]] = "D"
            i += 3
        else:
            files[parts[i + 1]] = st[:1]
            i += 2
    u = tools.git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    for p in u.stdout.split("\0"):
        if p:
            files[p] = "A"
    info.update(available=True, files=dict(sorted(files.items())), resolved=tools.git(repo, "rev-parse", since + "^{commit}").stdout.strip())
    return info


def _digest(model: KnowledgeModel) -> dict[str, str]:
    ev = {e.id: e for e in model.evidence}
    out = {}
    for e in model.entities:
        h = hashlib.sha256(json.dumps([e.name, e.subtype, e.cls, e.status, e.external, e.attrs, e.approval, sorted((ev[i].path, ev[i].start_line, ev[i].end_line, ev[i].content_sha256, ev[i].cls) if i in ev else i for i in e.evidence_ids)],
                                      sort_keys=True, default=str).encode()).hexdigest()
        out[e.id] = h
    return out


def diff_models(old: KnowledgeModel, new: KnowledgeModel) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    do, dn = _digest(old), _digest(new)
    on, nn = {e.id: e for e in old.entities}, {e.id: e for e in new.entities}
    row = lambda e: {"id": e.id, "type": e.type, "name": e.name}
    gone = lambda i: i not in nn or (nn[i].status == "retired" and on[i].status != "retired")      # a merge keeps retired entities as history: for the reader they are removed
    ent = {"added": [row(nn[i]) for i in sorted(set(dn) - set(do))], "removed": [row(on[i]) for i in sorted(set(do)) if gone(i)],
           "changed": [row(nn[i]) for i in sorted(set(do) & set(dn)) if do[i] != dn[i] and not gone(i)]}
    ro, rn = {r.id: r for r in old.relationships}, {r.id: r for r in new.relationships}
    rel = {"added": len(set(rn) - set(ro)), "removed": len(set(ro) - set(rn)), "changed": sum(1 for i in set(ro) & set(rn) if ro[i].model_dump() != rn[i].model_dump() and
                                                                                                    ro[i].model_dump(exclude={"evidence_ids"}) != rn[i].model_dump(exclude={"evidence_ids"}))}
    return ent, rel


def _section_entities(doc: Document) -> dict[str, set[str]]:
    from yuktiforge.docint.audit.evaluation import items
    out: dict[str, set[str]] = {s.id: set() for s in doc.sections}
    for d_ in [doc]:
        for s in d_.sections:
            for b in s.blocks:
                from yuktiforge.docint.docgen.doc import Claim, Table
                if isinstance(b, Claim):
                    out[s.id].update(b.entity_ids)
                elif isinstance(b, Table):
                    for r in b.rows:
                        out[s.id].update(r.entity_ids)
    return out


def _diagram_hashes(model: KnowledgeModel) -> dict[str, str]:
    specs, _ = D.build_all(model)
    return {s.id: hashlib.sha256((canonical_json(s.model) + json.dumps(s.mapping, sort_keys=True)).encode()).hexdigest() for s in specs}


def plan(model_dir: Path, docs_path: Path, repo: Path, *, since: str | None = None, work: Path) -> UpdatePlan:
    old = loader.load_model(model_dir)
    docs, ddir = loader.load_documents(docs_path)
    since_eff = since or old.repository.get("revision")
    git = git_changes(repo, since_eff)
    sdir = work / "scan"
    write_outputs(scan(ScanConfig(repo=Path(repo), out=sdir)), sdir)
    fresh = build_model(sdir, Path(repo))
    new, _ = merge(old, fresh)
    ents, rels = diff_models(old, new)
    changed_ids = {e["id"] for v in ents.values() for e in v}
    review = loader.load_review(ddir)
    rows, regenerated = [], []
    for d in docs:
        ctx_sec = _section_entities(d)
        try:
            fresh_doc = engine.generate(d.doc_type, new, audience=d.audience, depth=d.depth, scope=d.scope)
        except Exception as e:
            rows.append({"document": d.doc_type, "doc_id": d.doc_id, "error": f"{type(e).__name__}: cannot regenerate", "changed_sections": [], "added_sections": [], "removed_sections": [], "unchanged_sections": []})
            regenerated.append(d)
            continue
        merged, st = regenerate(d, fresh_doc)
        regenerated.append(merged)
        causes = {sid: sorted(ctx_sec.get(sid, set()) & changed_ids)[:10] for sid in st["changed"]}
        approved_lost = [sid for sid in st["changed"] if review.get(d.doc_id, {}).get(sid, {}).get("state") == "approved"]
        rows.append({"document": d.doc_type, "doc_id": d.doc_id, "audience": d.audience, "depth": d.depth, "changed_sections": st["changed"], "added_sections": st["added"], "removed_sections": st["removed"],
                     "unchanged_sections": st["unchanged"], "causes": causes, "approvals_that_become_stale": approved_lost})
    dh_old, dh_new = _diagram_hashes(old), _diagram_hashes(new)
    diagrams = {"changed": sorted(k for k in dh_old if k in dh_new and dh_old[k] != dh_new[k]), "added": sorted(set(dh_new) - set(dh_old)), "removed": sorted(set(dh_old) - set(dh_new))}
    p = UpdatePlan(since_eff, git, old, new, ents, rels, rows, diagrams, regenerated, sorted(git["files"]))
    return p


def apply(p: UpdatePlan, model_dir: Path, docs_path: Path) -> list[str]:
    """Write the new model (merged into the store so user statements survive) and only the documents/sections that changed. Nothing is rewritten when nothing changed."""
    written: list[str] = []
    if p.unchanged:
        return written
    store = Store(model_dir / "store")
    try:
        store.save(p.new_model)
        model = store.load()
    finally:
        store.close()
    KO.write_all(model, model_dir)
    written.append("model")
    docs, ddir = loader.load_documents(docs_path)
    review = loader.load_review(ddir)
    affected = {r["doc_id"] for r in p.documents if r["changed_sections"] or r["added_sections"] or r["removed_sections"]}
    to_write = [d for d in p.new_documents if d.doc_id in affected]                          # a document nothing reaches is not rewritten, not even its header
    if to_write:
        write_documents(to_write, model, ddir, review)
        written += [d.doc_type for d in to_write]
    return written


# ----------------------------------------------------------------------------- the human report
def change_report(p: UpdatePlan) -> str:
    L = ["# Change report", "", f"Compared against revision: `{p.since or 'none recorded'}`" + (f" (resolved {p.git.get('resolved', '')[:12]})" if p.git.get("resolved") else ""), ""]
    if not p.git["available"]:
        L += [f"> Revision comparison was not possible: {p.git.get('reason', 'unknown reason')}. The comparison below is between the stored knowledge model and a fresh scan of the repository.", ""]
    else:
        L += [f"{len(p.changed_files)} file(s) changed in the working tree since that revision.", ""]
        if p.changed_files:
            L += ["| File | Change |", "|---|---|"] + [f"| `{f}` | {p.git['files'][f]} |" for f in p.changed_files[:60]] + [""]
    if p.unchanged:
        return "\n".join(L + ["## Result", "", "**No change reaches the documentation.** Entities, relationships, document sections and diagrams are identical; nothing needs regenerating and no approval is affected.", ""]) + "\n"
    L += ["## Knowledge-model changes", "", f"Entities: {len(p.entities['added'])} added, {len(p.entities['removed'])} removed, {len(p.entities['changed'])} changed. Relationships: {p.relationships['added']} added, {p.relationships['removed']} removed, {p.relationships['changed']} changed.", ""]
    for k in ("added", "removed", "changed"):
        if p.entities[k]:
            L += [f"**{k.capitalize()}**", ""] + [f"- {e['type']} `{e['name']}`" for e in p.entities[k][:40]] + (["- ..."] if len(p.entities[k]) > 40 else []) + [""]
    L += ["## Documents and sections", "", "| Document | Changed sections | Added | Removed | Approvals that become STALE |", "|---|---|---|---|---|"]
    for d in p.documents:
        if d["changed_sections"] or d["added_sections"] or d["removed_sections"]:
            L.append(f"| {d['document']} ({d.get('audience', '')}/{d.get('depth', '')}) | {', '.join(d['changed_sections']) or '-'} | {', '.join(d['added_sections']) or '-'} | {', '.join(d['removed_sections']) or '-'} | {', '.join(d.get('approvals_that_become_stale', [])) or '-'} |")
    L += ["", f"{sum(1 for d in p.documents if not (d['changed_sections'] or d['added_sections'] or d['removed_sections']))} document(s) are unaffected and stay byte-for-byte as they are.", "", "## Diagrams", ""]
    for k in ("changed", "added", "removed"):
        L.append(f"- {k}: {', '.join(p.diagrams[k]) or 'none'}")
    L += ["", "## What to do", "", "Run again with `--apply` to regenerate only the sections listed above. Review decisions stay on file; those on changed sections show as STALE until a person reviews the new text.", ""]
    return "\n".join(L) + "\n"


def change_json(p: UpdatePlan) -> dict[str, Any]:
    return {"format": "yuktiforge-change-impact-report/1", "since": p.since, "git": {k: v for k, v in p.git.items() if k != "files"}, "changed_files": {f: p.git["files"][f] for f in p.changed_files}, "entities": p.entities,
            "relationships": p.relationships, "documents": p.documents, "diagrams": p.diagrams, "unchanged": p.unchanged}
