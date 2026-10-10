"""Canonical architecture model.

Structure is parsed leniently (ids default to "") so `validate_model` can *report* missing
ids, dangling edges and duplicates instead of the loader raising on the first one.
Rendering consumes only this model; the source language never reaches the renderer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_serializer

from yuktiforge.errors import SchemaError

MODEL_VERSION = "1.0"
ID_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,63}$"

EvidenceStatus = Literal["verified", "user-supplied", "inferred"]
STATUS_RANK: dict[str, int] = {"verified": 2, "user-supplied": 1, "inferred": 0}

ComponentKind = Literal["person", "system", "external-system", "container", "service", "component",
                        "datastore", "queue", "infrastructure", "module", "package", "library", "entity"]
RelationKind = Literal["uses", "calls", "reads-writes", "publishes", "subscribes", "depends-on",
                       "data-flow", "deploys-to", "other"]
BoundaryKind = Literal["system", "trust", "deployment", "team", "other"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(_M):
    kind: Literal["file", "analyzer", "user", "document"]
    ref: str = Field(min_length=1)  # path[:line], analyzer id, "user", or document name
    detail: str = ""


class Evidence(_M):
    status: EvidenceStatus = "user-supplied"
    sources: tuple[Provenance, ...] = ()
    rationale: str = ""            # mandatory for inferred
    confidence: float | None = Field(default=None, ge=0, le=1)


class Layer(_M):
    id: str = ""
    name: str = ""
    order: int = 0


class Boundary(_M):
    id: str = ""
    name: str = ""
    kind: BoundaryKind = "other"
    parent: str | None = None


class Component(_M):
    id: str = ""
    name: str = ""
    kind: ComponentKind = "component"
    layer: str | None = None
    boundary: str | None = None
    technology: str = ""
    description: str = ""
    attributes: tuple[str, ...] = ()   # one line each (e.g. a column and its type) for kinds that show members, such as `entity` in the ERD view
    evidence: Evidence = Evidence()

    @model_serializer(mode="wrap")
    def _omit_empty_attributes(self, handler):
        """Models without members serialize exactly as they did before `attributes` existed, so existing bundles still rebuild byte-for-byte."""
        data = handler(self)
        if not data.get("attributes"):
            data.pop("attributes", None)
        return data


class Relation(_M):
    id: str = ""
    source: str = ""
    target: str = ""
    label: str = ""
    kind: RelationKind = "uses"
    technology: str = ""
    evidence: Evidence = Evidence()


class LanguageCoverage(_M):
    language: str
    files: int = Field(ge=0)
    analyzers: tuple[str, ...] = ()
    depth: Literal["none", "manifest", "imports"] = "none"


class AnalyzerCoverage(_M):
    analyzer_id: str
    status: Literal["ran", "not-applicable"]
    languages: tuple[str, ...]
    files_examined: int = 0
    limitations: tuple[str, ...] = ()


class Coverage(_M):
    languages: tuple[LanguageCoverage, ...] = ()
    analyzers: tuple[AnalyzerCoverage, ...] = ()
    notes: tuple[str, ...] = ()
    unparsed_files: tuple[str, ...] = ()    # files an analyzer could not read: their facts are UNKNOWN, not absent


class ArchitectureModel(_M):
    model_version: str = MODEL_VERSION
    name: str = ""
    description: str = ""
    layers: tuple[Layer, ...] = ()
    boundaries: tuple[Boundary, ...] = ()
    components: tuple[Component, ...] = ()
    relations: tuple[Relation, ...] = ()
    coverage: Coverage = Coverage()


def parse_model(data: Any) -> ArchitectureModel:
    if not isinstance(data, dict):
        raise SchemaError("architecture model must be a mapping at top level")
    try:
        return ArchitectureModel.model_validate(data)
    except ValidationError as e:
        raise SchemaError("; ".join(f"{'.'.join(map(str, x['loc'])) or '<root>'}: {x['msg']}"
                                    for x in e.errors())) from e


def load_model(path: str | Path) -> ArchitectureModel:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise SchemaError(f"cannot read {p}: {e}") from e
    return parse_model(data)


def canonical_json(model: ArchitectureModel) -> str:
    """Stable serialisation: sorted by id so the same architecture always yields the same bytes."""
    d = model.model_dump(mode="json")
    for key in ("layers", "boundaries", "components", "relations"):
        d[key] = sorted(d[key], key=lambda x: (x.get("order", 0), x["id"]) if key == "layers" else x["id"])
    return json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --- merging -------------------------------------------------------------------------------

def _merge_evidence(a: Evidence, b: Evidence) -> Evidence:
    best = a if STATUS_RANK[a.status] >= STATUS_RANK[b.status] else b
    seen: dict[tuple[str, str], Provenance] = {}
    for s in (*a.sources, *b.sources):
        seen.setdefault((s.kind, s.ref), s)
    return Evidence(status=best.status, sources=tuple(seen.values()),
                    rationale=best.rationale or a.rationale or b.rationale,
                    confidence=best.confidence if best.confidence is not None else None)


def _enrich(base: Component, over: Component) -> Component:
    """Overlay wins for descriptive fields it sets; evidence is merged, never downgraded."""
    upd: dict[str, Any] = {"evidence": _merge_evidence(base.evidence, over.evidence)}
    for f in ("name", "kind", "layer", "boundary", "technology", "description"):
        v = getattr(over, f)
        # model_fields_set: a default value (e.g. kind="component") must not overwrite an analyzer's finding
        if f in over.model_fields_set and v not in ("", None):
            upd[f] = v
    return base.model_copy(update=upd)


def merge_models(base: ArchitectureModel, overlay: ArchitectureModel) -> ArchitectureModel:
    """Merge `overlay` (typically user-supplied facts) into `base` (typically analyzer output).

    Same component id -> enrich. Relation with same (source,target,kind) -> single relation with
    merged evidence. Everything else is unioned. Duplicate ids *within* one side are preserved so
    validation can report them rather than the merge hiding them.
    """
    comps = {c.id: c for c in base.components}
    extra_comps: list[Component] = []
    for oc in overlay.components:
        if oc.id in comps and oc.id:
            comps[oc.id] = _enrich(comps[oc.id], oc)
        else:
            extra_comps.append(oc)
    merged_comps = tuple(comps[c.id] if c.id in comps and c.id else c for c in base.components) + tuple(extra_comps)
    by_key: dict[tuple[str, str, str], int] = {}
    rels: list[Relation] = list(base.relations)
    for i, r in enumerate(rels):
        by_key.setdefault((r.source, r.target, r.kind), i)
    for orl in overlay.relations:
        key = (orl.source, orl.target, orl.kind)
        if key in by_key:
            cur = rels[by_key[key]]
            rels[by_key[key]] = cur.model_copy(update={
                "label": orl.label or cur.label, "technology": orl.technology or cur.technology,
                "evidence": _merge_evidence(cur.evidence, orl.evidence)})
        else:
            rels.append(orl)
    def union(a, b):
        seen, out = set(), []
        for x in (*a, *b):
            if x.id in seen and x.id:
                continue
            seen.add(x.id)
            out.append(x)
        return tuple(out)
    return ArchitectureModel(
        name=overlay.name or base.name, description=overlay.description or base.description,
        layers=union(base.layers, overlay.layers), boundaries=union(base.boundaries, overlay.boundaries),
        components=merged_comps, relations=tuple(rels),
        coverage=Coverage(languages=base.coverage.languages or overlay.coverage.languages,
                          analyzers=base.coverage.analyzers or overlay.coverage.analyzers,
                          notes=(*base.coverage.notes, *overlay.coverage.notes),
                          unparsed_files=tuple(sorted({*base.coverage.unparsed_files, *overlay.coverage.unparsed_files}))))
