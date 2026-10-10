"""Map a KnowledgeModel onto the Architecture Visualizer's canonical model (`yuktiforge.visualizer.model`). The visualizer keeps its own renderer; this only translates.

What maps, and how:
  component entities that own modules  -> service components      (verified: a manifest is on disk)
  deployment_boundary(container)       -> container components    (deploys-to relation from the owning component; inferred, with the rule's rationale)
  database_entity tables               -> ONE datastore component (inferred: the source cannot tell which database instance a table lives in)
  external API targets                 -> one external-system per host
  events                               -> queue components
  imports/calls/reads/writes/publishes/subscribes between them -> aggregated relations with file citations
Entities with no compatible kind (symbols, fields, technologies, candidates, ...) are NOT mapped; the adapter reports how many were left out and why.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from yuktiforge.docint.knowledge import ids
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import KnowledgeModel
from yuktiforge.visualizer import model as V

MAX_REFS = 3
_HOST = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://)?(?:[^/@]*@)?([^/:?#]+)")


def _vid(prefix: str, key: str) -> str:
    return f"{prefix}-{ids.slug(key, 40)}-{ids.make_id('x', key).rsplit('-', 1)[-1]}"[:64]


def to_architecture_model(model: KnowledgeModel) -> tuple[V.ArchitectureModel, dict[str, Any]]:
    g = Graph(model)
    comps: dict[str, V.Component] = {}
    rels: dict[tuple[str, str, str], dict[str, Any]] = {}
    skipped: dict[str, int] = defaultdict(int)

    def ev_of(entity_ids: list[str], inferred_note: str | None = None) -> V.Evidence:
        refs: list[V.Provenance] = []
        for eid in entity_ids:
            for i in g.ent[eid].evidence_ids:
                e = g.ev[i]
                if e.path and len(refs) < MAX_REFS:
                    refs.append(V.Provenance(kind="file", ref=f"{e.path}:{e.start_line}"))
        if inferred_note:
            return V.Evidence(status="inferred", sources=tuple(refs), rationale=inferred_note)
        weakest = min((g.ent[e].cls for e in entity_ids), key=lambda c: {"verified": 3, "user-supplied": 2, "inferred": 1, "unknown": 0}[c])
        if weakest == "verified" and refs:
            return V.Evidence(status="verified", sources=tuple(refs))
        if weakest == "user-supplied":
            return V.Evidence(status="user-supplied", sources=(V.Provenance(kind="user", ref="asserted in the knowledge model"),))
        return V.Evidence(status="inferred", sources=tuple(refs), rationale="derived from the knowledge model with less than verified evidence")

    owner_comp: dict[str, str] = {}               # any entity id -> component entity id that (transitively) owns it
    for c in model.entities:
        if c.type == "component":
            stack = [c.id]
            while stack:
                n = stack.pop()
                for r in g.out.get(n, []):
                    if r.type == "owns" and r.target not in owner_comp:
                        owner_comp[r.target] = c.id
                        stack.append(r.target)
    mod_count: dict[str, int] = defaultdict(int)
    for eid, cid in owner_comp.items():
        if g.ent[eid].type == "module":
            mod_count[cid] += 1
    vid_of: dict[str, str] = {}
    for c in model.entities:
        if c.type == "component" and mod_count.get(c.id):
            vid = _vid("svc", c.name)
            vid_of[c.id] = vid
            lang = ", ".join(c.attrs.get("languages", []) or [])
            comps[vid] = V.Component(id=vid, name=c.name, kind="service", technology=lang, description=f"{mod_count[c.id]} source modules", evidence=ev_of([c.id]))
        elif c.type == "component":
            skipped["component-without-modules"] += 1
    for d in model.entities:
        if d.type == "deployment_boundary" and d.subtype == "container":
            vid = _vid("ctr", f"{d.attrs.get('defined_in', '')}|{d.name}")
            vid_of[d.id] = vid
            comps[vid] = V.Component(id=vid, name=d.name, kind="container", technology=str(d.attrs.get("framework", "")), evidence=ev_of([d.id]))
    tables = [e for e in model.entities if e.type == "database_entity" and e.subtype == "table"]
    ds_id = None
    if tables:
        ds_id = "datastore-main"
        names = ", ".join(sorted(t.name for t in tables)[:12]) + (" ..." if len(tables) > 12 else "")
        comps[ds_id] = V.Component(id=ds_id, name="Database", kind="datastore", description=f"{len(tables)} table(s): {names}",
                                   evidence=ev_of([t.id for t in tables], f"{len(tables)} tables are grouped into one datastore: the source does not say which database instance each belongs to"))
        for t in tables:
            vid_of[t.id] = ds_id
    hosts: dict[str, list[str]] = defaultdict(list)
    for a in model.entities:
        if a.type == "api" and a.external:
            m = _HOST.match(str(a.attrs.get("url", "")))
            if m and "." in m.group(1) or (m and "://" in str(a.attrs.get("url", ""))):
                hosts[m.group(1)].append(a.id)
            else:
                skipped["external-api-without-host"] += 1
    for h, aids in sorted(hosts.items()):
        vid = _vid("ext", h)
        comps[vid] = V.Component(id=vid, name=h, kind="external-system", description=f"{len(aids)} endpoint(s) called", evidence=ev_of(aids))
        for a in aids:
            vid_of[a] = vid
    for e in model.entities:
        if e.type == "event":
            vid = _vid("evt", e.name)
            vid_of[e.id] = vid
            comps[vid] = V.Component(id=vid, name=e.name, kind="queue", technology=str(e.attrs.get("framework", "")), evidence=ev_of([e.id]))
    for e in model.entities:
        if e.type not in ("component", "deployment_boundary", "database_entity", "event") and not (e.type == "api" and e.external):
            skipped[f"{e.type}"] += 1

    def add(src: str, dst: str, kind: str, label: str, evidence_from: list[str], note: str | None = None, rid: str | None = None) -> None:
        if src == dst or src not in comps or dst not in comps:
            return
        cur = rels.setdefault((src, dst, kind), {"labels": set(), "ev": [], "note": note, "rids": []})
        cur["labels"].add(label)
        cur["ev"] += evidence_from
        if rid:
            cur["rids"].append(rid)

    for r in model.relationships:
        s_owner = owner_comp.get(r.source)
        src = vid_of.get(s_owner) if s_owner else vid_of.get(r.source)
        dst = vid_of.get(r.target) or (vid_of.get(owner_comp.get(r.target, "")) if r.target in owner_comp else None)
        if r.type in ("reads", "writes") and src and r.target in vid_of:
            add(src, vid_of[r.target], "reads-writes", r.type, [r.source, r.target], rid=r.id)
        elif r.type == "calls" and src and g.ent[r.target].external and r.target in vid_of:
            add(src, vid_of[r.target], "calls", "HTTP", [r.source, r.target], rid=r.id)
        elif r.type == "calls" and src and dst and g.ent[r.source].type in ("symbol", "interface") and g.ent[r.target].type in ("symbol", "interface"):
            add(src, dst, "calls", "calls", [r.source, r.target], rid=r.id)
        elif r.type in ("publishes", "subscribes") and src and r.target in vid_of:
            add(src, vid_of[r.target], r.type, r.type, [r.source, r.target], rid=r.id)
        elif r.type == "imports" and src and g.ent[r.target].type == "module" and r.target in owner_comp and vid_of.get(owner_comp[r.target]):
            add(src, vid_of[owner_comp[r.target]], "depends-on", "imports", [r.source, r.target], rid=r.id)
        elif r.type == "deploys-to" and r.source in vid_of and r.target in vid_of:
            add(vid_of[r.source], vid_of[r.target], "deploys-to", "deploys to", [r.source, r.target], note=next((g.ev[i].note for i in r.evidence_ids if g.ev[i].cls == "inferred"), None), rid=r.id)
    relations = []
    for (s, d, kind), v in sorted(rels.items()):
        relations.append(V.Relation(id=_vid("rel", f"{s}|{d}|{kind}"), source=s, target=d, kind=kind, label=", ".join(sorted(v["labels"])), evidence=ev_of(v["ev"][:20], v["note"])))
    lang_cov = tuple(V.LanguageCoverage(language=k, files=v["files"], depth="imports" if v["analyzed"] else "none") for k, v in sorted(model.coverage.get("languages", {}).items()))
    notes = tuple(g_.detail for g_ in model.gaps if g_.kind in ("unsupported-language", "no-call-graph", "partial-analysis", "unresolved-calls"))
    unparsed = tuple(sorted(g_.detail.split(" ", 1)[0] for g_ in model.gaps if g_.kind == "parse-failure"))
    am = V.ArchitectureModel(name=str(model.repository.get("name", "")), description="Derived from the System Knowledge Model by the D2 adapter; every element cites knowledge-model evidence.",
                             components=tuple(sorted(comps.values(), key=lambda c: c.id)), relations=tuple(relations), coverage=V.Coverage(languages=lang_cov, notes=notes, unparsed_files=unparsed))
    comp_entities: dict[str, list[str]] = defaultdict(list)
    for eid, vid in vid_of.items():
        comp_entities[vid].append(eid)
    mapping = {"components": {v: sorted(e) for v, e in sorted(comp_entities.items())},
               "relations": {r.id: sorted(set(rels[(r.source, r.target, r.kind)]["rids"])) for r in relations}}
    return am, {"mapped_components": len(comps), "mapped_relations": len(relations), "not_mapped": dict(sorted(skipped.items())), "mapping": mapping}
