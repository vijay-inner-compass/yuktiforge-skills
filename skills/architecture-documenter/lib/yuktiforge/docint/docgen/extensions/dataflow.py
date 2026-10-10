"""EXTENSION (registered through the public registry, no engine change): Data Flow summary — processes, data stores, external entities and the flows between them."""
from __future__ import annotations

from yuktiforge.docint.docgen.helpers import NSV, Q, SB, labels_of
from yuktiforge.docint.docgen.registry import register
from yuktiforge.docint.docgen.spi import DocumentType, GenContext, OutputProfile, SectionSpec


class DataFlow(DocumentType):
    id, title, version = "dataflow", "Data Flow Summary (extension)", "1.0"
    template_id = "extension/dataflow"
    input_dependencies = ("component", "database_entity", "event", "api", "symbol")
    sections = (SectionSpec("elements", "Processes, stores and external parties"), SectionSpec("flows", "Flows"), SectionSpec("unknowns", "What is not known"))
    output_profile = OutputProfile(file_stem="dataflow")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        s = SB(ctx, "elements", "Processes, stores and external parties")
        rows = [((c.name, "process", ctx.cite(c.evidence_ids)), labels_of(c), c.evidence_ids, (c.id,)) for c in q.comps()]
        rows += [((t.name, "data store (table)", ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)) for t in q.of("database_entity") if t.subtype == "table"]
        rows += [((e.name, "message channel", ctx.cite(e.evidence_ids)), labels_of(e), e.evidence_ids, (e.id,)) for e in q.of("event")]
        rows += [((a.name, "external party", ctx.cite(a.evidence_ids)), labels_of(a), a.evidence_ids, (a.id,)) for a in q.of("api", external=True)]
        if rows:
            s.table("els", ("Element", "Role", "Source"), rows)
        else:
            s.empty("data-flow elements", "no-elements")
        a_sec = s.build()
        s = SB(ctx, "flows", "Flows")
        flows: dict[tuple, tuple[list, set]] = {}
        for r in ctx.model.relationships:
            if r.type not in ("reads", "writes", "publishes", "subscribes", "calls"):
                continue
            src, dst = ctx.graph.ent.get(r.source), ctx.graph.ent.get(r.target)
            if not src or not dst or (r.type == "calls" and not dst.external):
                continue
            comp = q.component_of(src.id)
            who = comp.name if comp else src.name
            direction = {"reads": f"{dst.name} -> {who}", "writes": f"{who} -> {dst.name}", "publishes": f"{who} -> {dst.name}", "subscribes": f"{dst.name} -> {who}", "calls": f"{who} -> {dst.name}"}[r.type]
            key = (direction, r.type, src.name, ", ".join(ctx.graph.cite(r.evidence_ids)[:1]))
            evs, ents = flows.setdefault(key, ([], set()))
            evs.extend(i for i in r.evidence_ids if i not in evs)
            ents.update((src.id, dst.id))
        if flows:
            s.table("fl", ("Flow", "Kind", "Initiated by", "Source"), [(k, ("VERIFIED",) if all(ctx.graph.ev[i].cls == "verified" for i in v[0]) else ("INFERRED",), v[0], tuple(sorted(v[1]))) for k, v in sorted(flows.items())[:300]])
        else:
            s.claim("No data flows were found.", ("UNKNOWN",))
        b_sec = s.build()
        s = SB(ctx, "unknowns", "What is not known")
        s.claim("What data items travel along each flow (field-level lineage), and their sensitivity, are not analyzed.", ("UNKNOWN", NSV))
        return [a_sec, b_sec, s.build()]


register(DataFlow(), "extension:dataflow")
