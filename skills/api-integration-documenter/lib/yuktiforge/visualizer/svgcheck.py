"""Inspect rendered output: semantic comparison with the model, overlap and clipping.

Operates on Graphviz SVG geometry. Text extents are ESTIMATED (avg glyph width 0.5 em), so text
findings are warnings; node/cluster geometry findings are errors.
"""
from __future__ import annotations

import re
import struct
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from yuktiforge.visualizer.validate import Issue

NS = "{http://www.w3.org/2000/svg}"
TOL = 0.5


@dataclass
class BBox:
    x0: float; y0: float; x1: float; y1: float

    def overlap(self, o: "BBox") -> float:
        w = min(self.x1, o.x1) - max(self.x0, o.x0)
        h = min(self.y1, o.y1) - max(self.y0, o.y0)
        return w * h if w > TOL and h > TOL else 0.0

    def contains(self, o: "BBox", tol: float = TOL) -> bool:
        return o.x0 >= self.x0 - tol and o.y0 >= self.y0 - tol and o.x1 <= self.x1 + tol and o.y1 <= self.y1 + tol


@dataclass
class Text:
    s: str; x: float; y: float; size: float; anchor: str

    def bbox(self) -> BBox:
        w = len(self.s) * self.size * 0.5
        x0 = self.x - w / 2 if self.anchor == "middle" else self.x - w if self.anchor == "end" else self.x
        return BBox(x0, self.y - self.size, x0 + w, self.y + self.size * 0.25)


@dataclass
class Shape:
    id: str
    title: str
    box: BBox | None
    texts: list[Text] = field(default_factory=list)
    points: list[tuple[float, float]] = field(default_factory=list)   # edge path control points
    estimated: bool = False   # box derived from text extents (shapeless node such as the legend)


@dataclass
class SvgDoc:
    width: float
    height: float
    nodes: dict[str, Shape]
    edges: dict[str, Shape]
    clusters: dict[str, Shape]


