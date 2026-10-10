"""Building blocks shared by the document types: a section builder that forces labels and evidence onto every statement, and query helpers over the model."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Iterable

from yuktiforge.docint.docgen.doc import Claim, Gap, Label, Note, Row, Section, Table
from yuktiforge.docint.docgen.spi import GenContext
from yuktiforge.docint.knowledge.schema import Entity

CLS_LABEL: dict[str, Label] = {"verified": "VERIFIED", "inferred": "INFERRED", "user-supplied": "USER_SUPPLIED", "unknown": "UNKNOWN"}
NSV: Label = "NEEDS_STAKEHOLDER_VALIDATION"
SECURITY_NOTE = "source inspection cannot verify security or compliance properties; this is an observation, not an assurance"


def label_of(e: Entity) -> Label:
    return CLS_LABEL[e.cls]


def labels_of(*ents: Entity) -> tuple[Label, ...]:
    order = ["VERIFIED", "INFERRED", "USER_SUPPLIED", "UNKNOWN"]
    present = {label_of(e) for e in ents}
    weakest = next((x for x in reversed(order) if x in present), "UNKNOWN") if present else "UNKNOWN"
    return (weakest,)                                   # a statement is as certain as the weakest thing it rests on


def sha8(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:8]


def esc(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


class SB:
    """Collects the blocks of one section. Every claim and row must be labelled; the facts it rests on are hashed so the section can be regenerated or its review invalidated."""

    def __init__(self, ctx: GenContext, sid: str, title: str, *, audiences: tuple[str, ...] | None = None, depth: str = "summary", version: str = "1"):
        self.ctx, self.sid, self.title, self.audiences, self.depth, self.version = ctx, sid, title, audiences, depth, version
        self.blocks: list = []
        self.gaps: list[Gap] = []
        self._ents: set[str] = set()
        self._evs: set[str] = set()

    def _touch(self, entity_ids: Iterable[str], evidence_ids: Iterable[str]) -> None:
        self._ents.update(entity_ids)
        self._evs.update(evidence_ids)

    def claim(self, text: str, labels: Iterable[Label], *, evidence: Iterable[str] = (), entities: Iterable[str] = (), key: str | None = None, fact: str | None = None) -> None:
        labels, evidence, entities = tuple(labels), tuple(evidence), tuple(entities)
        cid = f"{self.sid}.{sha8(key or text)}"
        self.blocks.append(Claim(id=cid, text=text, labels=labels, evidence_ids=evidence, entity_ids=entities, fact_key=key, fact_value=fact))
        self._touch(entities, evidence)

    def about(self, text: str, e: Entity, *extra: Label, attr: str | None = None, fact: str | None = None) -> None:
        """A statement about one model entity: labelled from the entity's own evidence class, cited from its evidence."""
        self.claim(text, (*labels_of(e), *extra), evidence=e.evidence_ids, entities=(e.id,), key=f"{e.id}|{attr}" if attr else None, fact=fact)

    def note(self, text: str) -> None:
        self.blocks.append(Note(text=text))

    def table(self, tid: str, header: Iterable[str], rows: Iterable[tuple[Iterable[object], Iterable[Label], Iterable[str], Iterable[str]]], caption: str = "") -> None:
        out = []
        for cells, labels, evs, ents in rows:
            cells, labels, evs, ents = tuple(esc(c) for c in cells), tuple(labels), tuple(evs), tuple(ents)
            out.append(Row(cells=cells, labels=labels, evidence_ids=evs, entity_ids=ents, id=f"{self.sid}.{tid}.{sha8(*cells)}"))
            self._touch(ents, evs)
        if out:
            self.blocks.append(Table(id=f"{self.sid}.{tid}", caption=caption, header=tuple(header), rows=tuple(out)))

    def gap(self, code: str, message: str, severity: str = "warning") -> None:
        self.gaps.append(Gap(code=code, message=message, section_id=self.sid, severity=severity))   # type: ignore[arg-type]
        self.blocks.append(Claim(id=f"{self.sid}.gap.{sha8(code, message)}", text=message, labels=("UNKNOWN", NSV)))

    def empty(self, what: str, code: str) -> None:
        self.claim(f"No {what} were found in the analyzed evidence.", ("UNKNOWN",))
        self.gaps.append(Gap(code=code, message=f"no {what}", section_id=self.sid, severity="warning"))

    def build(self) -> Section:
        m = self.ctx.model
        ev = {e.id: e for e in m.evidence}
        ent = {e.id: e for e in m.entities}
        facts = {"v": self.version, "t": self.ctx.template, "a": self.ctx.audience, "d": self.ctx.depth,
                 "entities": {i: (ent[i].model_dump(mode="json", exclude={"evidence_ids"}) if i in ent else None) for i in sorted(self._ents)},
                 "evidence": {i: ((ev[i].path, ev[i].start_line, ev[i].end_line, ev[i].content_sha256, ev[i].cls) if i in ev else None) for i in sorted(self._evs)}}
        h = hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()
        return Section(id=self.sid, title=self.title, blocks=tuple(self.blocks), audiences=self.audiences, depth=self.depth, gaps=tuple(self.gaps), input_hash=h)   # type: ignore[arg-type]


