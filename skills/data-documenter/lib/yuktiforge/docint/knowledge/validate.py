"""Integrity checks over a KnowledgeModel (and, with the repository, over its evidence). Errors mean the model must not be used to generate documents."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from yuktiforge.docint.knowledge.schema import ACYCLIC, APPROVABLE, CLASS_RANK, KnowledgeModel


@dataclass(frozen=True)
class Finding:
    severity: str          # error | warning
    code: str
    message: str
    ref: str = ""


def _dups(items, what) -> list[Finding]:
    return [Finding("error", "duplicate-id", f"{what} id used {n} times", i) for i, n in Counter(x.id for x in items).items() if n > 1]


def validate(model: KnowledgeModel, repo: Path | None = None, current_revision: str | None = None) -> list[Finding]:
    out: list[Finding] = []
    ents = {e.id: e for e in model.entities}
    evs = {e.id: e for e in model.evidence}
    out += _dups(model.entities, "entity") + _dups(model.relationships, "relationship") + _dups(model.evidence, "evidence")
    for r in model.relationships:
        for end, label in ((r.source, "source"), (r.target, "target")):
            if end not in ents:
                out.append(Finding("error", "dangling-relationship", f"{r.type} relationship has {label} '{end}' which is not an entity", r.id))
        for e in r.evidence_ids:
            if e not in evs:
                out.append(Finding("error", "dangling-evidence", f"relationship cites unknown evidence '{e}'", r.id))
    for e in model.entities:
        if not e.evidence_ids:
            out.append(Finding("error", "no-evidence", f"{e.type} '{e.name}' has no evidence", e.id))
        classes = []
        for i in e.evidence_ids:
            if i not in evs:
                out.append(Finding("error", "dangling-evidence", f"entity cites unknown evidence '{i}'", e.id))
            else:
                classes.append(evs[i].cls)
        if classes and CLASS_RANK[e.cls] > min(CLASS_RANK[c] for c in classes):
            out.append(Finding("error", "confidence-upgraded", f"{e.type} '{e.name}' is '{e.cls}' but its weakest evidence is '{min(classes, key=lambda c: CLASS_RANK[c])}': classes are never upgraded", e.id))
        if e.approval is not None and e.type not in APPROVABLE:
            out.append(Finding("error", "approval-not-allowed", f"{e.type} cannot carry an approval", e.id))
        if e.type in APPROVABLE:
            if e.approval is None or not (e.approval == "unapproved" or e.approval.startswith("approved-by:")):
                out.append(Finding("error", "bad-approval", f"{e.type} '{e.name}' must be 'unapproved' or 'approved-by:<name>'", e.id))
            elif e.approval.startswith("approved-by:"):
                who = e.approval.split(":", 1)[1]
                if not who.strip() or not any(evs[i].cls == "user-supplied" and who in evs[i].note for i in e.evidence_ids if i in evs):
                    out.append(Finding("error", "approval-without-record", f"'{e.name}' claims approval by '{who}' but no user-supplied evidence records it", e.id))
    for ev in model.evidence:
        if ev.cls == "verified" and not (ev.path or ev.method in ("scan", "rule", "user")) :
            out.append(Finding("error", "verified-without-source", "verified evidence has no file pointer", ev.id))
        if ev.cls == "inferred" and not ev.note.strip():
            out.append(Finding("error", "inferred-without-rationale", "inferred evidence must say why", ev.id))
        if ev.start_line and ev.end_line and ev.end_line < ev.start_line:
            out.append(Finding("error", "bad-range", "end line before start line", ev.id))
    for g in model.gaps:
        for i in g.entity_ids:
            if i not in ents:
                out.append(Finding("error", "dangling-gap", f"gap refers to unknown entity '{i}'", g.id))
    for c in model.conflicts:
        for i in c.entity_ids:
            if i not in ents:
                out.append(Finding("error", "dangling-conflict", f"conflict refers to unknown entity '{i}'", c.id))
        out.append(Finding("warning", "conflict", c.detail, c.id))
    # cycles in relationship types that must be acyclic
    for t in ACYCLIC:
        adj = defaultdict(list)
        for r in model.relationships:
            if r.type == t and r.source in ents and r.target in ents:
                adj[r.source].append(r.target)
        color: dict[str, int] = {}
        for start in list(adj):
            if color.get(start):
                continue
            stack = [(start, iter(adj[start]))]
            color[start] = 1
            while stack:
                node, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    color[node] = 2
                    stack.pop()
                elif color.get(nxt) == 1:
                    out.append(Finding("error", "forbidden-cycle", f"'{t}' relationships form a cycle through '{nxt}'", nxt))
                    color[nxt] = 2
                elif not color.get(nxt):
                    color[nxt] = 1
                    stack.append((nxt, iter(adj[nxt])))
    if repo is not None:
        out += check_evidence_against_repo(model, Path(repo))
    if current_revision and model.repository.get("revision") and current_revision != model.repository["revision"]:
        out.append(Finding("warning", "stale-snapshot", f"model was built at {model.repository['revision'][:12]} but the repository is at {current_revision[:12]}", model.scan_id))
    return out


def check_evidence_against_repo(model: KnowledgeModel, repo: Path) -> list[Finding]:
    """Evidence must still point at the text it was taken from: a missing file or line range is an error; changed text is STALE evidence."""
    out: list[Finding] = []
    cache: dict[str, list[str] | None] = {}
    for ev in model.evidence:
        if not ev.path or ev.start_line is None:
            continue
        if ev.path not in cache:
            p = repo / ev.path
            cache[ev.path] = p.read_text(encoding="utf-8", errors="replace").split("\n") if p.is_file() and not p.is_symlink() else None
        ls = cache[ev.path]
        if ls is None:
            out.append(Finding("error", "evidence-file-deleted", f"{ev.path} no longer exists", ev.id))
        elif (ev.end_line or ev.start_line) > len(ls):
            out.append(Finding("error", "evidence-lines-deleted", f"{ev.path}:{ev.start_line}-{ev.end_line} is beyond the end of the file ({len(ls)} lines)", ev.id))
        elif ev.content_sha256 and hashlib.sha256("\n".join(ls[ev.start_line - 1:ev.end_line]).encode("utf-8", "replace")).hexdigest() != ev.content_sha256:
            out.append(Finding("error", "evidence-stale", f"text at {ev.path}:{ev.start_line}-{ev.end_line} changed since the scan: the claim must be re-established", ev.id))
    return out
