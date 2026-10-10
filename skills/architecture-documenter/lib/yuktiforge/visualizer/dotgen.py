"""Canonical model -> Graphviz DOT. Deterministic: sorted ids, fixed attributes, no timestamps.

Only the model is read. Provenance *sources* are never drawn (only the evidence *status*), so the
same architecture renders identically whatever language/tooling produced the facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Literal

from yuktiforge.errors import YuktiForgeError
from yuktiforge.visualizer.model import ArchitectureModel, Boundary, Component, Relation

ViewName = Literal["layered", "c4-context", "c4-container", "c4-component", "deployment", "integration", "data-flow", "erd"]

# Honest per-view status. Only views with a rendering function AND tests may be "supported".
VIEW_COVERAGE: dict[str, dict[str, str]] = {
    "layered": {"status": "supported", "note": "components grouped into ordered layers; unlayered ones go to 'Unassigned'"},
    "c4-context": {"status": "supported", "note": "only person/system/external-system components and direct relations between them; no relation lifting"},
    "c4-container": {"status": "supported", "note": "person/external-system/container/service/datastore/queue/infrastructure; component-level kinds omitted"},
    "c4-component": {"status": "supported", "note": "components/modules/packages/libraries of one container with their datastores, queues and external systems"},
    "deployment": {"status": "supported", "note": "containers, infrastructure, services, datastores, queues and external systems; deploys-to relations"},
    "data-flow": {"status": "supported", "note": "data-flow diagram notation: external entities (boxes), processes (ellipses), data stores (cylinders/queues); one level per model"},
    "event-driven": {"status": "not-implemented", "note": ""},
    "integration": {"status": "supported", "note": "services/containers with external systems and queues; no datastores"},
    "erd": {"status": "supported", "note": "entities with their attributes and the relations between them"},
    "infrastructure": {"status": "not-implemented", "note": "infrastructure-kind components can be drawn in the layered/container views"},
}
SUPPORTED_VIEWS = tuple(v for v, c in VIEW_COVERAGE.items() if c["status"] == "supported")

THEME = {  # enterprise-light
    "font": "Helvetica", "text": "#1F2937", "muted": "#6B7280", "line": "#475569", "bg": "#FFFFFF",
    "layer_fill": "#F8FAFC", "layer_line": "#CBD5E1", "boundary_line": "#94A3B8",
    "accent": "#1D4ED8", "inferred": "#B45309",
}
# Routing: Graphviz `splines=ortho` cannot place real edge labels (it degrades to loose xlabels that
# collided with nodes in our first render), so labelled views use polyline routing instead.
KIND_STYLE: dict[str, tuple[str, str]] = {   # kind -> (shape, fill)
    "person": ("box", "#DBEAFE"), "system": ("box", "#E0E7FF"), "external-system": ("box", "#E5E7EB"),
    "container": ("box", "#FFFFFF"), "service": ("box", "#FFFFFF"), "component": ("box", "#FFFFFF"),
    "datastore": ("cylinder", "#ECFDF5"), "queue": ("box", "#FEF3C7"), "infrastructure": ("box3d", "#F3F4F6"),
    "module": ("box", "#FFFFFF"), "package": ("box", "#FFFFFF"), "library": ("box", "#FFFFFF"), "entity": ("plaintext", "#FFFFFF"),
}
# Ordered, deterministic layout candidates. The pipeline renders them in order, scores each with the output
# checker, and keeps the best (stopping early at the first clean one). No single Graphviz setting suits every graph.
LAYOUTS: tuple[dict, ...] = (
    {"name": "auto-polyline", "splines": "polyline", "nodesep": 0.7, "ranksep": 1.0, "xlabel": False, "samerank": "auto", "skiplabels": False},
    {"name": "auto-spline", "splines": "spline", "nodesep": 0.7, "ranksep": 1.0, "xlabel": False, "samerank": "auto", "skiplabels": False},
    {"name": "auto-polyline-skiplabels", "splines": "polyline", "nodesep": 0.7, "ranksep": 1.0, "xlabel": False, "samerank": "auto", "skiplabels": True},
    {"name": "auto-spline-skiplabels", "splines": "spline", "nodesep": 0.7, "ranksep": 1.0, "xlabel": False, "samerank": "auto", "skiplabels": True},
    {"name": "rows-polyline", "splines": "polyline", "nodesep": 0.7, "ranksep": 1.0, "xlabel": False, "samerank": True, "skiplabels": False},
    {"name": "rows-polyline-skiplabels", "splines": "polyline", "nodesep": 1.0, "ranksep": 1.3, "xlabel": False, "samerank": True, "skiplabels": True},
)
@dataclass(frozen=True)
class RenderOptions:
    """Presentation-only knobs. NONE of them can change an architecture fact (components, relations, evidence, layers).

    The bounded repair loop (evaluation.repair) may only adjust these. `fixed_node_width` exists so tests can
    inject a *defect* (text wider than its node); production builds never set it.
    """
    spacing_scale: float = 1.0                     # multiplies nodesep and ranksep
    node_margin: tuple[float, float] = (0.25, 0.15)
    wrap_at: int = 0                               # 0 = never wrap; N = break names/labels at word boundaries near N chars
    fixed_node_width: float | None = None          # inches; DEFECT INJECTION ONLY

    def as_dict(self) -> dict:
        return {"spacing_scale": self.spacing_scale, "node_margin": list(self.node_margin), "wrap_at": self.wrap_at,
                "fixed_node_width": self.fixed_node_width}


DEFAULT_OPTIONS = RenderOptions()


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap; a single word longer than `width` is kept whole (never split mid-word)."""
    if width <= 0 or len(text) <= width:
        return [text]
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return [*lines, cur]


