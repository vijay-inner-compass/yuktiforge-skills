"""`yuktiforge docs scan`: inventory, analysis, resolution and the four index files. Static and non-executing: every file is only READ as text, below the
repository root, after name-based exclusions; nothing is imported, compiled, built or run, and no network is used."""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yuktiforge.docint import inventory as INV
from yuktiforge.docint import safety as S
from yuktiforge.docint.analyzers import base as AB
from yuktiforge.docint.index import FactCache, config_hash
from yuktiforge.docint.model import SCAN_FORMAT, Artifact, Boundary, Call, Dependency, FileFacts, Import, Symbol, clip
from yuktiforge.docint.analyzers.knowledge import BUILD_BY_ECO, FRAMEWORKS, WORKSPACE_MARKERS
from yuktiforge.docint.analyzers.resolvers import Resolver

TOOL = "yuktiforge-docint/1.0"
OUTPUT_FILES = ("repository-inventory.json", "symbol-index.json", "dependency-index.json", "coverage.json")

@dataclass
class ScanConfig:
    repo: Path
    out: Path | None = None
    cache: Path | None = None                 # None: <out>/.scan-cache/index.sqlite when out is given, otherwise in memory
    limits: S.Limits = S.DEFAULT_LIMITS
    include_generated: bool = False
    max_seconds: float | None = None          # analysis time budget; the rest is reported and a re-run resumes
    use_cache: bool = True


@dataclass
class ScanResult:
    outputs: dict[str, dict[str, Any]]
    stats: dict[str, Any]
    facts: dict[str, FileFacts] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def engine_hash() -> str:
    """Hash of the analysis code itself: a cached fact is only reused when the code that produced it is byte-identical (a fix to an analyzer invalidates its old output
    even if nobody remembered to bump a version number)."""
    here = Path(__file__).parent
    files = sorted(list((here / "analyzers").glob("*.py")) + [here / n for n in ("model.py", "safety.py")])
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def git_revision(root: Path) -> str | None:
    """HEAD commit read straight from `.git` files (no git process): regular files only, small, hex-validated; anything odd gives None."""
    try:
        g = root / ".git"
        if g.is_symlink() or not g.is_dir():
            return None
        head = _small(g / "HEAD")
        if head is None:
            return None
        if re.fullmatch(r"[0-9a-f]{40}", head):
            return head
        m = re.fullmatch(r"ref: (refs/[A-Za-z0-9._/-]+)", head)
        if not m or ".." in m.group(1):
            return None
        ref = _small(g / m.group(1))
        if ref and re.fullmatch(r"[0-9a-f]{40}", ref):
            return ref
        packed = _small(g / "packed-refs", 2_000_000)
        if packed:
            for ln in packed.splitlines():
                if ln.endswith(" " + m.group(1)) and re.match(r"^[0-9a-f]{40} ", ln):
                    return ln[:40]
    except OSError:
        pass
    return None


def _small(p: Path, limit: int = 4096) -> str | None:
    if p.is_symlink() or not p.is_file() or p.stat().st_size > limit:
        return None
    return p.read_text(encoding="utf-8", errors="replace").strip()


def _clamp(text: str, n: int) -> tuple[str, bool]:
    if len(text) <= n * 20 and "\n" in text and max(map(len, text.split("\n"))) <= n:
        return text, False
    lines = text.split("\n")
    changed = False
    for i, ln in enumerate(lines):
        if len(ln) > n:
            lines[i] = ln[:n]
            changed = True
    return "\n".join(lines), changed


def _scrub_obj(o):
    if isinstance(o, str):
        return S.scrub_text(o)
    if isinstance(o, (list, tuple)):
        return [_scrub_obj(x) for x in o]
    if isinstance(o, dict):
        return {k: _scrub_obj(v) for k, v in o.items()}
    return o


def _scrub_facts(f: FileFacts) -> FileFacts:
    return FileFacts.model_validate(_scrub_obj(f.model_dump()))


def _merge(parts: list[FileFacts]) -> FileFacts:
    return FileFacts(symbols=tuple(x for p in parts for x in p.symbols), imports=tuple(x for p in parts for x in p.imports), calls=tuple(x for p in parts for x in p.calls),
                     boundaries=tuple(x for p in parts for x in p.boundaries), dependencies=tuple(x for p in parts for x in p.dependencies),
                     artifacts=tuple(x for p in parts for x in p.artifacts), warnings=tuple(x for p in parts for x in p.warnings), parsed=all(p.parsed for p in parts))


