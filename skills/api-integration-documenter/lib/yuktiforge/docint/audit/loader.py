"""Reading a directory written by `docs generate` / `docs publish` back into documents, plus the review decisions stored beside them."""
from __future__ import annotations

import json
from pathlib import Path

from yuktiforge.docint.docgen import review as R
from yuktiforge.docint.docgen.doc import Document
from yuktiforge.docint.knowledge.migrate import load_model_file
from yuktiforge.docint.knowledge.schema import KnowledgeModel
from yuktiforge.errors import YuktiForgeError

_SKIP = (".evidence-map.json", ".coverage.json")
_META = {"manifest.json", "glossary.json", "validation.json", "contradictions.json", "requirements-traceability.json", "review.json", "evaluation.json", "pack-manifest.json", "links.json", "visual-qa.json"}


def docs_dir(path: Path) -> Path:
    """Accept either the generate output itself or a publish pack (source/documents)."""
    p = Path(path)
    if (p / "source" / "documents").is_dir():
        return p / "source" / "documents"
    return p


def load_documents(path: Path) -> tuple[list[Document], Path]:
    d = docs_dir(path)
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name in _META or p.name.endswith(_SKIP):
            continue
        try:
            doc = Document.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append(doc)
    if not out:
        raise YuktiForgeError(f"no generated documents found in {path} (expected the output of `docs generate` or `docs publish`)")
    return out, d


def load_model(path: Path) -> KnowledgeModel:
    p = Path(path)
    cands = [p / "system-knowledge.json", p / "source" / "system-knowledge.json"]
    for c in cands:
        if c.is_file():
            return load_model_file(c)[0]
    raise YuktiForgeError(f"no system-knowledge.json in {path}: build one with `docs model build`")


def load_review(d: Path) -> R.ReviewDb:
    return R.load(d / "review.json")


def load_glossary(d: Path) -> dict:
    p = d / "glossary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"terms": []}
