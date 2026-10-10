"""Validation of a generated document against its profile. DEFECTS mean the generator broke a rule (the document must not be used); GAPS mean the evidence is missing
(the document is honest but incomplete)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from yuktiforge.docint.docgen import registry
from yuktiforge.docint.docgen.doc import Claim, Document, Table
from yuktiforge.docint.knowledge.schema import KnowledgeModel

SECURITYISH = re.compile(r"\b(secur\w*|complian\w*|encrypt\w*|authenticat\w*|authoriz\w*|gdpr|hipaa|pci|soc ?2|audit\w*|vulnerab\w*)\b", re.I)


@dataclass
class Report:
    defects: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.defects


def _items(doc: Document):
    for s in doc.sections:
        for b in s.blocks:
            if isinstance(b, Claim):
                yield s.id, b.id, b.text, b.labels, b.evidence_ids, b.entity_ids
            elif isinstance(b, Table):
                for r in b.rows:
                    yield s.id, r.id, " | ".join(r.cells), r.labels, r.evidence_ids, r.entity_ids


def validate_document(doc: Document, model: KnowledgeModel) -> Report:
    dt = registry.get(doc.doc_type)
    rep = Report()
    ev = {e.id: e for e in model.evidence}
    ent = {e.id: e for e in model.entities}
    for sid, iid, text, labels, evs, ents in _items(doc):
        where = f"{doc.doc_type}:{sid}:{iid}"
        if dt.evidence_rules.every_claim_labelled and not labels:
            rep.defects.append(f"{where}: statement has no label")
        for i in evs:
            if i not in ev:
                rep.defects.append(f"{where}: cites unknown evidence {i}")
        for i in ents:
            if i not in ent:
                rep.defects.append(f"{where}: refers to unknown entity {i}")
        if "VERIFIED" in labels:
            if dt.evidence_rules.verified_needs_evidence and not evs and not ents:
                rep.defects.append(f"{where}: VERIFIED without evidence")
            weak = [ent[i].cls for i in ents if i in ent and ent[i].cls != "verified"]
            if weak and "INFERRED" not in labels and "UNKNOWN" not in labels:
                rep.defects.append(f"{where}: labelled VERIFIED but rests on {weak[0]} evidence")
        if "USER_SUPPLIED" in labels and not any(i in ent and (ent[i].cls == "user-supplied" or any(ev[x].cls == "user-supplied" for x in ent[i].evidence_ids if x in ev)) for i in ents):
            rep.defects.append(f"{where}: USER_SUPPLIED but no user-supplied entity is cited")
        if dt.evidence_rules.no_security_verification and SECURITYISH.search(re.sub(r"`[^`]*`", "", text)) and "VERIFIED" in labels and "NEEDS_STAKEHOLDER_VALIDATION" not in labels:
            rep.defects.append(f"{where}: security/compliance statement labelled VERIFIED from source inspection alone")
        if "UNKNOWN" not in labels and "NEEDS_STAKEHOLDER_VALIDATION" not in labels and not evs and not ents and not text.startswith(("Scope:", "Note")):
            rep.defects.append(f"{where}: unlabelled-as-unknown statement with neither evidence nor entity")
    if doc.reconstruction or dt.evidence_rules.reconstructed:
        if not any("DRAFT" in b.upper() or "NOT AN APPROVED" in b.upper() for b in doc.banner):
            rep.defects.append("reconstruction without the draft/not-approved banner")
        if not doc.status.startswith(("DRAFT", "REVIEWED")):
            rep.defects.append(f"reconstruction has status '{doc.status}'")
        has_intent = any(e.type == "requirement_candidate" and (e.cls == "user-supplied" or any(ev[x].cls == "user-supplied" for x in e.evidence_ids if x in ev)) for e in model.entities)
        gap_codes = {g.code for g in doc.gaps}
        if doc.doc_type == "brd-draft":
            if not has_intent and "missing-business-intent" not in gap_codes:
                rep.defects.append("no business intent was supplied but the document does not report the gap")
            if has_intent and "missing-business-intent" in gap_codes:
                rep.defects.append("business intent exists in the model but the document reports it missing")
    for g in doc.gaps:
        rep.gaps.append(f"{g.severity}: {g.code} — {g.message}" + (f" [{g.section_id}]" if g.section_id else ""))
    return rep
