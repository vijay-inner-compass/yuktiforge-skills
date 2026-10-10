"""Writers for the D2 deliverables: system-knowledge.json, traceability.json, change-impact.json (canonical, ASCII, sorted, atomic)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import KnowledgeModel


def canon(o: Any) -> str:
    return json.dumps(o, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def traceability(model: KnowledgeModel) -> dict[str, Any]:
    g = Graph(model)
    apis = [e for e in model.entities if e.type == "api" and not e.external and e.subtype != "client-target"]
    reqs = [g.trace_request(a.id) for a in sorted(apis, key=lambda x: x.id)]
    spec_links = [{"spec": g.ent[r.source].name, "spec_id": r.source, "code": g.ent[r.target].name, "code_id": r.target, "basis": "same method and normalised path (by name)", "cls": r.cls}
                  for r in model.relationships if r.type == "traces-to"]
    return {"format": "yuktiforge-traceability/1", "scan_id": model.scan_id, "repository": model.repository, "request_paths": reqs, "spec_to_code": spec_links,
            "gaps": [g_.model_dump(mode="json") for g_ in model.gaps], "conflicts": [c.model_dump(mode="json") for c in model.conflicts],
            "evidence_index": {e.id: g.cite(e.evidence_ids) for e in model.entities if e.type in ("api", "database_entity", "event")},
            "notes": ["request paths are reconstructed from observed static relationships; a hop marked uncertain may continue beyond what is shown"]}


def change_impact(model: KnowledgeModel, depth: int = 3) -> dict[str, Any]:
    g = Graph(model)
    mods = [e for e in model.entities if e.type == "module"]
    rows = []
    for m in sorted(mods, key=lambda x: x.name):
        imp = g.impact(g.seeds_for_paths([m.name]), depth=depth)
        rows.append({"file": m.name, "affected_count": imp["affected_count"], "by_type": imp["by_type"],
                     "affected_modules": [a["name"] for a in imp["affected"] if a["type"] == "module"][:20],
                     "affected_apis": [a["name"] for a in imp["affected"] if a["type"] == "api"][:20]})
    return {"format": "yuktiforge-change-impact/1", "scan_id": model.scan_id, "repository": model.repository, "depth": depth, "per_file": rows,
            "basis": "static relationships only (imports, resolved calls, ORM mappings, table and topic sharing); reflection and run-time wiring are not followed, so a file absent from another's list is not proof of independence",
            "how_to_use": "yuktiforge docs model impact --model <dir> --changed <path> ..."}


def write_all(model: KnowledgeModel, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    docs = {"system-knowledge.json": model.model_dump(mode="json"), "traceability.json": traceability(model), "change-impact.json": change_impact(model)}
    paths = []
    for name, doc in docs.items():
        p = out / name
        tmp = out / (name + ".tmp")
        tmp.write_text(canon(doc), encoding="utf-8")
        os.replace(tmp, p)
        paths.append(p)
    return paths
