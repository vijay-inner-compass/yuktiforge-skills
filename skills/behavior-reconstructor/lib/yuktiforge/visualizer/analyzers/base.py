"""RepositoryAnalyzer contract.

An analyzer reads files (never executes them), reports what it can see, and states exactly what it
cannot. It must not invent relations: every finding carries file-level provenance.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from yuktiforge.visualizer.model import Boundary, Component, Relation

Granularity = Literal["package", "module"]


@dataclass(frozen=True)
class AnalyzerCapabilities:
    analyzer_id: str
    languages: tuple[str, ...]         # languages whose files this analyzer understands
    file_patterns: tuple[str, ...]     # exact filenames or *.ext it reads
    granularity: Granularity
    depth: Literal["manifest", "imports"]
    confidence: Literal["high", "medium", "low"]   # how literally findings follow from the files
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class RepoFile:
    rel: str            # POSIX path relative to repo root
    path: Path
    language: str | None
    size: int


@dataclass
class RepoScan:
    root: Path
    files: list[RepoFile]
    truncated: bool = False
    skipped_large: int = 0

    def matching(self, patterns: tuple[str, ...]) -> list[RepoFile]:
        out = []
        for f in self.files:
            name = f.rel.rsplit("/", 1)[-1]
            if any(name == p or (p.startswith("*.") and name.endswith(p[1:])) for p in patterns):
                out.append(f)
        return out


@dataclass
class AnalyzerReport:
    analyzer_id: str
    components: list[Component] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    boundaries: list[Boundary] = field(default_factory=list)
    files_examined: int = 0
    languages_covered: set[str] = field(default_factory=set)  # languages actually parsed this run
    skipped: list[str] = field(default_factory=list)   # files that could not be parsed (facts unknown, not absent)
    notes: list[str] = field(default_factory=list)


class RepositoryAnalyzer(ABC):
    @abstractmethod
    def capabilities(self) -> AnalyzerCapabilities: ...

    @abstractmethod
    def analyze(self, scan: RepoScan) -> AnalyzerReport: ...
