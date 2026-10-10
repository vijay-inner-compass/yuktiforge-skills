"""Markdown, evidence map, coverage report and manifest for generated documents. Labels are always visible; nothing is rendered without them."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from yuktiforge.docint.docgen.doc import Claim, Document, Note, Table
from yuktiforge.docint.docgen.helpers import esc
from yuktiforge.docint.docgen.review import effective_status
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import KnowledgeModel


def safe_md(text: str) -> str:
    """Text from a repository (route templates such as `/orders/<int:id>`, table names, topic names) must never be read as HTML by a Markdown renderer. Outside code spans `<` and `>` become
    entities; inside code spans Markdown already treats them literally."""
    parts = text.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "`".join(parts)


def tags(labels) -> str:
    return " ".join(f"[{l}]" for l in labels)


def cites(g: Graph, ev_ids, limit: int = 2) -> str:
    c = g.cite(ev_ids)[:limit]
    return " (" + "; ".join(x.strip("()") if x.startswith("(") else x for x in c) + ")" if c else ""


def to_markdown(doc: Document, model: KnowledgeModel, review: dict | None = None) -> str:
    g = Graph(model)
    L = [f"# {safe_md(doc.title)}", ""]
    st = effective_status(doc, review) if review is not None else doc.status
    L.append(f"**Status: {safe_md(st)}**")
    for b in doc.banner:
        L += ["", f"> {safe_md(b)}"]
    L += ["", f"*Document `{doc.doc_id}` · type `{doc.doc_type}` v{doc.doc_type_version} · audience {doc.audience}, {doc.depth} · model scan `{doc.scan_id}` · revision {doc.revision or 'unknown'}*", "",
          "Labels: `[VERIFIED]` observed in source · `[INFERRED]` derived by a stated rule · `[USER_SUPPLIED]` stated by a named person · `[UNKNOWN]` could not be established · `[NEEDS_STAKEHOLDER_VALIDATION]` needs a business, security or compliance owner.", ""]
    L.append("## Contents\n")
    for s in doc.sections:
        L.append(f"- [{s.title}](#{s.id})")
    L.append("")
    for s in doc.sections:
        L += [f'<a id="{s.id}"></a>', f"## {s.title}", ""]
        if review is not None:
            rs = review.get(doc.doc_id, {}).get(s.id)
            if rs:
                L += [f"*Review: {rs['state']}" + (f" by {rs['by']}" if rs.get("by") else "") + (" — STALE: section changed after this decision" if rs.get("content_hash") not in (None, s.content_hash()) else "") + "*", ""]
        for b in s.blocks:
            if isinstance(b, Claim):
                L += [f'<a id="{b.id}"></a>{safe_md(b.text)} {tags(b.labels)}{safe_md(cites(g, b.evidence_ids))}', ""]
            elif isinstance(b, Note):
                L += [f"*{safe_md(b.text)}*", ""]
            elif isinstance(b, Table):
                if b.caption:
                    L += [f"**{safe_md(esc(b.caption))}**", ""]
                L += ["| " + " | ".join(safe_md(h) for h in b.header) + " | Basis |", "|" + "---|" * (len(b.header) + 1)]
                for r in b.rows:
                    cells = [safe_md(c) for c in r.cells]
                    L.append("| " + " | ".join(cells) + f" | {tags(r.labels)} |")
                L.append("")
        if s.gaps:
            L += ["**Validation gaps in this section:**", ""] + [f"- `{x.code}` ({x.severity}): {safe_md(x.message)}" for x in s.gaps] + [""]
    if doc.glossary_terms:
        L += ["## Terms used", "", ", ".join(f"`{t}`" for t in doc.glossary_terms[:60]) + (" ..." if len(doc.glossary_terms) > 60 else ""), "(definitions: glossary.md)", ""]
    return "\n".join(L).rstrip() + "\n"


def evidence_map(doc: Document, model: KnowledgeModel) -> dict:
    g = Graph(model)
    claims = {}
    for s in doc.sections:
        for b in s.blocks:
            if isinstance(b, Claim):
                claims[b.id] = {"section": s.id, "labels": list(b.labels), "entities": list(b.entity_ids), "evidence": g.cite(b.evidence_ids), "evidence_ids": list(b.evidence_ids)}
            elif isinstance(b, Table):
                for r in b.rows:
                    claims[r.id] = {"section": s.id, "labels": list(r.labels), "entities": list(r.entity_ids), "evidence": g.cite(r.evidence_ids), "evidence_ids": list(r.evidence_ids)}
    return {"format": "yuktiforge-evidence-map/1", "doc_id": doc.doc_id, "scan_id": doc.scan_id, "claims": claims}


def coverage_report(doc: Document, model: KnowledgeModel) -> dict:
    lab: Counter[str] = Counter()
    n = cited = 0
    for s in doc.sections:
        for b in s.blocks:
            items = [b] if isinstance(b, Claim) else (list(b.rows) if isinstance(b, Table) else [])
            for it in items:
                n += 1
                lab.update(it.labels)
                cited += bool(it.evidence_ids)
    mentioned = {i for s in doc.sections for b in s.blocks for i in ([e for x in b.rows for e in x.entity_ids] if isinstance(b, Table) else list(b.entity_ids) if isinstance(b, Claim) else [])}
    return {"format": "yuktiforge-doc-coverage/1", "doc_id": doc.doc_id, "doc_type": doc.doc_type, "statements": n, "with_evidence": cited, "labels": dict(sorted(lab.items())),
            "sections": [{"id": s.id, "title": s.title, "gaps": len(s.gaps), "statements": len(s.blocks)} for s in doc.sections], "gaps": [g.model_dump(mode="json") for g in doc.gaps],
            "entities_mentioned": len(mentioned), "entities_in_model": len(model.entities),
            "unknown_or_needs_validation": lab.get("UNKNOWN", 0) + lab.get("NEEDS_STAKEHOLDER_VALIDATION", 0)}


def manifest_entry(doc: Document, files: dict[str, str]) -> dict:
    return {"doc_id": doc.doc_id, "doc_type": doc.doc_type, "doc_type_version": doc.doc_type_version, "title": doc.title, "audience": doc.audience, "depth": doc.depth, "status": doc.status,
            "scan_id": doc.scan_id, "revision": doc.revision, "files": files, "section_hashes": {s.id: s.content_hash() for s in doc.sections}, "input_hashes": {s.id: s.input_hash for s in doc.sections},
            "generated_with": doc.generated_with}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
