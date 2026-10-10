"""Diagram specifications derived from the System Knowledge Model, rendered by the EXISTING Architecture Visualizer (no second rendering engine).
Each diagram carries a mapping from every drawn element to the model entities/relationships it came from, so the picture can be checked against its source and an
element with no source is an error. Views the evidence or the engine cannot support are listed with the reason, never silently skipped."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from yuktiforge.docint.knowledge import ids
from yuktiforge.docint.knowledge.adapter_viz import to_architecture_model
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import Entity, KnowledgeModel
from yuktiforge.visualizer import model as V

MAX_MODULES = 40
MAX_STORES_IN_DFD = 10
_HOST = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://)?(?:[^/@]*@)?([^/:?#]+)")
_REF = re.compile(r"\bREFERENCES\s+([\w\".]+)", re.I)
_FK = re.compile(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+([\w\".]+)", re.I)


@dataclass
class DiagramSpec:
    id: str
    view: str                         # visualizer view name
    title: str
    purpose: str                      # which document sections / audiences use it (HLD, LLD, ...)
    model: V.ArchitectureModel
    mapping: dict[str, dict[str, list[str]]]         # {"components": {element id: [entity ids]}, "relations": {relation id: [relationship ids]}}
    notes: list[str] = field(default_factory=list)
    level: str = ""                  # DFD level label
    parent: str = ""                 # DFD: the parent process this level decomposes


@dataclass
class Unsupported:
    id: str
    view: str
    reason: str


def vid(prefix: str, key: str) -> str:
    return f"{prefix}-{ids.slug(key, 36)}-{ids.make_id('x', key).rsplit('-', 1)[-1]}"[:64]


class VB:
    """Builds one ArchitectureModel plus its mapping."""

    def __init__(self, g: Graph, name: str):
        self.g, self.name = g, name
        self.comps: dict[str, V.Component] = {}
        self.rels: dict[tuple, dict[str, Any]] = {}
        self.cmap: dict[str, list[str]] = {}
        self.layers: list[V.Layer] = []

    def evidence(self, entity_ids: list[str], inferred: str | None = None) -> V.Evidence:
        refs: list[V.Provenance] = []
        for eid in entity_ids:
            for i in self.g.ent[eid].evidence_ids:
                e = self.g.ev[i]
                if e.path and len(refs) < 3:
                    refs.append(V.Provenance(kind="file", ref=f"{e.path}:{e.start_line}"))
        if not refs:
            refs.append(V.Provenance(kind="analyzer", ref="yuktiforge docs scan"))
        if inferred:
            return V.Evidence(status="inferred", sources=tuple(refs), rationale=inferred)
        classes = [self.g.ent[e].cls for e in entity_ids] or ["unknown"]
        rank = {"verified": 3, "user-supplied": 2, "inferred": 1, "unknown": 0}
        weakest = min(classes, key=lambda c: rank[c])
        if weakest == "verified":
            return V.Evidence(status="verified", sources=tuple(refs))
        if weakest == "user-supplied":
            return V.Evidence(status="user-supplied", sources=(V.Provenance(kind="user", ref="asserted in the knowledge model"),))
        return V.Evidence(status="inferred", sources=tuple(refs), rationale="derived from knowledge-model evidence that is less than verified")

    def comp(self, cid: str, name: str, kind: str, entity_ids: list[str], *, tech: str = "", desc: str = "", attrs: tuple[str, ...] = (), inferred: str | None = None, layer: str | None = None) -> str:
        if cid in self.comps:
            self.cmap[cid] = sorted(set(self.cmap[cid]) | set(entity_ids))
            return cid
        self.comps[cid] = V.Component(id=cid, name=name[:80], kind=kind, technology=tech[:60], description=desc[:240], attributes=attrs, layer=layer, evidence=self.evidence(entity_ids, inferred))   # type: ignore[arg-type]
        self.cmap[cid] = sorted(set(entity_ids))
        return cid

    def rel(self, src: str, dst: str, kind: str, label: str, rel_ids: list[str], ent_ids: list[str], inferred: str | None = None) -> None:
        if src == dst or src not in self.comps or dst not in self.comps:
            return
        cur = self.rels.setdefault((src, dst, kind), {"labels": set(), "rids": [], "ents": [], "inferred": inferred})
        cur["labels"].add(label)
        cur["rids"] += rel_ids
        cur["ents"] += ent_ids

    def prune(self, kinds: set[str]) -> list[str]:
        """Drop elements of these kinds that no relation touches (an external entity, store or process that has no flow in this diagram). Returns the names dropped."""
        used = {x for k in self.rels for x in k[:2]}
        gone = [c for c, comp in self.comps.items() if comp.kind in kinds and c not in used]
        names = [self.comps[c].name for c in gone]
        for cid in gone:
            del self.comps[cid]
            self.cmap.pop(cid, None)
        return sorted(names)

    def build(self) -> tuple[V.ArchitectureModel, dict[str, dict[str, list[str]]]]:
        relations, rmap = [], {}
        for (s, d, k), v in sorted(self.rels.items()):
            rid = vid("rel", f"{s}|{d}|{k}")
            relations.append(V.Relation(id=rid, source=s, target=d, kind=k, label=", ".join(sorted(v["labels"])), evidence=self.evidence(sorted(set(v["ents"])), v["inferred"])))   # type: ignore[arg-type]
            rmap[rid] = sorted(set(v["rids"]))
        am = V.ArchitectureModel(name=self.name, components=tuple(sorted(self.comps.values(), key=lambda c: c.id)), relations=tuple(relations), layers=tuple(self.layers))
        return am, {"components": dict(sorted(self.cmap.items())), "relations": rmap}


# ----------------------------------------------------------------------------- shared lookups
class Facts:
    def __init__(self, model: KnowledgeModel):
        self.m, self.g = model, Graph(model)
        self.repo = next(e for e in model.entities if e.type == "repository")
        self.owner: dict[str, str] = {}
        for c in model.entities:
            if c.type == "component":
                stack = [c.id]
                while stack:
                    n = stack.pop()
                    for r in self.g.out.get(n, []):
                        if r.type == "owns" and r.target not in self.owner:
                            self.owner[r.target] = c.id
                            stack.append(r.target)
        mods = [e for e in model.entities if e.type == "module"]
        self.mods_by_comp: dict[str, list[Entity]] = defaultdict(list)
        for m in mods:
            if m.id in self.owner:
                self.mods_by_comp[self.owner[m.id]].append(m)
        self.comps = [c for c in model.entities if c.type == "component" and self.mods_by_comp.get(c.id)]
        self.tables = [e for e in model.entities if e.type == "database_entity" and e.subtype == "table" and e.status == "active"]
        self.events = [e for e in model.entities if e.type == "event"]
        self.externals = [e for e in model.entities if e.type == "api" and e.external]
        self.actors = [e for e in model.entities if e.type == "actor" and e.cls == "user-supplied"]
        self.inbound = [e for e in model.entities if e.type == "api" and not e.external and e.subtype in ("route", "grpc", "graphql")]
        self.deploy = [e for e in model.entities if e.type == "deployment_boundary" and e.subtype in ("container", "infrastructure")]

    def host_of(self, api: Entity) -> str | None:
        m = _HOST.match(str(api.attrs.get("url", "")))
        return m.group(1) if m and ("." in m.group(1) or "://" in str(api.attrs.get("url", ""))) else None

    def owner_of_symbol(self, eid: str) -> str | None:
        """Component that (transitively) owns a symbol: symbols are owned by modules, which are owned by components."""
        return self.owner.get(eid)

    def module_of(self, eid: str) -> Entity | None:
        cur, seen = self.g.ent.get(eid), set()
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            if cur.type == "module":
                return cur
            up = [self.g.ent[r.source] for r in self.g.inc.get(cur.id, []) if r.type == "owns" and r.source in self.g.ent and self.g.ent[r.source].type in ("module", "symbol", "interface")]
            cur = up[0] if up else None
        return None


def _hosts(f: Facts) -> dict[str, list[Entity]]:
    out: dict[str, list[Entity]] = defaultdict(list)
    for a in f.externals:
        h = f.host_of(a)
        if h:
            out[h].append(a)
    return out


# ----------------------------------------------------------------------------- the views
def build_all(model: KnowledgeModel) -> tuple[list[DiagramSpec], list[Unsupported]]:
    f = Facts(model)
    specs: list[DiagramSpec] = []
    uns: list[Unsupported] = []
    name = str(model.repository.get("name", ""))

    def add(s: DiagramSpec | Unsupported) -> None:
        (specs if isinstance(s, DiagramSpec) else uns).append(s)

    add(context(f, name))
    add(container(f, name))
    add(technology(f, name))
    for s in components(f, name):
        add(s)
    add(deployment(f, name))
    add(integration(f, name))
    add(erd(f, name))
    for s in dfds(f, name):
        add(s)
    uns.append(Unsupported("sequence", "sequence", "the Architecture Visualizer has no sequence-diagram layout and a second engine is out of scope; the request paths that evidence supports are given as numbered flows in the HLD, functional specification and use cases"))
    uns.append(Unsupported("event-driven", "event-driven", "no event-driven view exists in the Architecture Visualizer; topics and their publishers/subscribers are shown in the integration view and the API/event catalog"))
    uns.append(Unsupported("infrastructure", "infrastructure", "infrastructure resources appear in the deployment view; a separate infrastructure view is not implemented in the Architecture Visualizer"))
    return specs, uns


def context(f: Facts, name: str) -> DiagramSpec | Unsupported:
    b = VB(f.g, f"{name} - system context")
    sysid = b.comp(vid("sys", name), name or "System", "system", [f.repo.id], desc="the analyzed repository as one system")
    hosts = _hosts(f)
    for h, apis in sorted(hosts.items()):
        cid = b.comp(vid("ext", h), h, "external-system", [a.id for a in apis], desc=f"{len(apis)} endpoint(s) called")
        rids = [r.id for a in apis for r in f.g.inc.get(a.id, []) if r.type == "calls"]
        b.rel(sysid, cid, "calls", "HTTP", rids, [a.id for a in apis])
    for a in f.actors:
        cid = b.comp(vid("act", a.name), a.name, "person", [a.id], desc=str(a.attrs.get("statement", "")))
        b.rel(cid, sysid, "uses", "uses", [], [a.id])
    if len(b.comps) < 2:
        return Unsupported("context", "c4-context", "no external systems with a literal host and no user-supplied actors: there is no neighbour to draw next to the system")
    am, mp = b.build()
    return DiagramSpec("context", "c4-context", "System context", "HLD, system architecture, executive summaries", am, mp, ["people appear only if a person supplied them (docs model assert)"])


def container(f: Facts, name: str) -> DiagramSpec | Unsupported:
    am, rep = to_architecture_model(f.m)
    if not any(c.kind in ("service", "container") for c in am.components):
        return Unsupported("container", "c4-container", "no component with source modules was found")
    return DiagramSpec("container", "c4-container", "Containers and data stores", "HLD, solution architecture", am, rep["mapping"],
                       [f"entities not drawn: {rep['not_mapped']}"] if rep["not_mapped"] else [])


def technology(f: Facts, name: str) -> DiagramSpec | Unsupported:
    am, rep = to_architecture_model(f.m)
    if not am.components:
        return Unsupported("technology", "layered", "nothing to show")
    band = {"external-system": "external", "person": "external", "service": "app", "container": "app", "component": "app", "datastore": "data", "queue": "data", "infrastructure": "infra"}
    layers = (V.Layer(id="external", name="External systems", order=1), V.Layer(id="app", name="Application components", order=2), V.Layer(id="data", name="Data stores and messaging", order=3), V.Layer(id="infra", name="Deployment and infrastructure", order=4))
    comps = tuple(c.model_copy(update={"layer": band.get(c.kind, "app")}) for c in am.components)
    am2 = am.model_copy(update={"layers": layers, "components": comps, "name": f"{name} - technology architecture"})
    return DiagramSpec("technology", "layered", "Technology architecture", "technology architecture, HLD", am2, rep["mapping"],
                       ["layers group elements by KIND (a presentation choice, not a claim about tiers in the system); each element shows its languages where known"])


def components(f: Facts, name: str) -> list[DiagramSpec | Unsupported]:
    out: list[DiagramSpec | Unsupported] = []
    g = f.g
    for c in f.comps:
        mods = sorted(f.mods_by_comp[c.id], key=lambda m: m.name)
        mods = [m for m in mods if m.subtype == "source"]
        if len(mods) < 2:
            out.append(Unsupported(f"component-{ids.slug(c.name, 20)}", "c4-component", f"component '{c.name}' has fewer than two source modules: a component view would show one box"))
            continue
        links = defaultdict(list)
        for m in mods:
            for r in g.out.get(m.id, []):
                if r.type == "imports" and r.target in {x.id for x in mods}:
                    links[(m.id, r.target)].append(r.id)
        busy = {x for k in links for x in k}
        notes = []
        shown = mods
        if len(mods) > MAX_MODULES:
            shown = [m for m in mods if m.id in busy][:MAX_MODULES]
            notes.append(f"{len(mods) - len(shown)} of {len(mods)} modules are not drawn (no import relation inside this component, or beyond the {MAX_MODULES}-module limit)")
        b = VB(g, f"{name} - {c.name} components")
        shown_ids = {m.id for m in shown}
        for m in shown:
            b.comp(vid("mod", m.id), m.name.rsplit("/", 1)[-1] if len(m.name) > 28 else m.name, "module", [m.id], tech=str(m.attrs.get("language", "")), desc=m.name)
        for (s_, d_), rids in links.items():
            if s_ in shown_ids and d_ in shown_ids:
                b.rel(vid("mod", s_), vid("mod", d_), "depends-on", "imports", rids, [s_, d_])
        for m in shown:
            for r in g.out.get(m.id, []):
                t = g.ent.get(r.target)
                if t is None:
                    continue
                if r.type in ("reads", "writes") and t.type == "database_entity":
                    sid = b.comp(vid("tbl", t.name), t.name, "datastore", [t.id])
                    b.rel(vid("mod", m.id), sid, "reads-writes", r.type, [r.id], [m.id, t.id])
        for m in shown:                                   # module-level boundary access through its symbols
            for kid in [x for x in g.out.get(m.id, []) if x.type == "owns"]:
                for r in g.out.get(kid.target, []):
                    t = g.ent.get(r.target)
                    if t is None:
                        continue
                    if r.type in ("reads", "writes") and t.type == "database_entity":
                        sid = b.comp(vid("tbl", t.name), t.name, "datastore", [t.id])
                        b.rel(vid("mod", m.id), sid, "reads-writes", r.type, [r.id], [m.id, t.id])
                    elif r.type == "calls" and t.external and f.host_of(t):
                        xid = b.comp(vid("ext", f.host_of(t) or ""), f.host_of(t) or "", "external-system", [t.id])
                        b.rel(vid("mod", m.id), xid, "calls", "HTTP", [r.id], [m.id, t.id])
                    elif r.type in ("publishes", "subscribes") and t.type == "event":
                        qid = b.comp(vid("evt", t.name), t.name, "queue", [t.id])
                        b.rel(vid("mod", m.id), qid, r.type, r.type, [r.id], [m.id, t.id])
        if len(b.rels) == 0:
            out.append(Unsupported(f"component-{ids.slug(c.name, 20)}", "c4-component", f"no import or boundary relation was found between the modules of '{c.name}'"))
            continue
        am, mp = b.build()
        out.append(DiagramSpec(f"components-{ids.slug(c.name, 24)}", "c4-component", f"Components of {c.name}", "LLD, code explanation", am, mp, notes))
    return out


def deployment(f: Facts, name: str) -> DiagramSpec | Unsupported:
    if not f.deploy:
        return Unsupported("deployment", "deployment", "no container or infrastructure definition (Dockerfile, compose file, Terraform) was found")
    b = VB(f.g, f"{name} - deployment")
    for d in f.deploy:
        kind = "infrastructure" if d.subtype == "infrastructure" else "container"
        b.comp(vid("dep", f"{d.attrs.get('defined_in', '')}|{d.name}"), d.name, kind, [d.id], tech=str(d.attrs.get("framework", "")), desc=f"defined in {d.attrs.get('defined_in', '')}")
    for c in f.comps:
        b.comp(vid("svc", c.name), c.name, "service", [c.id], tech=", ".join(str(x) for x in c.attrs.get("languages", []) or []))
    for r in f.m.relationships:
        if r.type == "deploys-to" and r.source in f.g.ent and r.target in f.g.ent:
            s_, t_ = f.g.ent[r.source], f.g.ent[r.target]
            sc, tc = vid("svc", s_.name), vid("dep", f"{t_.attrs.get('defined_in', '')}|{t_.name}")
            b.rel(sc, tc, "deploys-to", "deployed as", [r.id], [s_.id, t_.id], inferred=next((f.g.ev[i].note for i in r.evidence_ids if f.g.ev[i].cls == "inferred"), "matched by file proximity or name"))
    if f.tables:
        b.comp("datastore-main", "Database", "datastore", [t.id for t in f.tables], desc=f"{len(f.tables)} table(s)", inferred="the source does not say which database instance holds the tables")
        for c in f.comps:
            touched = False
            for t in f.tables:
                if any(f.owner.get(r.source) == c.id or (f.module_of(r.source) and f.owner.get(f.module_of(r.source).id) == c.id) for r in f.g.inc.get(t.id, []) if r.type in ("reads", "writes")):
                    touched = True
                    b.rel(vid("svc", c.name), "datastore-main", "reads-writes", "reads/writes", [r.id for r in f.g.inc.get(t.id, []) if r.type in ("reads", "writes")][:50], [c.id, t.id])
    if len(b.rels) == 0 and len(b.comps) < 2:
        return Unsupported("deployment", "deployment", "deployment definitions exist but nothing relates them to the components")
    am, mp = b.build()
    return DiagramSpec("deployment", "deployment", "Deployment", "HLD, operations", am, mp, ["a component is tied to a container by file proximity or by name; this is inferred, not proven"])


def integration(f: Facts, name: str) -> DiagramSpec | Unsupported:
    hosts = _hosts(f)
    if not hosts and not f.events:
        return Unsupported("integration", "integration", "no outbound HTTP call with a literal host and no messaging topic was found")
    b = VB(f.g, f"{name} - integration")
    for c in f.comps:
        b.comp(vid("svc", c.name), c.name, "service", [c.id], tech=", ".join(str(x) for x in c.attrs.get("languages", []) or []))
    for h, apis in sorted(hosts.items()):
        b.comp(vid("ext", h), h, "external-system", [a.id for a in apis])
    for e in f.events:
        b.comp(vid("evt", e.name), e.name, "queue", [e.id], tech=str(e.attrs.get("framework", "")))
    for r in f.m.relationships:
        s_, t_ = f.g.ent.get(r.source), f.g.ent.get(r.target)
        if not s_ or not t_:
            continue
        comp = f.owner.get(s_.id) or (f.owner.get(f.module_of(s_.id).id) if f.module_of(s_.id) else None)
        if comp is None or comp not in {c.id for c in f.comps}:
            continue
        cn = vid("svc", f.g.ent[comp].name)
        if r.type == "calls" and t_.external and f.host_of(t_):
            b.rel(cn, vid("ext", f.host_of(t_) or ""), "calls", "HTTP", [r.id], [comp, t_.id])
        elif r.type in ("publishes", "subscribes") and t_.type == "event":
            b.rel(cn, vid("evt", t_.name), r.type, r.type, [r.id], [comp, t_.id])
    if not b.rels:
        return Unsupported("integration", "integration", "no relation between a component and an external system or topic could be established")
    am, mp = b.build()
    return DiagramSpec("integration", "integration", "Integrations", "HLD, API/event catalog", am, mp)


def erd(f: Facts, name: str) -> DiagramSpec | Unsupported:
    tables = [t for t in f.tables if any(e.type == "field" for _, e in [(r.type, f.g.ent[r.target]) for r in f.g.out.get(t.id, []) if r.type == "owns"])]
    if not tables:
        return Unsupported("erd", "erd", "no table with a column definition (CREATE TABLE) was found: tables known only from queries have unknown columns")
    b = VB(f.g, f"{name} - entity relationship")
    by_name = {t.name.lower(): t for t in tables}
    for t in sorted(tables, key=lambda x: x.name):
        fields = [f.g.ent[r.target] for r in f.g.out.get(t.id, []) if r.type == "owns" and f.g.ent[r.target].type == "field"]
        attrs = tuple(f"{x.name.split('.', 1)[-1]} {str(x.attrs.get('definition', '')).split(' ', 1)[0] if x.attrs.get('definition') else ''}".strip() + (" PK" if "PRIMARY KEY" in str(x.attrs.get("definition", "")).upper() else "") for x in fields)
        b.comp(vid("ent", t.name.lower()), t.name, "entity", [t.id, *[x.id for x in fields]], attrs=attrs[:30])
    fk = 0
    for t in tables:
        fields = [f.g.ent[r.target] for r in f.g.out.get(t.id, []) if r.type == "owns" and f.g.ent[r.target].type == "field"]
        for x in fields:
            m = _REF.search(str(x.attrs.get("definition", "")))
            if m and m.group(1).strip('"').split(".")[-1].lower() in by_name:
                tgt = by_name[m.group(1).strip('"').split(".")[-1].lower()]
                b.rel(vid("ent", t.name.lower()), vid("ent", tgt.name.lower()), "other", f"{x.name.split('.', 1)[-1]} references {tgt.name}", [], [t.id, x.id, tgt.id])
                fk += 1
        for cons in t.attrs.get("constraints") or []:
            m = _FK.search(str(cons))
            if m and m.group(2).strip('"').split(".")[-1].lower() in by_name:
                tgt = by_name[m.group(2).strip('"').split(".")[-1].lower()]
                b.rel(vid("ent", t.name.lower()), vid("ent", tgt.name.lower()), "other", f"({m.group(1)}) references {tgt.name}", [], [t.id, tgt.id])
                fk += 1
    am, mp = b.build()
    notes = [] if fk else ["no foreign key is declared in the analyzed schema files: the tables are drawn without relationships (relations enforced only by application code are not visible)"]
    return DiagramSpec("erd", "erd", "Entity-relationship diagram", "data dictionary, database documentation, LLD", am, mp, notes)


# ----------------------------------------------------------------------------- data flow diagrams (levels 0..N)
def _flows(f: Facts, comp_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Directed data flows in terms of model entities: {'from': entity id, 'to': entity id, 'label': str, 'rids': [..], 'by': component id}."""
    out = []
    for r in f.m.relationships:
        s_, t_ = f.g.ent.get(r.source), f.g.ent.get(r.target)
        if not s_ or not t_:
            continue
        mod = f.module_of(s_.id) if s_.type in ("symbol", "interface") else (s_ if s_.type == "module" else None)
        comp = f.owner.get(mod.id) if mod else f.owner.get(s_.id)
        if comp is None or (comp_ids is not None and comp not in comp_ids):
            continue
        if r.type == "reads" and t_.type == "database_entity":
            out.append({"from": t_.id, "to": s_.id, "label": "reads", "rids": [r.id], "by": comp, "mod": mod.id if mod else None})
        elif r.type == "writes" and t_.type == "database_entity":
            out.append({"from": s_.id, "to": t_.id, "label": "writes", "rids": [r.id], "by": comp, "mod": mod.id if mod else None})
        elif r.type == "calls" and t_.external and f.host_of(t_):
            out.append({"from": s_.id, "to": t_.id, "label": "request", "rids": [r.id], "by": comp, "mod": mod.id if mod else None})
        elif r.type == "publishes" and t_.type == "event":
            out.append({"from": s_.id, "to": t_.id, "label": "publishes", "rids": [r.id], "by": comp, "mod": mod.id if mod else None})
        elif r.type == "subscribes" and t_.type == "event":
            out.append({"from": t_.id, "to": s_.id, "label": "delivers", "rids": [r.id], "by": comp, "mod": mod.id if mod else None})
    return out


