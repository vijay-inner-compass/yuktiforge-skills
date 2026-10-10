"""Incremental fact cache keyed by (content hash, analyzer fingerprints, config hash). A file whose content, analyzers and settings are unchanged is
never re-analyzed; an interrupted scan resumes from what was already committed. SQLite (standard library), no timestamps (output stays deterministic)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from yuktiforge.docint.model import SCAN_FORMAT, FileFacts

SCHEMA = 1


def config_hash(**cfg) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


class FactCache:
    def __init__(self, path: Path | None):
        self.path = path
        self._mem: dict[str, tuple[str, str, str]] = {}
        self._db: sqlite3.Connection | None = None
        self._pending = 0
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path))
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
            self._db.execute("CREATE TABLE IF NOT EXISTS facts(rel TEXT PRIMARY KEY, sha TEXT NOT NULL, key TEXT NOT NULL, json TEXT NOT NULL)")
            row = self._db.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
            if row is None or row[0] != f"{SCHEMA}/{SCAN_FORMAT}":
                self._db.execute("DELETE FROM facts")
                self._db.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (f"{SCHEMA}/{SCAN_FORMAT}",))
            self._db.commit()

    def previous_run_complete(self) -> bool | None:
        if self._db is None:
            return None
        row = self._db.execute("SELECT v FROM meta WHERE k='run'").fetchone()
        return None if row is None else row[0] == "complete"

    def start_run(self) -> None:
        self._set("run", "running")

    def finish_run(self) -> None:
        self.flush()
        self._set("run", "complete")

    def _set(self, k: str, v: str) -> None:
        if self._db is not None:
            self._db.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (k, v))
            self._db.commit()

    def get(self, rel: str, sha: str, key: str) -> FileFacts | None:
        if self._db is None:
            hit = self._mem.get(rel)
            row = hit if hit and hit[0] == sha and hit[1] == key else None
            return FileFacts.model_validate_json(row[2]) if row else None
        row = self._db.execute("SELECT sha, key, json FROM facts WHERE rel=?", (rel,)).fetchone()
        if row and row[0] == sha and row[1] == key:
            try:
                return FileFacts.model_validate_json(row[2])
            except ValueError:
                return None                   # a damaged or older-format row is re-analyzed, never trusted
        return None

    def put(self, rel: str, sha: str, key: str, facts: FileFacts) -> None:
        blob = facts.model_dump_json()
        if self._db is None:
            self._mem[rel] = (sha, key, blob)
            return
        self._db.execute("INSERT OR REPLACE INTO facts VALUES(?,?,?,?)", (rel, sha, key, blob))
        self._pending += 1
        if self._pending >= 200:
            self.flush()

    def flush(self) -> None:
        if self._db is not None:
            self._db.commit()
            self._pending = 0

    def prune(self, keep: set[str]) -> int:
        """Forget files that no longer exist in the repository."""
        if self._db is None:
            gone = [r for r in self._mem if r not in keep]
            for r in gone:
                del self._mem[r]
            return len(gone)
        gone = [r for (r,) in self._db.execute("SELECT rel FROM facts") if r not in keep]
        self._db.executemany("DELETE FROM facts WHERE rel=?", [(r,) for r in gone])
        self._db.commit()
        return len(gone)

    def close(self) -> None:
        if self._db is not None:
            self.flush()
            self._db.close()
            self._db = None
