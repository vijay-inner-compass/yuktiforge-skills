"""End-to-end build: model -> validate -> DOT -> render -> inspect -> export.

Reuses Phase 1: RunStore (SQLite + artifacts) and the explicit state machine. Stage mapping:
  discover  inputs loaded (by caller)       specify  canonical model validated
  design    view selected, DOT built        generate sources written
  execute   external render                 evaluate rendered output inspected
  package   exports complete + checks pass  failed   any error-severity finding
`repair` is not implemented: a failing build ends in `failed`.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from yuktiforge.errors import YuktiForgeError
from yuktiforge.state import Stage
from yuktiforge.store import RunStore
from yuktiforge.visualizer import runner, svgcheck
from yuktiforge.visualizer.dotgen import DEFAULT_OPTIONS, LAYOUTS, VIEW_COVERAGE, RenderOptions, ViewResult, render_view
from yuktiforge.visualizer.model import ArchitectureModel, canonical_json
from yuktiforge.visualizer.validate import Issue, has_errors, validate_model

SKILL_ID = "architecture-visualizer"

# Layout-defect weights used to rank candidate layouts (lower is better). Any error outweighs every warning.
_WEIGHT = {"clipped": 0, "clipped-text": 0,   # estimate-based; real pixels decide (see below)
           "edges-coincide": 30, "label-detached": 20, "edge-crosses-title": 20, "edge-on-border": 10, "label-overlaps-node": 10}


def _score(issues: list[Issue]) -> int:
    return sum(1000 if i.severity == "error" else _WEIGHT.get(i.code, 1) for i in issues)


@dataclass
class BuildResult:
    ok: bool
    out_dir: Path
    run_id: str | None
    report: dict
    files: dict[str, Path] = field(default_factory=dict)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _preview_html(m: ArchitectureModel, vr: ViewResult, report: dict) -> str:
    e = escape
    comps = {c.id: c for c in m.components}
    def src(ev) -> str:
        return e("; ".join(f"{s.ref}" + (f" ({s.detail})" if s.detail else "") for s in ev.sources) or "—")
    crow = "".join(
        f"<tr><td>{e(comps[i].name or i)}</td><td>{e(comps[i].kind)}</td><td class='{comps[i].evidence.status}'>"
        f"{e(comps[i].evidence.status)}</td><td>{src(comps[i].evidence)}</td></tr>" for i in sorted(vr.components))
    rels = {r.id: r for r in m.relations}
    rrow = "".join(
        f"<tr><td>{e(comps[rels[i].source].name or rels[i].source)} → {e(comps[rels[i].target].name or rels[i].target)}</td>"
        f"<td>{e(rels[i].label)}</td><td class='{rels[i].evidence.status}'>{e(rels[i].evidence.status)}</td>"
        f"<td>{src(rels[i].evidence)}{(' — ' + e(rels[i].evidence.rationale)) if rels[i].evidence.rationale else ''}</td></tr>"
        for i in sorted(vr.relations))
    issues = "".join(f"<li class='{e(i['severity'])}'>{e(i['severity'])}: {e(i['code'])} — {e(i['message'])}</li>"
                     for i in report["model_issues"] + report["render_issues"]) or "<li>none</li>"
    langs = "".join(f"<tr><td>{e(l['language'])}</td><td>{l['files']}</td><td>{e(l['depth'])}</td>"
                    f"<td>{e(', '.join(l['analyzers']) or 'NONE — not analyzed')}</td></tr>"
                    for l in report["coverage"]["languages"]) or "<tr><td colspan='4'>no source repository analyzed</td></tr>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'">
<title>{e(m.name or 'Architecture')} — {e(vr.view)}</title>
<style>
body{{font-family:Helvetica,Arial,sans-serif;color:#1F2937;margin:0;background:#fff}}
main{{max-width:1200px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px}} h2{{font-size:16px;margin-top:28px}}
img{{max-width:100%;height:auto;border:1px solid #CBD5E1;border-radius:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #E5E7EB;padding:6px 8px;text-align:left;vertical-align:top}}
.verified{{color:#334155;font-weight:600}} .user-supplied{{color:#1D4ED8}} .inferred{{color:#B45309;font-style:italic}}
.error{{color:#B91C1C}} .warning{{color:#B45309}} .pass{{color:#047857}} .fail{{color:#B91C1C}}
</style></head><body><main>
<h1>{e(m.name or 'Architecture')} — {e(vr.view)} view</h1>
<p>Result: <b class="{report['result']}">{e(report['result'].upper())}</b> · view coverage:
{e(VIEW_COVERAGE[vr.view]['status'])} — {e(VIEW_COVERAGE[vr.view]['note'])}</p>
<img src="diagram.svg" alt="{e(vr.view)} architecture diagram of {e(m.name or 'the system')}">
<h2>Components ({len(vr.components)})</h2>
<table><tr><th>Name</th><th>Kind</th><th>Evidence</th><th>Sources</th></tr>{crow}</table>
<h2>Relations ({len(vr.relations)})</h2>
<table><tr><th>Edge</th><th>Label</th><th>Evidence</th><th>Sources / rationale</th></tr>{rrow}</table>
<h2>Source coverage</h2>
<table><tr><th>Language</th><th>Files</th><th>Depth</th><th>Analyzers</th></tr>{langs}</table>
{''.join(f'<p>{e(n)}</p>' for n in report['coverage']['notes'])}
{''.join(f'<p class="warning">Could not parse <code>{e(f)}</code>: its relations are unknown, not absent.</p>' for f in report['coverage'].get('unparsed_files', []))}
<h2>Validation findings</h2><ul>{issues}</ul>
<p>Machine-readable: validation.json · architecture.json · diagram.dot</p>
</main></body></html>
"""


