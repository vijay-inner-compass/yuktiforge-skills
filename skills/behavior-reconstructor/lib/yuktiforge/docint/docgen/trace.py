"""Requirements-to-code-to-test traceability. A link from a requirement to code exists ONLY when a person made it (`docs model link`); tests are linked by import (a hint)."""
from __future__ import annotations

from yuktiforge.docint.docgen.types_req import module_of, tests_for
from yuktiforge.docint.docgen.helpers import Q
from yuktiforge.docint.docgen.spi import GenContext
from yuktiforge.docint.knowledge.graph import Graph
from yuktiforge.docint.knowledge.schema import KnowledgeModel


def requirements_traceability(model: KnowledgeModel) -> dict:
    g = Graph(model)
    ctx = GenContext(model=model, graph=g)
    q = Q(ctx)
    reqs = [e for e in model.entities if e.type in ("requirement_candidate", "business_rule_candidate") and (e.cls == "user-supplied" or any(g.ev[i].cls == "user-supplied" for i in e.evidence_ids if i in g.ev))]
    rows, linked_code = [], set()
    for r in sorted(reqs, key=lambda x: x.id):
        targets = [g.ent[rel.target] for rel in g.out.get(r.id, []) if rel.type == "traces-to" and rel.target in g.ent]
        code, tests = [], []
        for t in targets:
            linked_code.add(t.id)
            m = module_of(q, t) if t.type in ("symbol", "interface") else (t if t.type == "module" else None)
            handlers = q.handlers(t) if t.type == "api" else []
            for h in handlers:
                linked_code.add(h.id)
            for x in ([m] if m else []) + [module_of(q, h) for h in handlers if module_of(q, h)]:
                tests += [tt.name for tt in tests_for(ctx, q, x.id)]
            code.append({"id": t.id, "name": t.name, "type": t.type, "evidence": g.cite(t.evidence_ids)})
        rows.append({"requirement": {"id": r.id, "name": r.name, "statement": r.attrs.get("statement", ""), "approval": r.approval, "supplied_by": r.attrs.get("asserted_by", "?")},
                     "code": code, "tests_importing_that_code": sorted(set(tests)),
                     "status": "linked" if code else "NO CODE LINKED (a person must link it, or it is not implemented)", "basis": "link made by a person; tests by import hint"})
    apis = [a for a in q.of("api", external=False) if a.subtype in ("route", "grpc", "graphql")]
    unreq = [{"id": a.id, "name": a.name} for a in apis if a.id not in linked_code]
    return {"format": "yuktiforge-requirements-traceability/1", "scan_id": model.scan_id, "requirements": rows, "apis_without_a_linked_requirement": unreq,
            "notes": ["Reconstructed documents do not create requirement-to-code links. Only links recorded by named people appear as 'linked'."]}