def _cap_facts(f: FileFacts, limit: int) -> FileFacts:
    total = len(f.symbols) + len(f.imports) + len(f.calls) + len(f.boundaries) + len(f.dependencies)
    if total <= limit:
        return f
    share = max(1, limit // 5)
    return f.model_copy(update=dict(symbols=f.symbols[:share], imports=f.imports[:share], calls=f.calls[:share], boundaries=f.boundaries[:share], dependencies=f.dependencies[:share],
                                    warnings=f.warnings + (f"more than {limit} facts in one file: output truncated; the rest is UNKNOWN",)))


def _canon(o: Any) -> str:
    return json.dumps(o, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def scan(cfg: ScanConfig) -> ScanResult:
    root = cfg.repo.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"repository path is not a directory: {cfg.repo}")
    out_rel: str | None = None
    if cfg.out is not None:
        o = cfg.out.resolve()
        if o == root:
            raise ValueError("--out must not be the repository root")
        if root in o.parents:
            out_rel = o.relative_to(root).as_posix()
    inv = INV.walk(root, cfg.limits, cfg.include_generated)
    records = [r for r in inv.records if not (out_rel and (r.rel == out_rel or r.rel.startswith(out_rel + "/")))]
    cache_path = cfg.cache if cfg.cache is not None else ((cfg.out / ".scan-cache" / "index.sqlite") if (cfg.out is not None and cfg.use_cache) else None)
    cache = FactCache(cache_path if cfg.use_cache else None)
    resumed = cache.previous_run_complete() is False
    cache.start_run()
    cfg_h = config_hash(limits=cfg.limits.__dict__, include_generated=cfg.include_generated, engine=engine_hash())
    t0 = time.monotonic()
    facts: dict[str, FileFacts] = {}
    status: dict[str, str] = {}
    analyzed_n = reused_n = 0
    for r in records:
        if not r.eligible:
            status[r.rel] = "skipped"
            continue
        if cfg.max_seconds is not None and time.monotonic() - t0 > cfg.max_seconds:
            r.skip = "analysis time budget exhausted: re-run to continue"
            status[r.rel] = "skipped"
            continue
        anz = AB.analyzers_for(r.rel)
        try:
            with open(root / r.rel, "rb") as fh:
                data = fh.read(cfg.limits.max_file_bytes + 1)
        except OSError:
            r.skip = "unreadable"
            status[r.rel] = "skipped"
            continue
        if len(data) > cfg.limits.max_file_bytes:
            r.skip = f"larger than {cfg.limits.max_file_bytes} bytes"
            status[r.rel] = "skipped"
            continue
        r.sha256 = hashlib.sha256(data).hexdigest()
        if not anz:
            status[r.rel] = "no-analyzer"
            continue
        r.analyzed_by = sorted(a.capability.fingerprint() for a in anz)
        key = cfg_h + "|" + ",".join(r.analyzed_by)
        got = cache.get(r.rel, r.sha256, key)
        if got is not None:
            reused_n += 1
        else:
            text = data.decode("utf-8", errors="replace").lstrip("﻿")
            clamped_text, clamped = _clamp(text, cfg.limits.max_line_chars)       # only the token-based analyzers are protected this way: data parsers need the exact text
            parts = []
            for a in anz:
                lexical = a.capability.method == "lexical"
                try:
                    f = a.analyze(r.rel, clamped_text if lexical else text)
                    if lexical and clamped:
                        f = f.model_copy(update=dict(warnings=f.warnings + (f"lines longer than {cfg.limits.max_line_chars} characters were truncated before analysis",)))
                    parts.append(f)
                except Exception as e:                                      # an analyzer bug must not stop the scan; the failure is recorded
                    parts.append(FileFacts(warnings=(f"analyzer {a.capability.fingerprint()} failed ({type(e).__name__})",), parsed=False))
            got = _merge(parts)
            got = _scrub_facts(_cap_facts(got, cfg.limits.max_facts_per_file))
            cache.put(r.rel, r.sha256, key, got)
            analyzed_n += 1
        facts[r.rel] = got
        status[r.rel] = "analyzed" if got.parsed else "parse-failed"
    cache.prune({r.rel for r in records})
    complete = not any(r.skip and r.skip.startswith("analysis time budget") for r in records)
    if complete:
        cache.finish_run()
    cache.close()

    symbols = [s for rel in sorted(facts) for s in facts[rel].symbols]
    imports = [i for rel in sorted(facts) for i in facts[rel].imports]
    calls = [c for rel in sorted(facts) for c in facts[rel].calls]
    bounds = [b for rel in sorted(facts) for b in facts[rel].boundaries]
    deps = [d for rel in sorted(facts) for d in facts[rel].dependencies]
    arts = [a for rel in sorted(facts) for a in facts[rel].artifacts]
    langs = {r.rel: r.language for r in records}
    res = Resolver({r.rel for r in records}, symbols, arts, langs)
    imports = [res.resolve_import(i) for i in imports]
    calls = res.resolve_calls(calls, imports)

    revision = git_revision(root)
    scan_id = hashlib.sha256(json.dumps([revision, sorted((r.rel, r.sha256) for r in records if r.sha256), sorted({x for r in records for x in r.analyzed_by}), cfg_h], sort_keys=True).encode()).hexdigest()[:16]
    outputs = _outputs(root, inv, records, status, facts, symbols, imports, calls, bounds, deps, arts, revision, scan_id, complete)
    stats = {"files_analyzed": analyzed_n, "files_reused_from_cache": reused_n, "resumed_after_interruption": resumed, "cache": "sqlite" if cache_path and cfg.use_cache else "memory",
             "analysis_complete": complete}
    return ScanResult(outputs, stats, facts)


def _outputs(root, inv, records, status, facts, symbols, imports, calls, bounds, deps, arts, revision, scan_id, complete) -> dict[str, dict[str, Any]]:
    header = {"format": SCAN_FORMAT, "tool": TOOL, "scan_id": scan_id,
              "repository": {"name": S.safe_display(root.name), "revision": revision, "revision_note": None if revision else "not a readable git checkout: revision unknown"}}
    # ------------------------------------------------------------ inventory
    lang_files: Counter[str] = Counter()
    lang_bytes: Counter[str] = Counter()
    for r in records:
        if r.language:
            lang_files[r.language] += 1
            lang_bytes[r.language] += r.size
    cat_paths: dict[str, list[str]] = defaultdict(list)
    for r in records:
        cat_paths[r.category].append(r.rel)
    projects = INV.detect_projects(records)
    frameworks = _frameworks(deps, bounds)
    for p in projects:
        pref = "" if p["root"] == "." else p["root"] + "/"
        c = Counter(r.language for r in records if r.language and r.category in ("source", "test") and r.rel.startswith(pref))
        p["languages"] = [k for k, _ in c.most_common()]
        p["frameworks"] = sorted({f for (m, f) in frameworks["by_manifest"] if m.startswith(pref) and "/" not in m[len(pref):]})
    entry = sorted({(b.prov.path, b.prov.start_line, b.name, b.framework) for b in bounds if b.kind == "entry-point"})
    scripts = sorted({(a.path, a.prov.start_line, a.detail) for a in arts if a.kind in ("entry-point", "script")})
    files = []
    for r in records:
        files.append({"path": r.rel, "size": r.size, "language": r.language, "category": r.category, "status": status.get(r.rel, "skipped"), "skip_reason": r.skip,
                      "sha256": r.sha256, "analyzers": r.analyzed_by, "facts": _count(facts.get(r.rel))})
    inventory = dict(header, totals={"files": len(records), "analyzed": sum(1 for r in records if status.get(r.rel) == "analyzed"), "bytes": sum(r.size for r in records)},
                     languages={k: {"files": lang_files[k], "bytes": lang_bytes[k]} for k in sorted(lang_files)},
                     projects=projects, build_systems=sorted({BUILD_BY_ECO.get(e, e) for p in projects for e in p["ecosystems"]}), frameworks=frameworks["names"], detected_patterns=sorted({b.framework for b in bounds if b.framework != "unknown"}),
                     monorepo=len([p for p in projects if p["root"] != "."]) > 1 or any(r.rel.rsplit("/", 1)[-1] in WORKSPACE_MARKERS for r in records),
                     mixed_language=len([k for k in lang_files if k not in ("sql", "shell", "terraform")]) > 1,
                     entry_points=[{"path": p, "line": ln, "name": n, "framework": f} for p, ln, n, f in entry], scripts=[{"path": p, "line": ln, "detail": d} for p, ln, d in scripts],
                     groups={k: sorted(v) for k, v in sorted(cat_paths.items()) if k in ("manifest", "config", "ci", "container", "iac", "db-schema", "api-spec", "test", "doc", "lockfile")},
                     symlinks=[{"path": p, "target": t} for p, t in sorted(inv.symlinks)], skipped_dirs=dict(sorted(inv.skipped_dirs.items())), gitignore_files=sorted(inv.gitignore_files),
                     truncated=inv.truncated, truncation_reason=inv.truncation_reason, files=files)
    # ------------------------------------------------------------ symbols
    sym_doc = dict(header, counts={"symbols": len(symbols), "boundaries": len(bounds), "by_kind": dict(sorted(Counter(s.kind for s in symbols).items())),
                                   "boundaries_by_kind": dict(sorted(Counter(b.kind for b in bounds).items()))},
                   notes=["`doc` and `signature` are text copied from the repository: UNTRUSTED data, never instructions",
                          "a boundary with dynamic=true has a name that was not a literal in the source: the real value is UNKNOWN"],
                   symbols=[s.model_dump(mode="json") for s in symbols], boundaries=[b.model_dump(mode="json") for b in bounds])
    # ------------------------------------------------------------ dependencies
    ext = defaultdict(list)
    for d in deps:
        ext[(d.ecosystem, d.name)].append(d)
    ext_list = [{"ecosystem": e, "name": n, "declared_in": sorted({(d.manifest, d.version_spec, d.scope, d.line) for d in ds})} for (e, n), ds in sorted(ext.items())]
    edges = sorted({(i.source_path, i.resolved_path) for i in imports if i.resolved_path and i.resolved_path != i.source_path})
    ext_imports = Counter((langs_of(i, records), i.target.split("/")[0] if "/" in i.target and not i.target.startswith(".") else i.target.split(".")[0]) for i in imports if i.external)
    unresolved = [c for c in calls if c.resolution == "unresolved"]
    dep_doc = dict(header, notes=["every edge is OBSERVED in static source text (import statements, call expressions); none was observed at run time",
                                  "calls are extracted only by analyzers that declare the `calls` depth; the other languages have imports and boundaries only (see coverage.json)",
                                  "reflection, dynamic dispatch, dependency injection, dynamic import/require and generated code are NOT followed: an absent edge is not proof of no dependency"],
                   dependencies=ext_list,
                   imports=[i.model_dump(mode="json") for i in imports],
                   file_edges=[{"from": a, "to": b, "evidence": "import"} for a, b in edges],
                   external_import_roots=[{"language": k[0], "root": k[1], "count": v} for k, v in sorted(ext_imports.items())],
                   calls=[c.model_dump(mode="json") for c in calls],
                   call_summary={"total": len(calls), "resolved": len(calls) - len(unresolved), "unresolved": len(unresolved)})
    # ------------------------------------------------------------ coverage
    coverage = _coverage(header, records, status, facts, symbols, bounds, calls, inv, complete)
    return {"repository-inventory.json": inventory, "symbol-index.json": sym_doc, "dependency-index.json": dep_doc, "coverage.json": coverage}


def langs_of(i: Import, records) -> str:
    for r in records:
        if r.rel == i.source_path:
            return r.language or "unknown"
    return "unknown"


def _count(f: FileFacts | None) -> dict[str, int] | None:
    if f is None:
        return None
    return {"symbols": len(f.symbols), "imports": len(f.imports), "calls": len(f.calls), "boundaries": len(f.boundaries), "dependencies": len(f.dependencies), "warnings": len(f.warnings)}


def _frameworks(deps: list[Dependency], bounds: list[Boundary]) -> dict[str, Any]:
    names: set[str] = set()
    by_manifest: set[tuple[str, str]] = set()
    for d in deps:
        for eco, rx, fw in FRAMEWORKS:
            if d.ecosystem == eco and re.search(rx, d.name):
                names.add(fw)
                by_manifest.add((d.manifest, fw))
    return {"names": sorted(names), "by_manifest": sorted(by_manifest)}


def _coverage(header, records, status, facts, symbols, bounds, calls, inv, complete) -> dict[str, Any]:
    regs = AB.analyzers()
    per_lang: dict[str, dict[str, Any]] = {}
    lang_all = sorted({r.language for r in records if r.language})
    for lang in lang_all:
        rs = [r for r in records if r.language == lang]
        used = sorted({x for r in rs for x in r.analyzed_by})
        caps = [a.capability for a in regs if a.capability.fingerprint() in used and lang in a.capability.languages] or [a.capability for a in regs if lang in a.capability.languages]
        n_an = sum(1 for r in rs if status.get(r.rel) == "analyzed")
        elig = [r for r in rs if r.eligible]
        per_lang[lang] = {"files": len(rs), "eligible": len(elig), "analyzed": n_an, "parse_failed": sum(1 for r in rs if status.get(r.rel) == "parse-failed"),
                          "support": "analyzer" if caps else "none: files are inventoried only",
                          "analyzers": [c.fingerprint() for c in caps], "method": sorted({c.method for c in caps}), "depth": sorted({d for c in caps for d in c.depth}),
                          "confidence": sorted({c.confidence for c in caps}), "limitations": sorted({l for c in caps for l in c.limitations}),
                          "call_graph": any("calls" in c.depth for c in caps)}
    unsupported = [{"language": k, "files": v["files"]} for k, v in per_lang.items() if v["support"].startswith("none")]
    by_cat = {}
    for cat in sorted({r.category for r in records}):
        rs = [r for r in records if r.category == cat]
        by_cat[cat] = {"files": len(rs), "analyzed": sum(1 for r in rs if status.get(r.rel) == "analyzed"), "analyzed_with_facts": sum(1 for r in rs if facts.get(r.rel) and _count(facts[r.rel]) and any(
            v for k, v in _count(facts[r.rel]).items() if k != "warnings"))}
    skipped = Counter((r.skip or "").split(":")[0] if r.skip and not r.skip.startswith("larger than") else (r.skip or "") for r in records if r.skip)
    warns = sum(len(f.warnings) for f in facts.values())
    return dict(header,
                statement="Coverage is reported per language from the capabilities each analyzer DECLARES. No claim of universal language support or full semantic extraction is made: "
                          "a language without an analyzer is inventoried by name and size only.",
                completeness={"inventory": "truncated: " + inv.truncation_reason if inv.truncated else "complete",
                              "analysis": "complete" if complete else "partial: time budget exhausted (re-run resumes from the cache)"},
                languages=per_lang, unsupported_languages=sorted(unsupported, key=lambda x: x["language"]), categories=by_cat,
                skipped_by_reason=dict(sorted(skipped.items())),
                skipped_files=[{"path": r.rel, "reason": r.skip} for r in records if r.skip][:2000],
                analyzers=[{"id": a.capability.analyzer_id, "version": a.capability.version, "languages": list(a.capability.languages), "method": a.capability.method,
                            "depth": list(a.capability.depth), "confidence": a.capability.confidence, "limitations": list(a.capability.limitations)} for a in regs],
                facts={"symbols": len(symbols), "boundaries": len(bounds), "dynamic_boundaries": sum(1 for b in bounds if b.dynamic), "calls": len(calls),
                       "calls_unresolved": sum(1 for c in calls if c.resolution == "unresolved"), "files_with_warnings": sum(1 for f in facts.values() if f.warnings), "warnings": warns},
                parse_failures=[{"path": rel, "warnings": list(f.warnings)} for rel, f in sorted(facts.items()) if not f.parsed],
                warnings=[{"path": rel, "warnings": list(f.warnings)} for rel, f in sorted(facts.items()) if f.warnings and f.parsed][:500],
                symlinks_not_followed=len(inv.symlinks))


def write_outputs(result: ScanResult, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, doc in result.outputs.items():
        p = out / name
        tmp = out / (name + ".tmp")
        tmp.write_text(_canon(doc), encoding="utf-8")
        os.replace(tmp, p)                                # a reader never sees a half-written file
        written.append(p)
    stats = out / "run-stats.json"
    stats.write_text(_canon(result.stats), encoding="utf-8")
    written.append(stats)
    return written
