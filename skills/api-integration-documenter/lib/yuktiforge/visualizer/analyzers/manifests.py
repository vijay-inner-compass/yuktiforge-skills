"""Language-neutral-in-spirit analyzer: reads dependency manifests and links in-repo packages.

Facts reported (all verified, with file provenance):
  * a package exists (manifest declares a name)
  * package A declares a dependency on package B, where B is ALSO defined in this repository
Not reported: third-party dependencies, runtime/network calls, anything about source code.
"""
from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from yuktiforge.visualizer.analyzers.base import (
    AnalyzerCapabilities, AnalyzerReport, RepoScan, RepositoryAnalyzer,
)
from yuktiforge.visualizer.model import Component, Evidence, Provenance, Relation

ANALYZER_ID = "manifest-dependencies"
PATTERNS = ("package.json", "pyproject.toml", "pom.xml", "go.mod", "Cargo.toml")


@dataclass
class _Pkg:
    eco: str                    # ecosystem label
    language: str
    name: str
    deps: list[str]
    rel: str                    # manifest path
    group: str = ""
    id: str = ""


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "x"


def _pep508_name(spec: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return re.sub(r"[-_.]+", "-", m.group(1)).lower() if m else ""


def _norm_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_package_json(text: str, rel: str) -> list[_Pkg]:
    d = json.loads(text)
    if not isinstance(d, dict) or not isinstance(d.get("name"), str):
        return []
    deps: list[str] = []
    for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        if isinstance(d.get(k), dict):
            deps += list(d[k])
    return [_Pkg("npm", "typescript/javascript", d["name"], deps, rel)]


def _parse_pyproject(text: str, rel: str) -> list[_Pkg]:
    d = tomllib.loads(text)
    proj, poetry = d.get("project", {}), d.get("tool", {}).get("poetry", {})
    name = proj.get("name") or poetry.get("name")
    if not isinstance(name, str):
        return []
    deps = [_pep508_name(x) for x in proj.get("dependencies", []) if isinstance(x, str)]
    for group in proj.get("optional-dependencies", {}).values():
        deps += [_pep508_name(x) for x in group if isinstance(x, str)]
    deps += [_norm_py(k) for k in poetry.get("dependencies", {}) if k.lower() != "python"]
    return [_Pkg("python", "python", _norm_py(name), [x for x in deps if x], rel)]


def _parse_pom(raw: bytes, rel: str) -> list[_Pkg]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DOCTYPE/ENTITY declarations are refused")
    root = ET.fromstring(raw)
    ns = "{" + root.tag[1:].split("}")[0] + "}" if root.tag.startswith("{") else ""
    def txt(el, tag):
        c = el.find(f"{ns}{tag}")
        return (c.text or "").strip() if c is not None and c.text else ""
    parent = root.find(f"{ns}parent")
    group = txt(root, "groupId") or (txt(parent, "groupId") if parent is not None else "")
    art = txt(root, "artifactId")
    if not art:
        return []
    deps = []
    for d in root.iterfind(f"{ns}dependencies/{ns}dependency"):
        a, g = txt(d, "artifactId"), txt(d, "groupId")
        if a:
            deps.append(f"{g}:{a}")
    return [_Pkg("maven", "java", art, deps, rel, group=group)]


def _parse_gomod(text: str, rel: str) -> list[_Pkg]:
    m = re.search(r"^module\s+(\S+)", text, re.M)
    if not m:
        return []
    deps = re.findall(r"^\s*(?:require\s+)?([\w.\-/~]+\.[\w.\-/~]+)\s+v[\w.\-+]+", text, re.M)
    return [_Pkg("go", "go", m.group(1), [d for d in deps if d != m.group(1)], rel)]


def _parse_cargo(text: str, rel: str) -> list[_Pkg]:
    d = tomllib.loads(text)
    name = d.get("package", {}).get("name")
    if not isinstance(name, str):
        return []
    deps: list[str] = []
    for k in ("dependencies", "dev-dependencies", "build-dependencies"):
        deps += list(d.get(k, {}))
    return [_Pkg("cargo", "rust", name, deps, rel)]


class ManifestDependencyAnalyzer(RepositoryAnalyzer):
    def capabilities(self) -> AnalyzerCapabilities:
        return AnalyzerCapabilities(
            analyzer_id=ANALYZER_ID,
            languages=("javascript", "typescript", "python", "java", "go", "rust"),
            file_patterns=PATTERNS, granularity="package", depth="manifest", confidence="high",
            limitations=(
                "Reads manifests only; no source code is inspected.",
                "Only dependencies on packages defined inside this repository become relations.",
                "Runtime calls, HTTP/queue links and infrastructure are invisible here.",
                "Gradle/sbt/CMake/Composer/NuGet/Swift Package Manager manifests are not read.",
            ))

    def analyze(self, scan: RepoScan) -> AnalyzerReport:
        rep = AnalyzerReport(ANALYZER_ID)
        pkgs: list[_Pkg] = []
        for f in scan.matching(PATTERNS):
            fn = f.rel.rsplit("/", 1)[-1]
            rep.files_examined += 1
            try:
                if fn == "package.json":
                    found = _parse_package_json(f.path.read_text(encoding="utf-8"), f.rel)
                elif fn == "pyproject.toml":
                    found = _parse_pyproject(f.path.read_text(encoding="utf-8"), f.rel)
                elif fn == "pom.xml":
                    found = _parse_pom(f.path.read_bytes(), f.rel)
                elif fn == "go.mod":
                    found = _parse_gomod(f.path.read_text(encoding="utf-8"), f.rel)
                else:
                    found = _parse_cargo(f.path.read_text(encoding="utf-8"), f.rel)
            except (ValueError, OSError, ET.ParseError, tomllib.TOMLDecodeError) as e:
                rep.notes.append(f"{f.rel}: unreadable manifest skipped ({type(e).__name__}: {e})")
                rep.skipped.append(f.rel)
                continue
            if not found:
                rep.notes.append(f"{f.rel}: no package name declared; skipped")
            pkgs += found
            for p in found:
                rep.languages_covered.update(p.language.split("/"))

        used: set[str] = set()
        for p in sorted(pkgs, key=lambda x: (x.eco, x.name, x.rel)):
            base = f"{p.eco}.{_slug(p.name)}"
            p.id = base if base not in used else f"{base}-{_slug(p.rel.rsplit('/', 1)[0] or 'root')}"
            used.add(p.id)
            rep.components.append(Component(
                id=p.id, name=p.name, kind="package", technology=p.eco,
                description=f"{p.eco} package declared in {p.rel}",
                evidence=Evidence(status="verified", confidence=1.0, sources=(
                    Provenance(kind="file", ref=p.rel, detail="package name declared"),
                    Provenance(kind="analyzer", ref=ANALYZER_ID)))))

        by_key = {(p.eco, p.name): p for p in pkgs if p.eco != "maven"}
        maven = {p.name: p for p in pkgs if p.eco == "maven"}
        seen: set[tuple[str, str]] = set()
        for p in sorted(pkgs, key=lambda x: x.id):
            for dep in sorted(set(p.deps)):
                if p.eco == "maven":
                    g, _, a = dep.rpartition(":")
                    t = maven.get(a)
                    if t is None or (g and t.group and not g.startswith("${") and g != t.group):
                        continue
                else:
                    t = by_key.get((p.eco, _norm_py(dep) if p.eco == "python" else dep))
                if t is None or t.id == p.id or (p.id, t.id) in seen:
                    continue
                seen.add((p.id, t.id))
                rep.relations.append(Relation(
                    id=f"rel-{p.id}--{t.id}", source=p.id, target=t.id, kind="depends-on",
                    label="depends on", technology=p.eco,
                    evidence=Evidence(status="verified", confidence=1.0, sources=(
                        Provenance(kind="file", ref=p.rel, detail=f"declares dependency '{dep}'"),
                        Provenance(kind="analyzer", ref=ANALYZER_ID)))))
        return rep