def dfds(f: Facts, name: str) -> list[DiagramSpec | Unsupported]:
    comp_ids = {c.id for c in f.comps}
    flows = _flows(f, comp_ids)
    hosts = _hosts(f)
    consumers_note = "API consumers (not identified in the code)"
    has_inbound = bool(f.inbound)
    if not flows and not has_inbound:
        return [Unsupported("dfd", "data-flow", "no data flow (table access, outbound call, topic) and no inbound API was found")]
    out: list[DiagramSpec | Unsupported] = []

    def externals(b: VB) -> dict[str, str]:
        ex: dict[str, str] = {}
        for h, apis in sorted(hosts.items()):
            ex[h] = b.comp(vid("ext", h), h, "external-system", [a.id for a in apis])
        for a in f.actors:
            ex[a.name] = b.comp(vid("act", a.name), a.name, "person", [a.id])
        if has_inbound and not f.actors:
            ex["consumers"] = b.comp("ext-consumers", consumers_note, "external-system", [a.id for a in f.inbound][:50], inferred="APIs exist, so something calls them; who it is UNKNOWN and is not invented")
        return ex

    ev_host = {a.id: h for h, apis in hosts.items() for a in apis}
    # ------------------------------------------------------------------ level 0: one process
    b = VB(f.g, f"{name} - DFD level 0")
    proc = b.comp(vid("proc", name), name or "System", "service", [f.repo.id], desc="the whole system as one process")
    ex = externals(b)
    pairs = set()
    for fl in flows:
        if fl["label"] == "request":
            h = ev_host.get(fl["to"])
            if h:
                b.rel(proc, ex[h], "data-flow", "request", fl["rids"], [fl["from"], fl["to"]])
                pairs.add((h, "out"))
    if has_inbound:
        key = "consumers" if "consumers" in ex else sorted(a.name for a in f.actors)[0]
        b.rel(ex[key], proc, "data-flow", "requests", [], [a.id for a in f.inbound][:50])
        b.rel(proc, ex[key], "data-flow", "responses", [], [a.id for a in f.inbound][:50], inferred="an API that receives a request returns a response; the content is not analyzed")
    if f.events:
        broker = b.comp("ext-broker", "Message broker", "external-system", [e.id for e in f.events], inferred="topics imply a broker; its identity is not stated in the code")
        for e in f.events:
            for r in f.g.inc.get(e.id, []):
                if r.type == "publishes":
                    b.rel(proc, broker, "data-flow", "publishes", [r.id], [e.id])
                elif r.type == "subscribes":
                    b.rel(broker, proc, "data-flow", "delivers", [r.id], [e.id])
    if len(b.rels) >= 1:
        am, mp = b.build()
        out.append(DiagramSpec("dfd-0", "data-flow", "Data flow diagram, level 0 (context)", "HLD, solution architecture", am, mp, level="0", parent=""))
    else:
        out.append(Unsupported("dfd-0", "data-flow", "no flow crosses the system boundary"))
    # ------------------------------------------------------------------ level 1: components are processes
    b = VB(f.g, f"{name} - DFD level 1")
    procs = {c.id: b.comp(vid("proc", c.name), c.name, "service", [c.id], tech=", ".join(str(x) for x in c.attrs.get("languages", []) or [])) for c in f.comps}
    ex = externals(b)
    if f.events:
        broker = b.comp("ext-broker", "Message broker", "external-system", [e.id for e in f.events], inferred="topics imply a broker; its identity is not stated in the code")
    stores = {}
    if f.tables:
        if len(f.tables) <= MAX_STORES_IN_DFD:
            stores = {t.id: b.comp(vid("tbl", t.name), t.name, "datastore", [t.id]) for t in f.tables}
        else:
            one = b.comp("ds-database", f"Database ({len(f.tables)} tables)", "datastore", [t.id for t in f.tables], inferred="more tables than a diagram can show: grouped into one store")
            stores = {t.id: one for t in f.tables}
    for fl in flows:
        p = procs.get(fl["by"])
        if p is None:
            continue
        if fl["label"] == "reads" and fl["from"] in stores:
            b.rel(stores[fl["from"]], p, "data-flow", "reads", fl["rids"], [fl["from"], fl["by"]])
        elif fl["label"] == "writes" and fl["to"] in stores:
            b.rel(p, stores[fl["to"]], "data-flow", "writes", fl["rids"], [fl["to"], fl["by"]])
        elif fl["label"] == "request" and ev_host.get(fl["to"]):
            b.rel(p, ex[ev_host[fl["to"]]], "data-flow", "request", fl["rids"], [fl["to"], fl["by"]])
        elif fl["label"] == "publishes" and f.events:
            b.rel(p, broker, "data-flow", "publishes", fl["rids"], [fl["to"], fl["by"]])
        elif fl["label"] == "delivers" and f.events:
            b.rel(broker, p, "data-flow", "delivers", fl["rids"], [fl["from"], fl["by"]])
    if has_inbound:
        key = "consumers" if "consumers" in ex else sorted(a.name for a in f.actors)[0]
        for c in f.comps:
            mine = [a for a in f.inbound if f.owner.get(a.id) == c.id]
            if mine:
                b.rel(ex[key], procs[c.id], "data-flow", "requests", [], [a.id for a in mine][:50])
                b.rel(procs[c.id], ex[key], "data-flow", "responses", [], [a.id for a in mine][:50], inferred="an API that receives a request returns a response; the content is not analyzed")
    dropped = b.prune({"datastore", "queue", "external-system", "person", "service"})
    am1, mp1 = b.build()
    if b.rels:
        notes1 = [f"not drawn because no data flow was found for them: {', '.join(dropped)}"] if dropped else []
        out.append(DiagramSpec("dfd-1", "data-flow", "Data flow diagram, level 1 (components)", "HLD, LLD", am1, mp1, notes1, level="1", parent="dfd-0"))
    # ------------------------------------------------------------------ level 2: modules of one component
    for c in f.comps:
        mods = {m.id: m for m in f.mods_by_comp[c.id] if m.subtype == "source"}
        fl2 = [x for x in flows if x["by"] == c.id and x["mod"] in mods]
        handler_mods: dict[str, list[tuple[str, str]]] = {}
        for a in [a for a in f.inbound if f.owner.get(a.id) == c.id]:
            for h in f.g.inc.get(a.id, []):
                if h.type == "implements":
                    mod = f.module_of(h.source)
                    if mod and mod.id in mods:
                        handler_mods.setdefault(a.id, []).append((h.id, mod.id))
        if len({x["mod"] for x in fl2} | {m for v in handler_mods.values() for _, m in v}) < 2:
            continue
        b2 = VB(f.g, f"{name} - DFD level 2 - {c.name}")
        pm = {mid: b2.comp(vid("proc", mid), mods[mid].name.rsplit("/", 1)[-1], "module", [mid], desc=mods[mid].name) for mid in sorted({x["mod"] for x in fl2} | {m for v in handler_mods.values() for _, m in v})}
        ex2 = externals(b2)
        brk = None
        if f.events:
            brk = b2.comp("ext-broker", "Message broker", "external-system", [e.id for e in f.events], inferred="topics imply a broker; its identity is not stated in the code")
        st2: dict[str, str] = {}
        table_ids = {t.id for t in f.tables}
        for x in fl2:
            for tid in (x["from"], x["to"]):
                if tid in table_ids and tid not in st2:
                    if len(f.tables) <= MAX_STORES_IN_DFD:
                        st2[tid] = b2.comp(vid("tbl", f.g.ent[tid].name), f.g.ent[tid].name, "datastore", [tid])
                    else:                          # the same grouping as level 1, so the stores seen from outside are the same
                        st2[tid] = b2.comp("ds-database", f"Database ({len(f.tables)} tables)", "datastore", [t.id for t in f.tables], inferred="more tables than a diagram can show: grouped into one store")
        for x in fl2:
            p = pm[x["mod"]]
            if x["label"] == "reads":
                b2.rel(st2[x["from"]], p, "data-flow", "reads", x["rids"], [x["from"], x["mod"]])
            elif x["label"] == "writes":
                b2.rel(p, st2[x["to"]], "data-flow", "writes", x["rids"], [x["to"], x["mod"]])
            elif x["label"] == "request" and ev_host.get(x["to"]):
                b2.rel(p, ex2[ev_host[x["to"]]], "data-flow", "request", x["rids"], [x["to"], x["mod"]])
            elif x["label"] == "publishes" and brk:
                b2.rel(p, brk, "data-flow", "publishes", x["rids"], [x["to"], x["mod"]])
            elif x["label"] == "delivers" and brk:
                b2.rel(brk, p, "data-flow", "delivers", x["rids"], [x["from"], x["mod"]])
        for aid, pairs in handler_mods.items():
            for hid, mid in pairs:
                key = "consumers" if "consumers" in ex2 else (sorted(x.name for x in f.actors)[0] if f.actors else None)
                if key:
                    b2.rel(ex2[key], pm[mid], "data-flow", "requests", [hid], [aid, mid])
                    b2.rel(pm[mid], ex2[key], "data-flow", "responses", [hid], [aid, mid], inferred="an API that receives a request returns a response; the content is not analyzed")
        for r in f.m.relationships:
            if r.type != "calls":
                continue
            ms, mt = f.module_of(r.source), f.module_of(r.target)
            if ms and mt and ms.id != mt.id and ms.id in pm and mt.id in pm:
                b2.rel(pm[ms.id], pm[mt.id], "data-flow", "calls", [r.id], [ms.id, mt.id])
        b2.prune({"external-system", "datastore", "queue", "person"})
        am2, mp2 = b2.build()
        if b2.rels:
            out.append(DiagramSpec(f"dfd-2-{ids.slug(c.name, 20)}", "data-flow", f"Data flow diagram, level 2: {c.name}", "LLD", am2, mp2, level="2", parent=f"dfd-1:{vid('proc', c.name)}"))
    return out


