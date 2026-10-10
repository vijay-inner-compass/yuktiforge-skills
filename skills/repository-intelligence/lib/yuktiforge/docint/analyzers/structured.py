"""Structured non-code files: OpenAPI/Swagger specs, SQL DDL, Dockerfiles, docker-compose, GitHub Actions workflows, .proto, GraphQL schemas, Terraform.
Data parsers only (safe YAML with an alias-bomb pre-check, json, line-oriented recognizers). Nothing in these files is executed or interpolated."""
from __future__ import annotations

import json
import re

import yaml

from yuktiforge.docint.analyzers import sqlutil
from yuktiforge.docint.analyzers.base import Capability, FileAnalyzer, boundary_id, prov, register, split_lines
from yuktiforge.docint.model import Artifact, Boundary, FileFacts, Import, Symbol, clip
from yuktiforge.docint.safety import redact_url

_ANCHOR = re.compile(r"(^|[\s\[{,:-])[&*][A-Za-z0-9_-]+")
MAX_YAML_ALIASES = 50
_VERBS = ("get", "post", "put", "delete", "patch", "head", "options")


def safe_yaml(text: str):
    """yaml.safe_load, after refusing alias-heavy documents ("billion laughs")."""
    if len(_ANCHOR.findall(text)) > MAX_YAML_ALIASES:
        raise ValueError("too many YAML anchors/aliases (possible expansion bomb)")
    return yaml.safe_load(text)


