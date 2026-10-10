"""Bounded, non-executing repository walk."""
from __future__ import annotations

import os
from pathlib import Path

from yuktiforge.errors import YuktiForgeError
from yuktiforge.visualizer.analyzers.base import RepoFile, RepoScan
from yuktiforge.visualizer.analyzers.languages import SKIP_DIRS, language_of

MAX_FILES = 20_000
MAX_FILE_BYTES = 1_000_000


def scan_repo(root: str | Path) -> RepoScan:
    r = Path(root).resolve()
    if not r.is_dir():
        raise YuktiForgeError(f"not a directory: {root}")
    scan = RepoScan(root=r, files=[])
    for dirpath, dirnames, filenames in os.walk(r, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not (Path(dirpath) / d).is_symlink())
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.is_symlink() or not p.is_file():
                continue
            size = p.stat().st_size
            if len(scan.files) >= MAX_FILES:
                scan.truncated = True
                return scan
            if size > MAX_FILE_BYTES:
                scan.skipped_large += 1
                continue
            scan.files.append(RepoFile(p.relative_to(r).as_posix(), p, language_of(fn), size))
    return scan
