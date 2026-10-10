"""Queries over a KnowledgeModel: lookup, neighbours, request-path reconstruction and change-impact traversal."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from yuktiforge.docint.knowledge.schema import Entity, KnowledgeModel, Relationship

MAX_ROWS = 500


class Graph:
    def __init__(self, model: KnowledgeModel):
        self.m = model
        self.ent = {e.id: e for e in model.entities}
        self.ev = {e.id: e for e in model.evidence}
        self.out: dict[str, list[Relationship]] = defaultdict(list)
        self.inc: dict[str, list[Relationship]] = defaultdict(list)
        for r in model.relationships:
            self.out[r.source].append(r)
            self.inc[r.target].append(r)

    def cite(self, ev_ids) -> list[str]:
        res = []
        for i in ev_ids:
            e = self.ev.get(i)
            if e and e.path:
                res.append(f"{e.path}:{e.start_line}-{e.end_line}")
            elif e:
                res.append(f"({e.method}) {e.note[:80]}")
        return res[:4]

    def get(self, eid: str) -> Entity:
        if eid not in self.ent:
            raise KeyError(eid)
        return self.ent[eid]

    def find(self, type_: str | None = None, text: str | None = None, subtype: str | None = None) -> list[Entity]:
        t = text.lower() if text else None
        rows = [e for e in self.m.entities if (not type_ or e.type == type_) and (not subtype or e.subtype == subtype) and (not t or t in e.name.lower())]
        return rows[:MAX_ROWS]

    def neighbors(self, eid: str, types: set[str] | None = None, direction: str = "both") -> list[dict[str, Any]]:
        rows = []
        if direction in ("out", "both"):
            rows += [{"direction": "out", "rel": r.type, "other": r.target, "evidence": self.cite(r.evidence_ids), "cls": r.cls} for r in self.out.get(eid, []) if not types or r.type in types]
        if direction in ("in", "both"):
            rows += [{"direction": "in", "rel": r.type, "other": r.source, "evidence": self.cite(r.evidence_ids), "cls": r.cls} for r in self.inc.get(eid, []) if not types or r.type in types]
        for row in rows:
            o = self.ent.get(row["other"])
            row["other_name"], row["other_type"] = (o.name, o.type) if o else ("?", "?")
        return rows[:MAX_ROWS]

    # ------------------------------------------------------------------ request path
    def trace_request(self, api_id: str, max_depth: int = 8) -> dict[str, Any]:
        api = self.get(api_id)
        handlers = [r.source for r in self.inc.get(api_id, []) if r.type == "implements"]
        steps, touches, uncertain = [], [], []
        seen: dict[str, int] = {}
        q = deque((h, 0, None) for h in handlers)
        while q:
            node, depth, via = q.popleft()
            if node in seen or depth > max_depth:
                continue
            seen[node] = depth
            e = self.ent[node]
            steps.append({"depth": depth, "symbol": e.name, "id": node, "at": f"{e.attrs.get('path')}:{e.attrs.get('start_line')}-{e.attrs.get('end_line')}" if e.attrs.get("path") else "",
                          "via": via, "evidence": self.cite(e.evidence_ids)})
            if e.attrs.get("unresolved_calls"):
                uncertain.append({"symbol": e.name, "id": node, "unresolved_calls": e.attrs["unresolved_calls"],
                                  "note": "calls here could not be resolved: the request path may continue beyond what is shown"})
            for r in self.out.get(node, []):
                t = self.ent.get(r.target)
                if t is None:
                    continue
                if r.type == "calls" and t.type in ("symbol", "interface"):
                    q.append((r.target, depth + 1, r.attrs.get("resolution")))
                elif r.type in ("reads", "writes", "publishes", "subscribes", "calls"):
                    touches.append({"from": e.name, "from_id": e.id, "rel": r.type, "kind": t.type, "target": t.name, "target_id": t.id, "external": t.external, "evidence": self.cite(r.evidence_ids), "evidence_ids": list(r.evidence_ids), "cls": r.cls})
        notes = []
        if not handlers:
            notes.append("no handler symbol is linked to this API: the implementing code was not found")
        if not any(self.m.coverage.get("languages", {}).get(self.ent[h].attrs.get("language", ""), {}).get("call_graph") for h in handlers):
            notes.append("the handler's language has no call graph: only boundaries inside the handler itself are shown, not what it calls")
        return {"api": {"id": api_id, "name": api.name, "cls": api.cls}, "handlers": [self.ent[h].name for h in handlers], "steps": steps, "touches": touches, "uncertain_hops": uncertain,
                "notes": notes, "basis": "observed in source text; not run-time behaviour"}

    # ------------------------------------------------------------------ change impact
    def affects(self) -> dict[str, list[tuple[str, str, str]]]:
        """Directed 'if X changes, Y may be affected' edges derived from typed relationships: (to, via relationship type, relationship id)."""
        a: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for r in self.m.relationships:
            s, t, k = r.source, r.target, r.type
            if k == "calls":
                a[t].append((s, k, r.id))
            elif k == "imports":
                a[t].append((s, k, r.id))
            elif k == "implements":
                a[s].append((t, k, r.id))
            elif k == "owns":
                a[t].append((s, k, r.id))
            elif k in ("reads", "writes", "subscribes"):
                a[t].append((s, k, r.id))
                if k == "writes":
                    a[s].append((t, k, r.id))
            elif k == "publishes":
                a[s].append((t, k, r.id))
            elif k in ("derived-from",):
                a[t].append((s, k, r.id))
        return a

    def seeds_for_paths(self, paths: list[str]) -> set[str]:
        ps = set(paths)
        return {e.id for e in self.m.entities if (e.type == "module" and e.name in ps) or (e.attrs.get("path") in ps and e.type in ("symbol", "interface", "field"))}

    def impact(self, seeds: set[str], depth: int = 3, skip_types: frozenset[str] = frozenset({"repository"})) -> dict[str, Any]:
        aff = self.affects()
        dist: dict[str, int] = {s: 0 for s in seeds}
        chain: dict[str, list[str]] = {s: [] for s in seeds}
        q = deque(seeds)
        while q:
            n = q.popleft()
            if dist[n] >= depth:
                continue
            for t, k, rid in aff.get(n, []):
                if t in dist or self.ent[t].type in skip_types:
                    continue
                dist[t] = dist[n] + 1
                chain[t] = chain[n] + [f"{k}"]
                q.append(t)
        rows = [{"id": i, "type": self.ent[i].type, "name": self.ent[i].name, "distance": d, "via": chain[i]} for i, d in dist.items() if i not in seeds]
        rows.sort(key=lambda r: (r["distance"], r["type"], r["name"]))
        by_type: dict[str, int] = defaultdict(int)
        for r in rows:
            by_type[r["type"]] += 1
        return {"seeds": sorted(self.ent[s].name for s in seeds), "depth": depth, "affected_count": len(rows), "by_type": dict(sorted(by_type.items())), "affected": rows[:MAX_ROWS],
                "truncated": len(rows) > MAX_ROWS,
                "basis": "static relationships only; reflection, dependency injection and run-time wiring are not followed, so absence from this list is not proof of no impact"}
