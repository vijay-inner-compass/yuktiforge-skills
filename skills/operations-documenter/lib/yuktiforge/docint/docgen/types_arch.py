"""Architecture documents: system, solution and technology architecture, HLD, LLD."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from yuktiforge.docint.docgen.helpers import NSV, SECURITY_NOTE, Q, SB, labels_of
from yuktiforge.docint.docgen.spi import DocumentType, GenContext, OutputProfile, SectionSpec

_AUTH = re.compile(r"authoriz|authenticat|secured|preauthorize|rolesallowed|login_required|permission|jwt|oauth", re.I)
_SECRETISH = re.compile(r"secret|token|password|passwd|api[_-]?key|credential", re.I)


def security_observations(ctx: GenContext, s: SB, q: Q) -> None:
    """What static inspection can SEE about security; never an assurance. Every item is INFERRED and needs stakeholder validation."""
    items = 0
    for e in q.of("symbol", "interface"):
        hit = [a for a in e.attrs.get("annotations", []) if _AUTH.search(str(a))]
        if hit:
            s.claim(f"`{e.name}` carries authorization-related annotations ({', '.join(hit)}).", ("INFERRED", NSV), evidence=e.evidence_ids, entities=(e.id,))
            items += 1
    for t in q.of("technology", subtype="config-variable"):
        if _SECRETISH.search(t.name):
            s.claim(f"Configuration variable `{t.name}` looks like a credential and is read from the environment (value not inspected).", ("INFERRED", NSV), evidence=t.evidence_ids, entities=(t.id,))
            items += 1
    for a in q.of("api", external=True):
        if str(a.attrs.get("url", "")).startswith("http://"):
            s.claim(f"`{a.name}` is called over plain HTTP.", ("VERIFIED", NSV), evidence=a.evidence_ids, entities=(a.id,))
            items += 1
    if not items:
        s.claim("No authentication, authorization or credential handling was recognised by the analyzers. This does NOT mean none exists.", ("UNKNOWN", NSV))
    s.claim(f"Note: {SECURITY_NOTE}. Security design, threat model, encryption, secrets management and compliance posture need review by the people who own them.", ("UNKNOWN", NSV))


def _components(ctx: GenContext, s: SB, q: Q, deep: bool = False) -> None:
    comps = q.comps()
    rows = []
    for c in comps:
        mods = q.modules_of(c)
        langs = ", ".join(str(x) for x in c.attrs.get("languages", []) or [])
        apis = [a for a in q.of("api", external=False) if (q.component_of(a.id) or c).id == c.id and q.component_of(a.id)]
        rows.append(((c.name, langs or "?", len(mods), len(apis), ", ".join(str(x) for x in c.attrs.get("frameworks", []) or []) or "-", ctx.cite(c.evidence_ids)), labels_of(c), c.evidence_ids, (c.id,)))
    if rows:
        s.table("components", ("Component", "Languages", "Source modules", "Inbound APIs", "Frameworks", "Source"), rows)
    else:
        s.empty("components", "no-components")


def _relations(ctx: GenContext, s: SB, q: Q) -> None:
    pair: dict[tuple[str, str, str], list] = defaultdict(list)
    for r in ctx.model.relationships:
        if r.type not in ("imports", "calls", "reads", "writes", "publishes", "subscribes"):
            continue
        a, b = ctx.graph.ent.get(r.source), ctx.graph.ent.get(r.target)
        if not a or not b:
            continue
        ca = q.component_of(a.id)
        cb = q.component_of(b.id) if not b.external and b.type in ("module", "symbol", "interface") else None
        if not ca:
            continue
        if cb and cb.id != ca.id and r.type in ("imports", "calls"):
            pair[(ca.name, cb.name, r.type)].append(r)
        elif b.type in ("database_entity", "event") or b.external:
            pair[(ca.name, b.name, r.type)].append(r)
    rows = []
    for (a, b, t), rs in sorted(pair.items()):
        ev = tuple(dict.fromkeys(i for r in rs for i in r.evidence_ids))[:6]
        rows.append(((a, t, b, len(rs), ", ".join(ctx.graph.cite(ev)[:2])), ("VERIFIED",) if all(r.cls == "verified" for r in rs) else ("INFERRED",), ev, ()))
    if rows:
        s.table("relations", ("From", "Relation", "To", "Count", "Source"), rows[:200])
    else:
        s.claim("No relationships between components, data stores or external systems were found.", ("UNKNOWN",))


class SystemArchitecture(DocumentType):
    id, title, version = "system-architecture", "System Architecture", "1.0"
    template_id = "architecture/system"
    input_dependencies = ("component", "module", "api", "database_entity", "event", "deployment_boundary")
    sections = (SectionSpec("context", "System context"), SectionSpec("components", "Components"), SectionSpec("relations", "How the parts connect"), SectionSpec("data", "Data stores and messaging"), SectionSpec("deploy", "Deployment"), SectionSpec("unknowns", "What is not known"))
    output_profile = OutputProfile(file_stem="system-architecture")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "context", "System context")
        mods = q.of("module")
        syms = q.of("symbol", "interface")
        s.claim(f"The repository contains {len(q.comps())} component(s), {len(mods)} analyzed source module(s) and {len(syms)} declared symbol(s).", ("VERIFIED",), entities=q.repo_ids, evidence=q.repo_ev)
        ext = q.of("api", external=True)
        s.claim(f"It calls {len(ext)} external HTTP endpoint(s) with literal addresses, uses {len(q.of('event'))} messaging topic(s) and names {len([t for t in q.of('database_entity') if t.subtype == 'table'])} database table(s).", ("VERIFIED",), entities=q.repo_ids, evidence=q.repo_ev)
        s.claim("The purpose of the system and the identity of its users and neighbouring systems are not in the code.", ("UNKNOWN", NSV))
        out.append(s.build())
        s = SB(ctx, "components", "Components")
        _components(ctx, s, q)
        out.append(s.build())
        s = SB(ctx, "relations", "How the parts connect")
        _relations(ctx, s, q)
        out.append(s.build())
        s = SB(ctx, "data", "Data stores and messaging", audiences=("architect", "developer", "support", "qa"))
        rows = [((e.name, e.subtype, ctx.cite(e.evidence_ids)), labels_of(e), e.evidence_ids, (e.id,)) for e in q.of("database_entity", "event") if e.subtype in ("table", "topic-or-queue")]
        if rows:
            s.table("stores", ("Name", "Kind", "Source"), rows)
        else:
            s.claim("No data stores or topics with literal names were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "deploy", "Deployment")
        rows = [((d.name, d.subtype, d.attrs.get("defined_in", ""), ctx.cite(d.evidence_ids)), labels_of(d), d.evidence_ids, (d.id,)) for d in q.of("deployment_boundary")]
        if rows:
            s.table("deploy", ("Name", "Kind", "Defined in", "Source"), rows)
        else:
            s.claim("No container, CI or infrastructure definitions were found.", ("UNKNOWN",))
        for r in ctx.model.relationships:
            if r.type == "deploys-to":
                a, b = ctx.graph.ent[r.source], ctx.graph.ent[r.target]
                s.claim(f"Component `{a.name}` is deployed as `{b.name}` (based on file proximity or matching names, not proven).", ("INFERRED",), evidence=r.evidence_ids, entities=(a.id, b.id))
        out.append(s.build())
        s = SB(ctx, "unknowns", "What is not known")
        for g in ctx.model.gaps:
            s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        out.append(s.build())
        return out


class SolutionArchitecture(DocumentType):
    id, title, version = "solution-architecture", "Solution Architecture", "1.0"
    template_id = "architecture/solution"
    input_dependencies = ("api", "component", "database_entity", "event", "requirement_candidate")
    sections = (SectionSpec("capabilities", "Capabilities and where they live"), SectionSpec("integration", "Integration view"), SectionSpec("quality", "Quality attributes (observations)"), SectionSpec("decisions", "Architecture decisions"), SectionSpec("unknowns", "What is not known"))
    output_profile = OutputProfile(file_stem="solution-architecture")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "capabilities", "Capabilities and where they live")
        rows = []
        for a in q.of("api", external=False):
            if a.subtype not in ("route", "grpc", "graphql"):
                continue
            hs = q.handlers(a)
            data = sorted({e.name for h in hs for t, es in q.touches(h).items() for e in es if t in ("reads", "writes")})
            comp = q.component_of(a.id)
            rows.append(((a.name, comp.name if comp else "?", ", ".join(h.name for h in hs) or "?", ", ".join(data) or "-", "UNKNOWN (business capability not stated in code)"), labels_of(a), a.evidence_ids, (a.id,)))
        if rows:
            s.table("cap", ("Entry point", "Component", "Handler", "Data", "Business capability"), rows)
        else:
            s.empty("entry points", "no-entry-points")
        out.append(s.build())
        s = SB(ctx, "integration", "Integration view")
        _relations(ctx, s, q)
        out.append(s.build())
        s = SB(ctx, "quality", "Quality attributes (observations)", audiences=("architect", "executive", "developer"))
        security_observations(ctx, s, q)
        s.claim("Performance, scalability, availability and resilience characteristics cannot be established from static source.", ("UNKNOWN", NSV))
        out.append(s.build())
        s = SB(ctx, "decisions", "Architecture decisions")
        ds = q.of("decision")
        if ds:
            for d in ds:
                s.about(f"{d.name}: {d.attrs.get('statement', '')} (approval: {d.approval})", d)
        else:
            s.claim("No architecture decision records were supplied. Decisions cannot be reconstructed from code; the reasons behind the structure are UNKNOWN.", ("UNKNOWN", NSV))
        out.append(s.build())
        s = SB(ctx, "unknowns", "What is not known")
        for g in ctx.model.gaps:
            s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        out.append(s.build())
        return out


class TechnologyArchitecture(DocumentType):
    id, title, version = "technology-architecture", "Technology Architecture", "1.0"
    template_id = "architecture/technology"
    input_dependencies = ("technology", "component", "deployment_boundary", "module")
    sections = (SectionSpec("stack", "Languages and frameworks"), SectionSpec("deps", "Declared dependencies"), SectionSpec("config", "Configuration read from the environment"), SectionSpec("build", "Build and delivery"))
    output_profile = OutputProfile(file_stem="technology-architecture")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "stack", "Languages and frameworks")
        langs = Counter(str(m.attrs.get("language", "")) for m in q.of("module"))
        for lang, n in sorted(langs.items()):
            s.claim(f"{n} analyzed module(s) written in {lang}.", ("VERIFIED",), evidence=[i for m in q.of('module') if m.attrs.get('language') == lang for i in m.evidence_ids][:3], key=f"lang|{lang}", fact=str(n))
        for fw in q.of("technology", subtype="framework"):
            s.about(f"Framework in use: {fw.name} (inferred from declared dependencies).", fw)
        if not langs:
            s.empty("analyzed source modules", "no-modules")
        out.append(s.build())
        s = SB(ctx, "deps", "Declared dependencies", audiences=("architect", "developer", "support", "qa", "onboarding"))
        deps = q.of("technology", subtype="dependency")
        by_eco: dict[str, list] = defaultdict(list)
        for d in deps:
            by_eco[str(d.attrs.get("ecosystem", ""))].append(d)
        for eco, ds in sorted(by_eco.items()):
            s.table(f"deps-{eco}", ("Package", "Declared version", "Scope", "Source"), [((d.name, d.attrs.get("declared_version", "") or "(unspecified)", d.attrs.get("scope", ""), ctx.cite(d.evidence_ids)), labels_of(d), d.evidence_ids, (d.id,)) for d in ds], caption=eco)
        if not deps:
            s.claim("No dependency manifests were recognised.", ("UNKNOWN",))
        s.note("Versions are the ranges as declared; the versions actually resolved at build time are not known without a lockfile and a build.")
        out.append(s.build())
        s = SB(ctx, "config", "Configuration read from the environment", audiences=("developer", "support", "architect", "onboarding"))
        rows = [((t.name, ", ".join(sorted(e.name for _, e in q.inc(t.id, "reads"))) or "?", ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)) for t in q.of("technology", subtype="config-variable")]
        if rows:
            s.table("env", ("Variable", "Read by", "Source"), rows)
            s.note("Only names are recorded; values, defaults and which are required are not analyzed.")
        else:
            s.claim("No environment variable reads with literal names were found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "build", "Build and delivery")
        rows = [((d.name, d.subtype, d.attrs.get("defined_in", ""), ctx.cite(d.evidence_ids)), labels_of(d), d.evidence_ids, (d.id,)) for d in q.of("deployment_boundary")]
        if rows:
            s.table("bd", ("Name", "Kind", "Defined in", "Source"), rows)
        else:
            s.claim("No CI, container or infrastructure definitions were found.", ("UNKNOWN",))
        out.append(s.build())
        return out


class HLD(DocumentType):
    id, title, version = "hld", "High-Level Design", "1.0"
    template_id = "design/hld"
    input_dependencies = ("component", "api", "database_entity", "event", "deployment_boundary", "technology")
    sections = (SectionSpec("overview", "Overview"), SectionSpec("components", "Component design"), SectionSpec("flows", "Key flows"), SectionSpec("data", "Data design"), SectionSpec("integration", "Integration"), SectionSpec("security", "Security observations"), SectionSpec("risks", "Gaps and risks"))
    output_profile = OutputProfile(file_stem="hld")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "overview", "Overview")
        s.claim(f"{len(q.comps())} component(s); {len(q.of('api', external=False))} inbound API entry point(s); {len([t for t in q.of('database_entity') if t.subtype == 'table'])} table(s); {len(q.of('event'))} topic(s).", ("VERIFIED",), entities=q.repo_ids, evidence=q.repo_ev)
        s.claim("Design intent (why the system is structured this way) is not recoverable from code and is marked UNKNOWN throughout.", ("UNKNOWN", NSV))
        out.append(s.build())
        s = SB(ctx, "components", "Component design")
        _components(ctx, s, q)
        out.append(s.build())
        s = SB(ctx, "flows", "Key flows")
        any_flow = False
        for a in [a for a in q.of("api", external=False) if a.subtype in ("route", "grpc", "graphql")][:12]:
            t = ctx.graph.trace_request(a.id, 6)
            if not t["steps"]:
                continue
            any_flow = True
            chain = " -> ".join(x["symbol"] for x in t["steps"][:6])
            s.claim(f"`{a.name}`: {chain}" + (" (the path may continue: some calls could not be resolved)" if t["uncertain_hops"] else ""), ("VERIFIED",) if not t["uncertain_hops"] else ("VERIFIED", "UNKNOWN"),
                    evidence=[i for st in t["steps"] for i in ctx.graph.ent[st["id"]].evidence_ids][:6], entities=(a.id,))
        if not any_flow:
            s.claim("No request path could be reconstructed: no handler was linked to an entry point.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "data", "Data design")
        rows = [((t.name, len(q.fields_of(t)) or "?", ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)) for t in q.of("database_entity") if t.subtype == "table"]
        if rows:
            s.table("tbl", ("Table", "Columns known", "Source"), rows)
        else:
            s.claim("No tables found.", ("UNKNOWN",))
        out.append(s.build())
        s = SB(ctx, "integration", "Integration")
        _relations(ctx, s, q)
        out.append(s.build())
        s = SB(ctx, "security", "Security observations")
        security_observations(ctx, s, q)
        out.append(s.build())
        s = SB(ctx, "risks", "Gaps and risks")
        for g in ctx.model.gaps:
            s.claim(g.detail, ("UNKNOWN",), evidence=g.evidence_ids, entities=g.entity_ids)
        for c in ctx.model.conflicts:
            s.claim(f"Conflict: {c.detail}", ("VERIFIED", NSV), evidence=c.evidence_ids, entities=c.entity_ids)
        out.append(s.build())
        return out


class LLD(DocumentType):
    id, title, version = "lld", "Low-Level Design", "1.0"
    template_id = "design/lld"
    input_dependencies = ("module", "symbol", "interface", "field", "api", "database_entity")
    sections = (SectionSpec("modules", "Modules and their contents"), SectionSpec("types", "Types and inheritance"), SectionSpec("handlers", "Handlers in detail"), SectionSpec("data", "Data access in detail"))
    output_profile = OutputProfile(file_stem="lld")
    audiences = ("developer", "architect", "qa", "onboarding")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        out = []
        s = SB(ctx, "modules", "Modules and their contents", depth="summary")
        for m in q.of("module", subtype="source"):
            kids = q.children(m.id)
            s.claim(f"`{m.name}` ({m.attrs.get('language', '')}): " + (", ".join(f"{k.subtype} `{k.name.rsplit('.', 1)[-1]}`" for k in kids[:12]) + (" ..." if len(kids) > 12 else "") if kids else "no declarations found"),
                    ("VERIFIED",), evidence=m.evidence_ids, entities=(m.id,))
        out.append(s.build())
        s = SB(ctx, "types", "Types and inheritance", depth="deep")
        rows = []
        for e in q.of("symbol", "interface"):
            if e.subtype not in ("class", "interface", "struct", "record", "enum"):
                continue
            members = [k for k in q.children(e.id)]
            bases = ", ".join(str(b) for b in e.attrs.get("bases", []) or []) or "-"
            rows.append(((e.name, e.subtype, bases, ", ".join(k.name.rsplit(".", 1)[-1] for k in members[:10]) + (" ..." if len(members) > 10 else ""), ctx.cite(e.evidence_ids)), labels_of(e), e.evidence_ids, (e.id,)))
        if rows:
            s.table("types", ("Type", "Kind", "Bases (as written)", "Members", "Source"), rows[:400])
        else:
            s.empty("types", "no-types")
        out.append(s.build())
        s = SB(ctx, "handlers", "Handlers in detail", depth="deep")
        for a in [a for a in q.of("api", external=False) if a.subtype in ("route", "grpc", "graphql")]:
            for h in q.handlers(a):
                touch = q.touches(h)
                parts = [f"{t} {', '.join(sorted({e.name for e in es}))}" for t, es in sorted(touch.items())]
                s.claim(f"`{a.name}` is handled by `{h.name}` ({h.attrs.get('path', '')}:{h.attrs.get('start_line', '')}-{h.attrs.get('end_line', '')})" + ("; touches: " + "; ".join(parts) if parts else "; no data or messaging access seen directly in the handler"),
                        labels_of(a, h), evidence=(*a.evidence_ids, *h.evidence_ids), entities=(a.id, h.id))
        out.append(s.build())
        s = SB(ctx, "data", "Data access in detail", depth="deep")
        rows = []
        for t in q.of("database_entity"):
            for rel, who in q.inc(t.id, "reads", "writes"):
                rows.append(((who.name, rel, t.name, ctx.cite(who.evidence_ids)), labels_of(who, t), who.evidence_ids, (who.id, t.id)))
        if rows:
            s.table("acc", ("Code", "Access", "Table", "Source"), rows[:400])
        else:
            s.claim("No direct table access was recognised in code.", ("UNKNOWN",))
        out.append(s.build())
        return out
