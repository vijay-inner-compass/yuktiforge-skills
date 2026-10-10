"""Repository inventory: a bounded, deterministic, non-executing walk that classifies every file and says why anything was not analyzed."""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from yuktiforge.docint import safety as S
from yuktiforge.docint.analyzers.knowledge import MANIFEST_GLOBS, MANIFEST_NAMES, TEST_RE, WORKSPACE_MARKERS

CI_PATTERNS = (".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", ".circleci/config.yml", "bitbucket-pipelines.yml", ".travis.yml")
CONTAINER_GLOBS = ("Dockerfile", "Dockerfile.*", "*.dockerfile", "docker-compose*.yml", "docker-compose*.yaml", "compose.yml", "compose.yaml")
IAC_GLOBS = ("*.tf", "*.tfvars", "Chart.yaml", "serverless.yml", "serverless.yaml", "*.bicep", "Pulumi.yaml")
SCHEMA_GLOBS = ("*.sql", "*.prisma")
APISPEC_GLOBS = ("openapi*.json", "openapi*.yml", "openapi*.yaml", "swagger*.json", "swagger*.yml", "swagger*.yaml", "*.proto", "*.graphql", "*.gql", "*.wsdl", "asyncapi*.yml", "asyncapi*.yaml")
DOC_EXT = (".md", ".rst", ".adoc", ".txt", ".markdown")
CONFIG_GLOBS = ("application*.properties", "application*.yml", "application*.yaml", "appsettings*.json", "web.config", "app.config", "*.ini", "*.cfg", "*.conf", "*.toml",
                "tsconfig*.json", ".env.example", ".env.sample", ".env.template", "*.properties", "logback*.xml", "log4j*.xml", "nginx*.conf")


@dataclass(slots=True)
class FileRecord:
    rel: str
    size: int
    language: str | None
    category: str                      # source | test | manifest | config | ci | container | iac | db-schema | api-spec | doc | lockfile | asset | data | other
    skip: str | None = None            # why the file was NOT analyzed (None = eligible)
    sha256: str | None = None          # only for files that were read
    analyzed_by: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return self.skip is None


@dataclass
class Inventory:
    records: list[FileRecord] = field(default_factory=list)
    truncated: bool = False
    truncation_reason: str = ""
    symlinks: list[tuple[str, str]] = field(default_factory=list)    # (path, "inside"|"outside"|"broken") : never followed
    skipped_dirs: dict[str, str] = field(default_factory=dict)       # dir -> reason
    gitignore_files: list[str] = field(default_factory=list)


def categorize(rel: str, language: str | None) -> str:
    name = rel.rsplit("/", 1)[-1]
    low = name.lower()
    if name in S.LOCKFILES:
        return "lockfile"
    if name in MANIFEST_NAMES or any(fnmatch.fnmatchcase(name, g) for g in MANIFEST_GLOBS):
        return "manifest"
    if any(fnmatch.fnmatchcase(rel, p) or fnmatch.fnmatchcase(name, p) for p in CI_PATTERNS):
        return "ci"
    if any(fnmatch.fnmatchcase(name, g) or fnmatch.fnmatchcase(low, g.lower()) for g in CONTAINER_GLOBS):
        return "container"
    if any(fnmatch.fnmatchcase(name, g) for g in IAC_GLOBS):
        return "iac"
    if any(fnmatch.fnmatchcase(low, g) for g in APISPEC_GLOBS):
        return "api-spec"
    if any(fnmatch.fnmatchcase(low, g) for g in SCHEMA_GLOBS) or "/migrations/" in "/" + rel or "/db/migrate/" in "/" + rel:
        return "db-schema" if low.endswith((".sql", ".prisma")) else "source" if language else "data"
    if TEST_RE.search(rel) and language:
        return "test"
    if language and language not in ("sql", "terraform"):
        return "source"
    if low.endswith(DOC_EXT) or low.startswith(("readme", "changelog", "license", "contributing")):
        return "doc"
    if any(fnmatch.fnmatchcase(name, g) for g in CONFIG_GLOBS) or low.endswith((".yml", ".yaml", ".json", ".xml")):
        return "config"
    return "other"


