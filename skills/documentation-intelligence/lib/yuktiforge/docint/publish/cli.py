"""`yuktiforge docs diagrams | publish | tools` (D4)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from yuktiforge.docint.docgen.doc import AUDIENCES
from yuktiforge.docint.knowledge.migrate import load_model_file
from yuktiforge.docint.publish import pack, tools
from yuktiforge.docint.publish.render_diagrams import render_all
from yuktiforge.errors import YuktiForgeError


def _model(path: str):
    m, _ = load_model_file(Path(path) / "system-knowledge.json")
    return m


def cmd_diagrams(a: argparse.Namespace) -> int:
    results, unsupported, summary = render_all(_model(a.model), Path(a.out))
    for r in results:
        print(f"{r.spec.id:34s} {r.spec.view:13s} {len(r.spec.model.components):3d} elements {len(r.spec.model.relations):3d} relations  {'OK' if r.ok else 'FAIL'}")
        for e in r.errors[:5]:
            print(f"    ERROR {e}")
    for u in unsupported:
        print(f"{u.id:34s} {u.view:13s} NOT GENERATED: {u.reason}")
    for e in summary["dfd_balance_errors"]:
        print(f"DFD BALANCE ERROR: {e}")
    print(f"wrote {len(results)} diagram(s) to {a.out} (diagrams.json)")
    return 1 if summary["failed"] or summary["dfd_balance_errors"] else 0


def cmd_publish(a: argparse.Namespace) -> int:
    formats = tuple(x.strip() for x in a.formats.split(",") if x.strip())
    rep = pack.publish(_model(a.model), Path(a.out), formats=formats, title=a.title, types=a.type, audience=a.audience, depth=a.depth)
    bad = 0
    for fmt, e in rep["exports"].items():
        extra = "" if e["status"] in ("ok",) else f" ({e.get('reason') or e.get('link_problems') or ''})"
        print(f"{fmt:5s} {e['status']}{extra}" + (f"  {e.get('pages', '')} pages" if e.get("pages") else ""))
        bad += e["status"] not in ("ok", "UNAVAILABLE")
    for k, v in rep["qa"].items():
        s = v.get("status") or (v["structure"]["status"], v["visual"]["status"])
        print(f"QA {k}: {s}")
    d = rep["diagrams"]
    print(f"diagrams: {d['diagrams']} generated, {len(d['unsupported'])} not generated, {len(d['failed'])} failed, {len(d['dfd_balance_errors'])} DFD balance error(s)")
    print(f"pack written to {a.out} ({rep['files']} files; pack-manifest.json, visual-qa.json, links.json)")
    return 1 if bad or d["failed"] or d["dfd_balance_errors"] else 0


def cmd_tools(a: argparse.Namespace) -> int:
    for name, info in tools.tool_report().items():
        print(f"{name:20s} {info['path'] or 'NOT FOUND':50s} {info['version'] or ''}")
    return 0


def add_publish_commands(ds) -> None:
    d = ds.add_parser("diagrams", help="render architecture, data-flow, ERD and other diagrams from the knowledge model through the Architecture Visualizer, with source-to-diagram checks")
    d.add_argument("--model", required=True)
    d.add_argument("--out", required=True)
    d.set_defaults(fn=cmd_diagrams)
    p = ds.add_parser("publish", help="build the documentation pack: Markdown sources, diagrams, HTML site, DOCX and A4 PDF, with link and visual QA")
    p.add_argument("--model", required=True, help="directory written by `docs model build`")
    p.add_argument("--out", required=True)
    p.add_argument("--formats", default="html,docx,pdf", help="comma separated: html, docx, pdf")
    p.add_argument("--title", default="Knowledge transfer pack")
    p.add_argument("--audience", default="architect", choices=AUDIENCES)
    p.add_argument("--depth", default="summary", choices=["summary", "deep"])
    p.add_argument("--type", action="append", help="document type id (repeatable); default: every type offered for the audience")
    p.set_defaults(fn=cmd_publish)
    t = ds.add_parser("tools", help="show which publishing tools are available (pandoc, Chromium, LibreOffice, Graphviz, ...)")
    t.set_defaults(fn=cmd_tools)
