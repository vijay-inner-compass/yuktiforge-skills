"""Entry for the skills that also render, publish, audit or compare against git history: architecture-/data-/api-integration-/operations-documenter,
documentation-quality-auditor, documentation-publisher and the documentation-intelligence orchestrator."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yuktiforge.docint import safety as S
from yuktiforge.docint.cmds import cmd_docs_query, cmd_docs_scan
from yuktiforge.docint.skillmain import base, workspace

def _document(a: argparse.Namespace) -> int:
    spec = base.SKILLS[a.skill]
    out = Path(a.out)
    rc = workspace.run(a.repo, out, list(spec["types"]), a.audience, a.depth)
    if rc or a.no_diagrams:
        return rc
    return _diagrams_for(a.skill, out)


def _prepare(a: argparse.Namespace) -> int:
    return workspace.run(a.repo, Path(a.out), list(base.SKILLS[a.skill]["types"]), a.audience, a.depth)


def _diagrams_for(skill: str, out: Path) -> int:
    from yuktiforge.docint.publish.cli import cmd_diagrams
    return cmd_diagrams(argparse.Namespace(model=str(out / "model"), out=str(out / "diagrams")))


def _run_all(a: argparse.Namespace) -> int:
    out = Path(a.out)
    types = a.type or ["system-architecture", "hld", "api-catalog", "data-dictionary", "business-rule-catalog", "operations-runbook"]
    rc = workspace.run(a.repo, out, types, a.audience, a.depth)
    return rc or _diagrams_for("documentation-intelligence", out)


def build_parser(skill: str) -> argparse.ArgumentParser:
    spec = base.SKILLS[skill]
    allowed = spec["actions"]
    p = argparse.ArgumentParser(prog="yuktiforge_docs.py", description=f"{skill}: evidence-backed documentation from source, with diagrams, publishing and audit where this skill offers them")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<action>")
    from yuktiforge.docint.skillmain.tools_report import report
    base.doctor_parser(sub, skill, report)
    if "document" in allowed:
        c = sub.add_parser("document", help="scan, model and document the repository: " + ", ".join(spec["types"]) + " (and diagrams)")
        base.add_workspace_args(c, audience="architect")
        c.add_argument("--no-diagrams", action="store_true")
        c.set_defaults(fn=_document, skill=skill)
    if "prepare" in allowed:
        c = sub.add_parser("prepare", help="scan, model and generate a working set (" + ", ".join(spec["types"]) + ") when no other skill has produced one")
        base.add_workspace_args(c, audience="architect")
        c.set_defaults(fn=_prepare, skill=skill)
    if "run" in allowed:
        c = sub.add_parser("run", help="scan, model, a default document set and diagrams, in one step")
        base.add_workspace_args(c, audience="architect")
        c.add_argument("--type", action="append", help="document type id (repeatable); default: architecture, API, data, rules and operations documents")
        c.set_defaults(fn=_run_all, skill=skill)
    if "scan" in allowed:
        sc = sub.add_parser("scan", help="read-only static scan of a repository")
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
    if "model" in allowed:
        from yuktiforge.docint.knowledge.cli import add_model_commands
        add_model_commands(base.Allowed(sub, ("model",)))
    if {"types", "generate", "review"} & set(allowed):
        from yuktiforge.docint.docgen.cli import add_docgen_commands
        add_docgen_commands(base.Allowed(sub, [x for x in ("types", "generate", "review") if x in allowed]))
    if {"diagrams", "publish"} & set(allowed):
        from yuktiforge.docint.publish.cli import add_publish_commands
        add_publish_commands(base.Allowed(sub, [x for x in ("diagrams", "publish") if x in allowed]))
    if {"audit", "update"} & set(allowed):
        from yuktiforge.docint.audit.cli import add_audit_commands
        add_audit_commands(base.Allowed(sub, [x for x in ("audit", "update") if x in allowed]))
    return p


def main(argv: list[str] | None = None, skill: str = "documentation-intelligence") -> int:
    return base.run_main(build_parser(skill), argv)


if __name__ == "__main__":
    sys.exit(main())
