"""`yuktiforge docs model build|validate|query|trace|impact|assert|approve|viz|migrate` (D2)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from yuktiforge.docint.knowledge import outputs as O
from yuktiforge.docint.knowledge.adapter_viz import to_architecture_model
from yuktiforge.docint.knowledge.build import build_model
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.migrate import load_model_file
from yuktiforge.docint.knowledge.store import Store
from yuktiforge.docint.knowledge.validate import validate
from yuktiforge.docint.scan import git_revision
from yuktiforge.errors import YuktiForgeError

MODEL_FILE = "system-knowledge.json"


def _load(model_dir: str):
    m, applied = load_model_file(Path(model_dir) / MODEL_FILE)
    if applied:
        print("migrated in memory: " + "; ".join(applied))
    return m


def _store_model(model_dir: str):
    s = Store(Path(model_dir) / "store")
    m = s.load()
    s.close()
    return m or _load(model_dir)


def cmd_build(a: argparse.Namespace) -> int:
    out = Path(a.out)
    model = build_model(Path(a.scan), Path(a.repo) if a.repo else None)
    store = Store(out / "store")
    stats = store.apply_scan(model)
    merged = store.load()
    sha = store.put_artifact((Path(a.scan) / "coverage.json").read_bytes())
    store.close()
    paths = O.write_all(merged, out)
    f = validate(merged, Path(a.repo) if a.repo else None)
    errs = [x for x in f if x.severity == "error"]
    from collections import Counter
    print(f"knowledge model {merged.schema_version}: {len(merged.entities)} entities, {len(merged.relationships)} relationships, {len(merged.evidence)} evidence, {len(merged.gaps)} gaps, {len(merged.conflicts)} conflicts")
    print("entities by type: " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(e.type for e in merged.entities).items())))
    print("evidence class  : " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(e.cls for e in merged.entities).items())))
    print(f"merge           : retired {stats['retired']}, kept user entities {stats['kept_user_entities']}, new user-vs-observed conflicts {stats['new_conflicts']}")
    print(f"validation      : {len(errs)} error(s), {len(f) - len(errs)} warning(s)" + ("" if a.repo else "   (evidence not checked against the repository: pass --repo)"))
    for x in errs[:10]:
        print(f"  ERROR {x.code}: {x.message}")
    for p in paths:
        print(f"  wrote {p}")
    print(f"  store {out / 'store' / 'knowledge.sqlite'}  (scan coverage artifact {sha[:12]})")
    return 1 if errs else 0


def cmd_validate(a: argparse.Namespace) -> int:
    m = _load(a.model)
    repo = Path(a.repo) if a.repo else None
    f = validate(m, repo, git_revision(repo) if repo else None)
    for x in f:
        print(f"{x.severity.upper():7s} {x.code}: {x.message}" + (f"  [{x.ref}]" if x.ref else ""))
    errs = sum(1 for x in f if x.severity == "error")
    print(f"{errs} error(s), {len(f) - errs} warning(s)")
    return 1 if errs else 0


def cmd_query(a: argparse.Namespace) -> int:
    g = Graph(_load(a.model))
    if a.entity:
        e = g.get(a.entity)
        print(json.dumps({"entity": e.model_dump(mode="json"), "evidence": g.cite(e.evidence_ids), "neighbors": g.neighbors(a.entity)}, indent=1, ensure_ascii=True))
    elif a.find:
        t, _, text = a.find.partition(":")
        print(json.dumps([{"id": e.id, "type": e.type, "name": e.name, "cls": e.cls, "status": e.status} for e in g.find(t or None, text or None)], indent=1, ensure_ascii=True))
    else:
        raise YuktiForgeError("give --entity ID or --find TYPE[:text]")
    return 0


def cmd_trace(a: argparse.Namespace) -> int:
    g = Graph(_load(a.model))
    api = a.api
    if api not in g.ent:
        hits = [e for e in g.find("api", api) if not e.external]
        if len(hits) != 1:
            raise YuktiForgeError(f"'{api}' matches {len(hits)} APIs: " + ", ".join(e.name for e in hits[:8]))
        api = hits[0].id
    print(json.dumps(g.trace_request(api), indent=1, ensure_ascii=True))
    return 0


def cmd_impact(a: argparse.Namespace) -> int:
    g = Graph(_load(a.model))
    seeds = g.seeds_for_paths(a.changed)
    if not seeds:
        raise YuktiForgeError("none of the given paths is a module in the model (paths are repository-relative)")
    print(json.dumps(g.impact(seeds, depth=a.depth), indent=1, ensure_ascii=True))
    return 0


def cmd_assert(a: argparse.Namespace) -> int:
    s = Store(Path(a.model) / "store")
    try:
        e = s.assert_entity(a.type, a.name, a.text, a.by, source_note=a.source or "")
        m = s.load()
    finally:
        s.close()
    O.write_all(m, Path(a.model))
    print(f"recorded user-supplied {e.type} {e.id} ({'unapproved' if e.approval else 'no approval concept'}); it is NOT verified against code")
    return 0


def cmd_approve(a: argparse.Namespace) -> int:
    s = Store(Path(a.model) / "store")
    try:
        e = s.approve(a.id, a.by, a.note)
        m = s.load()
    finally:
        s.close()
    O.write_all(m, Path(a.model))
    print(f"{e.id} is now {e.approval}")
    return 0


def cmd_link(a: argparse.Namespace) -> int:
    s = Store(Path(a.model) / "store")
    try:
        r = s.link(a.source, a.target, a.by, a.note)
        m = s.load()
    finally:
        s.close()
    O.write_all(m, Path(a.model))
    print(f"recorded user-supplied link {r.id}: {a.source} traces-to {a.target} (made by {a.by}; not verified against code)")
    return 0


def cmd_viz(a: argparse.Namespace) -> int:
    from yuktiforge.visualizer.model import canonical_json
    from yuktiforge.visualizer.validate import validate_model
    am, rep = to_architecture_model(_load(a.model))
    problems = [i for i in validate_model(am) if i.severity == "error"]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(canonical_json(am), encoding="utf-8")
    print(f"architecture model written to {a.out}: {rep['mapped_components']} components, {rep['mapped_relations']} relations; not mapped: {rep['not_mapped']}")
    print(f"visualizer validation: {len(problems)} error(s)")
    return 1 if problems else 0


def cmd_migrate(a: argparse.Namespace) -> int:
    from yuktiforge.docint.knowledge.migrate import migrate
    doc = json.loads(Path(a.file).read_text(encoding="utf-8"))
    new, applied = migrate(doc)
    Path(a.out).write_text(O.canon(new), encoding="utf-8")
    print("migrated: " + ("; ".join(applied) or "already current"))
    return 0


def add_model_commands(ds) -> None:
    m = ds.add_parser("model", help="the evidence-backed System Knowledge Model built from a scan (D2)")
    ms = m.add_subparsers(dest="model_cmd", required=True, metavar="<action>")
    b = ms.add_parser("build", help="build/merge the model from a scan; writes system-knowledge.json, traceability.json, change-impact.json and a SQLite store")
    b.add_argument("--scan", required=True, help="directory written by `docs scan`")
    b.add_argument("--out", required=True)
    b.add_argument("--repo", help="the repository itself: lets evidence carry a hash of the cited lines (stale-evidence detection)")
    b.set_defaults(fn=cmd_build)
    v = ms.add_parser("validate", help="check integrity (dangling links, forbidden cycles, upgraded confidence, approvals) and, with --repo, stale or deleted evidence")
    v.add_argument("--model", required=True)
    v.add_argument("--repo")
    v.set_defaults(fn=cmd_validate)
    q = ms.add_parser("query", help="read one entity with its neighbours, or find entities")
    q.add_argument("--model", required=True)
    q.add_argument("--entity")
    q.add_argument("--find", help="TYPE[:text], e.g. api:orders")
    q.set_defaults(fn=cmd_query)
    t = ms.add_parser("trace", help="reconstruct the request path of an API from code evidence")
    t.add_argument("--model", required=True)
    t.add_argument("--api", required=True, help="an API entity id or part of its name")
    t.set_defaults(fn=cmd_trace)
    i = ms.add_parser("impact", help="what may be affected if these files change")
    i.add_argument("--model", required=True)
    i.add_argument("--changed", nargs="+", required=True)
    i.add_argument("--depth", type=int, default=3)
    i.set_defaults(fn=cmd_impact)
    s = ms.add_parser("assert", help="record a user-supplied statement (never treated as verified)")
    s.add_argument("--model", required=True)
    s.add_argument("--type", required=True, choices=["requirement_candidate", "business_rule_candidate", "actor", "workflow", "decision", "risk", "document"])
    s.add_argument("--name", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--by", required=True, help="who is making the statement")
    s.add_argument("--source", help="where the statement comes from (a document, a meeting)")
    s.set_defaults(fn=cmd_assert)
    ap = ms.add_parser("approve", help="record that a named person approved a candidate (the only way a candidate becomes approved)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--by", required=True)
    ap.add_argument("--note", required=True)
    ap.set_defaults(fn=cmd_approve)
    lk = ms.add_parser("link", help="a person links a requirement or rule to code (traces-to); the only way requirement-to-code links exist")
    lk.add_argument("--model", required=True)
    lk.add_argument("--source", required=True, help="entity id of the requirement or rule")
    lk.add_argument("--target", required=True, help="entity id of the API, symbol or module that implements it")
    lk.add_argument("--by", required=True)
    lk.add_argument("--note", required=True)
    lk.set_defaults(fn=cmd_link)
    z = ms.add_parser("viz", help="translate the model into an Architecture Visualizer model file")
    z.add_argument("--model", required=True)
    z.add_argument("--out", required=True)
    z.set_defaults(fn=cmd_viz)
    mg = ms.add_parser("migrate", help="upgrade a model file written by an older schema version")
    mg.add_argument("--file", required=True)
    mg.add_argument("--out", required=True)
    mg.set_defaults(fn=cmd_migrate)