C4_CONTEXT_KINDS = {"person", "system", "external-system"}
C4_CONTAINER_KINDS = {"person", "external-system", "system", "container", "service", "datastore", "queue", "infrastructure"}
C4_COMPONENT_KINDS = {"person", "external-system", "system", "service", "component", "module", "package", "library", "datastore", "queue"}
DEPLOYMENT_KINDS = {"container", "infrastructure", "service", "datastore", "queue", "external-system"}
DATAFLOW_KINDS = {"person", "external-system", "system", "service", "container", "component", "module", "datastore", "queue"}
INTEGRATION_KINDS = {"person", "external-system", "system", "container", "service", "queue"}
DFD_EXTERNAL = {"person", "external-system", "system"}
DFD_STORE = {"datastore", "queue"}


@dataclass
class ViewResult:
    view: str
    dot: str
    components: list[str]
    relations: list[str]
    omitted_components: dict[str, str] = field(default_factory=dict)   # id -> reason
    omitted_relations: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    layer_order: list[str] = field(default_factory=list)   # cluster ids, top to bottom (layered view only)


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _t(s: str) -> str:
    """Label text: collapse all whitespace (incl. newlines, which HTML labels would silently drop) to single spaces."""
    return " ".join(s.split())


def _node_label(c: Component, lay: dict) -> str:
    f = THEME["font"]
    rows = [f'<B>{escape(line)}</B>' for line in _wrap(_t(c.name or c.id), lay["wrap_at"])]
    sub = " · ".join(x for x in (c.kind.replace("-", " "), _t(c.technology)) if x)
    rows.append(f'<FONT POINT-SIZE="9" COLOR="{THEME["muted"]}">[{escape(sub)}]</FONT>')
    if c.evidence.status == "inferred":
        rows.append(f'<FONT POINT-SIZE="9" COLOR="{THEME["inferred"]}"><I>inferred</I></FONT>')
    return "<" + "<BR/>".join(rows) + ">"