def walk(root: Path, limits: S.Limits = S.DEFAULT_LIMITS, include_generated: bool = False) -> Inventory:
    """Deterministic (sorted) walk. Symlinks are recorded and never followed. Nothing is opened except the head of regular text candidates to
    detect binary/generated files, and only after name-based exclusions (secret-like, ignored, vendored)."""
    root = Path(root)
    inv = Inventory()
    root_real = root.resolve()
    total = 0
    stack: list[tuple[str, list[S._Rule]]] = [("", [])]
    while stack:
        rel_dir, rules = stack.pop()
        here = root / rel_dir if rel_dir else root
        try:
            with os.scandir(here) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            inv.skipped_dirs[rel_dir or "."] = "unreadable"
            continue
        gi = next((e for e in entries if e.name == ".gitignore" and e.is_file(follow_symlinks=False)), None)
        if gi is not None:
            try:
                rules = rules + S.parse_gitignore(Path(gi.path).read_text(encoding="utf-8", errors="replace")[:200_000], rel_dir)
                inv.gitignore_files.append((rel_dir + "/.gitignore") if rel_dir else ".gitignore")
            except OSError:
                pass
        subdirs: list[tuple[str, list[S._Rule]]] = []
        for e in entries:
            rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
            if S.unsafe_name(e.name):
                inv.records.append(FileRecord(S.safe_display(rel), 0, None, "other", "unsafe-name"))
                continue
            if e.is_symlink():
                try:
                    tgt = Path(os.path.realpath(e.path))
                    kind = "inside" if (tgt == root_real or root_real in tgt.parents) and tgt.exists() else ("broken" if not tgt.exists() else "outside")
                except OSError:
                    kind = "broken"
                inv.symlinks.append((rel, kind))
                continue
            if e.is_dir(follow_symlinks=False):
                if e.name in S.SKIP_DIRS:
                    inv.skipped_dirs[rel] = "dependency, build output or tooling directory"
                elif S.ignored_by(rules, rel, True):
                    inv.skipped_dirs[rel] = "matched by .gitignore"
                elif rel.count("/") + 1 > limits.max_depth:
                    inv.skipped_dirs[rel] = f"deeper than {limits.max_depth} levels"
                else:
                    subdirs.append((rel, rules))
                continue
            if not e.is_file(follow_symlinks=False):
                continue
            if len(inv.records) >= limits.max_files:
                inv.truncated, inv.truncation_reason = True, f"more than {limits.max_files} files"
                stack.clear()
                break
            lang = S.language_for(rel)
            cat = categorize(rel, lang)
            try:
                size = e.stat(follow_symlinks=False).st_size
            except OSError:
                inv.records.append(FileRecord(rel, 0, lang, cat, "unreadable"))
                continue
            rec = FileRecord(rel, size, lang, cat)
            ext = rel[rel.rfind("."):].lower() if "." in rel.rsplit("/", 1)[-1] else ""
            if S.is_secret_like(rel):
                rec.skip = "secret-like name: content never read"
            elif S.ignored_by(rules, rel, False):
                rec.skip = "matched by .gitignore"
            elif cat == "lockfile":
                rec.skip = "lockfile: inventoried, not analyzed"
            elif ext in S.BINARY_EXT:
                rec.skip = "binary"
            elif S.is_generated_name(rel.rsplit("/", 1)[-1]) and not include_generated:
                rec.skip = "generated file"
            elif size > limits.max_file_bytes:
                rec.skip = f"larger than {limits.max_file_bytes} bytes"
            elif total + size > limits.max_total_bytes:
                rec.skip = "total size budget exhausted"
                inv.truncated, inv.truncation_reason = True, "total size budget"
            else:
                try:
                    with open(e.path, "rb") as fh:
                        head = fh.read(8192)
                except OSError:
                    rec.skip = "unreadable"
                else:
                    if S.looks_binary(head, ext):
                        rec.skip = "binary"
                    elif not include_generated and S.has_generated_header(head.decode("utf-8", "replace")):
                        rec.skip = "generated file"
                    else:
                        total += size
            inv.records.append(rec)
        for d in reversed(subdirs):
            stack.append(d)
    inv.records.sort(key=lambda r: r.rel)
    return inv


def detect_projects(records: list[FileRecord]) -> list[dict]:
    """Projects by manifest location (path-based). Nested projects and workspaces are reported; names/frameworks come from manifests later."""
    by_dir: dict[str, list[tuple[str, str]]] = {}
    for r in records:
        if r.category != "manifest":
            continue
        name = r.rel.rsplit("/", 1)[-1]
        eco = MANIFEST_NAMES.get(name) or next((v for g, v in MANIFEST_GLOBS.items() if fnmatch.fnmatchcase(name, g)), None)
        d = r.rel.rsplit("/", 1)[0] if "/" in r.rel else "."
        by_dir.setdefault(d, []).append((r.rel, eco or "unknown"))
    roots = sorted(by_dir, key=lambda d: (d.count("/") if d != "." else -1, d))
    projects = []
    for d in roots:
        manifests = sorted(by_dir[d])
        ecos = sorted({e for _, e in manifests if e not in ("cmake",)}) or sorted({e for _, e in manifests})
        parent = next((p for p in reversed(roots[:roots.index(d)]) if p == "." or d.startswith(p + "/")), None)
        projects.append({"root": d, "ecosystems": ecos, "manifests": [m for m, _ in manifests], "parent": parent})
    return projects