class StructuredAnalyzer(FileAnalyzer):
    def __init__(self):
        self.capability = Capability("structured-files", "1.0", ("openapi", "sql", "docker", "compose", "github-actions", "protobuf", "graphql", "terraform"),
                                     ("*.yaml", "*.yml", "*.json", "*.sql", "Dockerfile", "Dockerfile.*", "*.dockerfile", "docker-compose*.yml", "docker-compose*.yaml", "compose.yml", "compose.yaml",
                                      "*.proto", "*.graphql", "*.gql", "*.tf"),
                                     "structured", ("routes", "db", "containers", "ci", "infra", "schema", "events", "config"), "high",
                                     ("only files recognised by name and shape (OpenAPI, GitHub Actions, docker-compose, Dockerfile, SQL DDL, .proto, GraphQL, Terraform resource blocks) yield facts; other YAML/JSON is ignored",
                                      "SQL: CREATE TABLE/INDEX/VIEW and ALTER TABLE are recognised line-wise; dialect-specific syntax and stored-procedure bodies are not interpreted",
                                      "Terraform: resource/module blocks by name only; expressions, variables and modules are not evaluated",
                                      "YAML anchors/aliases beyond a small bound and DOCTYPE-style constructs are refused"))

    def analyze(self, rel: str, text: str) -> FileFacts:
        name = rel.rsplit("/", 1)[-1]
        low = name.lower()
        cap = self.capability
        lines = split_lines(text)
        syms: list[Symbol] = []
        bnds: list[Boundary] = []
        arts: list[Artifact] = []
        imps: list[Import] = []
        warn: list[str] = []
        parsed = True
        taken: set[str] = set()

        def line_of(needle: str, start: int = 1) -> int:
            for i in range(start - 1, len(lines)):
                if needle in lines[i]:
                    return i + 1
            return 1

        def bnd(kind, nm, ln, framework, end=None, details=None, symbol=None):
            if len(bnds) < 20000:
                bnds.append(Boundary(id=boundary_id(rel, kind, nm, ln), kind=kind, name=clip(nm, 200), framework=framework, symbol=symbol, details=details or {}, prov=prov(rel, ln, end, cap)))

        def sym(q, nm, kind, ln, end=None, sig="", parent=None):
            sid = f"{rel}::{q}" if f"{rel}::{q}" not in taken else f"{rel}::{q}@{ln}"
            taken.add(sid)
            syms.append(Symbol(id=sid, name=clip(nm, 100), qualified_name=q, kind=kind, language="sql" if low.endswith(".sql") else "config", parent=parent, signature=clip(sig), prov=prov(rel, ln, end, cap)))

        def art(kind, detail, ln=1):
            arts.append(Artifact(kind=kind, path=rel, detail=clip(detail), prov=prov(rel, ln, ln, cap)))

        try:
            if low.endswith(".sql"):
                self._sql(text, lines, rel, bnd, sym, art)
            elif low == "dockerfile" or low.startswith("dockerfile.") or low.endswith(".dockerfile"):
                self._docker(lines, bnd, art, imps, cap, rel)
            elif low.endswith((".yaml", ".yml", ".json")):
                data = json.loads(text) if low.endswith(".json") else safe_yaml(text)
                if isinstance(data, dict):
                    if ("openapi" in data or "swagger" in data) and isinstance(data.get("paths"), dict):
                        self._openapi(data, bnd, art, line_of)
                    elif low.startswith(("docker-compose", "compose")) or ("services" in data and isinstance(data.get("services"), dict)):
                        self._compose(data, bnd, art, line_of)
                    elif ".github/workflows/" in rel and isinstance(data.get("jobs"), dict):
                        self._actions(data, bnd, art, line_of)
            elif low.endswith(".proto"):
                self._proto(lines, bnd, sym, art)
            elif low.endswith((".graphql", ".gql")):
                self._graphql(lines, bnd, sym, art)
            elif low.endswith(".tf"):
                self._tf(lines, bnd, art)
        except (ValueError, yaml.YAMLError, RecursionError) as e:
            parsed = False
            warn.append(f"file could not be parsed ({type(e).__name__}: {clip(str(e), 80)}); its content is UNKNOWN, not absent")
        return FileFacts(symbols=tuple(syms), imports=tuple(imps), boundaries=tuple(bnds), artifacts=tuple(arts), warnings=tuple(warn), parsed=parsed)

    # ---------------------------------------------------------------- recognizers
    def _openapi(self, data, bnd, art, line_of):
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        art("api-spec", f"OpenAPI {data.get('openapi') or data.get('swagger')}: {info.get('title', '?')} v{info.get('version', '?')}")
        for path, item in data["paths"].items():
            if isinstance(item, dict):
                for verb in item:
                    if str(verb).lower() in _VERBS:
                        op = item[verb] if isinstance(item[verb], dict) else {}
                        ln = line_of(str(path))
                        bnd("http-route", f"{str(verb).upper()} {path}", ln, "openapi", details={"operationId": str(op.get("operationId", "")), "summary": clip(str(op.get("summary", "")), 100)} if op else {})

    def _compose(self, data, bnd, art, line_of):
        art("container", f"docker compose: {len(data['services'])} services")
        for svc, cfg in data["services"].items():
            cfg = cfg if isinstance(cfg, dict) else {}
            ports = [str(p) for p in (cfg.get("ports") or []) if isinstance(p, (str, int))]
            deps = cfg.get("depends_on") or []
            deps = list(deps) if isinstance(deps, (list, dict)) else []
            bnd("container-service", str(svc), line_of(f"{svc}:"), "docker-compose", details={"image": clip(str(cfg.get("image", cfg.get("build", ""))), 100), "ports": ports[:20],
                                                                                                "depends_on": [str(d) for d in deps][:20]})
            env = cfg.get("environment") or []
            names = list(env.keys()) if isinstance(env, dict) else [str(e).split("=", 1)[0] for e in env if isinstance(e, str)]
            for n_ in names[:100]:
                bnd("config-env", str(n_), line_of(str(n_)), "docker-compose", details={"service": str(svc)})

    def _actions(self, data, bnd, art, line_of):
        art("ci", f"GitHub Actions workflow: {data.get('name', '?')}")
        for job, cfg in data["jobs"].items():
            cfg = cfg if isinstance(cfg, dict) else {}
            steps = [s for s in (cfg.get("steps") or []) if isinstance(s, dict)]
            bnd("ci-job", str(job), line_of(f"{job}:"), "github-actions", details={"runs-on": clip(str(cfg.get("runs-on", "")), 60), "steps": len(steps),
                                                                                    "uses": sorted({str(s["uses"]) for s in steps if "uses" in s})[:20]})

    def _docker(self, lines, bnd, art, imps, cap, rel):
        art("container", "Dockerfile")
        for i, raw in enumerate(lines, 1):
            s = raw.strip()
            m = re.match(r"(?i)^(FROM|EXPOSE|ENTRYPOINT|CMD|ENV|ARG)\s+(.*)$", s)
            if not m:
                continue
            kw, rest = m.group(1).upper(), m.group(2)
            if kw == "FROM":
                img = rest.split()[0] if rest.split() else ""
                bnd("container-service", redact_url(img), i, "dockerfile", details={"stage": "build" if " as " in rest.lower() else "base"})
            elif kw == "EXPOSE":
                bnd("container-service", f"expose {rest.split()[0]}", i, "dockerfile", details={"ports": rest.split()[:10]})
            elif kw in ("ENTRYPOINT", "CMD"):
                bnd("entry-point", f"{kw}: {clip(rest, 100)}", i, "dockerfile")
            elif kw in ("ENV", "ARG"):
                nm = re.split(r"[=\s]", rest, 1)[0]
                if nm:
                    bnd("config-env", nm, i, "dockerfile", details={"declared": kw})

    def _sql(self, text, lines, rel, bnd, sym, art):
        art("db-schema", "SQL script")
        rx = re.compile(r"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:UNIQUE\s+)?(?:TEMP(?:ORARY)?\s+)?(TABLE|VIEW|INDEX|MATERIALIZED\s+VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\".`\[\]]+)")
        for m in rx.finditer(text[:2_000_000]):
            kind = m.group(1).upper().split()[-1]
            nm = sqlutil.clean_ident(m.group(2))
            ln = text.count("\n", 0, m.start()) + 1
            if not nm:                                   # a name that is not a plain identifier (quoted markup, an expression): not recorded rather than recorded empty
                continue
            if kind == "TABLE":
                body_end = text.find(";", m.end())
                end_ln = text.count("\n", 0, body_end if body_end > 0 else m.end()) + 1
                cols, cons = self._cols(text[m.end():body_end if body_end > 0 else m.end() + 4000])
                bnd("db-schema", nm, ln, "sql", end=end_ln, details={"object": "table", "columns": cols[:60], "constraints": cons[:20]})
                sym(nm, nm, "type", ln, end_ln, f"table {nm}")
            else:
                bnd("db-schema", nm, ln, "sql", details={"object": kind.lower()})
        for m in re.finditer(r"(?is)\bALTER\s+TABLE\s+(?:ONLY\s+)?(?:IF\s+EXISTS\s+)?([\w\".`\[\]]+)", text[:2_000_000]):
            bnd("db-schema", sqlutil.clean_ident(m.group(1)), text.count("\n", 0, m.start()) + 1, "sql", details={"object": "alter-table"})

    @staticmethod
    def _cols(body: str) -> tuple[list[str], list[str]]:
        """(column definitions, table-level constraints) of a CREATE TABLE body, as written (clipped). Constraints are quoted, not interpreted."""
        i = body.find("(")
        if i < 0:
            return [], []
        depth, cur, out = 0, "", []
        for ch in body[i:]:
            if ch == "(":
                depth += 1
                if depth == 1:
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            if depth == 1 and ch == ",":
                out.append(cur.strip())
                cur = ""
            else:
                cur += ch
        if cur.strip():
            out.append(cur.strip())
        cols, cons = [], []
        for d in out:
            w = d.split()
            if not w:
                continue
            if w[0].upper() in ("PRIMARY", "FOREIGN", "CONSTRAINT", "UNIQUE", "KEY", "INDEX", "CHECK"):
                cons.append(clip(" ".join(w), 100))
            else:
                cols.append(clip(f"{sqlutil.clean_ident(w[0])} {' '.join(w[1:])}".strip(), 100))
        return cols, cons

    def _proto(self, lines, bnd, sym, art):
        art("api-spec", "Protocol Buffers definition")
        svc = None
        for i, raw in enumerate(lines, 1):
            s = raw.split("//", 1)[0].strip()
            m = re.match(r"^(service|message|enum)\s+(\w+)", s)
            if m:
                kind = {"service": "interface", "message": "type", "enum": "enum"}[m.group(1)]
                sym(m.group(2), m.group(2), kind, i, sig=s)
                svc = m.group(2) if m.group(1) == "service" else None
                if svc:
                    bnd("grpc-service", svc, i, "grpc")
            r = re.match(r"^rpc\s+(\w+)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(stream\s+)?([\w.]+)\s*\)", s)
            if r and svc:
                bnd("grpc-service", f"{svc}.{r.group(1)}", i, "grpc", details={"request": r.group(3), "response": r.group(5)})

    def _graphql(self, lines, bnd, sym, art):
        art("api-spec", "GraphQL schema")
        cur = None
        for i, raw in enumerate(lines, 1):
            s = raw.split("#", 1)[0].strip()
            m = re.match(r"^(?:extend\s+)?type\s+(Query|Mutation|Subscription)\b", s)
            if m:
                cur = m.group(1)
                continue
            if re.match(r"^(?:extend\s+)?(type|input|enum|interface|union|scalar)\s+(\w+)", s):
                mm = re.match(r"^(?:extend\s+)?(type|input|enum|interface|union|scalar)\s+(\w+)", s)
                sym(mm.group(2), mm.group(2), "enum" if mm.group(1) == "enum" else "type", i, sig=s)
                cur = None
                continue
            if s.startswith("}"):
                cur = None
            elif cur:
                f = re.match(r"^(\w+)\s*[\(:]", s)
                if f:
                    bnd("graphql-operation", f"{cur}.{f.group(1)}", i, "graphql")

    def _tf(self, lines, bnd, art):
        art("iac", "Terraform configuration")
        for i, raw in enumerate(lines, 1):
            m = re.match(r'^\s*resource\s+"([\w-]+)"\s+"([\w-]+)"', raw)
            if m:
                bnd("infra-resource", f"{m.group(1)}.{m.group(2)}", i, "terraform", details={"type": m.group(1)})
            m = re.match(r'^\s*module\s+"([\w-]+)"', raw)
            if m:
                bnd("infra-resource", f"module.{m.group(1)}", i, "terraform", details={"type": "module"})


register(StructuredAnalyzer())