# ----------------------------------------------------------------------------- DFD semantic rules and level balance
_DIR = {"requests": "in", "responses": "out", "request": "out", "reads": "in", "writes": "out", "publishes": "out", "delivers": "in"}


def validate_dfd(am: V.ArchitectureModel) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors are structural DFD rules: named elements, valid endpoints, no flow between two stores or two external entities, every flow labelled,
    every element on at least one flow. A process with no input (a miracle) or no output (a black hole) is a WARNING: it usually means the evidence stops there
    (for example a language without a call graph), not that the diagram is wrong, but the reader must be told."""
    errs: list[str] = []
    warns: list[str] = []
    kinds = {c.id: c.kind for c in am.components}
    ext = {"person", "external-system", "system"}
    store = {"datastore", "queue"}
    deg_in, deg_out = defaultdict(int), defaultdict(int)
    for c in am.components:
        if not c.name.strip():
            errs.append(f"element {c.id} has no name")
    for r in am.relations:
        if r.source not in kinds or r.target not in kinds:
            errs.append(f"flow {r.id} has an endpoint that is not an element")
            continue
        a, b = kinds[r.source], kinds[r.target]
        if a in store and b in store:
            errs.append(f"flow {r.label!r} connects two data stores")
        if a in ext and b in ext:
            errs.append(f"flow {r.label!r} connects two external entities")
        if not r.label.strip():
            errs.append(f"flow {r.id} has no label")
        deg_out[r.source] += 1
        deg_in[r.target] += 1
    for c in am.components:
        if deg_in[c.id] + deg_out[c.id] == 0:
            errs.append(f"{c.kind} '{c.name}' is on no flow")
        if c.kind not in ext and c.kind not in store:
            if deg_in[c.id] == 0:
                warns.append(f"process '{c.name}' has no known input: where its data comes from is not established by the evidence")
            if deg_out[c.id] == 0:
                warns.append(f"process '{c.name}' has no known output: where its data goes is not established by the evidence")
    return errs, warns


def boundary_interface(am: V.ArchitectureModel, process_ids: set[str]) -> set[tuple[str, str, str]]:
    """(peer name, direction as seen from the processes, label) of every flow that crosses the boundary around `process_ids`."""
    names = {c.id: c.name for c in am.components}
    out = set()
    for r in am.relations:
        if r.source in process_ids and r.target not in process_ids:
            out.add((names[r.target], "out", r.label))
        elif r.target in process_ids and r.source not in process_ids:
            out.add((names[r.source], "in", r.label))
    return out


def check_dfd_balance(parent: DiagramSpec, child: DiagramSpec) -> list[str]:
    """A child level must expose to the outside exactly the flows its parent process has.
    Level 0 (one process) vs level 1: the interface of the single process equals the flows between level-1 processes and the SAME peers (externals);
    level 1 vs level 2 (one component): the interface of that component's process equals the interface of the level-2 module set."""
    errs = []
    pa, ch = parent.model, child.model
    if child.level == "1":
        want = boundary_interface(pa, {c.id for c in pa.components if c.kind == "service"})
        ext_ids = {c.id for c in ch.components if c.kind in ("person", "external-system", "system")}
        proc_ids = {c.id for c in ch.components if c.kind == "service"}
        got = {x for x in boundary_interface(ch, proc_ids) if x[0] in {c.name for c in ch.components if c.id in ext_ids}}
        want = {x for x in want}
        for x in sorted(got ^ want):
            errs.append(f"level 0 and level 1 disagree about the flow {x}")
    elif child.level == "2":
        pid = child.parent.split(":", 1)[1]
        proc = next((c for c in pa.components if c.id == pid), None)
        if proc is None:
            return [f"level 2 diagram refers to a parent process {pid} that is not in level 1"]
        want = boundary_interface(pa, {pid})
        mods = {c.id for c in ch.components if c.kind == "module"}
        got = boundary_interface(ch, mods)
        for x in sorted(got ^ want):
            errs.append(f"level 1 process '{proc.name}' and its level 2 decomposition disagree about the flow {x}")
    return errs
