"""Cross-document glossary and canonical identifiers. Every term is an entity of the model (so it has one canonical id and one set of evidence); a document lists only the terms it uses."""
from __future__ import annotations

from yuktiforge.docint.docgen.doc import Claim, Document, Table
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import KnowledgeModel

TERM_TYPES = {"component", "api", "database_entity", "event", "technology", "actor", "workflow", "requirement_candidate", "business_rule_candidate", "decision", "document"}
SKIP_SUBTYPE = {"dependency", "config-variable"}


def used_terms(doc: Document, model: KnowledgeModel) -> set[str]:
    ents = {e.id: e for e in model.entities}
    used: set[str] = set()
    for s in doc.sections:
        for b in s.blocks:
            if isinstance(b, Claim):
                used.update(b.entity_ids)
            elif isinstance(b, Table):
                for r in b.rows:
                    used.update(r.entity_ids)
    return {i for i in used if i in ents and ents[i].type in TERM_TYPES and ents[i].subtype not in SKIP_SUBTYPE}


def definition(model: KnowledgeModel, eid: str) -> str:
    g = Graph(model)
    e = g.ent[eid]
    cite = ", ".join(g.cite(e.evidence_ids)[:1])
    kind = e.subtype or e.type
    base = {"component": f"A deployable or buildable part of the system ({kind}).", "api": f"An {'external' if e.external else 'implemented'} {kind} interface.", "database_entity": f"A {kind} in the data store.",
            "event": "A messaging topic or queue.", "technology": f"A {kind} used by the system."}.get(e.type, f"A {e.type.replace('_', ' ')} recorded in the model.")
    stmt = f" {e.attrs['statement']}" if e.attrs.get("statement") else ""
    return f"{base}{stmt} Evidence class: {e.cls}." + (f" Source: {cite}." if cite else "")


def build_glossary(model: KnowledgeModel, docs: list[Document]) -> dict:
    terms: dict[str, dict] = {}
    for d in docs:
        for tid in d.glossary_terms:
            e = next(x for x in model.entities if x.id == tid)
            t = terms.setdefault(tid, {"id": tid, "term": e.name, "type": e.type, "cls": e.cls, "definition": definition(model, tid), "documents": []})
            t["documents"].append(d.doc_id)
    return {"format": "yuktiforge-glossary/1", "scan_id": model.scan_id, "terms": sorted(terms.values(), key=lambda x: (x["term"].lower(), x["id"]))}


def glossary_markdown(g: dict) -> str:
    lines = ["# Glossary", "", "Terms are entities of the System Knowledge Model; the id is the canonical identifier used by every document.", "", "| Term | Id | Meaning | Documents |", "|---|---|---|---|"]
    for t in g["terms"]:
        lines.append(f"| {t['term']} | `{t['id']}` | {t['definition'].replace('|', '/')} | {len(t['documents'])} |")
    return "\n".join(lines) + "\n"
