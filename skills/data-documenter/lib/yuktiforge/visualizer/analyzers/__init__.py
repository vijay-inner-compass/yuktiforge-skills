"""Analyzer registry, orchestration and honest coverage reporting."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from yuktiforge.visualizer.analyzers.base import (
    AnalyzerCapabilities, AnalyzerReport, Granularity, RepoScan, RepositoryAnalyzer,
)
from yuktiforge.visualizer.analyzers.manifests import ManifestDependencyAnalyzer
from yuktiforge.visualizer.analyzers.python_imports import PythonImportAnalyzer
from yuktiforge.visualizer.analyzers.scan import scan_repo
from yuktiforge.visualizer.model import (
    AnalyzerCoverage, ArchitectureModel, Coverage, LanguageCoverage,
)

REGISTRY: tuple[RepositoryAnalyzer, ...] = (ManifestDependencyAnalyzer(), PythonImportAnalyzer())


def discover_capabilities() -> list[AnalyzerCapabilities]:
    return [a.capabilities() for a in REGISTRY]


def analyze_repository(root: str | Path, granularity: Granularity = "package",
                       analyzers: tuple[RepositoryAnalyzer, ...] | None = None) -> ArchitectureModel:
    """Run every analyzer applicable at `granularity`, merge into ONE canonical model with coverage."""
    scan: RepoScan = scan_repo(root)
    chosen = analyzers if analyzers is not None else REGISTRY
    comps, rels, bounds, a_cov, unparsed = [], [], [], [], []
    covered: dict[str, set[str]] = {}
    depth_rank = {"none": 0, "manifest": 1, "imports": 2}
    depth: dict[str, str] = {}
    for a in chosen:
        cap = a.capabilities()
        if cap.granularity != granularity:
            a_cov.append(AnalyzerCoverage(analyzer_id=cap.analyzer_id, status="not-applicable",
                                          languages=cap.languages,
                                          limitations=(f"works at {cap.granularity} granularity; run was {granularity}",)))
            continue
        rep: AnalyzerReport = a.analyze(scan)
        comps += rep.components; rels += rep.relations; bounds += rep.boundaries; unparsed += rep.skipped
        a_cov.append(AnalyzerCoverage(analyzer_id=cap.analyzer_id, status="ran", languages=cap.languages,
                                      files_examined=rep.files_examined,
                                      limitations=(*cap.limitations, *rep.notes)))
        for lang in rep.languages_covered:
            covered.setdefault(lang, set()).add(cap.analyzer_id)
            if depth_rank[cap.depth] > depth_rank[depth.get(lang, "none")]:
                depth[lang] = cap.depth
    counts = Counter(f.language for f in scan.files if f.language)
    langs = tuple(LanguageCoverage(language=l, files=n, analyzers=tuple(sorted(covered.get(l, ()))),
                                   depth=depth.get(l, "none")) for l, n in sorted(counts.items()))
    notes = []
    if scan.truncated:
        notes.append(f"scan truncated at file limit; results are PARTIAL")
    if scan.skipped_large:
        notes.append(f"{scan.skipped_large} file(s) over the size limit were skipped")
    unsupported = [l.language for l in langs if l.depth == "none"]
    if unsupported:
        notes.append("languages detected with NO analyzer coverage at this granularity (their code is absent "
                     "from analyzer output): " + ", ".join(unsupported))
    return ArchitectureModel(name=scan.root.name, components=tuple(comps), relations=tuple(rels),
                             boundaries=tuple(bounds),
                             coverage=Coverage(languages=langs, analyzers=tuple(a_cov), notes=tuple(notes),
                                               unparsed_files=tuple(sorted(set(unparsed)))))


__all__ = ["REGISTRY", "RepositoryAnalyzer", "AnalyzerCapabilities", "AnalyzerReport", "analyze_repository",
           "discover_capabilities", "scan_repo"]
