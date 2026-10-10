"""EXTENSION: Operations runbook draft — configuration, deployment boundaries, runtime dependencies and health endpoints found in the repository, and what only operators can supply."""
from __future__ import annotations

from yuktiforge.docint.docgen.helpers import NSV, Q, SB, labels_of
from yuktiforge.docint.docgen.registry import register
from yuktiforge.docint.docgen.spi import DocumentType, GenContext, OutputProfile, SectionSpec


class OperationsRunbook(DocumentType):
    id, title, version = "operations-runbook", "Operations Runbook (draft)", "1.0"
    template_id = "extension/operations-runbook"
    input_dependencies = ("technology", "deployment_boundary", "database_entity", "event", "api", "component")
    sections = (SectionSpec("config", "Configuration the code reads"), SectionSpec("deploy", "Deployment boundaries"), SectionSpec("deps", "Runtime dependencies"),
                SectionSpec("health", "Health and probe endpoints"), SectionSpec("unknowns", "What operators must supply"))
    output_profile = OutputProfile(file_stem="operations-runbook")

    def build(self, ctx: GenContext):
        q = Q(ctx)
        s = SB(ctx, "config", "Configuration the code reads")
        env = [t for t in q.of("technology") if t.subtype == "config-variable"]
        if env:
            s.table("env", ("Variable", "Source"), [((t.name, ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)) for t in env])
        else:
            s.empty("environment variables", "no-config")
        sec_config = s.build()
        s = SB(ctx, "deploy", "Deployment boundaries")
        dep = q.of("deployment_boundary")
        if dep:
            s.table("dep", ("Boundary", "Kind", "Source"), [((d.name, d.subtype or "-", ctx.cite(d.evidence_ids)), labels_of(d), d.evidence_ids, (d.id,)) for d in dep])
        else:
            s.empty("deployment boundaries (Dockerfiles, compose files, Terraform, pipelines)", "no-deployment")
        sec_deploy = s.build()
        s = SB(ctx, "deps", "Runtime dependencies")
        rows = [((t.name, "database table", ctx.cite(t.evidence_ids)), labels_of(t), t.evidence_ids, (t.id,)) for t in q.of("database_entity") if t.subtype == "table"]
        rows += [((e.name, "message channel", ctx.cite(e.evidence_ids)), labels_of(e), e.evidence_ids, (e.id,)) for e in q.of("event")]
        rows += [((a.name, "external service", ctx.cite(a.evidence_ids)), labels_of(a), a.evidence_ids, (a.id,)) for a in q.of("api", external=True)]
        if rows:
            s.table("deps", ("Dependency", "Kind", "Source"), rows)
        else:
            s.empty("runtime dependencies", "no-dependencies")
        sec_deps = s.build()
        s = SB(ctx, "health", "Health and probe endpoints")
        probes = [a for a in q.of("api", external=False) if any(w in a.name.lower() for w in ("health", "ready", "live", "ping", "status"))]
        if probes:
            s.table("probes", ("Endpoint", "Source"), [((a.name, ctx.cite(a.evidence_ids)), labels_of(a), a.evidence_ids, (a.id,)) for a in probes])
        else:
            s.claim("No health or readiness endpoint was found in the analyzed code.", ("UNKNOWN",))
        sec_health = s.build()
        s = SB(ctx, "unknowns", "What operators must supply")
        for text in ("Start-up, shutdown and recovery procedures are not in the repository text and are not reconstructed.",
                     "Alert thresholds, service-level objectives, on-call ownership and escalation paths are not known.",
                     "Production topology, capacity and backup arrangements are not known."):
            s.claim(text, ("UNKNOWN", NSV))
        return [sec_config, sec_deploy, sec_deps, sec_health, s.build()]


register(OperationsRunbook(), "extension:operations")
