"""Diagram checks beyond the Architecture Visualizer's own (which inspect the rendered SVG): source-to-diagram consistency against the knowledge model,
semantic rules per view, DFD structure and balance between levels."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from yuktiforge.docint.knowledge.schema import KnowledgeModel
from yuktiforge.docint.publish.diagrams import DiagramSpec, check_dfd_balance, validate_dfd


def consistency(spec: DiagramSpec, model: KnowledgeModel) -> dict[str, Any]:
    """Every drawn element must come from the model; no relation may connect things the model does not connect; omissions are listed, not hidden."""
    ents = {e.id: e for e in model.entities}
    rels = {r.id: r for r in model.relationships}
    errors: list[str] = []
    parents: dict[str, set[str]] = defaultdict(set)
    for r in model.relationships:
        if r.type == "owns":
            parents[r.target].add(r.source)
    comp_map, rel_map = spec.mapping["components"], spec.mapping["relations"]
    for c in spec.model.components:
        srcs = comp_map.get(c.id)
        if not srcs:
            errors.append(f"element '{c.name}' ({c.id}) has no source entity in the knowledge model")
            continue
        for e in srcs:
            if e not in ents:
                errors.append(f"element '{c.name}' cites entity {e} which does not exist")
    for r in spec.model.relations:
        rids = rel_map.get(r.id)
        evidence_free = r.label in ("requests", "responses", "request", "uses") and not rids
        if not rids and not evidence_free:
            errors.append(f"relation '{r.label}' ({r.source} -> {r.target}) has no source relationship in the knowledge model")
            continue
        for rid in rids or []:
            if rid not in rels:
                errors.append(f"relation '{r.label}' cites relationship {rid} which does not exist")
                continue
            kr = rels[rid]
            ends = set(comp_map.get(r.source, [])) | set(comp_map.get(r.target, []))
            # at least one end of the model relationship must lie inside the entities drawn at the two ends, or be owned by them (modules/symbols inside a component)
            if not ({kr.source, kr.target} & ends) and not _owned(kr, ends, parents):
                errors.append(f"relation '{r.label}' ({r.source} -> {r.target}) is not supported by relationship {rid}")
    drawn_entities = {e for srcs in comp_map.values() for e in srcs}
    omitted = sorted({rid for rid, kr in rels.items() if kr.type in ("reads", "writes", "calls", "publishes", "subscribes", "imports") and kr.source in drawn_entities and kr.target in drawn_entities
                      and rid not in {x for v in rel_map.values() for x in v}})
    return {"errors": errors, "elements": len(spec.model.components), "relations": len(spec.model.relations), "relationships_in_scope_not_drawn": len(omitted), "omitted_sample": omitted[:10]}


def _owned(kr, ends: set[str], parents: dict[str, set[str]]) -> bool:
    """A symbol-level relationship supports a module- or component-level arrow when its endpoints sit inside the drawn entities (ownership is transitive)."""
    def up(x: str) -> set[str]:
        seen, stack = set(), [x]
        while stack:
            n = stack.pop()
            for p in parents.get(n, ()):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen
    return bool((up(kr.source) | up(kr.target)) & ends)


def semantic(spec: DiagramSpec) -> list[str]:
    errs: list[str] = []
    am = spec.model
    ids = {c.id for c in am.components}
    for r in am.relations:
        if r.source not in ids or r.target not in ids:
            errs.append(f"relation {r.id} has a dangling endpoint")
    for c in am.components:
        if c.evidence.status == "inferred" and not c.evidence.rationale.strip():
            errs.append(f"inferred element '{c.name}' states no rationale")
    for r in am.relations:
        if r.evidence.status == "inferred" and not r.evidence.rationale.strip():
            errs.append(f"inferred relation '{r.label}' states no rationale")
    kinds = defaultdict(int)
    for c in am.components:
        kinds[c.kind] += 1
    if spec.view == "c4-context":
        bad = [c.name for c in am.components if c.kind not in ("system", "person", "external-system")]
        errs += [f"context diagram contains non-context element '{n}'" for n in bad]
        if kinds["system"] != 1:
            errs.append("a context diagram has exactly one system")
    if spec.view == "erd":
        errs += [f"entity '{c.name}' has no attributes" for c in am.components if c.kind == "entity" and not c.attributes]
        errs += [f"ERD element '{c.name}' is not an entity" for c in am.components if c.kind != "entity"]
    if spec.view == "deployment":
        errs += ["deployment diagram has no container or infrastructure element"] if not (kinds["container"] or kinds["infrastructure"]) else []
    if spec.view == "data-flow":
        e, w = validate_dfd(am)
        errs += e
        for x in w:
            if x not in spec.notes:
                spec.notes.append("DFD: " + x)
    if spec.view == "c4-component":
        errs += ["component diagram has fewer than two modules"] if kinds["module"] < 2 else []
    return errs


def balance(specs: list[DiagramSpec]) -> list[str]:
    errs: list[str] = []
    by_id = {s.id: s for s in specs}
    l0 = by_id.get("dfd-0")
    l1 = by_id.get("dfd-1")
    if l0 and l1:
        errs += check_dfd_balance(l0, l1)
    elif l1 and not l0:
        errs.append("level 1 exists without a level 0")
    for s in specs:
        if s.level == "2":
            if l1 is None:
                errs.append(f"{s.id}: level 2 exists without level 1")
            else:
                errs += [f"{s.id}: {e}" for e in check_dfd_balance(l1, s)]
    return errs
