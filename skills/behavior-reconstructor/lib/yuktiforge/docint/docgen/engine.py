"""Generation engine: runs one document type over the model for an audience and depth, applies the profile, and attaches status, banner and glossary terms.
It knows nothing about individual document types."""
from __future__ import annotations

import hashlib

from yuktiforge.docint.docgen import registry
from yuktiforge.docint.docgen.doc import AUDIENCES, Document, Gap, Section
from yuktiforge.docint.docgen.glossary import used_terms
from yuktiforge.docint.docgen.spi import DocumentType, GenContext
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import SCHEMA_VERSION, KnowledgeModel
from yuktiforge.errors import YuktiForgeError

AUDIENCE_FRAMING = {
    "executive": "Written for executives: counts, risks and open questions; implementation detail is left out.",
    "ba": "Written for business analysts and product owners: observed behaviour and the questions that need business answers.",
    "architect": "Written for architects: structure, connections and what could not be established.",
    "developer": "Written for developers: names, locations and evidence for every statement.",
    "qa": "Written for QA: observable behaviour, data touched and where tests are or are not linked.",
    "support": "Written for support and operations: configuration, dependencies, data stores and known unknowns.",
    "onboarding": "Written for new team members: where things are and how they connect.",
}


def applies(sec: Section, audience: str, depth: str) -> bool:
    if sec.audiences is not None and audience not in sec.audiences:
        return False
    return not (sec.depth == "deep" and depth == "summary")


def generate(dt: DocumentType | str, model: KnowledgeModel, *, audience: str = "developer", depth: str = "summary", scope: str | None = None) -> Document:
    dt = registry.get(dt) if isinstance(dt, str) else dt
    if audience not in AUDIENCES:
        raise YuktiForgeError(f"unknown audience '{audience}'; one of: {', '.join(AUDIENCES)}")
    if depth not in ("summary", "deep"):
        raise YuktiForgeError("depth must be 'summary' or 'deep'")
    if audience not in dt.audiences:
        raise YuktiForgeError(f"'{dt.id}' is not offered for the '{audience}' audience (offered: {', '.join(dt.audiences)})")
    ctx = GenContext(model=model, graph=Graph(model), audience=audience, depth=depth, scope=scope, template=f"{dt.id}@{dt.version}")           # type: ignore[arg-type]
    built = dt.build(ctx)
    declared = {s.id for s in dt.sections}
    for s in built:
        if s.id not in declared:
            raise YuktiForgeError(f"document type '{dt.id}' produced undeclared section '{s.id}'")
    sections = tuple(s for s in built if applies(s, audience, depth))
    gaps = tuple(g for s in sections for g in s.gaps)
    # a required section that exists nowhere in the output is itself a validation gap
    present = {s.id for s in built}
    miss = tuple(Gap(code="missing-required-section", message=f"required section '{sp.title}' was not produced", section_id=sp.id, severity="error") for sp in dt.sections if sp.required and sp.id not in present)
    doc_id = "doc:" + dt.id + "-" + hashlib.sha1(f"{dt.id}|{audience}|{depth}|{scope}".encode()).hexdigest()[:8]      # stable across regenerations: reviews are keyed by it
    status = dt.status(ctx)
    errors = [g for g in (*gaps, *miss) if g.severity == "error"]
    if errors:
        status += " (INCOMPLETE: " + ", ".join(sorted({g.code for g in errors})) + ")"
    doc = Document(doc_id=doc_id, doc_type=dt.id, doc_type_version=dt.version, title=dt.title, audience=audience, depth=depth, scope=scope, scan_id=model.scan_id, model_schema=SCHEMA_VERSION,       # type: ignore[arg-type]
                   revision=model.repository.get("revision"), status=status, banner=(AUDIENCE_FRAMING[audience], *dt.banner), reconstruction=dt.evidence_rules.reconstructed, sections=sections, gaps=(*gaps, *miss))
    return doc.model_copy(update={"glossary_terms": tuple(sorted(used_terms(doc, model)))})


def generate_all(model: KnowledgeModel, type_ids: list[str] | None = None, *, audience: str = "developer", depth: str = "summary") -> list[Document]:
    out = []
    for dt in registry.all_types():
        if (type_ids and dt.id not in type_ids) or (audience not in dt.audiences):
            continue
        out.append(generate(dt, model, audience=audience, depth=depth))
    return out
