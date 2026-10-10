"""Shared by the skill entry points: the per-skill action table, the doctor, and the argparse plumbing. No heavy imports here, so a skill's vendored code stays what it needs."""
from __future__ import annotations

import argparse
import sys

from yuktiforge.errors import YuktiForgeError

# skill -> (actions, default document types, diagram views the skill is about; None = all). "run" = scan -> model -> documents (-> diagrams).
SKILLS: dict[str, dict] = {
    "documentation-intelligence": dict(actions=("doctor", "run", "scan", "query", "model", "types", "generate", "review", "diagrams", "publish", "audit", "update"),
                                       types=None, tier="full"),
    "code-explainer": dict(actions=("doctor", "explain"), types=("code-explanation",), tier="core"),
    "behavior-reconstructor": dict(actions=("doctor", "reconstruct", "model"), types=("functional-spec", "business-rule-catalog", "use-cases"), tier="core"),
    "requirements-reconstructor": dict(actions=("doctor", "reconstruct", "model"), types=("brd-draft", "srs-draft", "business-rule-catalog"), tier="core"),
    "architecture-documenter": dict(actions=("doctor", "document", "diagrams"), types=("system-architecture", "solution-architecture", "technology-architecture", "hld", "lld"), tier="full"),
    "data-documenter": dict(actions=("doctor", "document", "diagrams"), types=("data-dictionary", "database-doc"), tier="full"),
    "api-integration-documenter": dict(actions=("doctor", "document", "diagrams"), types=("api-catalog", "dataflow"), tier="full"),
    "operations-documenter": dict(actions=("doctor", "document", "diagrams"), types=("operations-runbook",), tier="full"),
    "documentation-quality-auditor": dict(actions=("doctor", "prepare", "audit", "update", "review"), types=("system-architecture", "api-catalog", "data-dictionary"), tier="full"),
    "documentation-publisher": dict(actions=("doctor", "prepare", "publish", "diagrams"), types=("system-architecture", "api-catalog", "data-dictionary"), tier="full"),
}
NEEDS = ("pydantic", "yaml")


def cmd_doctor(a: argparse.Namespace) -> int:
    missing = []
    try:
        import pydantic  # noqa: F401
    except ImportError:
        missing.append("pydantic")
    try:
        import yaml  # noqa: F401
    except ImportError:
        missing.append("yaml")
    print(f"interpreter {sys.version.split()[0]}")
    for m in NEEDS:
        print(f"  {m:10s} {'MISSING' if m in missing else 'ok'}")
    tier = SKILLS[a.skill]["tier"]
    if tier == "full" and a.report:
        a.report()
    if missing:
        print("missing packages: see INSTALL.md (scripts/bootstrap.py builds a private environment from requirements.lock); nothing was installed")
        return 1
    print("ready: the repository is only read; nothing is executed, built or installed" + ("; optional publishing tools are reported above" if tier == "full" else ""))
    return 0


def run_main(parser: argparse.ArgumentParser, argv: list[str] | None) -> int:
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except YuktiForgeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def doctor_parser(sub, skill: str, report=None) -> None:
    """`report` (optional) prints extra facts, such as which rendering tools exist; the core tier has none and must not import them."""
    sub.add_parser("doctor", help="check this skill's prerequisites").set_defaults(fn=cmd_doctor, skill=skill, report=report)


class Allowed:
    """Stands in for an argparse sub-parser group: commands outside the skill's action list are parsed into a throw-away parser, so the skill's CLI offers only its own actions."""

    def __init__(self, sub, allowed):
        self.sub, self.allowed = sub, frozenset(allowed)

    def add_parser(self, name, **kw):
        if name in self.allowed:
            return self.sub.add_parser(name, **kw)
        return argparse.ArgumentParser(prog="_unused_")


def add_workspace_args(p: argparse.ArgumentParser, *, audience: str, depth: str = "summary") -> None:
    from yuktiforge.docint.docgen.doc import AUDIENCES
    p.add_argument("--repo", default=".", help="repository root (read only)")
    p.add_argument("--out", required=True, help="workspace directory: scan/, model/, docs/ (and diagrams/) are written under it")
    p.add_argument("--audience", default=audience, choices=AUDIENCES)
    p.add_argument("--depth", default=depth, choices=["summary", "deep"])