def build_diagram(model: ArchitectureModel, view: str, out_dir: str | Path, *,
                  store: RunStore | None = None, input_note: str = "",
                  options: RenderOptions = DEFAULT_OPTIONS) -> BuildResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = store.create_run(SKILL_ID, max_repairs=len(LAYOUTS)) if store else None
    files: dict[str, Path] = {}

    def advance(stage: Stage, note: str = "") -> None:
        if store and run_id:
            store.advance(run_id, stage, note)

    def emit(name: str, data: bytes, stage: Stage) -> None:
        (out / name).write_bytes(data)
        files[name] = out / name
        if store and run_id:
            store.put_artifact(run_id, stage, f"exports/{name}", data)

    report: dict = {"skill": SKILL_ID, "view": view, "run_id": run_id, "input": input_note, "render_options": options.as_dict(),
                    "tools": {}, "model_issues": [], "render_issues": [], "exports": {},
                    "coverage": json.loads(model.coverage.model_dump_json()),
                    "view_coverage": VIEW_COVERAGE.get(view, {"status": "unknown", "note": ""}),
                    "result": "fail"}

    def finish(stage_note: str, final: Stage) -> BuildResult:
        report["result"] = "pass" if final is Stage.PACKAGE else "fail"
        data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        (out / "validation.json").write_bytes(data)
        files["validation.json"] = out / "validation.json"
        if store and run_id:
            store.put_artifact(run_id, Stage.EVALUATE, "exports/validation.json", data)
        advance(final, stage_note)
        return BuildResult(final is Stage.PACKAGE, out, run_id, report, files)

    advance(Stage.SPECIFY, "canonical model built")
    issues = validate_model(model)
    report["model_issues"] = [i.as_dict() for i in issues]
    emit("architecture.json", canonical_json(model).encode(), Stage.SPECIFY)
    report["evidence_summary"] = {s: sum(1 for x in (*model.components, *model.relations) if x.evidence.status == s)
                                  for s in ("verified", "user-supplied", "inferred")}
    if has_errors(issues):
        advance(Stage.DESIGN, "skipped: model invalid")
        report["render_skipped"] = "model validation errors; nothing was rendered"
        return finish("model validation failed", Stage.FAILED)

    advance(Stage.DESIGN, f"view={view}")
    try:
        vr = render_view(model, view, 0, options)          # candidate 0; later candidates are tried only if this one has defects
    except YuktiForgeError as e:
        report["render_issues"].append(Issue("view-unavailable", "error", str(e)).as_dict())
        return finish(str(e), Stage.FAILED)
    advance(Stage.GENERATE, "diagram source written")
    emit("diagram.dot", vr.dot.encode(), Stage.GENERATE)

    # ---- execute/evaluate/repair: render each layout candidate, inspect it, keep the best -------------------
    advance(Stage.EXECUTE, f"render layout {LAYOUTS[0]['name']}")
    try:
        report["tools"] = {"dot": runner.tool_version("dot"), "rsvg-convert": runner.tool_version("rsvg-convert")}
    except YuktiForgeError as e:
        report["render_issues"].append(Issue("render-failed", "error", str(e)).as_dict())
        return finish(str(e), Stage.FAILED)
    trials: list[dict] = []
    best: tuple[int, int, ViewResult, bytes, list[Issue]] | None = None
    for idx in range(len(LAYOUTS)):
        cand = vr if idx == 0 else render_view(model, view, idx, options)
        names = {c.id: c.name for c in model.components if c.id in set(cand.components)}
        rels = {r.id: (r.source, r.target) for r in model.relations if r.id in set(cand.relations)}
        try:
            res = runner.dot_to_svg(cand.dot)
        except YuktiForgeError as e:
            report["render_issues"].append(Issue("render-failed", "error", str(e)).as_dict())
            report["exports"]["svg"] = {"status": "failed", "reason": str(e)}
            return finish(str(e), Stage.FAILED)
        found = [Issue("renderer-warning", "warning", l.strip()) for l in res.stderr.splitlines() if l.strip()]
        found += svgcheck.check_svg(res.stdout, names, rels, cand.layer_order)
        sc = _score(found)
        trials.append({"layout": LAYOUTS[idx]["name"], "score": sc, "findings": sorted({i.code for i in found})})
        if best is None or sc < best[0]:
            best = (sc, idx, cand, res.stdout, found)
        advance(Stage.EVALUATE, f"layout {LAYOUTS[idx]['name']} score {sc}")
        if sc == 0 or idx == len(LAYOUTS) - 1:
            break
        advance(Stage.REPAIR, f"layout defects {trials[-1]['findings']}; trying next layout")
        advance(Stage.EXECUTE, f"render layout {LAYOUTS[idx + 1]['name']}")
    assert best is not None
    _, bidx, vr, svg, render_issues = best
    report["layout"] = {"chosen": LAYOUTS[bidx]["name"], "trials": trials}
    report["view_stats"] = {"components": len(vr.components), "relations": len(vr.relations),
                            "omitted_components": vr.omitted_components, "omitted_relations": vr.omitted_relations,
                            "notes": vr.notes}
    names = {c.id: c.name for c in model.components if c.id in set(vr.components)}
    rels = {r.id: (r.source, r.target) for r in model.relations if r.id in set(vr.relations)}
    emit("diagram.dot", vr.dot.encode(), Stage.GENERATE)
    emit("diagram.svg", svg, Stage.EXECUTE)
    report["exports"]["svg"] = {"status": "ok", "file": "diagram.svg", "sha256": _sha(svg), "bytes": len(svg)}
    for fmt in ("png", "pdf"):
        if runner.tool_path("rsvg-convert") is None:
            report["exports"][fmt] = {"status": "unavailable", "reason": "rsvg-convert not found on PATH"}
            continue
        try:
            data = runner.svg_to(fmt, svg).stdout
        except YuktiForgeError as e:
            report["exports"][fmt] = {"status": "failed", "reason": str(e)}
            render_issues.append(Issue(f"{fmt}-export-failed", "error", str(e)))
            continue
        emit(f"diagram.{fmt}", data, Stage.EVALUATE)
        report["exports"][fmt] = {"status": "ok", "file": f"diagram.{fmt}", "sha256": _sha(data), "bytes": len(data)}
    try:
        doc = svgcheck.parse_svg(svg)
        if "diagram.png" in files:
            render_issues += svgcheck.check_png(files["diagram.png"].read_bytes(), doc.width, doc.height)
        if "diagram.pdf" in files:
            render_issues += svgcheck.check_pdf(files["diagram.pdf"].read_bytes())
        if "diagram.png" in files:    # clipping judged on real pixels (a half-size raster keeps the stdlib-only decoder fast)
            small = runner.svg_to("png", svg, zoom=0.5).stdout
            render_issues += svgcheck.check_png_margins(small)
            margins = svgcheck.png_ink_margins(small)
            if margins is not None and min(margins) >= 2:
                # real pixels refute text-width ESTIMATES: drop estimate-based clipping warnings, keep the measurement
                render_issues = [i for i in render_issues if not (i.severity == "warning" and i.code in ("clipped", "clipped-text"))]
                report["png_clear_margin_px_at_half_size"] = {"left": margins[0], "top": margins[1], "right": margins[2], "bottom": margins[3]}
    except (ValueError, ET.ParseError) as e:  # parse failure is normally already reported by check_svg
        if not any(i.code == "svg-unparseable" for i in render_issues):
            render_issues.append(Issue("svg-unparseable", "error", str(e)))
    report["render_issues"] = [i.as_dict() for i in render_issues]
    report["semantic_comparison"] = {
        "model_components_in_view": len(names), "model_relations_in_view": len(rels),
        "svg_matches_model": not any(i.code.startswith(("node-", "edge-", "label-mismatch")) for i in render_issues)}
    ok = not has_errors(render_issues)
    preview_report = dict(report, result="pass" if ok else "fail")
    emit("preview.html", _preview_html(model, vr, preview_report).encode(), Stage.EVALUATE)
    report["exports"]["html"] = {"status": "ok", "file": "preview.html"}
    report["exports"]["architecture_json"] = {"status": "ok", "file": "architecture.json"}
    report["exports"]["source"] = {"status": "ok", "file": "diagram.dot", "format": "graphviz-dot"}
    return finish("all checks passed" if ok else "render checks failed", Stage.PACKAGE if ok else Stage.FAILED)
