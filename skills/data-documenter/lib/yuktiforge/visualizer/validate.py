"""Model validation: structural checks that run BEFORE rendering. Pure functions, no I/O."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from yuktiforge.visualizer.model import ID_PATTERN, ArchitectureModel

Severity = Literal["error", "warning"]
_ID = re.compile(ID_PATTERN)


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    subject: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message, "subject": self.subject}


def _dups(ids: list[str]) -> list[str]:
    return sorted(i for i, n in Counter(ids).items() if n > 1 and i)


def validate_model(m: ArchitectureModel) -> list[Issue]:
    out: list[Issue] = []
    err = lambda code, msg, subj="": out.append(Issue(code, "error", msg, subj))  # noqa: E731
    warn = lambda code, msg, subj="": out.append(Issue(code, "warning", msg, subj))  # noqa: E731

    if not m.components:
        err("empty-model", "model has no components")

    for kind, items in (("component", m.components), ("relation", m.relations),
                        ("boundary", m.boundaries), ("layer", m.layers)):
        for i, x in enumerate(items):
            if not x.id:
                err("missing-id", f"{kind} #{i + 1} has no id" + (f" (name {x.name!r})" if getattr(x, "name", "") else ""),
                    f"{kind}[{i}]")
            elif not _ID.match(x.id):
                err("bad-id", f"{kind} id {x.id!r} must match {ID_PATTERN}", x.id)
        for d in _dups([x.id for x in items]):
            err("duplicate-id", f"duplicate {kind} id {d!r}", d)

    cids = {c.id for c in m.components if c.id}
    bids = {b.id for b in m.boundaries if b.id}
    lids = {l.id for l in m.layers if l.id}

    names = Counter(c.name.strip().lower() for c in m.components if c.name.strip())
    for n, k in sorted(names.items()):
        if k > 1:
            warn("duplicate-name", f"{k} components share the name {n!r} (different ids; possible duplicates)", n)
    for c in m.components:
        if c.id and not c.name.strip():
            err("missing-name", "component has no name", c.id)
        if c.layer and c.layer not in lids:
            err("unknown-layer", f"component {c.id!r} references unknown layer {c.layer!r}", c.id)
        if c.boundary and c.boundary not in bids:
            err("unknown-boundary", f"component {c.id!r} references unknown boundary {c.boundary!r}", c.id)

    for r in m.relations:
        for end, v in (("source", r.source), ("target", r.target)):
            if not v:
                err("dangling-edge", f"relation {r.id or '?'} has no {end}", r.id)
            elif v not in cids:
                err("dangling-edge", f"relation {r.id or '?'} {end} {v!r} is not a component", r.id)
        if r.source and r.source == r.target:
            warn("self-edge", f"relation {r.id!r} connects {r.source!r} to itself", r.id)

    parents = {b.id: b.parent for b in m.boundaries if b.id}
    for b in m.boundaries:
        if b.parent and b.parent not in bids:
            err("unknown-boundary", f"boundary {b.id!r} references unknown parent {b.parent!r}", b.id)
        seen, cur = set(), b.id
        while cur and cur in parents and parents[cur]:
            if cur in seen:
                err("boundary-cycle", f"boundary {b.id!r} is part of a parent cycle", b.id)
                break
            seen.add(cur)
            cur = parents[cur]

    for kind, items in (("component", m.components), ("relation", m.relations)):
        for x in items:
            ev = x.evidence
            if ev.status == "verified" and not any(s.kind in ("file", "analyzer") for s in ev.sources):
                err("unsupported-verified", f"{kind} {x.id!r} is 'verified' but cites no file/analyzer source", x.id)
            if ev.status == "inferred" and not ev.rationale.strip():
                err("inferred-without-rationale", f"{kind} {x.id!r} is 'inferred' but gives no rationale", x.id)

    degree = Counter()
    for r in m.relations:
        degree[r.source] += 1
        degree[r.target] += 1
    for c in m.components:
        if c.id and m.relations and degree[c.id] == 0:
            warn("isolated-component", f"component {c.id!r} has no relations", c.id)
    return out


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)
