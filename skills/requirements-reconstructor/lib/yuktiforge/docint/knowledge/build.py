"""Build the System Knowledge Model from a finished D1 scan.

Rules that keep it honest:
  * everything taken straight from the scan is `verified` (it is written in a file) with the extraction confidence recorded; a LOW-confidence pattern is `inferred`;
  * anything produced by a rule that goes beyond the text (grouping, proximity such as "this Dockerfile belongs to that component") is `inferred` and says why;
  * a name that was not a literal is NOT turned into an entity: it becomes a gap;
  * nothing here creates a requirement, business rule or approval.
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from yuktiforge.docint.knowledge import ids
from yuktiforge.docint.knowledge.schema import CLASS_RANK, Conflict, Entity, Evidence, Gap, KnowledgeModel, Relationship
from yuktiforge.docint.query import load

WRITE_OPS = {"INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "CREATE", "ALTER", "DROP"}
SOURCE_CATEGORIES = ("source", "test")
SYMBOL_TYPE = {"interface": "interface"}


def weakest(classes: list[str]) -> str:
    return min(classes, key=lambda c: CLASS_RANK[c]) if classes else "unknown"


def recorded_time() -> str | None:
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde and sde.isdigit():
        return datetime.fromtimestamp(int(sde), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


class Builder:
    def __init__(self, scan_dir: Path, repo: Path | None):
        self.inv = load(scan_dir, "repository-inventory.json")
        self.sym = load(scan_dir, "symbol-index.json")
        self.dep = load(scan_dir, "dependency-index.json")
        self.cov = load(scan_dir, "coverage.json")
        self.repo = Path(repo) if repo else None
        self.revision = self.inv["repository"].get("revision")
        self.at = recorded_time()
        self.E: dict[str, dict[str, Any]] = {}
        self.R: dict[str, dict[str, Any]] = {}
        self.V: dict[str, Evidence] = {}
        self.gaps: list[Gap] = []
        self.conflicts: list[Conflict] = []
        self._lines: dict[str, list[str] | None] = {}
        roots = sorted({p["root"] for p in self.inv["projects"]} | {"."}, key=lambda r: (-len(r), r))      # "." always exists: files outside every project still belong somewhere
        self.roots = roots
        self.sym_by_key: dict[tuple[str, str], str] = {}       # (path, qualified) -> entity id
        self.module_of: dict[str, str] = {}                    # path -> module entity id
        self.comp_of_root: dict[str, str] = {}

    # ------------------------------------------------------------------ evidence
    def _file_lines(self, path: str) -> list[str] | None:
        if self.repo is None:
            return None
        if path not in self._lines:
            p = self.repo / path
            try:
                self._lines[path] = p.read_text(encoding="utf-8", errors="replace").split("\n") if p.is_file() and not p.is_symlink() else None
            except OSError:
                self._lines[path] = None
        return self._lines[path]

    def ev(self, prov: dict | None, *, cls: str | None = None, note: str = "", method: str | None = None) -> str:
        if prov is None:
            e = Evidence(id=ids.evidence_id(None, None, None, "rule", method or "rule", note), cls=cls or "inferred", method=method or "rule", note=note, revision=self.revision, recorded_at=self.at)
        else:
            low = prov["confidence"] == "low"
            klass = cls or ("inferred" if low else "verified")
            n = note or ("low-confidence pattern match: the text suggests it but does not prove it" if low and klass == "inferred" else "")
            sha = None
            ls = self._file_lines(prov["path"])
            if ls is not None:
                sha = hashlib.sha256("\n".join(ls[prov["start_line"] - 1:prov["end_line"]]).encode("utf-8", "replace")).hexdigest()
            e = Evidence(id=ids.evidence_id(prov["path"], prov["start_line"], prov["end_line"], prov["analyzer"], prov["method"], n), cls=klass, path=prov["path"],
                         start_line=prov["start_line"], end_line=prov["end_line"], revision=self.revision, method=prov["method"], analyzer=prov["analyzer"],
                         extraction_confidence=prov["confidence"], content_sha256=sha, note=n, recorded_at=self.at)
        self.V.setdefault(e.id, e)
        return e.id

    # ------------------------------------------------------------------ entities / relationships
    def entity(self, type_: str, key: str, name: str, ev_ids: list[str], *, subtype: str = "", external: bool = False, **attrs) -> str:
        eid = ids.make_id(type_, key)
        cur = self.E.get(eid)
        if cur is None:
            cur = {"id": eid, "type": type_, "name": name[:200], "subtype": subtype, "external": external, "attrs": {}, "evidence_ids": []}
            self.E[eid] = cur
        for e in ev_ids:
            if e not in cur["evidence_ids"]:
                cur["evidence_ids"].append(e)
        for k, v in attrs.items():
            if v is None:
                continue
            old = cur["attrs"].get(k)
            if isinstance(v, list) and isinstance(old, list):
                cur["attrs"][k] = sorted(set(old) | set(v))
            elif old is None or old == v:
                cur["attrs"][k] = v
            elif isinstance(v, list):
                cur["attrs"][k] = v
        return eid

    def rel(self, type_: str, src: str, dst: str, ev_ids: list[str], disc: str = "", **attrs) -> str | None:
        if src == dst and type_ != "calls":
            return None
        rid = ids.rel_id(type_, src, dst, disc)
        cur = self.R.get(rid)
        if cur is None:
            cur = {"id": rid, "type": type_, "source": src, "target": dst, "attrs": dict(attrs), "evidence_ids": []}
            self.R[rid] = cur
        for e in ev_ids:
            if e not in cur["evidence_ids"]:
                cur["evidence_ids"].append(e)
        return rid

    def comp_root(self, path: str) -> str:
        for r in self.roots:
            if r == "." or path == r or path.startswith(r + "/"):
                return r
        return "."

    # ------------------------------------------------------------------ build steps
    def build(self) -> KnowledgeModel:
        name = self.inv["repository"]["name"]
        repo_ev = self.ev(None, cls="verified", note="repository scanned by yuktiforge docs scan", method="scan")
        self.repo_id = self.entity("repository", name, name, [repo_ev], revision=self.revision or "unknown", scan_id=self.inv["scan_id"])
        self._components()
        self._modules_and_symbols()
        self._boundaries()
        self._imports_and_calls()
        self._technology()
        self._gaps()
        self._conflicts()
        return self._finish()

    def _components(self) -> None:
        projects = {p["root"]: p for p in self.inv["projects"]}
        for root in self.roots:
            p = projects.get(root)
            manifest = p["manifests"][0] if p else None
            if p:
                ev = self.ev({"path": manifest, "start_line": 1, "end_line": 1, "analyzer": "inventory", "method": "path", "confidence": "high"}, cls="verified")
            else:
                ev = self.ev(None, cls="inferred", note="files outside every project (no manifest of their own) are grouped under the repository root", method="rule")
            cname = (self.inv["repository"]["name"] if root == "." else root)
            cid = self.entity("component", root, cname, [ev], subtype="project" if p else "repository-level", root=root,
                              ecosystems=(p or {}).get("ecosystems", []), languages=(p or {}).get("languages", []), frameworks=(p or {}).get("frameworks", []))
            self.comp_of_root[root] = cid
            self.rel("owns", self.repo_id, cid, [ev])

    def _modules_and_symbols(self) -> None:
        analysed = {f["path"]: f for f in self.inv["files"] if f["status"] == "analyzed" and f["category"] in SOURCE_CATEGORIES}
        for path, f in sorted(analysed.items()):
            ev = self.ev({"path": path, "start_line": 1, "end_line": 1, "analyzer": "inventory", "method": "path", "confidence": "high"}, cls="verified")
            mid = self.entity("module", path, path, [ev], subtype=f["category"], language=f["language"] or "", sha256=f["sha256"] or "")
            self.module_of[path] = mid
            self.rel("owns", self.comp_of_root[self.comp_root(path)], mid, [ev])
        for s in self.sym["symbols"]:
            p = s["prov"]
            if s["kind"] == "module":
                continue
            ev = self.ev(p)
            type_ = SYMBOL_TYPE.get(s["kind"], "field" if s["kind"] == "field" else "symbol")
            sid = self.entity(type_, s["id"], s["qualified_name"], [ev], subtype=s["kind"], language=s["language"], path=p["path"], start_line=p["start_line"], end_line=p["end_line"],
                              annotations=list(s["annotations"]), bases=list(s["bases"]), modifiers=list(s["modifiers"]))
            self.sym_by_key.setdefault((p["path"], s["qualified_name"]), sid)
        for s in self.sym["symbols"]:
            if s["kind"] == "module":
                continue
            p = s["prov"]
            sid = self.sym_by_key[(p["path"], s["qualified_name"])]
            ev = self.E[sid]["evidence_ids"][0]
            parent = self.sym_by_key.get((p["path"], s["parent"])) if s.get("parent") else None
            owner = parent or self.module_of.get(p["path"])
            if owner:
                self.rel("owns", owner, sid, [ev])
            for b in s["bases"]:
                tgt = self._find_type(b.split("<", 1)[0].rsplit(".", 1)[-1])
                if tgt and tgt != sid:
                    self.rel("derived-from", sid, tgt, [ev], disc="base", role="extends/implements")

    def _find_type(self, simple: str) -> str | None:
        hits = [e["id"] for e in self.E.values() if e["type"] in ("symbol", "interface") and e["subtype"] in ("class", "interface", "struct", "record") and e["name"].rsplit(".", 1)[-1] == simple]
        return hits[0] if len(hits) == 1 else None          # ambiguous or external base types are not guessed

    def _owner(self, b: dict) -> str | None:
        p = b["prov"]["path"]
        return self.sym_by_key.get((p, b["symbol"])) if b.get("symbol") else self.module_of.get(p)

    def _boundaries(self) -> None:
        routes_by_key: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        spec_routes: list[tuple[str, str, dict]] = []
        for b in self.sym["boundaries"]:
            kind, p = b["kind"], b["prov"]
            ev = self.ev(p)
            owner = self._owner(b)
            comp = self.comp_root(p["path"])
            if b["dynamic"] and kind in ("http-route", "http-client", "event-publish", "event-subscribe", "db-table", "db-query"):
                self.gaps.append(Gap(id="gap:" + ids.rel_id("dyn", b["id"], ""), kind="dynamic-name", detail=f"{kind} '{b['name']}' at {p['path']}:{p['start_line']} is not a literal in the source: its real value is UNKNOWN",
                                     entity_ids=(owner,) if owner else (), evidence_ids=(ev,)))
                continue
            if kind == "http-route":
                method, _, path = b["name"].partition(" ")
                key = f"{comp}|{method}|{ids.norm_route(path)}"
                if b["framework"] == "openapi":
                    aid = self.entity("api", "spec|" + key, b["name"], [ev], subtype="spec", method=method, path=path, source="openapi")
                    spec_routes.append((aid, f"{method}|{ids.norm_route(path)}", b))
                else:
                    aid = self.entity("api", key, b["name"], [ev], subtype="route", method=method, path=path, framework=b["framework"], component=comp)
                    routes_by_key[f"{comp}|{method}|{ids.norm_route(path)}"].append((aid, b))
                    if owner:
                        self.rel("implements", owner, aid, [ev], role="handler")
                    self.rel("owns", self.comp_of_root[comp], aid, [ev])
            elif kind in ("grpc-service", "graphql-operation"):
                aid = self.entity("api", f"{kind}|{comp}|{b['name']}", b["name"], [ev], subtype=kind.split("-")[0], framework=b["framework"], component=comp)
                self.rel("owns", self.comp_of_root[comp], aid, [ev])
                if owner and p["path"] not in ("",):
                    pass
            elif kind == "http-client":
                verb, _, url = b["name"].partition(" ")
                target = re.sub(r"\?.*$", "", url)
                aid = self.entity("api", f"ext|{verb}|{target}", b["name"], [ev], subtype="client-target", external=True, method=verb, url=target)
                if owner:
                    self.rel("calls", owner, aid, [ev], role="http-client", framework=b["framework"])
            elif kind in ("event-publish", "event-subscribe"):
                evid = self.entity("event", b["name"], b["name"], [ev], subtype="topic-or-queue", framework=b["framework"])
                if owner:
                    self.rel("publishes" if kind == "event-publish" else "subscribes", owner, evid, [ev])
            elif kind == "db-table":
                tid = self.entity("database_entity", b["name"].lower(), b["name"], [ev], subtype="table", mapped_as=b["framework"])
                cls_sym = owner
                if cls_sym and self.E[cls_sym]["type"] in ("symbol", "interface") and self.E[cls_sym]["subtype"] in ("class", "interface", "struct", "record"):
                    self.rel("implements", cls_sym, tid, [ev], role="orm-mapping")
            elif kind == "db-schema":
                obj = b["details"].get("object", "table")
                tid = self.entity("database_entity", b["name"].lower(), b["name"], [ev], subtype=obj, defined_in=p["path"], constraints=list(b["details"].get("constraints", []) or []))
                for col in b["details"].get("columns", []) or []:
                    cname, _, cdef = col.partition(" ")
                    fid = self.entity("field", f"{b['name'].lower()}.{cname.lower()}", f"{b['name']}.{cname}", [ev], subtype="column", datatype=cdef.split(" ", 1)[0] if cdef else "", definition=cdef)
                    self.rel("owns", tid, fid, [ev])
            elif kind == "db-query":
                op = b["details"].get("operation", "")
                for t in b["details"].get("tables", []) or []:
                    tid = self.entity("database_entity", t.lower(), t, [ev], subtype="table")
                    if owner:
                        self.rel("writes" if op in WRITE_OPS else "reads", owner, tid, [ev], disc=op, operation=op)
            elif kind == "config-env":
                tid = self.entity("technology", f"env|{b['name']}", b["name"], [ev], subtype="config-variable")
                if owner:
                    self.rel("reads", owner, tid, [ev], access=str(b["details"].get("access", "")))
            elif kind in ("container-service", "ci-job", "infra-resource"):
                sub = {"container-service": "container", "ci-job": "ci-job", "infra-resource": "infrastructure"}[kind]
                did = self.entity("deployment_boundary", f"{kind}|{p['path']}|{b['name']}", b["name"], [ev], subtype=sub, defined_in=p["path"], framework=b["framework"])
                if kind == "container-service":
                    c = self.comp_root(p["path"])
                    iev = self.ev(None, cls="inferred", method="rule", note=f"{p['path']} lies under component '{c}' (path proximity); it is not proven that this container runs that component")
                    self.rel("deploys-to", self.comp_of_root[c], did, [iev], disc="proximity")
                    for root in self.roots:                                             # compose service named like a component
                        if root != "." and b["name"] == posixpath.basename(root) and p["path"].rsplit("/", 1)[-1].startswith(("docker-compose", "compose")):
                            nev = self.ev(None, cls="inferred", method="rule", note=f"compose service '{b['name']}' has the same name as component '{root}' (name match)")
                            self.rel("deploys-to", self.comp_of_root[root], did, [nev], disc="name")
            elif kind == "entry-point":
                if owner and self.E[owner]["type"] in ("symbol", "module"):
                    self.E[owner]["attrs"]["entry_point"] = True
                    if ev not in self.E[owner]["evidence_ids"]:
                        self.E[owner]["evidence_ids"].append(ev)
        for aid, nk, b in spec_routes:
            matches = [(cid, cb) for k, v in routes_by_key.items() for cid, cb in v if k.split("|", 1)[1] == nk]
            if matches:
                for cid, cb in matches:
                    tev = self.ev(None, cls="inferred", method="rule", note="same HTTP method and normalised path in the OpenAPI document and in code; the match is by name, not by proven link")
                    self.rel("traces-to", aid, cid, [tev])
            else:
                self.gaps.append(Gap(id="gap:" + ids.rel_id("spec-only", aid, ""), kind="spec-only-route", detail=f"{b['name']} is documented in {b['prov']['path']} but no implementing route was found in analyzed code",
                                     entity_ids=(aid,), evidence_ids=tuple(self.E[aid]["evidence_ids"])))
        spec_keys = {nk for _, nk, _ in spec_routes}
        if spec_routes:
            for k, v in routes_by_key.items():
                if k.split("|", 1)[1] not in spec_keys:
                    for cid, cb in v:
                        self.gaps.append(Gap(id="gap:" + ids.rel_id("code-only", cid, ""), kind="code-only-route", detail=f"{cb['name']} exists in code ({cb['prov']['path']}) but is not in any OpenAPI document found",
                                             entity_ids=(cid,), evidence_ids=tuple(self.E[cid]["evidence_ids"])))
        self._dup_routes = {k: v for k, v in routes_by_key.items() if len({b["symbol"] or b["prov"]["path"] for _, b in v}) > 1}

    def _imports_and_calls(self) -> None:
        seen: set[tuple[str, str]] = set()
        for i in self.dep["imports"]:
            tgt = i.get("resolved_path")
            if not tgt or tgt == i["source_path"]:
                continue
            s, d = self.module_of.get(i["source_path"]), self.module_of.get(tgt)
            if s and d and (s, d) not in seen:
                seen.add((s, d))
                self.rel("imports", s, d, [self.ev(i["prov"])])
        unresolved: Counter[str] = Counter()
        by_id = {s["id"]: s for s in self.sym["symbols"]}
        for c in self.dep["calls"]:
            caller = self.sym_by_key.get((c["source_path"], c["caller"])) if c.get("caller") else self.module_of.get(c["source_path"])
            if c["resolution"] == "unresolved":
                if caller:
                    unresolved[caller] += 1
                continue
            s = by_id.get(c["resolved"])
            if not s or not caller:
                continue
            callee = self.sym_by_key.get((s["prov"]["path"], s["qualified_name"]))
            if callee:
                self.rel("calls", caller, callee, [self.ev(c["prov"])], disc=c["resolution"], resolution=c["resolution"])
        for sid, n in unresolved.items():
            self.E[sid]["attrs"]["unresolved_calls"] = n
        self.unresolved_total = sum(unresolved.values())

    def _technology(self) -> None:
        for d in self.dep["dependencies"]:
            for manifest, ver, scope, line in d["declared_in"]:
                ev = self.ev({"path": manifest, "start_line": line, "end_line": line, "analyzer": "manifest-parsers@1.0", "method": "manifest", "confidence": "high"})
                tid = self.entity("technology", f"dep|{d['ecosystem']}|{d['name']}", d["name"], [ev], subtype="dependency", ecosystem=d["ecosystem"], declared_version=ver, scope=scope)
                self.rel("owns", self.comp_of_root[self.comp_root(manifest)], tid, [ev], disc="dependency", role="declares-dependency")
        for fw in self.inv["frameworks"]:
            ev = self.ev(None, cls="inferred", method="rule", note="inferred from declared dependencies (a framework used without being declared is not named)")
            self.entity("technology", f"framework|{fw}", fw, [ev], subtype="framework")

    def _gaps(self) -> None:
        cov = self.cov
        for u in cov["unsupported_languages"]:
            self.gaps.append(Gap(id="gap:" + ids.rel_id("lang", u["language"], ""), kind="unsupported-language", detail=f"{u['files']} {u['language']} file(s) were inventoried but have NO analyzer: nothing is known about their content"))
        for f in cov["parse_failures"]:
            self.gaps.append(Gap(id="gap:" + ids.rel_id("parse", f["path"], ""), kind="parse-failure", detail=f"{f['path']} could not be parsed: its content is UNKNOWN, not absent",
                                 entity_ids=(self.module_of[f["path"]],) if f["path"] in self.module_of else ()))
        if self.unresolved_total:
            self.gaps.append(Gap(id="gap:unresolved-calls", kind="unresolved-calls", detail=f"{self.unresolved_total} call(s) could not be tied to a symbol; a request path through them may continue beyond what the model shows "
                                                                                             "(see attrs.unresolved_calls on each symbol)"))
        no_graph = sorted(k for k, v in cov["languages"].items() if not v["call_graph"] and v["analyzed"])
        if no_graph:
            self.gaps.append(Gap(id="gap:no-call-graph", kind="no-call-graph", detail="no call graph for: " + ", ".join(no_graph) + "; calls between their symbols are unknown (imports and boundary patterns only)"))
        if cov["completeness"]["analysis"] != "complete" or cov["completeness"]["inventory"] != "complete":
            self.gaps.append(Gap(id="gap:partial", kind="partial-analysis", detail=f"scan is incomplete: inventory {cov['completeness']['inventory']}; analysis {cov['completeness']['analysis']}"))

    def _conflicts(self) -> None:
        for k, v in sorted(self._dup_routes.items()):
            aids = tuple(sorted({a for a, _ in v}))
            handlers = sorted({(b["symbol"] or b["prov"]["path"]) for _, b in v})
            self.conflicts.append(Conflict(id="conflict:" + ids.rel_id("dup", k, ""), kind="duplicate-route", detail=f"route {k.split('|', 1)[1].replace('|', ' ')} is declared by more than one handler: {', '.join(handlers)}",
                                           entity_ids=aids, evidence_ids=tuple(e for a in aids for e in self.E[a]["evidence_ids"])))
        schemas: dict[str, list[dict]] = defaultdict(list)
        for b in self.sym["boundaries"]:
            if b["kind"] == "db-schema" and b["details"].get("object") == "table":
                schemas[b["name"].lower()].append(b)
        for t, bs in sorted(schemas.items()):
            if len(bs) > 1 and len({tuple(x["details"].get("columns", [])) for x in bs}) > 1:
                tid = ids.make_id("database_entity", t)
                self.conflicts.append(Conflict(id="conflict:" + ids.rel_id("schema", t, ""), kind="schema-mismatch",
                                               detail=f"table {t} is created with different columns in: " + ", ".join(sorted(f"{x['prov']['path']}:{x['prov']['start_line']}" for x in bs)),
                                               entity_ids=(tid,), evidence_ids=tuple(self.E[tid]["evidence_ids"])))

    def _finish(self) -> KnowledgeModel:
        for c in self.conflicts:                                           # a conflict is also a typed relationship between the involved entities
            if len(c.entity_ids) >= 2:
                for a, b in zip(c.entity_ids, c.entity_ids[1:]):
                    self.rel("contradicts", a, b, list(c.evidence_ids[:2]), disc=c.id)
        entities = []
        for e in self.E.values():
            cls = weakest([self.V[i].cls for i in e["evidence_ids"]])
            entities.append(Entity(id=e["id"], type=e["type"], name=e["name"], subtype=e["subtype"], cls=cls, external=e["external"], attrs=e["attrs"], evidence_ids=tuple(e["evidence_ids"]),
                                   approval="unapproved" if e["type"] in ("requirement_candidate", "business_rule_candidate", "decision") else None))
        rels = [Relationship(id=r["id"], type=r["type"], source=r["source"], target=r["target"], cls=weakest([self.V[i].cls for i in r["evidence_ids"]]), attrs=r["attrs"],
                             evidence_ids=tuple(r["evidence_ids"])) for r in self.R.values()]
        cov = {"languages": {k: {"files": v["files"], "analyzed": v["analyzed"], "support": v["support"], "call_graph": v["call_graph"]} for k, v in self.cov["languages"].items()},
               "completeness": self.cov["completeness"], "unsupported_languages": self.cov["unsupported_languages"]}
        return KnowledgeModel(scan_id=self.inv["scan_id"], repository={"name": self.inv["repository"]["name"], "revision": self.revision}, entities=tuple(sorted(entities, key=lambda x: x.id)),
                              relationships=tuple(sorted(rels, key=lambda x: x.id)), evidence=tuple(sorted(self.V.values(), key=lambda x: x.id)), gaps=tuple(sorted(self.gaps, key=lambda x: x.id)),
                              conflicts=tuple(sorted(self.conflicts, key=lambda x: x.id)), coverage=cov)


def build_model(scan_dir: Path, repo: Path | None = None) -> KnowledgeModel:
    return Builder(Path(scan_dir), repo).build()
