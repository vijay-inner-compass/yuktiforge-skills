"""Schema migrations for knowledge-model files. Every released version has a step to the next; a file from a NEWER version is refused, never guessed at."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from yuktiforge.docint.knowledge.schema import FORMAT, SCHEMA_VERSION, KnowledgeModel
from yuktiforge.errors import YuktiForgeError


def _v10_to_v11(d: dict[str, Any]) -> dict[str, Any]:
    """1.0 -> 1.1: entities and relationships called their evidence class `confidence` (now `cls`), entities had no lifecycle `status`, and `external` did not exist."""
    d = copy.deepcopy(d)
    for coll in ("entities", "relationships"):
        for x in d.get(coll, []):
            if "confidence" in x and "cls" not in x:
                x["cls"] = x.pop("confidence")
    for e in d.get("entities", []):
        e.setdefault("status", "active")
        e.setdefault("external", False)
    d["schema_version"] = "1.1"
    return d


STEPS: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {"1.0": ("1.1", _v10_to_v11)}


def migrate(doc: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise YuktiForgeError(f"not a {FORMAT} document")
    v = str(doc.get("schema_version", ""))
    applied: list[str] = []
    while v != SCHEMA_VERSION:
        if v not in STEPS:
            raise YuktiForgeError(f"cannot migrate schema version '{v}' to {SCHEMA_VERSION}: " + ("it is newer than this tool understands" if v > SCHEMA_VERSION else "unknown version"))
        nxt, fn = STEPS[v]
        doc = fn(doc)
        applied.append(f"{v} -> {nxt}")
        v = nxt
    return doc, applied


def load_model_file(path: Path) -> tuple[KnowledgeModel, list[str]]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise YuktiForgeError(f"cannot read {path}: {e}") from e
    doc, applied = migrate(doc)
    try:
        return KnowledgeModel.model_validate(doc), applied
    except ValueError as e:
        raise YuktiForgeError(f"{path} does not match the schema: {str(e)[:300]}") from e
