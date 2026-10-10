"""Filesystem artifact storage. Content-hashed; confined to the run directory."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath

from yuktiforge.errors import ArtifactPathError


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
            raise ArtifactPathError(f"bad run id {run_id!r}")
        return self.root / run_id

    def _resolve(self, run_id: str, rel: str) -> Path:
        pp = PurePosixPath(rel)
        if not rel or pp.is_absolute() or ".." in pp.parts or "\\" in rel or "\0" in rel:
            raise ArtifactPathError(f"unsafe artifact path {rel!r}")
        base = self.run_dir(run_id)
        target = base / pp
        # Reject any symlink component, then confirm containment after resolution.
        cur = base
        for part in pp.parts:
            cur = cur / part
            if cur.is_symlink():
                raise ArtifactPathError(f"symlink in artifact path {rel!r}")
        resolved = target.resolve()
        if base.resolve() not in resolved.parents:
            raise ArtifactPathError(f"artifact path escapes run dir: {rel!r}")
        return target

    def write(self, run_id: str, rel: str, data: bytes) -> tuple[Path, str]:
        path = self._resolve(run_id, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return path, hashlib.sha256(data).hexdigest()

    def read(self, run_id: str, rel: str) -> bytes:
        return self._resolve(run_id, rel).read_bytes()

    def verify(self, run_id: str, rel: str, sha256: str) -> bool:
        try:
            return hashlib.sha256(self.read(run_id, rel)).hexdigest() == sha256
        except OSError:
            return False