def _entity_node(c: Component, lay: dict) -> str:
    """ERD entity: a table with the name in the header and one row per attribute."""
    f = THEME
    col = f["inferred"] if c.evidence.status == "inferred" else f["line"]
    rows = [f'<TR><TD BGCOLOR="#E0E7FF" ALIGN="CENTER"><B>{escape(_t(c.name or c.id))}</B></TD></TR>']
    rows += [f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="10">{escape(_t(a))}</FONT></TD></TR>' for a in (c.attributes or ("(attributes unknown)",))]
    if c.evidence.status == "inferred":
        rows.append(f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="9" COLOR="{f["inferred"]}"><I>inferred</I></FONT></TD></TR>')
    return (f'{q(c.id)} [id={q("n_" + c.id)}, shape=plaintext, label=<<TABLE BORDER="1" COLOR="{col}" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" BGCOLOR="#FFFFFF">'
            f'{"".join(rows)}</TABLE>>, tooltip={q(c.description or c.name or c.id)}];')


def _node(c: Component, lay: dict, shape_override: str | None = None) -> str:
    if c.kind == "entity":
        return _entity_node(c, lay)
    shape, fill = KIND_STYLE[c.kind]
    if shape_override:
        shape = shape_override
    st = {"verified": ("rounded,filled,bold", THEME["line"]),
          "user-supplied": ("rounded,filled", THEME["line"]),
          "inferred": ("rounded,filled,dashed", THEME["inferred"])}[c.evidence.status]
    style = "filled" if shape == "cylinder" else st[0]
    if shape == "cylinder" and c.evidence.status == "inferred":
        style = "filled,dashed"
    if shape in ("box3d",):
        style = "filled,dashed" if c.evidence.status == "inferred" else "filled"
    return (f'{q(c.id)} [id={q("n_" + c.id)}, label={_node_label(c, lay)}, shape={shape}, style={q(style)}, '
            f'fillcolor={q(fill)}, color={q(st[1])}, tooltip={q(c.description or c.name or c.id)}'
            + (f', fixedsize=true, width={lay["fixed_w"]}' if lay["fixed_w"] else '') + '];')


def _edge(r: Relation, lay: dict, skips: bool = False) -> str:
    lab = _t(r.label) + (f" [{_t(r.technology)}]" if r.technology else "")
    if r.evidence.status == "inferred":
        lab = (lab + " (inferred)").strip()
    style, color = {"verified": ("solid", THEME["line"]), "user-supplied": ("solid", THEME["accent"]),
                    "inferred": ("dashed", THEME["inferred"])}[r.evidence.status]
    attrs = [f"id={q('e_' + r.id)}", f"color={q(color)}", f"fontcolor={q(color)}", f"style={style}"]
    if lab and skips and lay["skiplabels"]:   # long edge crossing >1 layer: label near the arrowhead, not floating mid-air
        attrs.append(f'headlabel=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2" BGCOLOR="{THEME["bg"]}">'
                     f'<TR><TD>{escape(lab)}</TD></TR></TABLE>>, labeldistance=2.2, labelangle=-25')
    elif lab and lay["xlabel"]:   # orthogonal routing cannot place real labels; Graphviz offers loose xlabels
        attrs.append(f"xlabel={q(lab)}")
    elif lab:   # HTML label with a white background so the edge line never strikes through the text
        attrs.append(f'label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2" BGCOLOR="{THEME["bg"]}">'
                     f'<TR><TD>{escape(lab)}</TD></TR></TABLE>>')
    return f'{q(r.source)} -> {q(r.target)} [{", ".join(attrs)}];'


def _legend(m: ArchitectureModel | None = None, omitted: dict[str, int] | None = None) -> str:
    f = THEME
    def row(sample: str, text: str) -> str:
        return f'<TR><TD ALIGN="LEFT">{sample}</TD><TD ALIGN="LEFT">{escape(text)}</TD></TR>'
    rows = [
        row(f'<FONT COLOR="{f["line"]}">━━</FONT>', "verified (cited in source files)"),
        row(f'<FONT COLOR="{f["accent"]}">━━</FONT>', "user-supplied"),
        row(f'<FONT COLOR="{f["inferred"]}">╌╌</FONT>', "inferred (see rationale)"),
    ]
    rows.append(f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="{f["muted"]}">'
                'Node outline: bold = verified, thin = user-supplied, dashed = inferred</FONT></TD></TR>')
    if omitted and omitted.get("components"):     # a view must not imply the omitted parts do not exist
        kinds = ", ".join(sorted(omitted["kinds"]))
        rows.append(f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="{f["inferred"]}">'
                    f'Not shown in this view: {omitted["components"]} component(s) of kind {escape(kinds)}, '
                    f'{omitted["relations"]} relation(s)</FONT></TD></TR>')
    # A diagram must not imply that code it could not read does not exist.
    gaps = sorted(l.language for l in (m.coverage.languages if m else ()) if l.depth == "none")
    bad = list(m.coverage.unparsed_files) if m else []
    if bad:      # an unreadable file looks like "no dependencies" unless the picture says otherwise
        shown = ", ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else "")
        rows.append(f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="{THEME["inferred"]}">'
                    f'Could not parse {len(bad)} file(s): {escape(shown)} - relations of these are UNKNOWN, not absent</FONT></TD></TR>')
    if gaps:
        rows.append(f'<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="{THEME["inferred"]}">'
                    f'Not analyzed (no analyzer): {escape(", ".join(gaps))}</FONT></TD></TR>')
    return ('legend [id="legend", shape=plaintext, label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">'
            f'<TR><TD COLSPAN="2" ALIGN="LEFT"><B>Evidence</B></TD></TR>{"".join(rows)}</TABLE>>];')


def _header(rankdir: str, title: str, lay: dict) -> list[str]:
    t = THEME
    return [
        "digraph architecture {",
        f'  graph [rankdir={rankdir}, splines={lay["splines"]}, newrank=true, nodesep={round(lay["nodesep"] * lay["spacing"], 3)}, ranksep={round(lay["ranksep"] * lay["spacing"], 3)}, pad=0.4, '
        f'bgcolor={q(t["bg"])}, fontname={q(t["font"])}, fontsize=18, fontcolor={q(t["text"])}, '
        f'labelloc=t, labeljust=l, label={q(title)}, charset="UTF-8"];',
        f'  node [fontname={q(t["font"])}, fontsize=12, fontcolor={q(t["text"])}, margin="{lay["margin"][0]},{lay["margin"][1]}"];',
        f'  edge [fontname={q(t["font"])}, fontsize=10, arrowsize=0.8, penwidth=1.3];',
    ]


def _select(m: ArchitectureModel, kinds: set[str] | None, why: str):
    comps = [c for c in sorted(m.components, key=lambda x: x.id) if kinds is None or c.kind in kinds]
    omitted = {c.id: why for c in m.components if kinds is not None and c.kind not in kinds}
    ids = {c.id for c in comps}
    rels, omr = [], {}
    for r in sorted(m.relations, key=lambda x: x.id):
        if r.source in ids and r.target in ids:
            rels.append(r)
        else:
            omr[r.id] = "endpoint not in this view"
    return comps, rels, omitted, omr


def _paint_order(rels: list[Relation]) -> list[Relation]:
    """Verified first, inferred last: later edges paint on top, so dashed (inferred) edges are never hidden."""
    rank = {"verified": 0, "user-supplied": 1, "inferred": 2}
    return sorted(rels, key=lambda r: (rank[r.evidence.status], r.id))


def _indent(lines: list[str], n: int) -> list[str]:
    return [" " * n + ln for ln in lines]


def render_layered(m: ArchitectureModel, lay: dict) -> ViewResult:
    comps, rels, omc, omr = _select(m, None, "")
    layers = sorted((l for l in m.layers), key=lambda l: (l.order, l.id))
    groups: list[tuple[str, str, list[Component]]] = []
    lids = {l.id for l in layers}
    for l in layers:
        cs = [c for c in comps if c.layer == l.id]
        if cs:
            groups.append((l.id, l.name or l.id, cs))
    un = [c for c in comps if not c.layer or c.layer not in lids]
    notes = []
    if un:
        groups.append(("unassigned", "Unassigned (no layer given)", un))
        notes.append(f"{len(un)} component(s) have no layer and are shown under 'Unassigned'; layers are never guessed")
    gidx = {c.id: i for i, (_, _, cs) in enumerate(groups) for c in cs}
    intra = {gidx[r.source] for r in rels if gidx[r.source] == gidx[r.target]}
    out = _header("TB", f"{m.name or 'Architecture'} — layered view", lay)
    for gi, (lid, lname, cs) in enumerate(groups):
        tid = "t_" + lid     # layer title is a NODE: edges are routed around nodes but cut straight through cluster labels
        row = len(groups) > 1 and (lay["samerank"] is True or (lay["samerank"] == "auto" and gi not in intra))
        out += [f'  subgraph {q("cluster_" + lid)} {{',
                f'    graph [id={q("c_" + lid)}, label="", style="rounded,filled", '
                f'fillcolor={q(THEME["layer_fill"])}, color={q(THEME["layer_line"])}, margin=18];',
                f'    {q(tid)} [id={q(tid)}, shape=plaintext, label=<<B>{escape(_t(lname))}</B>>, fontsize=13, margin="0.1,0.05"];',
                f'    {{ rank=same; {q(tid)}; {q(cs[0].id)}; }}',
                f'    {q(tid)} -> {q(cs[0].id)} [style=invis, weight=20];']
        if row:      # a layer without internal edges is a single row
            out += ["    { rank=same;"] + _indent([_node(c, lay) for c in cs], 6) + ["    }", "  }"]
        else:        # a layer WITH internal edges cascades so those edges do not have to arc over their neighbours
            out += _indent([_node(c, lay) for c in cs], 4) + ["  }"]
    for (_, _, ca), (_, _, cb) in zip(groups, groups[1:]):
        # every node of a layer sits above every node of the next layer => layers are true vertical bands
        out += [f'  {q(u.id)} -> {q(v.id)} [style=invis, weight=1];' for u in ca for v in cb]
    out += _indent([_edge(r, lay, abs(gidx[r.source] - gidx[r.target]) >= 2) for r in _paint_order(rels)], 2)
    out += ["  { rank=sink;", "    " + _legend(m), "  }", "}"]
    res = ViewResult("layered", "\n".join(out) + "\n", [c.id for c in comps], [r.id for r in rels], omc, omr, notes)
    res.layer_order = ["c_" + g[0] for g in groups]
    return res


def _boundary_tree(m: ArchitectureModel, comps: list[Component]) -> tuple[dict[str | None, list[Boundary]], dict[str, list[Component]], list[Component]]:
    bids = {b.id for b in m.boundaries}
    kids: dict[str | None, list[Boundary]] = {}
    for b in sorted(m.boundaries, key=lambda x: x.id):
        kids.setdefault(b.parent if b.parent in bids else None, []).append(b)
    inb: dict[str, list[Component]] = {}
    loose: list[Component] = []
    for c in comps:
        (inb.setdefault(c.boundary, []) if c.boundary in bids else loose).append(c)
    return kids, inb, loose


def _render_boundaries(parent: str | None, kids, inb, depth: int, lay: dict) -> list[str]:
    out: list[str] = []
    for b in kids.get(parent, []):
        sub = _render_boundaries(b.id, kids, inb, depth + 1, lay)
        if not sub and not inb.get(b.id):
            continue
        pad = "  " * depth
        out += [f'{pad}subgraph {q("cluster_" + b.id)} {{',
                f'{pad}  graph [id={q("c_" + b.id)}, label={q(b.name or b.id)}, labeljust=l, style="rounded,dashed", '
                f'color={q(THEME["boundary_line"])}, fontsize=12, margin=16];']
        out += _indent([_node(c, lay, lay.get("shapes", {}).get(c.kind)) for c in inb.get(b.id, [])], len(pad) + 2)
        out += sub
        out.append(f"{pad}}}")
    return out


def _render_boundary_view(m: ArchitectureModel, name: str, kinds: set[str], title: str, lay: dict, shapes: dict[str, str] | None = None) -> ViewResult:
    comps, rels, omc, omr = _select(m, kinds, "kind not shown in this view")
    kids, inb, loose = _boundary_tree(m, comps)
    out = _header("LR", f"{m.name or 'Architecture'} — {title}", lay)
    if shapes:
        lay = {**lay, "shapes": shapes}
    out += _indent([_node(c, lay, (shapes or {}).get(c.kind)) for c in loose], 2)
    out += _indent(_render_boundaries(None, kids, inb, 1, lay), 0)
    out += _indent([_edge(r, lay) for r in _paint_order(rels)], 2)
    om = {"components": len(omc), "relations": len(omr), "kinds": {c.kind for c in m.components if c.id in omc}}
    out += ["  { rank=sink;", "    " + _legend(m, om), "  }", "}"]
    notes = []
    if omc:
        notes.append(f"{len(omc)} component(s) omitted: kind not part of this view")
    return ViewResult(name, "\n".join(out) + "\n", [c.id for c in comps], [r.id for r in rels], omc, omr, notes)


def render_view(m: ArchitectureModel, view: str, layout: int = 0, options: RenderOptions = DEFAULT_OPTIONS) -> ViewResult:
    status = VIEW_COVERAGE.get(view)
    if status is None:
        raise YuktiForgeError(f"unknown view {view!r}; known: {', '.join(VIEW_COVERAGE)}")
    if status["status"] != "supported":
        raise YuktiForgeError(f"view {view!r} is {status['status']}; supported views: {', '.join(SUPPORTED_VIEWS)}")
    lay = {**LAYOUTS[layout], "spacing": options.spacing_scale, "margin": options.node_margin,
           "wrap_at": options.wrap_at, "fixed_w": options.fixed_node_width}
    if view == "layered":
        res = render_layered(m, lay)
    elif view == "c4-context":
        res = _render_boundary_view(m, view, C4_CONTEXT_KINDS, "C4 system context", lay)
    elif view == "c4-component":
        res = _render_boundary_view(m, view, C4_COMPONENT_KINDS, "C4 component view", lay)
    elif view == "deployment":
        res = _render_boundary_view(m, view, DEPLOYMENT_KINDS, "deployment view", lay)
    elif view == "integration":
        res = _render_boundary_view(m, view, INTEGRATION_KINDS, "integration view", lay)
    elif view == "data-flow":
        res = _render_boundary_view(m, view, DATAFLOW_KINDS, "data flow diagram", lay, {k: "ellipse" for k in ("service", "container", "component", "module")})
    elif view == "erd":
        res = _render_boundary_view(m, view, {"entity"}, "entity-relationship diagram", lay)
    else:
        res = _render_boundary_view(m, view, C4_CONTAINER_KINDS, "C4 container view", lay)
    if not res.components:
        raise YuktiForgeError(f"view {view!r} has no components to draw for this model "
                              f"(omitted: {len(res.omitted_components)}); check component kinds")
    return res
