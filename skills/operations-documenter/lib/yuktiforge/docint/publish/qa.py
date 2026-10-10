"""Visual and structural QA of the exports. Every PDF page is rendered to an image and measured; DOCX files are checked structurally and rendered through LibreOffice.
A check that cannot run (no renderer) is reported NOT_TESTED, never PASS."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from yuktiforge.docint.publish import tools

BAD_TEXT = re.compile(r"\bundefined\b|\bNaN\b|\[object |\{\{|\}\}|TODO-REPLACE")


def pdf_pages(pdf: Path, cache: Path) -> dict[str, Any] | None:
    exe = tools.pdf_reader(cache)
    if exe is None:
        return None
    r = tools.run([str(exe), "info", str(pdf)], timeout=120)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def pdf_qa(pdf: Path, out_dir: Path, cache: Path, *, expect_footer: bool = True, min_pages: int = 2, required_texts: list[str] | None = None, cover_pages: int = 1) -> dict[str, Any]:
    exe = tools.pdf_reader(cache)
    if exe is None:
        return {"status": "NOT_TESTED", "reason": "no PDF renderer available (needs macOS PDFKit via the developer tools)", "defects": []}
    info = json.loads(tools.run([str(exe), "info", str(pdf)], timeout=120).stdout)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = json.loads(tools.run([str(exe), "render", str(pdf), str(out_dir), "70"], timeout=600).stdout)
    texts, metrics = info["texts"], rendered["metrics"]
    n = info["pages"]
    defects: list[str] = []
    if n < min_pages:
        defects.append(f"only {n} page(s)")
    for m, t in zip(metrics, texts):
        p = m["page"]
        if expect_footer and not re.search(rf"Page\s+{p}\s+of\s+{n}\b", t):
            defects.append(f"page {p}: footer 'Page {p} of {n}' not found")
        body_text = re.sub(r"Page\s+\d+\s+of\s+\d+", "", t).strip()
        if m["ink"] < 0.003 and len(body_text) < 5 and p > cover_pages:      # nothing to read and almost no ink (a page with a short last paragraph is not blank)
            defects.append(f"page {p}: blank")
        if m["left_margin_ink"] > 0.01 or m["right_margin_ink"] > 0.01:
            defects.append(f"page {p}: ink in the outer 6 mm margin (content may be clipped): left {m['left_margin_ink']:.3f}, right {m['right_margin_ink']:.3f}")
        bad = BAD_TEXT.search(t)
        if bad:
            defects.append(f"page {p}: suspicious text {bad.group(0)!r}")
    joined = "\n".join(texts)
    for need in required_texts or []:
        if need not in joined:
            defects.append(f"expected text not found in the PDF: {need!r}")
    return {"status": "PASS" if not defects else "FAIL", "pages": n, "defects": defects, "page_images": [m["file"] for m in metrics],
            "metrics": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items() if k not in ("file", "width_px", "height_px")} for m in metrics]}


def locate_headings(texts: list[str], headings: list[str], start_page: int) -> list[int | None]:
    """First page (1-based, never going backwards) whose text contains each heading, in order. One result per heading, so repeated titles ('Overview', 'Terms used') each get their own page."""
    out: list[int | None] = []
    cur = start_page
    last: dict[str, int] = {}
    for h in headings:
        found = None
        for i in range(max(cur, last.get(h, 0) + 1) - 1, len(texts)):       # the same title again must be on a LATER page than its previous occurrence
            if h in texts[i]:
                found = i + 1
                cur = found
                break
        if found:
            last[h] = found
        out.append(found)
    return out


def docx_structure(path: Path, expect_images: int | None = None) -> dict[str, Any]:
    defects: list[str] = []
    info: dict[str, Any] = {}
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return {"status": "FAIL", "defects": ["not a valid zip archive"]}
    names = set(z.namelist())
    for n in sorted(names):
        if n.endswith((".xml", ".rels")):
            try:
                ET.fromstring(z.read(n))
            except ET.ParseError as e:
                defects.append(f"{n}: not well-formed XML ({e})")
    doc = z.read("word/document.xml").decode("utf-8")
    rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    ids = set(re.findall(r'Id="([^"]+)"', rels))
    for rid in set(re.findall(r'r:(?:embed|id)="([^"]+)"', doc)):
        if rid not in ids:
            defects.append(f"document refers to relationship {rid} that does not exist")
    for target in re.findall(r'Target="([^"]+)"', rels):
        if not target.startswith(("http", "mailto")) and f"word/{target}" not in names and target not in names:
            defects.append(f"relationship target {target} is missing from the package")
    info["headings1"] = len(re.findall(r'w:pStyle w:val="Heading1"', doc))
    info["headings2"] = len(re.findall(r'w:pStyle w:val="Heading2"', doc))
    info["tables"] = doc.count("<w:tbl>")
    info["images"] = doc.count("<w:drawing>")
    info["hyperlinks_internal"] = len(re.findall(r'<w:hyperlink [^>]*w:anchor=', doc))
    footers = [z.read(n).decode("utf-8") for n in names if n.startswith("word/footer")]
    info["footer_has_page_fields"] = any("PAGE" in f and "NUMPAGES" in f for f in footers)
    info["page_size_a4"] = 'w:w="11906"' in doc and 'w:h="16838"' in doc
    if not info["footer_has_page_fields"]:
        defects.append("no footer with PAGE / NUMPAGES fields")
    if not info["page_size_a4"]:
        defects.append("page size is not A4")
    if not any(n.startswith("word/header") for n in names):
        defects.append("no header part")
    if info["headings1"] == 0:
        defects.append("no Heading 1 paragraphs")
    if expect_images is not None and info["images"] != expect_images:
        defects.append(f"expected {expect_images} embedded images, found {info['images']}")
    return {"status": "PASS" if not defects else "FAIL", "defects": defects, **info}
