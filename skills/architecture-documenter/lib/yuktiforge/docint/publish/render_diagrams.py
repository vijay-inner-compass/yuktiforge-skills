"""Render every diagram spec through the existing Architecture Visualizer pipeline, then apply the consistency / semantic / DFD-balance checks."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yuktiforge.docint.knowledge.schema import KnowledgeModel
from yuktiforge.docint.publish import diagrams as D
from yuktiforge.docint.publish import verify as VF
from yuktiforge.visualizer.model import canonical_json
from yuktiforge.visualizer.pipeline import build_diagram


@dataclass
class DiagramResult:
    spec: D.DiagramSpec
    dir: Path
    ok: bool
    render: dict[str, Any]
    consistency: dict[str, Any]
    semantic_errors: list[str]
    files: dict[str, str] = field(default_factory=dict)

    @property
    def errors(self) -> list[str]:
        out = list(self.semantic_errors) + list(self.consistency["errors"])
        if self.render.get("result") != "pass":
            out.append("render: " + "; ".join(i.get("message", "") for i in self.render.get("render_issues", []) + [x for x in self.render.get("model_issues", []) if x.get("severity") == "error"]))
        return out


def render_all(model: KnowledgeModel, out: Path) -> tuple[list[DiagramResult], list[D.Unsupported], dict[str, Any]]:
    specs, unsupported = D.build_all(model)
    results: list[DiagramResult] = []
    for s in specs:
        d = out / s.id
        res = build_diagram(s.model, s.view, d, input_note=f"knowledge model {model.scan_id}")
        (d / "mapping.json").write_text(json.dumps(s.mapping, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        cons = VF.consistency(s, model)
        sem = VF.semantic(s)
        (d / "checks.json").write_text(json.dumps({"consistency": cons, "semantic": sem, "view": s.view, "level": s.level, "notes": s.notes}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        same = (d / "architecture.json").read_text(encoding="utf-8") == canonical_json(s.model) if (d / "architecture.json").exists() else False
        if not same:
            sem.append("the architecture.json written by the renderer differs from the diagram specification")
        files = {p.name: p.name for p in sorted(d.iterdir()) if p.is_file()}
        results.append(DiagramResult(s, d, bool(res.ok) and not sem and not cons["errors"], res.report, cons, sem, files))
    bal = VF.balance(specs)
    summary = {"diagrams": len(results), "unsupported": [{"id": u.id, "view": u.view, "reason": u.reason} for u in unsupported], "dfd_balance_errors": bal,
               "failed": [r.spec.id for r in results if not r.ok]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "diagrams.json").write_text(json.dumps({"format": "yuktiforge-diagrams/1", "scan_id": model.scan_id, **summary,
                                                    "items": [{"id": r.spec.id, "view": r.spec.view, "title": r.spec.title, "purpose": r.spec.purpose, "level": r.spec.level, "ok": r.ok,
                                                               "elements": len(r.spec.model.components), "relations": len(r.spec.model.relations), "layout": r.render.get("layout", {}).get("chosen"),
                                                               "files": sorted(r.files), "notes": r.spec.notes, "errors": r.errors} for r in results]}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return results, unsupported, summary
