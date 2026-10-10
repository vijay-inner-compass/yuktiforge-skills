"""Plugin interface for document types. A new document type is one class registered with `registry.register`; the engine, renderer, validator, glossary,
review workflow and regeneration know nothing about individual types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from yuktiforge.docint.docgen.doc import AUDIENCES, Audience, Depth, Section
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import KnowledgeModel


@dataclass(frozen=True)
class SectionSpec:
    id: str
    title: str
    required: bool = True


@dataclass(frozen=True)
class EvidenceRules:
    """What a document of this type must show for its claims."""
    every_claim_labelled: bool = True
    verified_needs_evidence: bool = True
    reconstructed: bool = False            # a reconstruction (BRS/SRS): never presented as an approved requirement; banner is mandatory
    no_security_verification: bool = True  # security / compliance statements may never be VERIFIED from source inspection alone


@dataclass(frozen=True)
class OutputProfile:
    formats: tuple[str, ...] = ("markdown",)
    file_stem: str = ""


@dataclass
class GenContext:
    model: KnowledgeModel
    graph: Graph
    audience: Audience = "developer"
    depth: Depth = "summary"
    scope: str | None = None               # e.g. "module:src/app.py" for the code explanation
    template: str = ""                     # "<document type id>@<version>": part of every section's input hash, so changing a template regenerates its sections

    def cite(self, ev_ids) -> str:
        return ", ".join(self.graph.cite(ev_ids)[:2])


class DocumentType(ABC):
    id: str
    title: str
    version: str = "1.0"
    template_id: str = ""
    input_dependencies: tuple[str, ...] = ()           # entity types the document reads (shown by `docs types`; a missing input becomes a validation gap)
    sections: tuple[SectionSpec, ...] = ()
    evidence_rules: EvidenceRules = EvidenceRules()
    validation_profile: str = "standard"
    output_profile: OutputProfile = OutputProfile()
    audiences: tuple[str, ...] = AUDIENCES
    banner: tuple[str, ...] = ()

    @abstractmethod
    def build(self, ctx: GenContext) -> list[Section]: ...

    def status(self, ctx: GenContext) -> str:
        return "DRAFT"


@dataclass
class Registry:
    types: dict[str, DocumentType] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)       # id -> "builtin" | plug-in module name
