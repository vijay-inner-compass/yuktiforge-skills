"""Versioned schema of the System Knowledge Model.

Two different questions are kept apart on purpose:
  * the EVIDENCE CLASS of a claim: `verified` (observed in source/structured text), `user-supplied` (a person said so), `inferred` (derived by a rule or guess, needs a
    rationale) or `unknown` (named but not established). A class is never upgraded automatically: an entity can be no more certain than its weakest evidence.
  * the APPROVAL of a requirement or business-rule candidate: a reconstruction from code is never an approved requirement; only an explicit, recorded act by a named person
    changes that, and it is a separate field.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.1"
FORMAT = "yuktiforge-system-knowledge"

EntityType = Literal["repository", "module", "component", "symbol", "interface", "api", "event", "database_entity", "field", "business_rule_candidate", "workflow", "actor",
                     "requirement_candidate", "technology", "deployment_boundary", "risk", "decision", "document"]
RelType = Literal["calls", "imports", "owns", "reads", "writes", "publishes", "subscribes", "implements", "deploys-to", "traces-to", "contradicts", "derived-from"]
EvidenceClass = Literal["verified", "user-supplied", "inferred", "unknown"]
CLASS_RANK: dict[str, int] = {"unknown": 0, "inferred": 1, "user-supplied": 2, "verified": 3}
Status = Literal["active", "stale", "retired"]
Attr = str | int | bool | list[str]

# Relationships whose cycles are an error (containment and derivation must form a forest/DAG); imports and calls may legitimately cycle.
ACYCLIC = frozenset({"owns", "derived-from"})
# Entity types that are reconstructions: they carry an approval state that only an explicit human act can change.
APPROVABLE = frozenset({"requirement_candidate", "business_rule_candidate", "decision"})


class _K(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(_K):
    id: str
    cls: EvidenceClass
    path: str | None = None              # repository-relative; None for user-supplied statements
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    revision: str | None = None          # repository revision the scan was taken at
    method: str = ""                     # ast | lexical | structured | manifest | pattern | path | user | rule
    analyzer: str = ""
    extraction_confidence: Literal["high", "medium", "low"] | None = None
    content_sha256: str | None = None    # hash of the cited lines at scan time: if the file changes, the evidence is STALE
    note: str = ""                       # rationale for inferred evidence; statement and source for user-supplied
    recorded_at: str | None = None       # ISO time; only set when SOURCE_DATE_EPOCH is given or by a user assertion, so builds stay reproducible


class Entity(_K):
    id: str
    type: EntityType
    name: str
    subtype: str = ""
    cls: EvidenceClass
    status: Status = "active"
    external: bool = False               # lives outside the repository (a third-party API, a message topic owned elsewhere)
    attrs: dict[str, Attr] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    approval: str | None = None          # only for APPROVABLE types: "unapproved" or "approved-by:<name>"


class Relationship(_K):
    id: str
    type: RelType
    source: str
    target: str
    cls: EvidenceClass
    attrs: dict[str, Attr] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()


class Gap(_K):
    """Something the analysis could not establish. A generator must show it as unknown, never fill it in."""
    id: str
    kind: Literal["unresolved-calls", "dynamic-name", "unsupported-language", "parse-failure", "spec-only-route", "code-only-route", "partial-analysis", "no-call-graph"]
    detail: str
    entity_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class Conflict(_K):
    id: str
    kind: Literal["duplicate-route", "schema-mismatch", "user-vs-observed"]
    detail: str
    entity_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()


class KnowledgeModel(_K):
    format: str = FORMAT
    schema_version: str = SCHEMA_VERSION
    scan_id: str
    repository: dict[str, str | None]
    entities: tuple[Entity, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    gaps: tuple[Gap, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    coverage: dict[str, object] = Field(default_factory=dict)