def _nums(s: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", s)]


def _shape_bbox(g: ET.Element, dx: float, dy: float) -> BBox | None:
    xs: list[float] = []; ys: list[float] = []
    for el in g.iter():
        t = el.tag.replace(NS, "")
        if t == "polygon" or t == "polyline":
            n = _nums(el.get("points", ""))
            xs += n[0::2]; ys += n[1::2]
        elif t == "path":
            n = _nums(re.sub(r"[A-Za-z]", " ", el.get("d", "")))
            xs += n[0::2]; ys += n[1::2]
        elif t == "ellipse":
            cx, cy, rx, ry = (float(el.get(k, 0)) for k in ("cx", "cy", "rx", "ry"))
            xs += [cx - rx, cx + rx]; ys += [cy - ry, cy + ry]
    if not xs:
        return None
    return BBox(min(xs) + dx, min(ys) + dy, max(xs) + dx, max(ys) + dy)


def parse_svg(svg: bytes) -> SvgDoc:
    root = ET.fromstring(svg)
    vb = _nums(root.get("viewBox", ""))
    if len(vb) != 4:
        raise ValueError("svg has no viewBox")
    graph = next((g for g in root.iter(f"{NS}g") if g.get("class") == "graph"), None)
    if graph is None:
        raise ValueError("svg has no graph group")
    tr = re.search(r"translate\(([-\d.e]+)[ ,]+([-\d.e]+)\)", graph.get("transform", ""))
    dx, dy = (float(tr.group(1)), float(tr.group(2))) if tr else (0.0, 0.0)
    doc = SvgDoc(vb[2], vb[3], {}, {}, {})
    for g in graph.iter(f"{NS}g"):
        cls = g.get("class")
        if cls not in ("node", "edge", "cluster"):
            continue
        title = (g.findtext(f"{NS}title") or "").strip()
        texts = [Text("".join(t.itertext()), float(t.get("x", 0)) + dx, float(t.get("y", 0)) + dy,
                      float(t.get("font-size", 12)), t.get("text-anchor", "start"))
                 for t in g.iter(f"{NS}text")]
        sh = Shape(g.get("id", ""), title, _shape_bbox(g, dx, dy), texts)
        if cls == "node" and sh.box is None and texts:
            bbs = [t.bbox() for t in texts]
            sh.box = BBox(min(b.x0 for b in bbs), min(b.y0 for b in bbs), max(b.x1 for b in bbs), max(b.y1 for b in bbs))
            sh.estimated = True
        if cls == "edge":
            for p in g.iter(f"{NS}path"):
                n = _nums(re.sub(r"[A-Za-z]", " ", p.get("d", "")))
                sh.points = [(a + dx, b + dy) for a, b in zip(n[0::2], n[1::2])]
                break
        {"node": doc.nodes, "edge": doc.edges, "cluster": doc.clusters}[cls][sh.id] = sh
    return doc


def check_svg(svg: bytes, expect_nodes: dict[str, str], expect_edges: dict[str, tuple[str, str]],
              layer_order: list[str] | None = None) -> list[Issue]:
    """expect_nodes: component id -> name; expect_edges: relation id -> (source, target)."""
    out: list[Issue] = []
    try:
        doc = parse_svg(svg)
    except (ET.ParseError, ValueError) as e:
        return [Issue("svg-unparseable", "error", f"rendered SVG cannot be parsed: {e}")]

    got_nodes = {i[2:]: s for i, s in doc.nodes.items() if i.startswith("n_")}
    for cid in sorted(set(expect_nodes) - set(got_nodes)):
        out.append(Issue("node-missing-in-svg", "error", f"component {cid!r} is in the model but not in the SVG", cid))
    for cid in sorted(set(got_nodes) - set(expect_nodes)):
        out.append(Issue("node-extra-in-svg", "error", f"SVG draws {cid!r} which is not in the model view", cid))
    for cid, name in sorted(expect_nodes.items()):
        s = got_nodes.get(cid)
        # compare ignoring whitespace layout (Graphviz collapses/wraps whitespace inside labels)
        if s and " ".join(name.split()) not in " ".join(" ".join(t.s for t in s.texts).split()):
            out.append(Issue("label-mismatch", "error", f"node {cid!r} does not display its name {name!r}", cid))

    got_edges = {i[2:]: s for i, s in doc.edges.items() if i.startswith("e_")}
    for rid in sorted(set(expect_edges) - set(got_edges)):
        out.append(Issue("edge-missing-in-svg", "error", f"relation {rid!r} is in the model but not in the SVG", rid))
    for rid in sorted(set(got_edges) - set(expect_edges)):
        out.append(Issue("edge-extra-in-svg", "error", f"SVG draws edge {rid!r} which is not in the model view", rid))
    for rid, (s, t) in sorted(expect_edges.items()):
        e = got_edges.get(rid)
        if e and e.title != f"{s}->{t}":
            out.append(Issue("edge-endpoint-mismatch", "error", f"edge {rid!r} draws {e.title!r}, model says {s}->{t}", rid))

    boxed = {i: s.box for i, s in doc.nodes.items() if s.box}
    ids = sorted(boxed)
    for a_i, a in enumerate(ids):
        for b in ids[a_i + 1:]:
            ov = boxed[a].overlap(boxed[b])
            if ov:
                est = doc.nodes[a].estimated or doc.nodes[b].estimated
                out.append(Issue("legend-overlap" if est else "node-overlap", "warning" if est else "error",
                                 f"{a} and {b} overlap by {ov:.0f} sq pt" + (" (estimated extent)" if est else ""), f"{a},{b}"))
    canvas = BBox(0, 0, doc.width, doc.height)
    for kind, group in (("node", doc.nodes), ("cluster", doc.clusters), ("edge", doc.edges)):
        for i, s in group.items():
            if s.box and not canvas.contains(s.box, 1.0):
                # a box estimated from text extents can overshoot by a few pt; the PNG pixel check is the authority
                out.append(Issue("clipped", "warning" if s.estimated else "error",
                                 f"{kind} {i} extends outside the canvas" + (" (estimated extent)" if s.estimated else ""), i))
            for t in s.texts:
                if not canvas.contains(t.bbox(), 1.0):
                    out.append(Issue("clipped-text", "warning", f"text {t.s[:30]!r} may be clipped by the canvas", i))
    for i, s in doc.nodes.items():     # label wider than its own node
        for t in s.texts:
            if s.box and t.bbox().x1 - t.bbox().x0 > (s.box.x1 - s.box.x0) + 1:
                out.append(Issue("text-overflow", "warning", f"text {t.s[:30]!r} may overflow node {i}", i))
    for i, e in doc.edges.items():     # edge label sitting on top of a node
        for t in e.texts:
            for nid, nb in boxed.items():
                if t.bbox().overlap(nb) > 12:
                    out.append(Issue("label-overlaps-node", "warning", f"edge label {t.s[:30]!r} ({i}) overlaps node {nid}", i))
    if layer_order:      # a layered view must stack its layers: each band entirely below the previous one
        bands = [(c, doc.clusters[c].box) for c in layer_order if c in doc.clusters and doc.clusters[c].box]
        for (ca, a), (cb, b) in zip(bands, bands[1:]):
            if b.y0 < a.y1 - 0.5:
                out.append(Issue("layer-order", "error",
                                 f"layer {cb[2:]!r} is not below layer {ca[2:]!r} (bands overlap vertically by {a.y1 - b.y0:.0f}pt)", cb))
    out += _coincident_edges(doc)
    out += _layout_checks(doc)
    if not doc.nodes:
        out.append(Issue("blank-diagram", "error", "SVG contains no nodes"))
    return out


def _bez(points: list[tuple[float, float]], n: int = 20) -> list[tuple[float, float]]:
    """Sample the cubic segments of an SVG path given as [P0, c1, c2, P1, c1, c2, P2, ...]."""
    if len(points) < 4:
        return list(points)
    out = [points[0]]
    for i in range(0, len(points) - 3, 3):
        p0, p1, p2, p3 = points[i:i + 4]
        for k in range(1, n + 1):
            t = k / n; u = 1 - t
            out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def _plen(pts: list[tuple[float, float]]) -> float:
    return sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(pts, pts[1:]))


