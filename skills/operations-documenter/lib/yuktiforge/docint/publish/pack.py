"""The documentation pack: documents (canonical Markdown), diagrams (editable sources + renders), an HTML site, a DOCX and an A4 PDF, with QA reports.
Every export that cannot be produced here is reported UNAVAILABLE with the reason; nothing is faked, and editable sources are never replaced by images."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yuktiforge.docint.docgen import engine, glossary, registry, render
from yuktiforge.docint.docgen import review as R
from yuktiforge.docint.docgen import validate as DV
from yuktiforge.docint.docgen.doc import Document
from yuktiforge.docint.docgen.outputs import canon, write_documents
from yuktiforge.docint.docgen.trace import requirements_traceability
from yuktiforge.docint.knowledge.build import recorded_time
from yuktiforge.docint.knowledge.schema import KnowledgeModel
from yuktiforge.docint.publish import docx as DX
from yuktiforge.docint.publish import qa, site, tools
from yuktiforge.docint.publish.render_diagrams import DiagramResult, render_all
from yuktiforge.errors import YuktiForgeError

FORMATS = ("html", "docx", "pdf")
DEFAULT_ORDER = ("system-architecture", "hld", "solution-architecture", "technology-architecture", "lld", "api-catalog", "data-dictionary", "database-doc", "dataflow", "code-explanation",
                 "srs-draft", "brd-draft", "functional-spec", "business-rule-catalog", "use-cases")


@dataclass
class Meta:
    repo: str
    revision: str
    scan: str
    title: str

    def as_dict(self) -> dict[str, str]:
        return {"repo": self.repo, "revision": self.revision, "scan": self.scan, "title": self.title}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _strip_for_pack(md: str) -> str:
    md = md.replace("(definitions: glossary.md)", "(definitions: see the glossary, Appendix B)")
    md = re.sub(r"## Contents\n\n(?:- .*\n)+\n", "", md)
    md = re.sub(r"<a id=\"[^\"]*\"></a>", "", md)
    return md


def pack_html(pages: list[site.DocPage], diagrams: list[DiagramResult], gloss: dict, validation: dict, coverage: dict, unsupported: list, meta: Meta, numbers: dict[str, int] | None) -> tuple[str, list[tuple[str, str, int]]]:
    """(html, toc entries as (anchor, title, level)). `numbers` maps anchor -> page for the second pass; the first pass uses a same-width placeholder."""
    esc = site.esc
    entries: list[tuple[str, str, int]] = []
    chapters = []
    for p in pages:
        frag = site.md_to_html(_strip_for_pack(p.md)) if not p.html else re.sub(r"<h2 id=\"contents\">.*?</ul>", "", p.html, count=1, flags=re.S)
        frag = site.prefix_ids(frag, f"{p.stem}--")
        cid = f"ch-{p.stem}"
        entries.append((cid, p.doc.title.split(" — ")[0] if " — " in p.doc.title else p.doc.title, 1))
        subs = site.headings(frag, 2)
        for i, t in subs:
            entries.append((i, t, 2))
        rel = site.diagrams_for(p.doc.doc_type, diagrams)
        links = ("<p class='sources'>Related diagrams: " + ", ".join(f'<a href="#fig-{esc(r.spec.id)}">{esc(r.spec.title)}</a>' for r in rel) + " (Appendix A).</p>") if rel else ""
        frag = re.sub(r"<h1 id=\"([^\"]+)\"", lambda m: f'<h1 id="{cid}" data-orig="{m.group(1)}"', frag, count=1)
        chapters.append(f'<section class="chapter">{frag}{links}</section>')
    entries.append(("app-diagrams", "Appendix A. Diagrams", 1))
    figs = ""
    for r in diagrams:
        entries.append((f"fig-{r.spec.id}", r.spec.title, 2))
        notes = "".join(f"<li>{esc(n)}</li>" for n in r.spec.notes)
        figs += site.figure(r, "diagrams/", "") + (f"<ul class='sources'>{notes}</ul>" if notes else "")
    appx = f'<section class="chapter"><h1 id="app-diagrams">Appendix A. Diagrams</h1><p>Each diagram can be edited at its source (architecture.json for the model, diagram.dot for the layout) and re-rendered; the images here are renders, not the source. Dashed elements are inferred; the rationale is in the diagram page of the site and in architecture.json.</p>{figs}'
    if unsupported:
        appx += "<h2 id='app-unsupported'>Views not generated</h2><ul>" + "".join(f"<li><b>{esc(u.view)}</b> ({esc(u.id)}): {esc(u.reason)}</li>" for u in unsupported) + "</ul>"
        entries.append(("app-unsupported", "Views not generated", 2))
    appx += "</section>"
    entries.append(("app-glossary", "Appendix B. Glossary", 1))
    g_rows = "".join(f"<tr><td>{esc(t['term'])}</td><td><code>{esc(t['id'])}</code></td><td>{esc(t['definition'])}</td></tr>" for t in gloss["terms"])
    gl = f'<section class="chapter"><h1 id="app-glossary">Appendix B. Glossary</h1><p>Terms are entities of the System Knowledge Model; the id is the canonical identifier shared by every document.</p><table><thead><tr><th style="width:26%">Term</th><th style="width:30%">Id</th><th>Meaning</th></tr></thead><tbody>{g_rows}</tbody></table></section>'
    entries.append(("app-quality", "Appendix C. Validation and coverage", 1))
    q_rows = "".join(f"<tr><td>{esc(p.doc.title.split(' — ')[0])}</td><td>{coverage[p.doc.doc_id]['statements']}</td><td>{coverage[p.doc.doc_id]['with_evidence']}</td><td>{coverage[p.doc.doc_id]['unknown_or_needs_validation']}</td><td>{len(validation['documents'][p.doc.doc_id]['defects'])}</td><td>{len(p.doc.gaps)}</td></tr>" for p in pages)
    ql = (f'<section class="chapter"><h1 id="app-quality">Appendix C. Validation and coverage</h1><table><thead><tr><th>Document</th><th>Statements</th><th>With evidence</th><th>Unknown / needs validation</th><th>Defects</th><th>Gaps</th></tr></thead>'
          f'<tbody>{q_rows}</tbody></table><p class="sources">Labels: VERIFIED, INFERRED, USER_SUPPLIED, UNKNOWN, NEEDS_STAKEHOLDER_VALIDATION. A document with gaps is honest but incomplete.</p></section>')
    def num(a: str) -> str:
        return f"{numbers[a]}" if numbers and a in numbers else "00"
    toc_rows = "".join(f'<li class="{"sub" if lvl == 2 else ""}"><a class="t" href="#{esc(a)}">{esc(t)}</a><span class="dots"></span><span class="p">{num(a)}</span></li>' for a, t, lvl in entries if lvl == 1 or numbers is None or True)
    toc = f'<section class="toc-page"><h1 id="toc">Table of contents</h1><ol>{toc_rows}</ol></section>'
    cover = (f'<section class="cover"><h1>{esc(meta.title)}</h1><div class="sub">{esc(meta.repo)}</div><div class="meta">Revision {esc(meta.revision)}<br>Knowledge model scan {esc(meta.scan)}<br>Generated by yuktiforge</div>'
             f'<div class="draft"><b>DRAFT.</b> Reconstructed from source code. Requirement documents in this pack are reconstructions, not approved business requirements. Business intent, security posture and compliance are not established by code and are marked UNKNOWN or NEEDS_STAKEHOLDER_VALIDATION.</div></section>')
    css = (site.tools.ASSETS / "pack.css").read_text(encoding="utf-8")
    html = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{esc(meta.title)}</title><style>{css}</style></head><body>{cover}{toc}{"".join(chapters)}{appx}{gl}{ql}</body></html>'
    return html, entries


def weight_tables(md: str) -> str:
    """Pandoc gives pipe-table columns widths in proportion to the dashes of the separator row. Make the dashes follow the content so short columns are not squeezed and wide ones are not starved."""
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|(?:-{3,}\|)+", lines[i + 1].strip()):
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            block = [lines[k] for k in range(i, j) if k != i + 1]
            cols = [[c.strip() for c in re.split(r"(?<!\\)\|", row.strip())[1:-1]] for row in block]
            n = len(cols[0])
            widths = []
            for c in range(n):
                cells = [r[c] for r in cols if c < len(r)]
                longest = max((len(x) for x in cells), default=3)
                token = max((len(w) for x in cells for w in re.split(r"[\s/]+", x)), default=3)       # never narrower than the longest unbreakable word
                widths.append(max(token * 1.3, min(longest, 44) * 0.8, 8))
            total = sum(widths)
            out += [lines[i], "|" + "|".join("-" * max(3, round(w * 100 / total)) for w in widths) + "|"] + lines[i + 2:j]
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _markdown_for_docx(pages: list[site.DocPage], diagrams: list[DiagramResult], gloss: dict, validation: dict, coverage: dict, unsupported: list, meta: Meta) -> tuple[str, int]:
    """Pandoc-markdown for the DOCX. Chapters get explicit ids so the table of contents can link to them; returns (markdown, number of embedded images)."""
    out: list[str] = []
    toc: list[str] = []
    n_img = 0
    body: list[str] = []
    for p in pages:
        md = _strip_for_pack(p.md)
        titles = [s.title for s in p.doc.sections]
        lines = md.split("\n")
        res, first_h1, sec_i = [], True, 0
        for ln in lines:
            if first_h1 and ln.startswith("# "):
                res.append(ln + f" {{#ch-{p.stem}}}")
                toc.append(f"- [{ln[2:].strip().split(' — ')[0]}](#ch-{p.stem})")
                first_h1 = False
            elif ln.startswith("## ") and sec_i < len(titles) and ln[3:].strip() == titles[sec_i]:
                res.append(ln + f" {{#{p.stem}-{p.doc.sections[sec_i].id}}}")
                sec_i += 1
            elif ln.startswith("#"):
                res.append(ln)
            else:
                res.append(ln)
        rel = site.diagrams_for(p.doc.doc_type, diagrams)
        body.append("\n".join(res).rstrip())
        if rel:
            body.append("Related diagrams: " + ", ".join(f"[{r.spec.title}](#fig-{r.spec.id})" for r in rel) + " (Appendix A).")
    toc += ["- [Appendix A. Diagrams](#app-diagrams)", "- [Appendix B. Glossary](#app-glossary)", "- [Appendix C. Validation and coverage](#app-quality)"]
    out += [f"**DRAFT.** Reconstructed from source code. Requirement documents in this pack are reconstructions, not approved business requirements.", "", "**Table of contents**", "", *toc, ""]
    out += ["\n\n".join(body), ""]
    out += ["# Appendix A. Diagrams {#app-diagrams}", "", "Each diagram can be edited at its source (architecture.json, diagram.dot) and re-rendered. Dashed elements are inferred.", ""]
    for r in diagrams:
        png = f"diagrams/{r.spec.id}/diagram.png"
        out += [f"## {r.spec.title} {{#fig-{r.spec.id}}}", ""]
        if (r.dir / "diagram.png").is_file():
            out += [f"![{r.spec.title}]({png})", ""]
            n_img += 1
        for n in r.spec.notes:
            out += [f"- {n}"]
        out += [""]
    if unsupported:
        out += ["## Views not generated", ""] + [f"- **{u.view}** ({u.id}): {u.reason}" for u in unsupported] + [""]
    out += ["# Appendix B. Glossary {#app-glossary}", "", "| Term | Id | Meaning |", "|---|---|---|"]
    out += [f"| {t['term'].replace('|', '/')} | `{t['id']}` | {t['definition'].replace('|', '/')} |" for t in gloss["terms"]] + [""]
    out += ["# Appendix C. Validation and coverage {#app-quality}", "", "| Document | Statements | With evidence | Unknown or needs validation | Defects | Gaps |", "|---|---|---|---|---|---|"]
    out += [f"| {p.doc.title.split(' — ')[0]} | {coverage[p.doc.doc_id]['statements']} | {coverage[p.doc.doc_id]['with_evidence']} | {coverage[p.doc.doc_id]['unknown_or_needs_validation']} | {len(validation['documents'][p.doc.doc_id]['defects'])} | {len(p.doc.gaps)} |" for p in pages]
    return weight_tables("\n".join(out)) + "\n", n_img


def publish(model: KnowledgeModel, out: Path, *, formats: tuple[str, ...] = FORMATS, title: str = "Knowledge transfer pack", types: list[str] | None = None, audience: str = "architect", depth: str = "summary",
            review: R.ReviewDb | None = None) -> dict[str, Any]:
    for f in formats:
        if f not in FORMATS:
            raise YuktiForgeError(f"unknown format '{f}'; one of: {', '.join(FORMATS)}")
    out.mkdir(parents=True, exist_ok=True)
    registry.load_builtin()
    repo = str(model.repository.get("name", ""))
    meta = Meta(repo, (model.repository.get("revision") or "unknown")[:12], model.scan_id, title)
    report: dict[str, Any] = {"format": "yuktiforge-publish/1", "scan_id": model.scan_id, "repository": model.repository, "formats": list(formats), "tools": tools.tool_report(), "exports": {}, "qa": {}}
    # ------------------------------------------------------------------ documents (canonical, editable Markdown)
    ids_ = types or [t for t in DEFAULT_ORDER if t in registry.REGISTRY.types]
    docs: list[Document] = []
    for tid in ids_:
        dt = registry.get(tid)
        if audience in dt.audiences:
            docs.append(engine.generate(dt, model, audience=audience, depth=depth))
    if not docs:
        raise YuktiForgeError("no document type is offered for this audience")
    src = out / "source"
    man = write_documents(docs, model, src / "documents", review)
    gloss = json.loads((src / "documents" / "glossary.json").read_text())
    validation = json.loads((src / "documents" / "validation.json").read_text())
    trace = requirements_traceability(model)
    coverage = {d.doc_id: render.coverage_report(d, model) for d in docs}
    pages = [site.DocPage(d, (src / "documents" / f"{d.doc_type}.{d.audience}.{d.depth}.md").read_text(encoding="utf-8"), f"{d.doc_type}.{d.audience}.{d.depth}") for d in docs]
    # ------------------------------------------------------------------ diagrams
    results, unsupported, dsum = render_all(model, out / "diagrams")
    report["diagrams"] = dsum
    for r in results:                                              # the editable sources, collected apart from the renders
        dst = src / "diagrams" / r.spec.id
        dst.mkdir(parents=True, exist_ok=True)
        for name in ("architecture.json", "diagram.dot", "mapping.json"):
            if (r.dir / name).is_file():                          # a diagram that failed to render has no .dot; it is reported as failed, it does not stop the pack
                shutil.copy2(r.dir / name, dst / name)
    (src / "system-knowledge.json").write_text(canon(model.model_dump(mode="json")), encoding="utf-8")
    meta_d = meta.as_dict()
    # ------------------------------------------------------------------ HTML site
    if "html" in formats:
        try:
            written = site.build_site(out / "docs-site", pages, results, out / "diagrams", gloss, trace, validation, coverage, unsupported, meta_d)
            links = site.check_links(out / "docs-site")
            (out / "links.json").write_text(canon(links), encoding="utf-8")
            report["exports"]["html"] = {"status": "ok" if not links["problems"] else "defects", "files": len(written), "links_checked": links["links_checked"], "link_problems": links["problems"][:20]}
        except YuktiForgeError as e:
            report["exports"]["html"] = {"status": "UNAVAILABLE", "reason": str(e)}
    # ------------------------------------------------------------------ PDF (HTML -> Chromium, two passes so the table of contents carries real page numbers)
    cache = out / ".cache"
    if "pdf" in formats:
        report["exports"]["pdf"] = _pdf(pages, results, gloss, validation, coverage, unsupported, meta, out, cache, report)
    if "docx" in formats:
        report["exports"]["docx"] = _docx(pages, results, gloss, validation, coverage, unsupported, meta, out, cache, report)
    # ------------------------------------------------------------------ manifest
    files = {}
    for p in sorted(out.rglob("*")):
        rel = p.relative_to(out).as_posix()
        if p.is_file() and not rel.startswith((".cache", "qa/")) and ".lo-profile" not in rel:
            files[rel] = _sha(p)
    report["files"] = len(files)
    (out / "pack-manifest.json").write_text(canon({**report, "file_hashes": files, "documents": man["documents"]}), encoding="utf-8")
    return report


def _pdf(pages, results, gloss, validation, coverage, unsupported, meta, out: Path, cache: Path, report: dict) -> dict[str, Any]:
    pw = tools.playwright_root()
    if pw is None or not tools.which("node"):
        return {"status": "UNAVAILABLE", "reason": "needs Node.js and the Playwright Chromium package (set YUKTIFORGE_PLAYWRIGHT to its node_modules directory)"}
    if not tools.which("pandoc"):
        return {"status": "UNAVAILABLE", "reason": "needs pandoc"}
    html1, entries = pack_html(pages, results, gloss, validation, coverage, unsupported, meta, None)
    html_path = out / "document-pack.html"
    pdf = out / "document-pack.pdf"
    header = f"{meta.title} - {meta.repo} - DRAFT"
    footer = f"{meta.repo} · revision {meta.revision} · scan {meta.scan}"

    def render_pdf() -> None:
        r = tools.run(["node", str(tools.ASSETS / "render_pdf.cjs"), str(pw), str(html_path), str(pdf), header, footer], timeout=300)
        if r.returncode != 0 or not pdf.is_file():
            raise YuktiForgeError(f"Chromium could not render the PDF: {r.stderr.strip()[:300]}")

    html_path.write_text(html1, encoding="utf-8")
    render_pdf()
    info = qa.pdf_pages(pdf, cache)
    numbers: dict[str, int] = {}
    if info:
        texts = info["texts"]
        toc_end = 1
        for i, t in enumerate(texts):
            if "Table of contents" in t:
                toc_end = i + 1
            elif i > 1 and toc_end < i:
                break
        found = qa.locate_headings(texts, [t for _, t, _ in entries], toc_end + 1)
        numbers = {a: pg for (a, _, _), pg in zip(entries, found) if pg}
        html2, _ = pack_html(pages, results, gloss, validation, coverage, unsupported, meta, numbers)
        if html2 != html1:
            html_path.write_text(html2, encoding="utf-8")
            render_pdf()
    final = qa.pdf_qa(pdf, out / "qa" / "pdf-pages", cache, required_texts=["Table of contents", "Appendix A. Diagrams", "Appendix B. Glossary"])
    if final.get("status") != "NOT_TESTED":
        info2 = qa.pdf_pages(pdf, cache)
        if info2:
            toc_end = max([i + 1 for i, t in enumerate(info2["texts"]) if "Table of contents" in t] or [1])
            again = qa.locate_headings(info2["texts"], [t for _, t, _ in entries], toc_end + 1)
            wrong = [f"'{t}' is on page {pg} but the table of contents says {numbers.get(a)}" for (a, t, _), pg in zip(entries, again) if numbers.get(a) != pg]
            if wrong:
                final["defects"] += [f"table of contents: {w}" for w in wrong[:10]]
                final["status"] = "FAIL"
            final["toc_entries_checked"] = len(entries)
    report["qa"]["pdf"] = final
    (out / "visual-qa.json").write_text(canon(report["qa"]), encoding="utf-8")
    return {"status": "ok" if final.get("status") in ("PASS", "NOT_TESTED") else "defects", "file": "document-pack.pdf", "pages": final.get("pages"), "bytes": pdf.stat().st_size, "page_format": "A4", "toc_page_numbers": bool(numbers)}


def _docx(pages, results, gloss, validation, coverage, unsupported, meta, out: Path, cache: Path, report: dict) -> dict[str, Any]:
    if not tools.which("pandoc"):
        return {"status": "UNAVAILABLE", "reason": "needs pandoc"}
    md, n_img = _markdown_for_docx(pages, results, gloss, validation, coverage, unsupported, meta)
    work = out / ".cache" / "docx"
    work.mkdir(parents=True, exist_ok=True)
    (out / "document-pack.md").write_text(md, encoding="utf-8")
    ref = DX.make_reference(work / "reference.docx", f"{meta.title} - {meta.repo} - DRAFT", f"{meta.repo} · revision {meta.revision} · scan {meta.scan}")
    docx_path = out / "document-pack.docx"
    DX.build_docx(out / "document-pack.md", docx_path, ref, out, meta.title, meta.repo, recorded_time() or "")
    struct = qa.docx_structure(docx_path, expect_images=n_img)
    visual: dict[str, Any] = {"status": "NOT_TESTED", "reason": "LibreOffice not available to render the DOCX"}
    pdf = DX.to_pdf(docx_path, work)
    if pdf is not None:
        visual = qa.pdf_qa(pdf, out / "qa" / "docx-pages", cache, required_texts=["Table of contents", "Appendix A. Diagrams"])
    report["qa"]["docx"] = {"structure": struct, "visual": visual}
    (out / "visual-qa.json").write_text(canon(report["qa"]), encoding="utf-8")
    ok = struct["status"] == "PASS" and visual.get("status") in ("PASS", "NOT_TESTED")
    return {"status": "ok" if ok else "defects", "file": "document-pack.docx", "bytes": docx_path.stat().st_size, "images": struct.get("images"), "toc": "linked list (no page numbers; the PDF has them)"}
