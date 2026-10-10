"""DOCX export through pandoc with a generated reference document: A4, header, footer with page numbers (PAGE / NUMPAGES fields), bordered tables, a table of contents,
a page break before every chapter. The reference document is built from pandoc's own default so the styles pandoc relies on stay intact."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from yuktiforge.docint.publish import tools
from yuktiforge.errors import YuktiForgeError

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
HEADER = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {W}><w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="CBD5E1"/></w:pBdr></w:pPr><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">{{TEXT}}</w:t></w:r></w:p></w:hdr>'
FOOTER = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {W}><w:p><w:pPr><w:tabs><w:tab w:val="right" w:pos="9638"/></w:tabs></w:pPr>'
          '<w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">{LEFT}</w:t></w:r><w:r><w:tab/></w:r>'
          '<w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">Page </w:t></w:r>'
          '<w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:t>1</w:t></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>'
          '<w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve"> of </w:t></w:r>'
          '<w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:t>1</w:t></w:r><w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>'
          '</w:p></w:ftr>')
_BORDERS = ('<w:tblBorders><w:top w:val="single" w:sz="4" w:color="CBD5E1"/><w:left w:val="single" w:sz="4" w:color="CBD5E1"/><w:bottom w:val="single" w:sz="4" w:color="CBD5E1"/>'
            '<w:right w:val="single" w:sz="4" w:color="CBD5E1"/><w:insideH w:val="single" w:sz="4" w:color="CBD5E1"/><w:insideV w:val="single" w:sz="4" w:color="CBD5E1"/></w:tblBorders>')


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_reference(dest: Path, header_text: str, footer_left: str) -> Path:
    if not tools.which("pandoc"):
        raise YuktiForgeError("DOCX export needs pandoc, which was not found on PATH")
    r = tools.run(["pandoc", "-o", str(dest), "--print-default-data-file", "reference.docx"], timeout=60)
    if not dest.is_file():
        raise YuktiForgeError(f"pandoc could not write its reference document: {r.stderr[:200]}")
    src = zipfile.ZipFile(dest)
    parts = {n: src.read(n) for n in src.namelist()}
    src.close()
    doc = parts["word/document.xml"].decode("utf-8")
    doc = re.sub(r"<w:sectPr>.*?</w:sectPr>", '<w:sectPr><w:headerReference w:type="default" r:id="rIdHdr1"/><w:footerReference w:type="default" r:id="rIdFtr1"/>'
                 '<w:footnotePr><w:numRestart w:val="eachSect"/></w:footnotePr><w:pgSz w:w="11906" w:h="16838"/>'
                 '<w:pgMar w:top="1418" w:right="1134" w:bottom="1304" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>', doc, flags=re.S)
    parts["word/document.xml"] = doc.encode("utf-8")
    parts["word/header1.xml"] = HEADER.replace("{TEXT}", esc(header_text)).encode("utf-8")
    parts["word/footer1.xml"] = FOOTER.replace("{LEFT}", esc(footer_left)).encode("utf-8")
    ct = parts["[Content_Types].xml"].decode("utf-8")
    ct = ct.replace("</Types>", '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                    '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>')
    parts["[Content_Types].xml"] = ct.encode("utf-8")
    rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
    rels = rels.replace("</Relationships>", '<Relationship Id="rIdHdr1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
                        '<Relationship Id="rIdFtr1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>')
    parts["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    st = parts["word/styles.xml"].decode("utf-8")
    st = re.sub(r'<w:rFonts w:asciiTheme="minorHAnsi" w:eastAsiaTheme="minorEastAsia" w:hAnsiTheme="minorHAnsi" w:cstheme="minorBidi" />', '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/>', st, count=1)
    st = st.replace('<w:sz w:val="24" />\n        <w:szCs w:val="24" />', '<w:sz w:val="21" />\n        <w:szCs w:val="21" />', 1)
    st = st.replace('<w:tblInd w:w="0" w:type="dxa" />', '<w:tblInd w:w="0" w:type="dxa" />' + _BORDERS, 1)
    st = st.replace('<w:tblStylePr w:type="firstRow">\n      <w:tcPr>', '<w:tblStylePr w:type="firstRow">\n      <w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="F1F5F9"/>', 1)
    # chapters start on a new page (children of pPr must stay in schema order: keepNext, keepLines, pageBreakBefore, ...)
    st = re.sub(r'(<w:style w:type="paragraph" w:styleId="Heading1">.*?<w:keepLines />)', r'\1<w:pageBreakBefore />', st, count=1, flags=re.S)
    st = re.sub(r'(<w:style w:type="paragraph" w:customStyle="1" w:styleId="Compact">.*?<w:pPr>.*?</w:pPr>)', r'\1<w:rPr><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr>', st, count=1, flags=re.S)
    st = st.replace('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" />\n      <w:sz w:val="22" />', '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New" />\n      <w:sz w:val="17" />', 1)
    parts["word/styles.xml"] = st.encode("utf-8")
    th = parts.get("word/theme/theme1.xml")
    if th:
        parts["word/theme/theme1.xml"] = re.sub(rb'(<a:(?:major|minor)Font>\s*<a:latin typeface=")[^"]*(")', rb"\1Arial\2", th)
    out = zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED)
    for n, b in parts.items():
        out.writestr(n, b)
    out.close()
    return dest


def build_docx(markdown: Path, out: Path, reference: Path, resource_dir: Path, title: str, subtitle: str, date: str) -> None:
    r = tools.run(["pandoc", "-f", "markdown-smart-citations-tex_math_dollars-implicit_figures-raw_html-yaml_metadata_block-pandoc_title_block", "-t", "docx", "--reference-doc", str(reference), "--resource-path", str(resource_dir), "--metadata", f"title={title}",
                   "--metadata", f"subtitle={subtitle}", "--metadata", f"date={date}", "-o", str(out), str(markdown)], timeout=300, cwd=resource_dir)
    if r.returncode != 0 or not out.is_file():
        raise YuktiForgeError(f"pandoc could not build the DOCX: {r.stderr.strip()[:300]}")
    if r.stderr.strip():
        out.with_suffix(".pandoc-warnings.txt").write_text(r.stderr, encoding="utf-8")


def to_pdf(docx: Path, outdir: Path) -> Path | None:
    """LibreOffice renders the DOCX the way a reader would see it; used for the visual check. Returns None when LibreOffice is not available."""
    soffice = tools.which("soffice")
    if not soffice:
        return None
    profile = outdir / ".lo-profile"
    r = tools.run([soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(docx)], timeout=300)
    pdf = outdir / (docx.stem + ".pdf")
    return pdf if pdf.is_file() else None
