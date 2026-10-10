"""`yuktiforge docs types | generate | review` (D3)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from yuktiforge.docint.docgen import engine, registry, review as R
from yuktiforge.docint.docgen.doc import AUDIENCES, Document
from yuktiforge.docint.docgen.outputs import write_documents
from yuktiforge.docint.docgen.regen import regenerate
from yuktiforge.docint.knowledge.migrate import load_model_file
from yuktiforge.errors import YuktiForgeError

REVIEW_FILE = "review.json"


def _model(path: str):
    m, _ = load_model_file(Path(path) / "system-knowledge.json")
    return m


def cmd_types(a: argparse.Namespace) -> int:
    for m in a.plugin or []:
        registry.load_plugin(m)
    print(f"{'id':26s} {'version':8s} {'source':22s} {'audiences':9s} sections")
    for dt in registry.all_types():
        print(f"{dt.id:26s} {dt.version:8s} {registry.REGISTRY.sources[dt.id]:22s} {len(dt.audiences):<9d} {', '.join(s.id for s in dt.sections)}")
        print(f"{'':26s} needs: {', '.join(dt.input_dependencies) or '-'}; reconstruction: {'yes (never approved)' if dt.evidence_rules.reconstructed else 'no'}")
    return 0


def _prev(out: Path, d: Document) -> Document | None:
    p = out / f"{d.doc_type}.{d.audience}.{d.depth}.json"
    if p.is_file():
        try:
            return Document.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None


def cmd_generate(a: argparse.Namespace) -> int:
    for m in a.plugin or []:
        registry.load_plugin(m)
    model = _model(a.model)
    out = Path(a.out)
    types = a.type or ([] if a.all else None)
    if not types and not a.all:
        raise YuktiForgeError("give --type ID (repeatable) or --all")
    ids_ = [t.id for t in registry.all_types()] if a.all else types
    docs, notes = [], []
    only = set(a.sections.split(",")) if a.sections else None
    for tid in ids_:
        dt = registry.get(tid)
        if a.audience not in dt.audiences:
            if a.all:
                continue
        new = engine.generate(dt, model, audience=a.audience, depth=a.depth, scope=a.scope)
        merged, st = regenerate(_prev(out, new), new, only)
        docs.append(merged)
        notes.append((tid, st))
    rv = R.load(out / REVIEW_FILE)
    if a.ai_provider:
        try:
            from yuktiforge.docint.docgen.ai_cli import apply_ai
        except ImportError:
            raise YuktiForgeError("AI narration is not part of this installation: it needs a network client, and the packaged skills ship none") from None
        docs = apply_ai(docs, a, out)
    man = write_documents(docs, model, out, rv)
    bad = 0
    val = json.loads((out / "validation.json").read_text())
    for d in docs:
        v = val["documents"][d.doc_id]
        st = dict(notes)[d.doc_type]
        print(f"{d.doc_type:24s} {d.audience}/{d.depth:7s} {len(d.sections)} sections, {len(d.gaps)} gap(s); regeneration: {len(st['unchanged'])} unchanged, {len(st['changed'])} changed, {len(st['added'])} new"
              + (f", {len(st['held_back'])} held back" if st["held_back"] else "") + f"; validation: {'OK' if v['ok'] else str(len(v['defects'])) + ' DEFECT(S)'}")
        for x in v["defects"][:5]:
            print(f"    DEFECT {x}")
        bad += 0 if v["ok"] else 1
    print(f"wrote {len(man['documents'])} document(s) to {out} (manifest.json, glossary.md, contradictions.json, requirements-traceability.json, validation.json)")
    return 1 if bad else 0


def _doc(out: Path, doc_id: str) -> Document:
    for p in sorted(out.glob("*.json")):
        if p.name.endswith((".evidence-map.json", ".coverage.json")) or p.name in ("manifest.json", "glossary.json", "validation.json", "contradictions.json", "requirements-traceability.json", REVIEW_FILE):
            continue
        d = Document.model_validate_json(p.read_text(encoding="utf-8"))
        if d.doc_id == doc_id or d.doc_type == doc_id:
            return d
    raise YuktiForgeError(f"no generated document '{doc_id}' in {out}")


def cmd_review(a: argparse.Namespace) -> int:
    out = Path(a.docs)
    db = R.load(out / REVIEW_FILE)
    d = _doc(out, a.doc)
    if a.action == "submit":
        done = R.submit(db, d, a.section.split(",") if a.section else None, a.by)
        print(f"submitted {len(done)} section(s) of {d.doc_id} for review")
    elif a.action == "decide":
        if not a.section:
            raise YuktiForgeError("--section is required")
        rec = R.decide(db, d, a.section, a.state, a.by, a.note)
        print(f"{d.doc_id} section {a.section}: {rec['state']} by {rec['by']}")
    else:
        from yuktiforge.docint.audit import states as GS
        sec = GS.section_states(d, db, set())
        for s in d.sections:
            st, stale = R.section_state(d, db, s.id)
            print(f"  {s.id:18s} {sec[s.id]:17s} ({st})" + ("  changed since the decision" if stale else ""))
        print(f"document state: {GS.document_state(sec)}; " + R.effective_status(d, db))
        return 0
    R.save(db, out / REVIEW_FILE)
    from yuktiforge.docint.docgen.render import to_markdown
    model = _model(a.model) if a.model else None
    if model is not None:
        (out / f"{d.doc_type}.{d.audience}.{d.depth}.md").write_text(to_markdown(d, model, db), encoding="utf-8")
    print("  " + R.effective_status(d, db))
    return 0


def add_docgen_commands(ds) -> None:
    t = ds.add_parser("types", help="list the registered document types (built-in and plug-ins)")
    t.add_argument("--plugin", action="append", help="importable module that registers document types")
    t.set_defaults(fn=cmd_types)
    g = ds.add_parser("generate", help="generate documents from a knowledge model (deterministic; AI only if explicitly requested and approved)")
    g.add_argument("--model", required=True, help="directory written by `docs model build`")
    g.add_argument("--out", required=True)
    g.add_argument("--type", action="append", help="document type id (repeatable); see `docs types`")
    g.add_argument("--all", action="store_true", help="every document type offered for the audience")
    g.add_argument("--audience", default="developer", choices=AUDIENCES)
    g.add_argument("--depth", default="summary", choices=["summary", "deep"])
    g.add_argument("--scope", help="for code-explanation: module:<path> or symbol:<qualified name>")
    g.add_argument("--sections", help="regenerate only these section ids (comma separated); other sections are kept as they are")
    g.add_argument("--plugin", action="append", help="importable module that registers document types")
    g.add_argument("--ai-provider", help="optional AI narration: ollama | openai-compatible | anthropic (needs --approve-egress)")
    g.add_argument("--ai-model")
    g.add_argument("--ai-section", help="section id to narrate")
    g.add_argument("--ai-base-url")
    g.add_argument("--ai-key-env", help="name of the environment variable holding the API key")
    g.add_argument("--allow-network", action="store_true", help="allow a non-loopback AI endpoint")
    g.add_argument("--approve-egress", action="store_true", help="you have seen what would be sent (printed with --ai-provider and no approval) and approve sending it")
    g.set_defaults(fn=cmd_generate)
    r = ds.add_parser("review", help="human review of generated documents: submit, decide, status")
    r.add_argument("action", choices=["submit", "decide", "status"])
    r.add_argument("--docs", required=True, help="directory written by `docs generate`")
    r.add_argument("--doc", required=True, help="document id or type")
    r.add_argument("--section")
    r.add_argument("--state", choices=["approved", "changes-requested"])
    r.add_argument("--by", default="")
    r.add_argument("--note", default="")
    r.add_argument("--model", help="the knowledge model directory, to refresh the Markdown with the review state")
    r.set_defaults(fn=cmd_review)
