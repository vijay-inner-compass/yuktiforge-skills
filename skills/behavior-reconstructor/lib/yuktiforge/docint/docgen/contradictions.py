"""Contradiction detection across a set of generated documents and the model: the same fact (entity + attribute) stated with different values, plus conflicts the model itself records."""
from __future__ import annotations

from collections import defaultdict

from yuktiforge.docint.docgen.doc import Claim, Document
from yuktiforge.docint.knowledge.schema import KnowledgeModel


def find_contradictions(docs: list[Document], model: KnowledgeModel) -> list[dict]:
    seen: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for d in docs:
        for s in d.sections:
            for b in s.blocks:
                if isinstance(b, Claim) and b.fact_key and b.fact_value is not None:
                    seen[b.fact_key][b.fact_value].append(f"{d.doc_type}:{s.id}")
    out = []
    for key, vals in sorted(seen.items()):
        if len(vals) > 1:
            out.append({"kind": "document-vs-document", "fact": key, "statements": {v: sorted(set(w)) for v, w in sorted(vals.items())}})
    for c in model.conflicts:
        out.append({"kind": f"model:{c.kind}", "fact": c.id, "detail": c.detail, "entities": list(c.entity_ids)})
    return out
