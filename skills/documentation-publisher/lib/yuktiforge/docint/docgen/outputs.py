"""Write generated documents: Markdown, JSON document, evidence map, coverage report, glossary, manifest, validation report, contradictions."""
from __future__ import annotations

import json
import os
from pathlib import Path

from yuktiforge.docint.docgen import contradictions, glossary, render, validate
from yuktiforge.docint.docgen.doc import Document
from yuktiforge.docint.docgen.trace import requirements_traceability
from yuktiforge.docint.knowledge.schema import KnowledgeModel


def _w(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def canon(o) -> str:
    return json.dumps(o, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def write_documents(docs: list[Document], model: KnowledgeModel, out: Path, review: dict | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    manifest, validations = [], {}
    for d in docs:
        stem = f"{d.doc_type}.{d.audience}.{d.depth}"
        files = {"markdown": f"{stem}.md", "document": f"{stem}.json", "evidence_map": f"{stem}.evidence-map.json", "coverage": f"{stem}.coverage.json"}
        _w(out / files["markdown"], render.to_markdown(d, model, review))
        _w(out / files["document"], canon(d.model_dump(mode="json")))
        _w(out / files["evidence_map"], canon(render.evidence_map(d, model)))
        _w(out / files["coverage"], canon(render.coverage_report(d, model)))
        manifest.append(render.manifest_entry(d, files))
        rep = validate.validate_document(d, model)
        validations[d.doc_id] = {"doc_type": d.doc_type, "defects": rep.defects, "gaps": rep.gaps, "ok": rep.ok}
    g = glossary.build_glossary(model, docs)
    _w(out / "glossary.json", canon(g))
    _w(out / "glossary.md", glossary.glossary_markdown(g))
    cons = contradictions.find_contradictions(docs, model)
    _w(out / "contradictions.json", canon({"format": "yuktiforge-contradictions/1", "count": len(cons), "items": cons}))
    _w(out / "requirements-traceability.json", canon(requirements_traceability(model)))
    _w(out / "validation.json", canon({"format": "yuktiforge-doc-validation/1", "documents": validations, "all_ok": all(v["ok"] for v in validations.values())}))
    man = {"format": "yuktiforge-doc-manifest/1", "scan_id": model.scan_id, "repository": model.repository, "documents": manifest,
           "notes": ["every document is a DRAFT; reconstructions (BRD, SRS, functional spec, rule catalog, use cases) are never approved requirements"]}
    _w(out / "manifest.json", canon(man))
    return man