def _dist_to_poly(p: tuple[float, float], poly: list[tuple[float, float]]) -> float:
    best = float("inf")
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        dx, dy = x1 - x0, y1 - y0
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - x0) * dx + (p[1] - y0) * dy) / L))
        best = min(best, ((p[0] - x0 - t * dx) ** 2 + (p[1] - y0 - t * dy) ** 2) ** 0.5)
    return best


def _coincident_edges(doc: SvgDoc, min_len: float = 30.0) -> list[Issue]:
    """Warn when two different edges run on top of each other (any direction): one hides the other."""
    out: list[Issue] = []
    ids = sorted(doc.edges)
    polys = {i: _bez(doc.edges[i].points) for i in ids}
    for ai, a in enumerate(ids):
        for b in ids[ai + 1:]:
            if len(polys[a]) < 2 or len(polys[b]) < 2:
                continue
            pa = _bez(doc.edges[a].points, 40)
            step = _plen(pa) / max(len(pa) - 1, 1)
            shared = sum(1 for p in pa if _dist_to_poly(p, polys[b]) < 1.5) * step
            if shared > min_len:
                out.append(Issue("edges-coincide", "warning",
                                 f"edges {a} and {b} run on top of each other for ~{shared:.0f}pt; one hides the other", f"{a},{b}"))
    return out


def _layout_checks(doc: SvgDoc) -> list[Issue]:
    """Readability defects found by looking at rendered output: label/label overlap, detached labels,
    edges striking through group titles, edges lying on a group border."""
    out: list[Issue] = []
    labels = [(i, t) for i, e in sorted(doc.edges.items()) for t in e.texts]
    for k, (i1, t1) in enumerate(labels):
        for i2, t2 in labels[k + 1:]:
            if t1.bbox().overlap(t2.bbox()) > 4:
                out.append(Issue("label-overlap", "error", f"edge labels {t1.s[:30]!r} and {t2.s[:30]!r} overlap", f"{i1},{i2}"))
    for i, e in sorted(doc.edges.items()):
        poly = _bez(e.points)
        if len(poly) < 2:
            continue
        for t in e.texts:
            b = t.bbox()
            # distance from the label's nearest side (not its centre: long labels have far-off centres) to its own edge
            d = min(max(b.x0 - x, 0, x - b.x1) ** 2 + max(b.y0 - y, 0, y - b.y1) ** 2 for x, y in poly) ** 0.5
            if d > 15:
                out.append(Issue("label-detached", "warning", f"label {t.s[:30]!r} sits {d:.0f}pt from its own edge ({i})", i))
        for cid, c in sorted(doc.clusters.items()):
            for t in c.texts:
                tb = t.bbox()
                if any(tb.x0 < x < tb.x1 and tb.y0 < y < tb.y1 for x, y in poly):
                    out.append(Issue("edge-crosses-title", "warning", f"edge {i} runs through the title {t.s[:30]!r} of group {cid}", i))
            if c.box:
                b = c.box
                sides = [[(b.x0, b.y0), (b.x1, b.y0)], [(b.x0, b.y1), (b.x1, b.y1)],
                         [(b.x0, b.y0), (b.x0, b.y1)], [(b.x1, b.y0), (b.x1, b.y1)]]
                step = _plen(poly) / max(len(poly) - 1, 1)
                for side in sides:
                    on = sum(1 for p in poly if _dist_to_poly(p, side) < 2.0) * step
                    if on > 40:
                        out.append(Issue("edge-on-border", "warning",
                                         f"edge {i} runs along the border of group {cid} for ~{on:.0f}pt", i))
                        break
    return out


