"""Analyzer SPI. An analyzer reads ONE file's text (never executes it) and returns facts with provenance. It declares what it can and cannot see
(`Capability`), so coverage is reported from declarations, not from hope. Language-specific analyzers are plug-ins; the core names no language."""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from yuktiforge.docint.model import Confidence, FileFacts, Method, Provenance, clip
from yuktiforge.docint.safety import fnmatch_any

Depth = Literal["symbols", "imports", "calls", "routes", "db", "events", "http-clients", "config", "dependencies", "schema", "containers", "ci", "infra", "entry-points"]


@dataclass(frozen=True)
class Capability:
    analyzer_id: str
    version: str
    languages: tuple[str, ...]            # languages (or formats) whose files it understands
    patterns: tuple[str, ...]             # fnmatch patterns on the file's base name
    method: Method
    depth: tuple[Depth, ...]              # which kinds of facts it can produce
    confidence: Confidence                # how literally its facts follow from the text
    limitations: tuple[str, ...]

    def fingerprint(self) -> str:
        return f"{self.analyzer_id}@{self.version}"


class FileAnalyzer(ABC):
    capability: Capability

    def accepts(self, rel: str) -> bool:
        return fnmatch_any(rel.rsplit("/", 1)[-1], self.capability.patterns)

    @abstractmethod
    def analyze(self, rel: str, text: str) -> FileFacts: ...


_REGISTRY: list[FileAnalyzer] = []


def register(analyzer: FileAnalyzer) -> FileAnalyzer:
    ids = [a.capability.analyzer_id for a in _REGISTRY]
    if analyzer.capability.analyzer_id in ids:
        raise ValueError(f"analyzer id {analyzer.capability.analyzer_id!r} is already registered")
    _REGISTRY.append(analyzer)
    return analyzer


def unregister(analyzer_id: str) -> None:
    _REGISTRY[:] = [a for a in _REGISTRY if a.capability.analyzer_id != analyzer_id]


def analyzers() -> list[FileAnalyzer]:
    from yuktiforge.docint.analyzers import load_builtin
    load_builtin()
    return list(_REGISTRY)


def analyzers_for(rel: str) -> list[FileAnalyzer]:
    return [a for a in analyzers() if a.accepts(rel)]


# ------------------------------------------------------------------------------------------------ helpers shared by analyzers
_LINE_SPLIT = re.compile(r"\r\n|\n|\r")


def split_lines(text: str) -> list[str]:
    """Editor-style line splitting (\\n, \\r\\n, \\r only): str.splitlines() would also split on form feeds and U+2028 and shift every later line number."""
    return _LINE_SPLIT.split(text)


def prov(path: str, start: int, end: int | None, cap: Capability, *, method: Method | None = None, confidence: Confidence | None = None) -> Provenance:
    return Provenance(path=path, start_line=max(1, start), end_line=max(start, end or start, 1), analyzer=cap.fingerprint(), method=method or cap.method,
                      confidence=confidence or cap.confidence)


def sym_id(path: str, qualified: str, kind: str, line: int, taken: set[str]) -> str:
    """Readable and stable: `path::Qualified.Name`; overloads / duplicates get `@line`."""
    base = f"{path}::{qualified}"
    sid = base if base not in taken else f"{base}@{line}"
    taken.add(sid)
    return sid


def boundary_id(path: str, kind: str, name: str, line: int) -> str:
    return "bnd:" + hashlib.sha1(f"{path}|{kind}|{name}|{line}".encode()).hexdigest()[:12]


def doc_line(text: str) -> str:
    return clip(text, 200)
