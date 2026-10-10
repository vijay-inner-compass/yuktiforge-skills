"""Catalog-style documents: API / event / integration catalog, data dictionary, database documentation."""
from __future__ import annotations

import re

from yuktiforge.docint.docgen.helpers import NSV, Q, SB, labels_of
from yuktiforge.docint.docgen.spi import DocumentType, EvidenceRules, GenContext, OutputProfile, SectionSpec

_NOT_NULL = re.compile(r"\bNOT\s+NULL\b", re.I)
_REF = re.compile(r"\bREFERENCES\s+([\w\".]+)", re.I)


class ApiCatalog(DocumentType):
    id, title, version = "api-catalog", "API, Event and Integration Catalog", "1.0"
    template_id = "catalog/api"
    input_dependencies = ("api", "event", "symbol", "component")
    sections = (SectionSpec("inbound", "Inbound APIs"), SectionSpec("spec", "Specification coverage", False), SectionSpec("outbound", "Outbound integrations"), SectionSpec("events", "Events"), SectionSpec("unknowns", "What is not known"))
    output_profile = OutputProfile(file_stem="api-catalog")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "inbound", "Inbound APIs")
        apis = [a for a in q.of("api", external=False) if a.subtype in ("route", "grpc", "graphql")]
        rows = []
        for a in apis:
            hs = q.handlers(a)
            data = sorted({f"{t}:{e.name}" for h in hs for t, es in q.touches(h).items() for e in es if t in ("reads", "writes", "publishes")})
            comp = q.component_of(a.id)
            rows.append(((a.name, a.subtype, a.attrs.get("framework", ""), ", ".join(h.name for h in hs) or "UNKNOWN (no handler found)", comp.name if comp else "", "; ".join(data) or "none seen directly in the handler", ctx.cite(a.evidence_ids)),
                         labels_of(a), a.evidence_ids, (a.id, *[h.id for h in hs])))
        if rows:
            s.table("apis", ("API", "Kind", "Framework", "Handler", "Component", "Data touched directly", "Source"), rows)
        else:
            s.empty("inbound APIs", "no-inbound-apis")
        out.append(s.build())
        spec = [a for a in q.of("api") if a.subtype == "spec"]
        s = SB(ctx, "spec", "Specification coverage", audiences=("architect", "developer", "qa", "ba"))
        if spec:
            traced = {r.source for r in ctx.model.relationships if r.type == "traces-to"}
            s.table("spec", ("Specified route", "Implemented in code?", "Source"), [((a.name, "yes (matched by name)" if a.id in traced else "NOT FOUND in analyzed code"), labels_of(a) if a.id in traced else ("UNKNOWN",), a.evidence_ids, (a.id,)) for a in spec])
            for g in ctx.model.gaps:
                if g.kind == "code-only-route":
                    s.claim(g.detail, ("VERIFIED", "UNKNOWN"), evidence=g.evidence_ids, entities=g.entity_ids)
        else:
            s.claim("No API specification document (OpenAPI) was found, so documented-versus-implemented coverage cannot be stated.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "outbound", "Outbound integrations")
        ext = q.of("api", external=True)
        rows = []
        for a in ext:
            callers = sorted({e.name for t, e in q.inc(a.id, "calls")})
            rows.append(((a.name, ", ".join(callers) or "?", ctx.cite(a.evidence_ids)), labels_of(a), a.evidence_ids, (a.id,)))
        if rows:
            s.table("calls", ("Target", "Called from", "Source"), rows)
        else:
            s.claim("No outbound HTTP calls with literal targets were found.", ("UNKNOWN",))
        for g in ctx.model.gaps:
            if g.kind == "dynamic-name" and "http-client" in g.detail:
                s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        out.append(s.build())
        s = SB(ctx, "events", "Events")
        rows = []
        for ev in q.of("event"):
            pubs = sorted({e.name for _, e in q.inc(ev.id, "publishes")})
            subs = sorted({e.name for _, e in q.inc(ev.id, "subscribes")})
            rows.append(((ev.name, ev.attrs.get("framework", ""), ", ".join(pubs) or "none found", ", ".join(subs) or "none found", ctx.cite(ev.evidence_ids)), labels_of(ev), ev.evidence_ids, (ev.id,)))
        if rows:
            s.table("events", ("Topic / queue", "Framework", "Publishers", "Subscribers", "Source"), rows)
        else:
            s.claim("No messaging topics or queues with literal names were found.", ("UNKNOWN",))
        s.note("A topic with no publisher (or no subscriber) here may be produced or consumed by code outside this repository.")
        out.append(s.build())
        s = SB(ctx, "unknowns", "What is not known", audiences=("architect", "developer", "qa", "support"))
        for g in ctx.model.gaps:
            if g.kind in ("dynamic-name", "unresolved-calls", "no-call-graph", "unsupported-language", "parse-failure"):
                s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        s.claim("Authentication, authorization, rate limits, request and response schemas and error contracts are not extracted by the analyzers; do not infer them from this catalog.", ("UNKNOWN", NSV))
        out.append(s.build())
        return out


class DataDictionary(DocumentType):
    id, title, version = "data-dictionary", "Data Dictionary", "1.0"
    template_id = "catalog/data"
    input_dependencies = ("database_entity", "field", "symbol")
    sections = (SectionSpec("tables", "Tables and columns"), SectionSpec("mappings", "Entity classes mapped to tables", False), SectionSpec("meaning", "Business meaning"))
    output_profile = OutputProfile(file_stem="data-dictionary")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        tables = [t for t in q.of("database_entity") if t.subtype == "table"]
        s = SB(ctx, "tables", "Tables and columns")
        if not tables:
            s.empty("tables", "no-tables")
        for t in tables:
            fields = q.fields_of(t)
            s.claim(f"Table `{t.name}`" + (f", defined in {t.attrs['defined_in']}" if t.attrs.get("defined_in") else ", referenced by code but with no CREATE TABLE found") + ".", labels_of(t), evidence=t.evidence_ids, entities=(t.id,))
            if fields:
                rows = []
                for f in fields:
                    d = str(f.attrs.get("definition", ""))
                    flags = [x for x, ok in (("NOT NULL", bool(_NOT_NULL.search(d))), ("PRIMARY KEY", "PRIMARY KEY" in d.upper()), ("UNIQUE", "UNIQUE" in d.upper())) if ok]
                    ref = _REF.search(d)
                    rows.append(((f.name.split(".", 1)[-1], f.attrs.get("datatype", ""), ", ".join(flags) or "-", ref.group(1) if ref else "-", ctx.cite(f.evidence_ids)), labels_of(f), f.evidence_ids, (f.id,)))
                s.table(f"cols-{t.id.split('-')[-1]}", ("Column", "Type", "Constraints", "References", "Source"), rows, caption=t.name)
            else:
                s.claim(f"Columns of `{t.name}` are UNKNOWN: no schema definition was found for it.", ("UNKNOWN",), entities=(t.id,))
            cons = t.attrs.get("constraints") or []
            if cons:
                s.claim("Table constraints as written: " + "; ".join(f"`{c}`" for c in cons), labels_of(t), evidence=t.evidence_ids, entities=(t.id,))
        out.append(s.build())
        s = SB(ctx, "mappings", "Entity classes mapped to tables", audiences=("developer", "architect"))
        rows = [((c.name, t.name, ctx.cite(c.evidence_ids)), labels_of(c, t), c.evidence_ids, (c.id, t.id)) for t in tables for rel, c in q.inc(t.id, "implements") if c.type in ("symbol", "interface")]
        if rows:
            s.table("maps", ("Class", "Table", "Source"), rows)
        else:
            s.claim("No ORM entity-to-table mappings were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "meaning", "Business meaning")
        users = [e for e in ctx.model.entities if e.type == "document" and e.cls == "user-supplied"]
        for u in users:
            s.about(f"{u.name}: {u.attrs.get('statement', '')}", u)
        s.gap("business-meaning-of-data", "The business meaning of tables and columns (what a status code or amount stands for, who owns the data, retention) is not in the code. It needs a data owner.", "warning")
        out.append(s.build())
        return out


class DatabaseDoc(DocumentType):
    id, title, version = "database-doc", "Database Documentation", "1.0"
    template_id = "catalog/database"
    input_dependencies = ("database_entity", "field", "symbol", "module")
    sections = (SectionSpec("overview", "Overview"), SectionSpec("relationships", "Relationships between tables"), SectionSpec("access", "Who reads and writes what"), SectionSpec("objects", "Indexes and views", False), SectionSpec("unknowns", "What is not known"))
    output_profile = OutputProfile(file_stem="database")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        tables = [t for t in q.of("database_entity") if t.subtype == "table"]
        out = []
        s = SB(ctx, "overview", "Overview")
        defined = [t for t in tables if t.attrs.get("defined_in")]
        s.claim(f"{len(tables)} table(s) are named in the analyzed evidence; {len(defined)} have a schema definition in the repository.", ("VERIFIED",), entities=tuple(t.id for t in tables), evidence=[i for t in tables for i in t.evidence_ids][:20])
        s.claim("Which database product or instance holds these tables is not stated in the source; the diagram stage groups them into one datastore for that reason.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "relationships", "Relationships between tables")
        rows = []
        for t in defined:
            for f in q.fields_of(t):
                m = _REF.search(str(f.attrs.get("definition", "")))
                if m:
                    rows.append(((f"{t.name}.{f.name.split('.', 1)[-1]}", "REFERENCES", m.group(1), ctx.cite(f.evidence_ids)), labels_of(f), f.evidence_ids, (f.id, t.id)))
            for c in t.attrs.get("constraints") or []:
                m = re.search(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+([\w\".]+)", str(c), re.I)
                if m:
                    rows.append(((f"{t.name}({m.group(1)})", "REFERENCES", m.group(2), ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)))
        if rows:
            s.table("fks", ("From", "Relation", "To", "Source"), rows)
        else:
            s.claim("No foreign-key relationships were declared in the analyzed schema files. Relationships enforced only by application code are not visible here.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "access", "Who reads and writes what", audiences=("architect", "developer", "qa", "support"))
        rows = []
        for t in tables:
            rd = sorted({e.name for _, e in q.inc(t.id, "reads")})
            wr = sorted({e.name for _, e in q.inc(t.id, "writes")})
            rows.append(((t.name, ", ".join(rd) or "-", ", ".join(wr) or "-", ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)))
        if rows:
            s.table("access", ("Table", "Read by", "Written by", "Source"), rows)
        else:
            s.empty("table accesses", "no-table-access")
        out.append(s.build())
        s = SB(ctx, "objects", "Indexes and views", audiences=("developer", "architect"), depth="deep")
        rows = [((o.name, o.subtype, o.attrs.get("defined_in", ""), ctx.cite(o.evidence_ids)), labels_of(o), o.evidence_ids, (o.id,)) for o in q.of("database_entity") if o.subtype in ("index", "view", "alter-table")]
        if rows:
            s.table("objs", ("Object", "Kind", "Defined in", "Source"), rows)
        else:
            s.claim("No indexes or views were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "unknowns", "What is not known")
        s.claim("Stored procedures, triggers, migrations history, data volumes, backups and access control are not analyzed.", ("UNKNOWN", NSV))
        for g in ctx.model.gaps:
            if g.kind in ("dynamic-name", "unsupported-language", "parse-failure"):
                s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        out.append(s.build())
        return out