# ----------------------------------------------------------------------------- queries over the model
class Q:
    def __init__(self, ctx: GenContext):
        self.ctx, self.g, self.m = ctx, ctx.graph, ctx.model
        self.ents = self.m.entities
        self.repo = next((e for e in self.ents if e.type == "repository"), None)
        self.repo_ids: tuple[str, ...] = (self.repo.id,) if self.repo else ()
        self.repo_ev: tuple[str, ...] = self.repo.evidence_ids if self.repo else ()
        self._owner: dict[str, str] = {}
        for c in self.ents:
            if c.type == "component":
                stack = [c.id]
                while stack:
                    n = stack.pop()
                    for r in self.g.out.get(n, []):
                        if r.type == "owns" and r.target not in self._owner:
                            self._owner[r.target] = c.id
                            stack.append(r.target)

    def of(self, *types: str, subtype: str | None = None, external: bool | None = None, active: bool = True) -> list[Entity]:
        return sorted((e for e in self.ents if e.type in types and (subtype is None or e.subtype == subtype) and (external is None or e.external == external)
                       and (not active or e.status == "active")), key=lambda e: (e.name, e.id))

    def component_of(self, eid: str) -> Entity | None:
        c = self._owner.get(eid)
        return self.g.ent[c] if c else None

    def comps(self) -> list[Entity]:
        mods = {e.id for e in self.ents if e.type == "module"}
        return [c for c in self.of("component") if any(o == c.id and t in mods for t, o in self._owner.items())]

    def modules_of(self, comp: Entity) -> list[Entity]:
        return sorted((self.g.ent[t] for t, o in self._owner.items() if o == comp.id and self.g.ent[t].type == "module"), key=lambda e: e.name)

    def out(self, eid: str, *types: str) -> list[tuple[str, Entity]]:
        return [(r.type, self.g.ent[r.target]) for r in self.g.out.get(eid, []) if r.type in types and r.target in self.g.ent]

    def inc(self, eid: str, *types: str) -> list[tuple[str, Entity]]:
        return [(r.type, self.g.ent[r.source]) for r in self.g.inc.get(eid, []) if r.type in types and r.source in self.g.ent]

    def handlers(self, api: Entity) -> list[Entity]:
        return [e for t, e in self.inc(api.id, "implements")]

    def touches(self, sym: Entity) -> dict[str, list[Entity]]:
        res: dict[str, list[Entity]] = defaultdict(list)
        for t, e in self.out(sym.id, "reads", "writes", "publishes", "subscribes", "calls"):
            if t == "calls" and not e.external:
                continue
            res[t].append(e)
        return res

    def children(self, eid: str) -> list[Entity]:
        return sorted((e for t, e in self.out(eid, "owns")), key=lambda e: (e.attrs.get("start_line", 0), e.name))

    def fields_of(self, table: Entity) -> list[Entity]:
        return [e for t, e in self.out(table.id, "owns") if e.type == "field"]

    def ev(self, e: Entity) -> tuple[str, ...]:
        return e.evidence_ids

    def cite(self, e: Entity) -> str:
        return ", ".join(self.g.cite(e.evidence_ids)[:2])

    def user_entities(self, *types: str) -> list[Entity]:
        return [e for e in self.of(*types) if e.cls == "user-supplied" or any(self.g.ev[i].cls == "user-supplied" for i in e.evidence_ids if i in self.g.ev)]
