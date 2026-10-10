"""Local SQLite run metadata."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from yuktiforge.errors import YuktiForgeError
from yuktiforge.state.machine import DEFAULT_MAX_REPAIRS, Stage, status_for, validate_transition
from yuktiforge.store.artifacts import ArtifactStore

SCHEMA_VERSION = 1
_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
  repairs INTEGER NOT NULL DEFAULT 0, max_repairs INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
  from_stage TEXT, to_stage TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
  stage TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, at TEXT NOT NULL,
  UNIQUE(run_id, path));
CREATE TABLE IF NOT EXISTS dependency_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
  package TEXT NOT NULL, version_spec TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected')),
  reviewer TEXT, at TEXT NOT NULL, UNIQUE(run_id, package, version_spec));
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    """Owns the SQLite DB and the artifact directory under `home` (default `<project>/.yuktiforge`)."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.db_path = self.home / "yuktiforge.db"
        self.artifacts = ArtifactStore(self.home / "runs")
        with self._conn() as c:
            c.executescript(_DDL)
            c.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _tx(self):
        return _Tx(self._conn())

    # -- runs -------------------------------------------------------------
    def create_run(self, skill_id: str, max_repairs: int = DEFAULT_MAX_REPAIRS) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = _now()
        with self._tx() as c:
            c.execute("INSERT INTO runs VALUES (?,?,?,?,0,?,?,?)",
                      (run_id, skill_id, Stage.DISCOVER.value, "active", max_repairs, now, now))
            c.execute("INSERT INTO transitions (run_id, from_stage, to_stage, note, at) VALUES (?,?,?,?,?)",
                      (run_id, None, Stage.DISCOVER.value, "run created", now))
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any]:
        with closing(self._conn()) as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise YuktiForgeError(f"no such run: {run_id}")
        return dict(row)

    def list_runs(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY created_at, id")]

    def advance(self, run_id: str, target: Stage, note: str = "") -> dict[str, Any]:
        """Validate and apply a transition atomically (check and write in one transaction)."""
        target = Stage(target)
        with self._tx() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise YuktiForgeError(f"no such run: {run_id}")
            validate_transition(Stage(row["stage"]), target, repairs_done=row["repairs"],
                                max_repairs=row["max_repairs"])
            now = _now()
            repairs = row["repairs"] + (1 if target is Stage.REPAIR else 0)
            c.execute("UPDATE runs SET stage=?, status=?, repairs=?, updated_at=? WHERE id=?",
                      (target.value, status_for(target).value, repairs, now, run_id))
            c.execute("INSERT INTO transitions (run_id, from_stage, to_stage, note, at) VALUES (?,?,?,?,?)",
                      (run_id, row["stage"], target.value, note, now))
        return self.get_run(run_id)

    def history(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute(
                "SELECT from_stage, to_stage, note, at FROM transitions WHERE run_id=? ORDER BY id", (run_id,))]

    # -- artifacts --------------------------------------------------------
    def put_artifact(self, run_id: str, stage: Stage, rel_path: str, data: bytes) -> dict[str, Any]:
        self.get_run(run_id)
        path, digest = self.artifacts.write(run_id, rel_path, data)
        with self._tx() as c:
            c.execute("INSERT INTO artifacts (run_id, stage, path, sha256, size, at) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(run_id, path) DO UPDATE SET stage=excluded.stage, sha256=excluded.sha256, "
                      "size=excluded.size, at=excluded.at",
                      (run_id, Stage(stage).value, rel_path, digest, len(data), _now()))
        return {"path": str(path), "sha256": digest, "size": len(data)}

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute("SELECT * FROM artifacts WHERE run_id=? ORDER BY id", (run_id,))]

    # -- dependency review (see security.policy) -------------------------
    def request_dependency(self, run_id: str, package: str, version_spec: str) -> None:
        self.get_run(run_id)
        with self._tx() as c:
            c.execute("INSERT OR IGNORE INTO dependency_reviews (run_id, package, version_spec, status, at) "
                      "VALUES (?,?,?,'pending',?)", (run_id, package, version_spec, _now()))

    def review_dependency(self, run_id: str, package: str, version_spec: str, approve: bool, reviewer: str) -> None:
        if not reviewer.strip():
            raise YuktiForgeError("reviewer is required")
        with self._tx() as c:
            cur = c.execute("UPDATE dependency_reviews SET status=?, reviewer=?, at=? "
                            "WHERE run_id=? AND package=? AND version_spec=?",
                            ("approved" if approve else "rejected", reviewer, _now(), run_id, package, version_spec))
            if cur.rowcount != 1:
                raise YuktiForgeError("no such dependency request")

    def dependency_status(self, run_id: str, package: str, version_spec: str) -> str | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT status FROM dependency_reviews WHERE run_id=? AND package=? AND version_spec=?",
                            (run_id, package, version_spec)).fetchone()
        return row["status"] if row else None

    def dump(self, run_id: str) -> str:
        return json.dumps({"run": self.get_run(run_id), "history": self.history(run_id),
                           "artifacts": self.list_artifacts(run_id)}, indent=2)


class _Tx:
    """Commit on success, rollback on error, always close (sqlite3's own CM does not close)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, *_):
        try:
            self.conn.rollback() if exc_type else self.conn.commit()
        finally:
            self.conn.close()
