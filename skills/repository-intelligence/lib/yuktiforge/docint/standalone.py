"""Entry point of the shipped Documentation Intelligence skills: `python3 scripts/yuktiforge_docs.py <action>`. It carries only the actions of the skill it ships
with and needs nothing but the packages pinned in the skill's `requirements.lock` (pydantic, PyYAML)."""
from __future__ import annotations

import argparse
import sys

from yuktiforge.docint.cmds import cmd_docs_query, cmd_docs_scan
from yuktiforge.docint import safety as S
from yuktiforge.errors import YuktiForgeError

NEEDS = ("pydantic", "yaml")
ACTIONS_BY_SKILL = {"repository-intelligence": ("doctor", "scan", "query")}


def actions(skill: str = "repository-intelligence") -> frozenset[str]:
    return frozenset(ACTIONS_BY_SKILL[skill])


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
    if missing:
        print("missing packages: see INSTALL.md (scripts/bootstrap.py builds a private environment from requirements.lock); nothing was installed")
        return 1
    print("ready: scan reads files only and never executes, builds or installs anything")
    return 0


def build_parser(skill: str = "repository-intelligence") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yuktiforge_docs.py", description="Repository intelligence: static, read-only scan of a source repository")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<action>")
    allowed = actions(skill)
    if "doctor" in allowed:
        sub.add_parser("doctor", help="check this skill's prerequisites").set_defaults(fn=cmd_doctor)
    if "scan" in allowed:
        sc = sub.add_parser("scan", help="scan a repository")
        sc.add_argument("--repo", default=".")
        sc.add_argument("--out", required=True)
        sc.add_argument("--cache")
        sc.add_argument("--no-cache", action="store_true")
        sc.add_argument("--max-seconds", type=float)
        sc.add_argument("--max-file-bytes", type=int, default=S.DEFAULT_LIMITS.max_file_bytes)
        sc.add_argument("--max-files", type=int, default=S.DEFAULT_LIMITS.max_files)
        sc.add_argument("--include-generated", action="store_true")
        sc.set_defaults(fn=cmd_docs_scan)
    if "query" in allowed:
        q = sub.add_parser("query", help="compact answers from a finished scan")
        q.add_argument("--scan", required=True)
        q.add_argument("--boundary")
        q.add_argument("--symbol")
        q.add_argument("--file")
        q.add_argument("--coverage", action="store_true")
        q.add_argument("--unresolved", action="store_true")
        q.set_defaults(fn=cmd_docs_query)
    return p


def main(argv: list[str] | None = None, skill: str = "repository-intelligence") -> int:
    args = build_parser(skill).parse_args(argv)
    try:
        return args.fn(args)
    except YuktiForgeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
