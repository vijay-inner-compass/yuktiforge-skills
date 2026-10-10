"""`yuktiforge viz ...` commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from yuktiforge.errors import YuktiForgeError
from yuktiforge.store import RunStore
from yuktiforge.visualizer.analyzers import analyze_repository, discover_capabilities
from yuktiforge.visualizer.dotgen import VIEW_COVERAGE
from yuktiforge.visualizer.model import ArchitectureModel, canonical_json, load_model, merge_models
from yuktiforge.visualizer.pipeline import build_diagram
from yuktiforge.visualizer.validate import validate_model


def _load(a: argparse.Namespace) -> tuple[ArchitectureModel, str]:
    if bool(a.model) == bool(a.repo):
        raise YuktiForgeError("give exactly one of --model (structured YAML/JSON) or --repo (source repository)")
    if a.model:
        if a.overlay:
            raise YuktiForgeError("--overlay only applies with --repo")
        return load_model(a.model), f"model:{a.model}"
    base = analyze_repository(a.repo, a.granularity)
    if a.overlay:
        return merge_models(base, load_model(a.overlay)), f"repo:{a.repo} + overlay:{a.overlay} ({a.granularity})"
    return base, f"repo:{a.repo} ({a.granularity})"


def cmd_views(a: argparse.Namespace) -> int:
    for v, c in VIEW_COVERAGE.items():
        print(f"{v:14s} {c['status']:16s} {c['note']}")
    return 0


def cmd_analyzers(a: argparse.Namespace) -> int:
    print(json.dumps([c.__dict__ for c in discover_capabilities()], indent=2))
    return 0


def cmd_analyze(a: argparse.Namespace) -> int:
    model, _ = _load(a)
    print(canonical_json(model), end="")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    model, _ = _load(a)
    issues = validate_model(model)
    for i in issues:
        print(f"{i.severity}: {i.code}: {i.message}")
    errs = sum(i.severity == "error" for i in issues)
    print(f"{len(model.components)} components, {len(model.relations)} relations, {errs} error(s), "
          f"{len(issues) - errs} warning(s)")
    return 1 if errs else 0


def cmd_build(a: argparse.Namespace) -> int:
    model, note = _load(a)
    home = getattr(a, "home", None)             # global option of the full CLI; the standalone skill supplies a temporary one
    store = RunStore(Path(home) if home else Path.cwd() / ".yuktiforge")
    res = build_diagram(model, a.view, a.out, store=store, input_note=note)
    r = res.report
    print(f"{'PASS' if res.ok else 'FAIL'}  view={a.view}  run={res.run_id}  out={res.out_dir}")
    for fmt, e in r["exports"].items():
        print(f"  {fmt:18s} {e['status']}" + (f" ({e['reason']})" if e.get("reason") else ""))
    for i in r["model_issues"] + r["render_issues"]:
        print(f"  {i['severity']}: {i['code']}: {i['message']}")
    return 0 if res.ok else 1


def cmd_package(a: argparse.Namespace) -> int:
    from yuktiforge.visualizer.skillpkg import build_skill_package      # lazy: the standalone skill bundle does not need the Creator's packager
    dest = build_skill_package(a.out)
    print(f"skill package written: {dest}")
    for p in sorted(x for x in dest.rglob('*') if x.is_file()):
        print(f"  {p.relative_to(dest)}")
    return 0


def add_viz_commands(sub: argparse._SubParsersAction) -> None:
    v = sub.add_parser("viz", help="architecture-visualizer: model, analyze, render")
    vs = v.add_subparsers(dest="sub", required=True, metavar="<action>")
    add_viz_actions(vs)


def add_viz_actions(vs: argparse._SubParsersAction, standalone: bool = False) -> None:
    """The visualizer's actions. `standalone` omits `package` (builds the Creator's own skill package; not part of the shipped skill)."""
    vs.add_parser("views", help="list view types and honest coverage status").set_defaults(fn=cmd_views)
    vs.add_parser("analyzers", help="list repository analyzer capabilities").set_defaults(fn=cmd_analyzers)

    def inputs(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", help="structured architecture model (.yaml/.json)")
        p.add_argument("--repo", help="source repository directory (any language; analyzers report coverage)")
        p.add_argument("--overlay", help="user-supplied model merged over analyzer output (with --repo)")
        p.add_argument("--granularity", choices=["package", "module"], default="package")

    an = vs.add_parser("analyze", help="print the canonical model JSON for an input")
    inputs(an)
    an.set_defaults(fn=cmd_analyze)
    va = vs.add_parser("validate", help="validate the model (ids, dangling edges, duplicates, evidence)")
    inputs(va)
    va.set_defaults(fn=cmd_validate)
    if not standalone:
        pk = vs.add_parser("package", help="build the architecture-visualizer skill package (SKILL.md + references)")
        pk.add_argument("--out", required=True)
        pk.set_defaults(fn=cmd_package)
    b = vs.add_parser("build", help="validate, render and export a diagram bundle")
    inputs(b)
    b.add_argument("--view", default="layered")
    b.add_argument("--out", required=True)
    b.set_defaults(fn=cmd_build)
