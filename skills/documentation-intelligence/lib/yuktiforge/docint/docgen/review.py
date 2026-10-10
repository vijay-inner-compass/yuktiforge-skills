"""Human review workflow. A review decision belongs to a NAMED person and is bound to the exact content of the section it was made on: if the section changes, the decision is
stale and the section is back to draft. A reconstruction (BRD/SRS...) that every section has approved is still not an approved business requirement; the status says exactly what was approved."""
from __future__ import annotations

import json
from pathlib import Path

from yuktiforge.docint.docgen.doc import Document
from yuktiforge.docint.knowledge.build import recorded_time
from yuktiforge.errors import YuktiForgeError

STATES = ("draft", "in-review", "changes-requested", "approved")
ReviewDb = dict[str, dict[str, dict]]


def load(path: Path) -> ReviewDb:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else {}
    except (OSError, ValueError) as e:
        raise YuktiForgeError(f"cannot read review file {path}: {e}") from e


def save(db: ReviewDb, path: Path) -> None:
    Path(path).write_text(json.dumps(db, indent=1, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _section(doc: Document, sid: str):
    for s in doc.sections:
        if s.id == sid:
            return s
    raise YuktiForgeError(f"document {doc.doc_id} has no section '{sid}'")


def submit(db: ReviewDb, doc: Document, section_ids: list[str] | None, by: str) -> list[str]:
    if not by.strip():
        raise YuktiForgeError("submitting for review needs the submitter's name")
    done = []
    for s in doc.sections:
        if section_ids and s.id not in section_ids:
            continue
        db.setdefault(doc.doc_id, {})[s.id] = {"state": "in-review", "by": by, "note": "", "content_hash": s.content_hash(), "at": recorded_time()}
        done.append(s.id)
    if not done:
        raise YuktiForgeError("no such section to submit")
    return done


def decide(db: ReviewDb, doc: Document, section_id: str, state: str, by: str, note: str) -> dict:
    if state not in ("approved", "changes-requested"):
        raise YuktiForgeError("a decision is 'approved' or 'changes-requested'")
    if not by.strip() or not note.strip():
        raise YuktiForgeError("a review decision needs the reviewer's name and a note")
    s = _section(doc, section_id)
    cur = db.get(doc.doc_id, {}).get(section_id)
    if cur is None or cur["state"] not in ("in-review", "approved", "changes-requested"):
        raise YuktiForgeError("the section was not submitted for review")
    if cur.get("content_hash") not in (None, s.content_hash()):
        raise YuktiForgeError("the section changed after it was submitted: submit the new version for review")
    rec = {"state": state, "by": by, "note": note, "content_hash": s.content_hash(), "at": recorded_time()}
    db[doc.doc_id][section_id] = rec
    return rec


def section_state(doc: Document, db: ReviewDb, sid: str) -> tuple[str, bool]:
    """(state, stale). A decision made on different content is stale and counts as draft."""
    rec = db.get(doc.doc_id, {}).get(sid)
    if rec is None:
        return "draft", False
    s = _section(doc, sid)
    if rec.get("content_hash") != s.content_hash():
        return "draft", True
    return rec["state"], False


def effective_status(doc: Document, db: ReviewDb) -> str:
    states = {s.id: section_state(doc, db, s.id) for s in doc.sections}
    n = len(states)
    approved = [k for k, (st, stale) in states.items() if st == "approved"]
    stale = [k for k, (st, sl) in states.items() if sl]
    base = doc.status
    if n and len(approved) == n:
        who = sorted({db[doc.doc_id][k]["by"] for k in approved})
        if doc.reconstruction:
            return f"REVIEWED: every section approved by {', '.join(who)} as an accurate description of the CURRENT IMPLEMENTATION. This is NOT an approved business requirement."
        return f"REVIEWED: every section approved by {', '.join(who)}"
    return f"{base}; review: {len(approved)}/{n} sections approved" + (f", {len(stale)} stale (changed since review)" if stale else "")
