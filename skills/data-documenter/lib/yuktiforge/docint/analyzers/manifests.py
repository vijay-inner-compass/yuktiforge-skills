"""Dependency and build manifests: requirements.txt, pyproject.toml, package.json, pom.xml, build.gradle(.kts), *.csproj, go.mod, Cargo.toml.
Parsed with data parsers only (tomllib, json, a hardened XML path, line regexes). No build tool is ever run, so versions are what is DECLARED
(ranges, properties and BOMs are copied as written, not resolved) and transitive dependencies are not known."""
from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET

from yuktiforge.docint.analyzers.base import Capability, FileAnalyzer, prov, register, split_lines
from yuktiforge.docint.model import Artifact, Dependency, FileFacts, clip
from yuktiforge.docint.safety import redact_url

_LIMITS = ("declared versions only: ranges, properties, BOMs and lockfiles are not resolved; transitive dependencies are unknown",
           "no build tool is run: generated or conditional dependencies are not seen")
_XML_BAD = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.I)
MAX_DEPS = 5000


class ManifestAnalyzer(FileAnalyzer):
    def __init__(self):
        self.capability = Capability("manifest-parsers", "1.0", ("manifest",),
                                     ("requirements*.txt", "pyproject.toml", "package.json", "pom.xml", "build.gradle", "build.gradle.kts", "*.csproj", "go.mod", "Cargo.toml"),
                                     "manifest", ("dependencies", "entry-points"), "high", _LIMITS)

    def analyze(self, rel: str, text: str) -> FileFacts:
        name = rel.rsplit("/", 1)[-1]
        lines = split_lines(text)
        deps: list[Dependency] = []
        arts: list[Artifact] = []
        warn: list[str] = []
        cap = self.capability

        def line_of(needle: str) -> int:
            for i, ln in enumerate(lines, 1):
                if needle in ln:
                    return i
            return 1

        def dep(eco, nm, ver="", scope="unknown", ln=None):
            if len(deps) < MAX_DEPS:
                ln = ln or line_of(nm)
                deps.append(Dependency(ecosystem=eco, name=clip(str(nm), 200), version_spec=clip(str(ver), 80), scope=scope, manifest=rel, line=ln, prov=prov(rel, ln, ln, cap)))

        def art(kind, detail, ln=1):
            arts.append(Artifact(kind=kind, path=rel, detail=clip(detail), prov=prov(rel, ln, ln, cap)))

        parsed = True
        try:
            if name.startswith("requirements") and name.endswith(".txt"):
                art("manifest", "pip requirements")
                for i, raw in enumerate(lines, 1):
                    s = raw.split(" #", 1)[0].strip()
                    if not s or s.startswith(("#", "-r", "-c", "--", "-e", "-f")) or "://" in s.split(";")[0] and "@" not in s:
                        continue
                    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*?)\s*(;.*)?$", s)
                    if m:
                        spec = m.group(3)
                        dep("pypi", m.group(1), redact_url(spec) if "://" in spec else spec, "runtime" if "dev" not in name and "test" not in name else "test" if "test" in name else "dev", i)
            elif name == "pyproject.toml":
                data = tomllib.loads(text)
                art("manifest", f"pyproject: {data.get('project', {}).get('name', data.get('tool', {}).get('poetry', {}).get('name', '?'))}")
                pr = data.get("project", {})
                for d in pr.get("dependencies", []) or []:
                    self._pep508(d, "runtime", dep)
                for grp, ds in (pr.get("optional-dependencies", {}) or {}).items():
                    for d in ds:
                        self._pep508(d, "test" if "test" in grp else "dev" if "dev" in grp else "optional", dep)
                for grp, ds in (data.get("dependency-groups", {}) or {}).items():
                    for d in ds:
                        if isinstance(d, str):
                            self._pep508(d, "test" if "test" in grp else "dev", dep)
                for d in data.get("build-system", {}).get("requires", []) or []:
                    self._pep508(d, "build", dep)
                poetry = data.get("tool", {}).get("poetry", {})
                for nm, v in (poetry.get("dependencies", {}) or {}).items():
                    if nm != "python":
                        dep("pypi", nm, v if isinstance(v, str) else (v.get("version", "") if isinstance(v, dict) else ""), "runtime")
                for nm, v in ((poetry.get("group", {}).get("dev", {}) or {}).get("dependencies", {}) or {}).items():
                    dep("pypi", nm, v if isinstance(v, str) else "", "dev")
                for nm, target in (pr.get("scripts", {}) or {}).items():
                    art("entry-point", f"{nm} = {target}", line_of(nm))
            elif name == "package.json":
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError("package.json is not an object")
                art("manifest", f"npm package: {data.get('name', '?')}")
                for key, scope in (("dependencies", "runtime"), ("devDependencies", "dev"), ("peerDependencies", "optional"), ("optionalDependencies", "optional")):
                    for nm, v in (data.get(key) or {}).items():
                        dep("npm", nm, v if isinstance(v, str) else "", scope)
                for nm, cmd in (data.get("scripts") or {}).items():
                    art("script", f"npm run {nm}: {cmd}", line_of(f'"{nm}"'))
                if isinstance(data.get("main"), str):
                    art("entry-point", f"main: {data['main']}", line_of('"main"'))
                bins = data.get("bin")
                if isinstance(bins, dict):
                    for nm, p in bins.items():
                        art("entry-point", f"bin {nm}: {p}", line_of('"bin"'))
                elif isinstance(bins, str):
                    art("entry-point", f"bin: {bins}", line_of('"bin"'))
            elif name == "pom.xml" or name.endswith(".csproj"):
                root = self._xml(text)
                if root is None:
                    parsed = False
                    warn.append("XML with a DOCTYPE or ENTITY declaration is refused (entity expansion / external entities); the file was not parsed")
                elif name == "pom.xml":
                    self._pom(root, rel, dep, art, line_of)
                else:
                    self._csproj(root, dep, art, line_of)
            elif name.startswith("build.gradle"):
                art("manifest", "gradle build script")
                rx = re.compile(r"""\b(implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|annotationProcessor|kapt|classpath|compile|testCompile)\b\s*\(?\s*['"]([^'":]+):([^'":]+)(?::([^'"]+))?['"]""")
                for i, ln in enumerate(lines, 1):
                    m = rx.search(ln)
                    if m:
                        conf = m.group(1)
                        dep("maven", f"{m.group(2)}:{m.group(3)}", m.group(4) or "", "test" if conf.startswith("test") else "build" if conf in ("classpath", "annotationProcessor", "kapt", "compileOnly") else "runtime", i)
            elif name == "go.mod":
                art("manifest", "go module")
                in_block = False
                for i, raw in enumerate(lines, 1):
                    s = raw.split("//", 1)[0].strip()
                    if s.startswith("module "):
                        art("manifest", f"go module {s[7:].strip()}", i)
                    elif s == "require (":
                        in_block = True
                    elif s == ")":
                        in_block = False
                    elif in_block or s.startswith("require "):
                        parts = s.replace("require ", "", 1).split()
                        if len(parts) >= 2:
                            dep("go", parts[0], parts[1], "runtime", i)
            elif name == "Cargo.toml":
                data = tomllib.loads(text)
                art("manifest", f"cargo package: {data.get('package', {}).get('name', '?')}")
                for key, scope in (("dependencies", "runtime"), ("dev-dependencies", "dev"), ("build-dependencies", "build")):
                    for nm, v in (data.get(key) or {}).items():
                        dep("cargo", nm, v if isinstance(v, str) else (v.get("version", "") if isinstance(v, dict) else ""), scope)
        except (ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError, ET.ParseError, AttributeError, TypeError) as e:
            parsed = False
            warn.append(f"manifest could not be parsed ({type(e).__name__}); its dependencies are UNKNOWN, not absent")
        if len(deps) >= MAX_DEPS:
            warn.append(f"more than {MAX_DEPS} dependencies: the rest are not listed")
        return FileFacts(dependencies=tuple(deps), artifacts=tuple(arts), warnings=tuple(warn), parsed=parsed)

    @staticmethod
    def _pep508(spec, scope, dep):
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;]*)", spec)
        if m:
            dep("pypi", m.group(1), m.group(3).strip(), scope)

    @staticmethod
    def _xml(text: str):
        if _XML_BAD.search(text):
            return None
        root = ET.fromstring(text)
        for el in root.iter():                       # strip namespaces
            if isinstance(el.tag, str) and "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        return root

    @staticmethod
    def _pom(root, rel, dep, art, line_of):
        def t(el, tag):
            x = el.find(tag)
            return (x.text or "").strip() if x is not None and x.text else ""
        art("manifest", f"maven project: {t(root, 'groupId') or t(root.find('parent') if root.find('parent') is not None else root, 'groupId')}:{t(root, 'artifactId')} {t(root, 'packaging') or 'jar'}")
        par = root.find("parent")
        if par is not None:
            dep("maven", f"{t(par, 'groupId')}:{t(par, 'artifactId')}", t(par, "version"), "build", line_of("<parent>"))
        for d in root.iterfind(".//dependencies/dependency"):
            sc = t(d, "scope") or "compile"
            dep("maven", f"{t(d, 'groupId')}:{t(d, 'artifactId')}", t(d, "version"), "test" if sc == "test" else "runtime" if sc in ("compile", "runtime") else "optional", line_of(t(d, "artifactId")))
        for m in root.iterfind("modules/module"):
            if m.text:
                art("other", f"maven module: {m.text.strip()}", line_of(m.text.strip()))

    @staticmethod
    def _csproj(root, dep, art, line_of):
        tf = [e.text.strip() for e in root.iter() if e.tag in ("TargetFramework", "TargetFrameworks") and e.text]
        out = [e.text.strip() for e in root.iter() if e.tag == "OutputType" and e.text]
        sdk = root.attrib.get("Sdk", "")
        art("manifest", f".NET project: sdk={sdk or '?'} target={';'.join(tf) or '?'} output={out[0] if out else 'Library'}")
        if sdk:
            dep("nuget", sdk, "", "build", line_of("Sdk="))
        for e in root.iter():
            if e.tag == "PackageReference":
                nm = e.attrib.get("Include") or e.attrib.get("Update") or ""
                v = e.attrib.get("Version") or (e.findtext("Version") or "")
                if nm:
                    dep("nuget", nm, v, "runtime")
            elif e.tag == "ProjectReference" and e.attrib.get("Include"):
                art("other", f"project reference: {e.attrib['Include'].replace(chr(92), '/')}", line_of(e.attrib["Include"]))


register(ManifestAnalyzer())
