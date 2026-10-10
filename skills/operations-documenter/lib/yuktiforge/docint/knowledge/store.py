"""SQLite metadata + a content-addressed artifact directory. No vector database. The store keeps the whole model as rows (one JSON document per row) so single
entities can be read without loading everything, and applies the MERGE POLICY when a newer scan arrives:

  * source-observed entities/relationships/evidence are REPLACED by the newer scan; ones no longer observed are kept as `retired` (history), not deleted;
  * user-supplied entities (assertions, approvals) are NEVER overwritten or dropped by a scan;
  * a user assertion that disagrees with what the scan now observes (same type and name, different attributes) is kept beside it and recorded as a `user-vs-observed`
    conflict with a `contradicts` relationship: neither side silently wins.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from yuktiforge.docint.knowledge import ids
from yuktiforge.docint.knowledge.build import recorded_time
from yuktiforge.docint.knowledge.schema import APPROVABLE, SCHEMA_VERSION, Conflict, Entity, Evidence, Gap, KnowledgeModel, Relationship
from yuktiforge.errors import YuktiForgeError


def merge(old: KnowledgeModel | None, new: KnowledgeModel) -> tuple[KnowledgeModel, dict[str, int]]:
    stats = {"retired": 0, "kept_user_entities": 0, "kept_user_relationships": 0, "dropped_user_relationships": 0, "new_conflicts": 0}
    if old is None:
        return new, stats
    ev = {e.id: e for e in old.evidence} | {e.id: e for e in new.evidence}
    new_ids = {e.id for e in new.entities}
    ents = {e.id: e for e in new.entities}
    for e in old.entities:
        user = e.cls == "user-supplied" or (e.type in APPROVABLE and any(ev[i].cls == "user-supplied" for i in e.evidence_ids if i in ev))
        if e.id in new_ids and not user:
            continue
        if user:
            ents[e.id] = e
            stats["kept_user_entities"] += 1
        elif e.status != "retired":
            ents[e.id] = e.model_copy(update={"status": "retired"})
            stats["retired"] += 1
        else:
            ents[e.id] = e
    rels = {r.id: r for r in new.relationships}
    for r in old.relationships:
        if r.id in rels:
            continue
        user = r.cls == "user-supplied"
        if user and r.source in ents and r.target in ents:
            rels[r.id] = r
            stats["kept_user_relationships"] += 1
        elif user:
            stats["dropped_user_relationships"] += 1
        elif r.source in ents and r.target in ents and (ents[r.source].status == "retired" or ents[r.target].status == "retired"):
            rels[r.id] = r                                                     # history of a retired entity
    conflicts = {c.id: c for c in new.conflicts}
    for c in old.conflicts:
        if c.kind == "user-vs-observed":
            conflicts[c.id] = c
    for u in [e for e in ents.values() if e.cls == "user-supplied" and e.status == "active"]:
        for o in new.entities:
            if o.type == u.type and o.name.lower() == u.name.lower() and o.cls != "user-supplied" and {k: v for k, v in u.attrs.items() if k in o.attrs and o.attrs[k] != v}:
                cid = "conflict:" + ids.rel_id("uvo", u.id, o.id)
                if cid not in conflicts:
                    diffs = ", ".join(f"{k}: user says {u.attrs[k]!r}, source shows {o.attrs[k]!r}" for k in u.attrs if k in o.attrs and o.attrs[k] != u.attrs[k])
                    conflicts[cid] = Conflict(id=cid, kind="user-vs-observed", detail=f"{u.type} '{u.name}': {diffs}", entity_ids=(u.id, o.id), evidence_ids=tuple(u.evidence_ids[:1] + o.evidence_ids[:1]))
                    stats["new_conflicts"] += 1
                    rid = ids.rel_id("contradicts", u.id, o.id, cid)
                    rels[rid] = Relationship(id=rid, type="contradicts", source=u.id, target=o.id, cls="inferred", evidence_ids=conflicts[cid].evidence_ids)
    merged = new.model_copy(update=dict(entities=tuple(sorted(ents.values(), key=lambda x: x.id)), relationships=tuple(sorted(rels.values(), key=lambda x: x.id)),
                                        evidence=tuple(sorted(ev.values(), key=lambda x: x.id)), conflicts=tuple(sorted(conflicts.values(), key=lambda x: x.id))))
    return merged, stats


class Store:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "artifacts").mkdir(exist_ok=True)
        self.db = sqlite3.connect(str(self.dir / "knowledge.sqlite"))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, cls TEXT NOT NULL, json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS relationships(id TEXT PRIMARY KEY, type TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS extras(k TEXT PRIMARY KEY, json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_rel_src ON relationships(source);
            CREATE INDEX IF NOT EXISTS ix_rel_dst ON relationships(target);
            CREATE INDEX IF NOT EXISTS ix_ent_type ON entities(type, name);
        """)
        row = self.db.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        if row and row[0] != SCHEMA_VERSION:
            raise YuktiForgeError(f"store has schema {row[0]}, this tool writes {SCHEMA_VERSION}: export with the old tool and re-import through `docs model migrate`")
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (SCHEMA_VERSION,))
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    # ------------------------------------------------------------------ whole model
    def load(self) -> KnowledgeModel | None:
        meta = dict(self.db.execute("SELECT k, v FROM meta"))
        if "scan_id" not in meta:
            return None
        extras = {k: json.loads(v) for k, v in self.db.execute("SELECT k, json FROM extras")}
        return KnowledgeModel(scan_id=meta["scan_id"], repository=json.loads(meta["repository"]),
                              entities=tuple(Entity.model_validate_json(j) for (j,) in self.db.execute("SELECT json FROM entities ORDER BY id")),
                              relationships=tuple(Relationship.model_validate_json(j) for (j,) in self.db.execute("SELECT json FROM relationships ORDER BY id")),
                              evidence=tuple(Evidence.model_validate_json(j) for (j,) in self.db.execute("SELECT json FROM evidence ORDER BY id")),
                              gaps=tuple(Gap.model_validate(x) for x in extras.get("gaps", [])),
                              conflicts=tuple(Conflict.model_validate(x) for x in extras.get("conflicts", [])), coverage=extras.get("coverage", {}))

    def save(self, model: KnowledgeModel) -> None:
        with self.db:
            for t in ("entities", "relationships", "evidence", "extras"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.executemany("INSERT INTO entities VALUES(?,?,?,?,?,?)", [(e.id, e.type, e.name, e.status, e.cls, e.model_dump_json()) for e in model.entities])
            self.db.executemany("INSERT INTO relationships VALUES(?,?,?,?,?)", [(r.id, r.type, r.source, r.target, r.model_dump_json()) for r in model.relationships])
            self.db.executemany("INSERT INTO evidence VALUES(?,?)", [(e.id, e.model_dump_json()) for e in model.evidence])
            self.db.executemany("INSERT INTO extras VALUES(?,?)", [("gaps", json.dumps([g.model_dump(mode="json") for g in model.gaps])),
                                                                    ("conflicts", json.dumps([c.model_dump(mode="json") for c in model.conflicts])), ("coverage", json.dumps(model.coverage))])
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('scan_id', ?)", (model.scan_id,))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('repository', ?)", (json.dumps(model.repository),))

    def apply_scan(self, new: KnowledgeModel) -> dict[str, int]:
        merged, stats = merge(self.load(), new)
        self.save(merged)
        return stats

    # ------------------------------------------------------------------ single rows
    def entity(self, eid: str) -> Entity | None:
        r = self.db.execute("SELECT json FROM entities WHERE id=?", (eid,)).fetchone()
        return Entity.model_validate_json(r[0]) if r else None

    def find(self, type_: str | None = None, text: str | None = None, limit: int = 200) -> list[Entity]:
        q, a = "SELECT json FROM entities WHERE 1=1", []
        if type_:
            q += " AND type=?"
            a.append(type_)
        if text:
            q += " AND lower(name) LIKE ?"
            a.append(f"%{text.lower()}%")
        return [Entity.model_validate_json(j) for (j,) in self.db.execute(q + " ORDER BY name LIMIT ?", (*a, limit))]

    # ------------------------------------------------------------------ user assertions (the only way a person adds to the model)
    def assert_entity(self, type_: str, name: str, statement: str, by: str, *, subtype: str = "", source_note: str = "") -> Entity:
        if not by.strip():
            raise YuktiForgeError("a user assertion needs the name of the person who makes it (--by)")
        if not statement.strip():
            raise YuktiForgeError("a user assertion needs a statement")
        m = self.load()
        if m is None:
            raise YuktiForgeError("the store is empty: build a model first")
        evid = Evidence(id=ids.evidence_id(None, None, None, "user", by, statement), cls="user-supplied", method="user", note=f"{by}: {statement}" + (f" (source: {source_note})" if source_note else ""),
                        revision=m.repository.get("revision"), recorded_at=recorded_time())
        ent = Entity(id=ids.make_id(type_, f"user|{name}"), type=type_, name=name, subtype=subtype, cls="user-supplied", attrs={"statement": statement, "asserted_by": by},
                     evidence_ids=(evid.id,), approval="unapproved" if type_ in APPROVABLE else None)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO evidence VALUES(?,?)", (evid.id, evid.model_dump_json()))
            self.db.execute("INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?)", (ent.id, ent.type, ent.name, ent.status, ent.cls, ent.model_dump_json()))
        return ent

    def link(self, from_id: str, to_id: str, by: str, note: str) -> Relationship:
        """A person states that a requirement/rule is implemented by (or traces to) a piece of the model. The link is user-supplied evidence, never verified."""
        if not by.strip() or not note.strip():
            raise YuktiForgeError("a link needs the name of the person making it and a note")
        a, b = self.entity(from_id), self.entity(to_id)
        if a is None or b is None:
            raise YuktiForgeError("both ends of a link must be entities of the model")
        m = self.load()
        evid = Evidence(id=ids.evidence_id(None, None, None, "link", by, from_id + to_id + note), cls="user-supplied", method="user", note=f"{by}: {note}", revision=m.repository.get("revision") if m else None,
                        recorded_at=recorded_time())
        rel = Relationship(id=ids.rel_id("traces-to", from_id, to_id, "user"), type="traces-to", source=from_id, target=to_id, cls="user-supplied", evidence_ids=(evid.id,))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO evidence VALUES(?,?)", (evid.id, evid.model_dump_json()))
            self.db.execute("INSERT OR REPLACE INTO relationships VALUES(?,?,?,?,?)", (rel.id, rel.type, rel.source, rel.target, rel.model_dump_json()))
        return rel

    def approve(self, eid: str, approver: str, note: str) -> Entity:
        """The ONLY way a candidate becomes approved: a named person, a recorded statement. Nothing else calls this."""
        e = self.entity(eid)
        if e is None:
            raise YuktiForgeError(f"no entity {eid}")
        if e.type not in APPROVABLE:
            raise YuktiForgeError(f"{e.type} entities are not approvable")
        if not approver.strip() or not note.strip():
            raise YuktiForgeError("approval needs the approver's name and a note saying what was approved")
        m = self.load()
        evid = Evidence(id=ids.evidence_id(None, None, None, "approval", approver, eid + note), cls="user-supplied", method="user", note=f"approved by {approver}: {note}",
                        revision=m.repository.get("revision") if m else None, recorded_at=recorded_time())
        e2 = e.model_copy(update={"approval": f"approved-by:{approver}", "evidence_ids": (*e.evidence_ids, evid.id)})
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO evidence VALUES(?,?)", (evid.id, evid.model_dump_json()))
            self.db.execute("INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?)", (e2.id, e2.type, e2.name, e2.status, e2.cls, e2.model_dump_json()))
        return e2

    # ------------------------------------------------------------------ artifact store
    def put_artifact(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        p = self.dir / "artifacts" / sha[:2] / sha
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        return sha

    def get_artifact(self, sha: str) -> bytes:
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise YuktiForgeError("artifact id must be a SHA-256 hex digest")
        p = self.dir / "artifacts" / sha[:2] / sha
        data = p.read_bytes() if p.is_file() else None
        if data is None:
            raise YuktiForgeError(f"artifact {sha[:12]} not found")
        if hashlib.sha256(data).hexdigest() != sha:
            raise YuktiForgeError(f"artifact {sha[:12]} is corrupt (hash mismatch)")
        return data
