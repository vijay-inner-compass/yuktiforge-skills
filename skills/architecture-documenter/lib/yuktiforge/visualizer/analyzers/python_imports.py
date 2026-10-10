"""Python import-graph analyzer (module granularity). Static: `ast.parse` only, nothing is imported or run.

Components: each immediate child (sub-package or module) of a top-level package found in the repo.
Relations: an import in one component's files that resolves to another component of the same
repository. One relation per (source, target); up to 3 file:line citations.
Not detected: dynamic imports (importlib/__import__), imports inside strings, framework wiring/DI,
third-party packages (deliberately not drawn).
"""
from __future__ import annotations

import ast
import re

from yuktiforge.visualizer.analyzers.base import (
    AnalyzerCapabilities, AnalyzerReport, RepoFile, RepoScan, RepositoryAnalyzer,
)
from yuktiforge.visualizer.model import Component, Evidence, Provenance, Relation

ANALYZER_ID = "python-imports"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class PythonImportAnalyzer(RepositoryAnalyzer):
    def capabilities(self) -> AnalyzerCapabilities:
        return AnalyzerCapabilities(
            analyzer_id=ANALYZER_ID, languages=("python",), file_patterns=("*.py",),
            granularity="module", depth="imports", confidence="high",
            limitations=("Static imports only; dynamic imports, DI/framework wiring and runtime calls are not seen.",
                         "Third-party imports are intentionally not drawn.",
                         "Only top-level packages (directories with __init__.py) are analyzed."))

    def analyze(self, scan: RepoScan) -> AnalyzerReport:
        rep = AnalyzerReport(ANALYZER_ID)
        pyfiles = [f for f in scan.files if f.language == "python"]
        # A package path is any directory chain of __init__.py. Top-level = package whose parent has none.
        init_dirs = {f.rel.rsplit("/", 1)[0] if "/" in f.rel else "" for f in pyfiles if f.rel.endswith("__init__.py")}
        tops = sorted(d for d in init_dirs if d and ("/" not in d or d.rsplit("/", 1)[0] not in init_dirs))
        if not tops:
            rep.notes.append("no top-level Python package (directory with __init__.py) found")
            return rep

        comp_of: dict[str, str] = {}          # dotted module path -> component id
        comp_names: dict[str, tuple[str, str]] = {}
        file_comp: dict[str, tuple[str, str, str]] = {}   # rel -> (component id, top dotted, dotted module)
        for top in tops:
            top_name = top.rsplit("/", 1)[-1]
            for f in pyfiles:
                if not f.rel.startswith(top + "/"):
                    continue
                parts = f.rel[len(top) + 1:].split("/")
                mod_parts = parts[:-1] + ([] if parts[-1] == "__init__.py" else [parts[-1][:-3]])
                dotted = ".".join([top_name, *mod_parts])
                if not mod_parts:                      # the package's own __init__.py
                    file_comp[f.rel] = ("", top_name, dotted)
                    continue
                child = mod_parts[0]
                key = f"{top_name}.{child}"
                if key not in comp_of:
                    cid = f"py.{_slug(top_name)}.{_slug(child)}"
                    n = 2
                    while cid in comp_names:      # slugging can collide (e.g. `main` vs `__main__`); never reuse an id
                        cid = f"py.{_slug(top_name)}.{_slug(child)}-{n}"
                        n += 1
                    is_dir = any(g.rel.startswith(f"{top}/{child}/") for g in pyfiles)
                    comp_names[cid] = (key, f"{top}/{child}" if is_dir else f"{top}/{child}.py")   # cite a path that EXISTS
                    comp_of[key] = cid
                file_comp[f.rel] = (comp_of[key], top_name, dotted)

        for cid, (name, path) in sorted(comp_names.items()):
            n = sum(1 for r, v in file_comp.items() if v[0] == cid)
            rep.components.append(Component(
                id=cid, name=name, kind="module", technology="Python",
                description=f"{n} Python file(s) under {path}",
                evidence=Evidence(status="verified", confidence=1.0, sources=(
                    Provenance(kind="file", ref=path, detail="directory/module exists"),
                    Provenance(kind="analyzer", ref=ANALYZER_ID)))))

        edges: dict[tuple[str, str], list[str]] = {}
        for f in pyfiles:
            if f.rel not in file_comp or not file_comp[f.rel][0]:
                continue
            rep.files_examined += 1
            src_id, top_name, dotted = file_comp[f.rel]
            is_pkg = f.rel.endswith("__init__.py")
            try:
                tree = ast.parse(f.path.read_text(encoding="utf-8"), filename=f.rel)
            except (SyntaxError, UnicodeDecodeError, ValueError) as e:
                rep.notes.append(f"{f.rel}: not parsed ({type(e).__name__})")
                rep.skipped.append(f.rel)
                continue
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        base = dotted.split(".")
                        base = base if is_pkg else base[:-1]
                        base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                        prefix = ".".join(base + ([node.module] if node.module else []))
                    else:
                        prefix = node.module or ""
                    targets = [prefix] + [f"{prefix}.{a.name}" for a in node.names if a.name != "*"]
                for t in targets:
                    parts = t.split(".")
                    key = ".".join(parts[:2]) if len(parts) >= 2 else ""
                    tid = comp_of.get(key)
                    if tid and tid != src_id:
                        cites = edges.setdefault((src_id, tid), [])
                        cite = f"{f.rel}:{node.lineno}"
                        if cite not in cites:
                            cites.append(cite)
        for (s, t), cites in sorted(edges.items()):
            rep.relations.append(Relation(
                id=f"rel-{s}--{t}", source=s, target=t, kind="depends-on", label="imports", technology="Python",
                evidence=Evidence(status="verified", confidence=1.0, sources=(
                    *(Provenance(kind="file", ref=c, detail="import statement") for c in sorted(cites)[:3]),
                    Provenance(kind="analyzer", ref=ANALYZER_ID)))))
        rep.languages_covered.add("python")
        return rep
