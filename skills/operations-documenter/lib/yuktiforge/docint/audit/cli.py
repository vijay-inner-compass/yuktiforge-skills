"""`yuktiforge docs audit --input <docs> --model <model>` and `docs update --model <model> --docs <docs> --repo <repo> [--since REV] [--apply]` (D5)."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from yuktiforge.docint.audit import evaluation as E
from yuktiforge.docint.audit import html as H
from yuktiforge.docint.audit import loader, update
from yuktiforge.docint.docgen.outputs import canon
from yuktiforge.errors import YuktiForgeError


def cmd_audit(a: argparse.Namespace) -> int:
    docs, ddir = loader.load_documents(Path(a.input))
    model_dir = Path(a.model) if a.model else None
    if model_dir is None:
        for c in (Path(a.input), Path(a.input) / "..", Path(a.input) / ".." / "model"):
            if (c / "system-knowledge.json").is_file() or (c / "source" / "system-knowledge.json").is_file():
                model_dir = c
                break
    if model_dir is None:
        raise YuktiForgeError("no knowledge model found: pass --model <dir written by `docs model build`>")
    model = loader.load_model(model_dir)
    ev = E.evaluate(docs, model, repo=Path(a.repo) if a.repo else None, review_db=loader.load_review(ddir), glossary=loader.load_glossary(ddir))
    out = Path(a.out) if a.out else ddir / "audit"
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(canon(ev), encoding="utf-8")
    (out / "coverage.html").write_text(H.render(ev), encoding="utf-8")
    e = ev["evidence"]
    print(f"audited {len(docs)} document(s), {e['statements']} statements against model {ev['model_scan_id']}")
    print(f"evidence    : {e['with_evidence']}/{e['statements']} cite evidence; {e['verified_with_valid_pointer']}/{e['verified']} VERIFIED have a valid pointer; labels {e['labels']}")
    f = ev["freshness"]
    print("freshness   : " + (f"{f['stale_or_missing']} stale or missing of {f['evidence_checked']} evidence records" if f["checked"] else "NOT_TESTED (" + f["reason"] + ")"))
    cov = ev["coverage"]
    print("coverage    : " + ", ".join(f"{t} {v['documented']}/{v['total']}" for t, v in cov["scope"].items()) + f"; document types missing: {', '.join(cov['document_types']['missing']) or 'none'}")
    for k, g in ev["gates"].items():
        print(f"  {g['status']:11s} {k}: {g['detail']}")
    print(f"wrote {out / 'evaluation.json'} and {out / 'coverage.html'}")
    return 0 if ev["verdict"]["passed"] else 1


def cmd_update(a: argparse.Namespace) -> int:
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="yuktiforge-update-"))
    p = update.plan(Path(a.model), Path(a.docs), Path(a.repo), since=a.since, work=work)
    out = Path(a.out) if a.out else Path(a.docs) / "update"
    out.mkdir(parents=True, exist_ok=True)
    (out / "change-report.md").write_text(update.change_report(p), encoding="utf-8")
    (out / "change-impact.json").write_text(canon(update.change_json(p)), encoding="utf-8")
    if p.unchanged:
        print("no change reaches the documentation: nothing to regenerate")
    else:
        ents = p.entities
        print(f"entities: {len(ents['added'])} added, {len(ents['removed'])} removed, {len(ents['changed'])} changed; relationships {p.relationships}")
        for d in p.documents:
            if d["changed_sections"] or d["added_sections"] or d["removed_sections"]:
                print(f"  {d['document']:24s} changed {d['changed_sections']} added {d['added_sections']} removed {d['removed_sections']}" + (f"  approvals becoming STALE: {d['approvals_that_become_stale']}" if d.get("approvals_that_become_stale") else ""))
        print(f"diagrams: {p.diagrams}")
    if not p.git["available"]:
        print(f"note: revision comparison unavailable ({p.git.get('reason')}); compared the stored model with a fresh scan")
    if a.apply:
        written = update.apply(p, Path(a.model), Path(a.docs))
        print("applied: " + (", ".join(written) if written else "nothing was rewritten"))
    else:
        print("dry run: add --apply to regenerate the sections listed above")
    print(f"wrote {out / 'change-report.md'} and {out / 'change-impact.json'}")
    return 0


def add_audit_commands(ds) -> None:
    au = ds.add_parser("audit", help="measure the correctness, coverage and freshness of generated documents against the knowledge model (gates PASS / FAIL / NOT_TESTED)")
    au.add_argument("--input", required=True, help="directory written by `docs generate` (or a publish pack)")
    au.add_argument("--model", help="directory written by `docs model build` (default: found next to the input)")
    au.add_argument("--repo", help="the repository: lets the audit check that cited text still exists (freshness)")
    au.add_argument("--out", help="where evaluation.json and coverage.html go (default <input>/audit)")
    au.set_defaults(fn=cmd_audit)
    up = ds.add_parser("update", help="what changed since a revision, which documents/sections/diagrams it affects, and (with --apply) regenerate only those")
    up.add_argument("--model", required=True)
    up.add_argument("--docs", required=True, help="directory written by `docs generate`")
    up.add_argument("--repo", required=True)
    up.add_argument("--since", help="git revision to compare against (default: the revision the model was built at)")
    up.add_argument("--apply", action="store_true", help="write the new model and regenerate the changed sections (default: dry run)")
    up.add_argument("--out", help="where change-report.md and change-impact.json go (default <docs>/update)")
    up.add_argument("--work", help="scratch directory for the fresh scan")
    up.set_defaults(fn=cmd_update)
