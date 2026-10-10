"""Entry for the skills that only read files and write documents: code-explainer, behavior-reconstructor, requirements-reconstructor. No diagram, publishing or git code is part of this tier."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yuktiforge.docint.skillmain import base, workspace


def _document(a: argparse.Namespace) -> int:
    types = base.SKILLS[a.skill]["types"]
    return workspace.run(a.repo, Path(a.out), list(types), a.audience, a.depth, getattr(a, "scope", None))


def build_parser(skill: str) -> argparse.ArgumentParser:
    spec = base.SKILLS[skill]
    p = argparse.ArgumentParser(prog="yuktiforge_docs.py", description=f"{skill}: evidence-backed documentation reconstructed from source, read-only")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<action>")
    base.doctor_parser(sub, skill)
    for name in ("explain", "reconstruct"):
        if name in spec["actions"]:
            c = sub.add_parser(name, help="scan the repository, build the knowledge model and write the documents of this skill: " + ", ".join(spec["types"]))
            base.add_workspace_args(c, audience="developer" if name == "explain" else "ba")
            if name == "explain":
                c.add_argument("--scope", help="module:<path> or symbol:<qualified name> (default: the whole repository)")
            c.set_defaults(fn=_document, skill=skill)
    if "model" in spec["actions"]:
        from yuktiforge.docint.knowledge.cli import add_model_commands
        add_model_commands(base.Allowed(sub, ("model",)))
    return p


def main(argv: list[str] | None = None, skill: str = "code-explainer") -> int:
    return base.run_main(build_parser(skill), argv)


if __name__ == "__main__":
    sys.exit(main())
