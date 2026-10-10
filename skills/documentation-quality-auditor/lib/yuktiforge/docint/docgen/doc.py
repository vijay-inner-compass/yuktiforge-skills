"""The document model every generator produces. A document is a tree of sections; every claim and every table row carries VISIBLE labels and evidence links.

Labels (rendered in the Markdown as bracketed tags):
  VERIFIED                      observed in source or structured text (evidence cited)
  INFERRED                      derived by a rule, a name heuristic or a low-confidence pattern (the rule is stated)
  USER_SUPPLIED                 a named person said so (recorded in the model); not checked against code
  UNKNOWN                       the analysis could not establish it; stated so rather than filled in
  NEEDS_STAKEHOLDER_VALIDATION  a statement about business meaning, intent, security or compliance that source inspection cannot establish
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

Label = Literal["VERIFIED", "INFERRED", "USER_SUPPLIED", "UNKNOWN", "NEEDS_STAKEHOLDER_VALIDATION"]
LABELS: tuple[str, ...] = ("VERIFIED", "INFERRED", "USER_SUPPLIED", "UNKNOWN", "NEEDS_STAKEHOLDER_VALIDATION")
Audience = Literal["executive", "ba", "architect", "developer", "qa", "support", "onboarding"]
AUDIENCES: tuple[str, ...] = ("executive", "ba", "architect", "developer", "qa", "support", "onboarding")
Depth = Literal["summary", "deep"]


class _D(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Claim(_D):
    kind: Literal["claim"] = "claim"
    id: str                                   # stable: derived from the section id and the claim's identity, never from its position
    text: str
    labels: tuple[Label, ...]
    evidence_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    fact_key: str | None = None               # "<entity id>|<attribute>": lets contradiction detection compare statements across documents
    fact_value: str | None = None


class Row(_D):
    cells: tuple[str, ...]
    labels: tuple[Label, ...]
    evidence_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    id: str = ""


class Table(_D):
    kind: Literal["table"] = "table"
    id: str
    caption: str = ""
    header: tuple[str, ...]
    rows: tuple[Row, ...]


class Note(_D):
    kind: Literal["note"] = "note"
    text: str


Block = Annotated[Union[Claim, Table, Note], Field(discriminator="kind")]


class Gap(_D):
    """A validation gap: something the document needs and the evidence does not provide. Never filled in by the generator."""
    code: str
    message: str
    section_id: str = ""
    severity: Literal["error", "warning"] = "warning"


class Section(_D):
    id: str
    title: str
    blocks: tuple[Block, ...] = ()
    audiences: tuple[Audience, ...] | None = None        # None = every audience
    depth: Depth = "summary"                              # a "deep" section is omitted from summary documents
    gaps: tuple[Gap, ...] = ()
    input_hash: str = ""                                  # hash of the facts this section was built from (section-level regeneration and review binding)

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json", exclude={"input_hash"}), sort_keys=True).encode()).hexdigest()


class Document(_D):
    format: str = "yuktiforge-document/1"
    doc_id: str
    doc_type: str
    doc_type_version: str
    title: str
    audience: Audience
    depth: Depth
    scope: str | None = None                              # e.g. module:<path> for a scoped code explanation; needed to regenerate the same document
    scan_id: str
    model_schema: str
    revision: str | None
    status: str                                            # always begins with DRAFT
    banner: tuple[str, ...]
    sections: tuple[Section, ...]
    gaps: tuple[Gap, ...] = ()
    glossary_terms: tuple[str, ...] = ()
    reconstruction: bool = False                           # a reconstruction (BRD/SRS...): never presented as approved business requirements
    generated_with: str = "deterministic templates (no AI)"
