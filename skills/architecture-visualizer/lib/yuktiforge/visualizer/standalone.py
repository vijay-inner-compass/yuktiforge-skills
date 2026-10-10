"""Entry point of the SHIPPED architecture-visualizer skill (scripts/yuktiforge_viz.py calls `main`). It exposes the visualizer's
actions without the rest of the YuktiForge CLI so the skill can be installed without the Creator. `doctor` reports what the
skill needs: Python packages, external tools, and whether PNG/PDF export is possible."""
from __future__ import annotations

import argparse
import importlib
import sys
import tempfile

from yuktiforge.errors import YuktiForgeError
from yuktiforge.visualizer import runner
from yuktiforge.visualizer.cli import add_viz_actions

PY_PACKAGES = (("pydantic", "model validation"), ("yaml", "reading YAML models (PyYAML)"))
TOOLS = (("dot", "Graphviz layout and SVG (required to build)"), ("rsvg-convert", "PNG/PDF export (optional; without it only SVG/HTML)"))


def cmd_doctor(a: argparse.Namespace) -> int:
    ok = True
    print(f"python {sys.version.split()[0]} at {sys.executable}")
    for mod, why in PY_PACKAGES:
        try:
            m = importlib.import_module(mod)
            print(f"python package {mod}: ok ({getattr(m, '__version__', 'version unknown')}) - {why}")
        except ImportError:
            ok = False
            print(f"python package {mod}: MISSING - {why}")
    for tool, why in TOOLS:
        v = runner.tool_version(tool)
        print(f"tool {tool}: {'ok (' + v + ')' if v else 'NOT FOUND'} - {why}")
        ok = ok and (v is not None or tool == "rsvg-convert")
    if not ok:
        print("not ready: install the missing items (see INSTALL.md in the skill folder); nothing was installed for you")
    return 0 if ok else 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yuktiforge_viz.py", description="architecture-visualizer (standalone skill entry point)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<action>")
    sub.add_parser("doctor", help="check Python packages and external tools").set_defaults(fn=cmd_doctor)
    add_viz_actions(sub, standalone=True)
    p.add_argument("--home", help="run-state directory (default: a temporary one that is deleted afterwards; nothing is written to your project)")
    return p


def actions() -> set[str]:
    """The actions the shipped skill really has (used to check that SKILL.md only tells an agent to run those)."""
    return set(next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)).choices)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.home:
            return args.fn(args)
        with tempfile.TemporaryDirectory(prefix="yuktiforge-viz-") as tmp:
            args.home = tmp
            return args.fn(args)
    except YuktiForgeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
