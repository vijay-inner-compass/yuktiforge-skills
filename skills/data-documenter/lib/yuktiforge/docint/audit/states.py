"""Review/approval states of the governance model: DRAFT, NEEDS_REVIEW, APPROVED_BY_USER, STALE. Approval needs an explicit human act (docs review decide) and is bound to the section's
exact content AND to the freshness of the evidence under it: a section whose source changed is STALE however it was approved."""
from __future__ import annotations

from yuktiforge.docint.docgen import review as R
from yuktiforge.docint.docgen.doc import Claim, Document, Table

DRAFT, NEEDS_REVIEW, APPROVED, STALE = "DRAFT", "NEEDS_REVIEW", "APPROVED_BY_USER", "STALE"


def section_evidence(doc: Document) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for s in doc.sections:
        ev: set[str] = set()
        for b in s.blocks:
            if isinstance(b, Claim):
                ev.update(b.evidence_ids)
            elif isinstance(b, Table):
                for r in b.rows:
                    ev.update(r.evidence_ids)
        out[s.id] = ev
    return out


def section_states(doc: Document, db: R.ReviewDb, stale_evidence: set[str]) -> dict[str, str]:
    ev = section_evidence(doc)
    out = {}
    for s in doc.sections:
        state, review_stale = R.section_state(doc, db, s.id)
        if review_stale or (ev[s.id] & stale_evidence):
            out[s.id] = STALE
        elif state == "approved":
            out[s.id] = APPROVED
        elif state in ("in-review", "changes-requested"):
            out[s.id] = NEEDS_REVIEW
        else:
            out[s.id] = DRAFT
    return out


def document_state(states: dict[str, str]) -> str:
    vals = set(states.values())
    if STALE in vals:
        return STALE
    if vals == {APPROVED}:
        return APPROVED
    if NEEDS_REVIEW in vals:
        return NEEDS_REVIEW
    return DRAFT