def check_png(png: bytes, svg_w: float, svg_h: float) -> list[Issue]:
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        return [Issue("png-invalid", "error", "PNG signature missing")]
    w, h = struct.unpack(">II", png[16:24])
    out: list[Issue] = []
    if w < 100 or h < 100:
        out.append(Issue("png-tiny", "error", f"PNG is only {w}x{h}"))
    if svg_w and svg_h and abs((w / h) - (svg_w / svg_h)) / (svg_w / svg_h) > 0.02:
        out.append(Issue("png-aspect", "error", f"PNG aspect {w}x{h} differs from SVG {svg_w}x{svg_h}"))
    idat, pos = b"", 8
    while pos < len(png):
        ln, typ = struct.unpack(">I4s", png[pos:pos + 8])
        if typ == b"IDAT":
            idat += png[pos + 8:pos + 8 + ln]
        pos += 12 + ln
    try:
        if len(set(zlib.decompress(idat))) < 6:
            out.append(Issue("png-blank", "error", "PNG pixel data looks blank"))
    except zlib.error:
        out.append(Issue("png-invalid", "error", "PNG data cannot be decompressed"))
    return out


def png_ink_margins(png: bytes) -> tuple[int, int, int, int] | None:
    """Smallest distance (px) between non-white pixels and each image edge (L, T, R, B), measured on the real
    raster -- no text-width estimates. Returns None if the PNG cannot be decoded (8-bit, non-interlaced only)."""
    try:
        pos, idat, w, h, ct = 8, b"", 0, 0, 0
        while pos < len(png):
            ln, typ = struct.unpack(">I4s", png[pos:pos + 8])
            data = png[pos + 8:pos + 8 + ln]
            if typ == b"IHDR":
                w, h, bd, ct, _, _, il = struct.unpack(">IIBBBBB", data)
                if bd != 8 or il != 0 or ct not in (0, 2, 4, 6):
                    return None
            elif typ == b"IDAT":
                idat += data
            pos += 12 + ln
        ch = {0: 1, 2: 3, 4: 2, 6: 4}[ct]
        raw, stride, prev, i = zlib.decompress(idat), w * ch, bytearray(w * ch), 0
        left, right, top, bottom = w, w, h, h
        for y in range(h):
            f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
            i += 1 + stride
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                up = prev[x]
                c = prev[x - ch] if x >= ch else 0
                if f == 1: line[x] = (line[x] + a) & 255
                elif f == 2: line[x] = (line[x] + up) & 255
                elif f == 3: line[x] = (line[x] + ((a + up) >> 1)) & 255
                elif f == 4:
                    p = a + up - c
                    pa, pb, pc = abs(p - a), abs(p - up), abs(p - c)
                    line[x] = (line[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 255
            prev = line
            inked = [x for x in range(w) if not (ch == 4 and line[x * ch + 3] < 8) and min(line[x * ch:x * ch + min(ch, 3)]) < 250]
            if inked:
                left, right = min(left, inked[0]), min(right, w - 1 - inked[-1])
                top, bottom = min(top, y), min(bottom, h - 1 - y)
        return left, top, right, bottom
    except (struct.error, zlib.error, KeyError, IndexError):
        return None


def check_png_margins(png: bytes, min_px: int = 2) -> list[Issue]:
    """Authoritative clipping test on REAL pixels: any ink within `min_px` of an edge means content was cut off.
    Run it on a small raster (the decoder uses only the stdlib, so it is slow on big images); margins scale with the image."""
    m = png_ink_margins(png)
    if m is None:
        return [Issue("png-margin-unchecked", "warning", "PNG could not be decoded for the clipping check")]
    if min(m) < min_px:
        return [Issue("png-clipped", "error", f"rendered ink touches the image edge (margins L,T,R,B = {m} px)")]
    return []


def check_pdf(pdf: bytes) -> list[Issue]:
    out: list[Issue] = []
    if not pdf.startswith(b"%PDF-"):
        out.append(Issue("pdf-invalid", "error", "PDF header missing"))
    if b"%%EOF" not in pdf[-1024:]:
        out.append(Issue("pdf-truncated", "error", "PDF has no EOF marker"))
    if _pdf_page_count(pdf) < 1:
        out.append(Issue("pdf-no-page", "error", "PDF has no page object"))
    return out


def _pdf_page_count(pdf: bytes) -> int:
    """Count /Type /Page objects, including those inside compressed object streams (PDF 1.5+)."""
    page = re.compile(rb"/Type\s*/Page(?![A-Za-z])")
    n = len(page.findall(pdf))
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            n += len(page.findall(zlib.decompress(m.group(1))))
        except zlib.error:
            continue
    return n
