"""The scan and query commands (D1). Kept apart from `cli.py` so the shipped repository-intelligence skill can use them without pulling in the later stages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from yuktiforge.docint import safety as S
from yuktiforge.docint.query import query as run_query
from yuktiforge.docint.scan import ScanConfig, scan, write_outputs
from yuktiforge.errors import YuktiForgeError


def cmd_docs_scan(a: argparse.Namespace) -> int:
    repo = Path(a.repo)
    if not repo.is_dir():
        raise YuktiForgeError(f"--repo is not a directory: {a.repo}")
    out = Path(a.out)
    if out.exists() and not out.is_dir():
        raise YuktiForgeError(f"--out exists and is not a directory: {a.out}")
    limits = S.Limits(max_file_bytes=a.max_file_bytes, max_files=a.max_files)
    try:
        res = scan(ScanConfig(repo=repo, out=out, cache=Path(a.cache) if a.cache else None, limits=limits, include_generated=a.include_generated,
                              max_seconds=a.max_seconds, use_cache=not a.no_cache))
    except (ValueError, OSError) as e:
        raise YuktiForgeError(str(e)) from e
    written = write_outputs(res, out)
    inv, cov, sym = res.outputs["repository-inventory.json"], res.outputs["coverage.json"], res.outputs["symbol-index.json"]
    print(f"scanned {inv['totals']['files']} files ({inv['totals']['analyzed']} analyzed) in repository '{inv['repository']['name']}' "
          f"revision {inv['repository']['revision'] or 'unknown'}   scan_id {inv['scan_id']}")
    print(f"languages : " + (", ".join(f"{k}={v['files']}" for k, v in inv["languages"].items()) or "none"))
    print(f"frameworks: " + (", ".join(inv["frameworks"]) or "none detected") + f"   build systems: " + (", ".join(inv["build_systems"]) or "none detected"))
    print(f"facts     : {sym['counts']['symbols']} symbols, {sym['counts']['boundaries']} boundaries, calls {cov['facts']['calls']} ({cov['facts']['calls_unresolved']} unresolved)")
    if cov["unsupported_languages"]:
        print("NO ANALYZER (inventoried only): " + ", ".join(f"{u['language']}={u['files']}" for u in cov["unsupported_languages"]))
    if cov["parse_failures"]:
        print(f"PARSE FAILURES: {len(cov['parse_failures'])} file(s) (content UNKNOWN); see coverage.json")
    print(f"incremental: analyzed {res.stats['files_analyzed']}, reused {res.stats['files_reused_from_cache']}"
          + ("  (resumed after an interrupted run)" if res.stats["resumed_after_interruption"] else ""))
    print(f"completeness: inventory {cov['completeness']['inventory']}; analysis {cov['completeness']['analysis']}")
    for p in written:
        print(f"  wrote {p}")
    return 0


def cmd_docs_query(a: argparse.Namespace) -> int:
    print(json.dumps(run_query(Path(a.scan), boundary=a.boundary, symbol=a.symbol, file=a.file, coverage=a.coverage, unresolved=a.unresolved), indent=1, ensure_ascii=True))
    return 0
