"""Fact model of the repository scan (D1). Every fact carries provenance: relative path, line range, the analyzer that produced it, how it
was extracted and how much to trust it. Free text copied from source (comments, docstrings) is marked untrusted: it is data, never instructions."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCAN_FORMAT = "yuktiforge-repository-scan/1"
Method = Literal["ast", "lexical", "structured", "manifest", "pattern", "path"]
Confidence = Literal["high", "medium", "low"]
SymbolKind = Literal["module", "namespace", "class", "interface", "enum", "struct", "record", "trait", "function", "method", "constructor", "property", "type", "field", "variable"]
BoundaryKind = Literal["http-route", "http-client", "db-table", "db-query", "db-schema", "event-publish", "event-subscribe", "grpc-service", "graphql-operation",
                       "config-env", "container-service", "ci-job", "infra-resource", "entry-point"]


class _F(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Provenance(_F):
    path: str                          # POSIX, relative to the repository root, never absolute
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    analyzer: str
    method: Method
    confidence: Confidence


class Symbol(_F):
    id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    language: str
    parent: str | None = None          # qualified name of the enclosing symbol
    signature: str = ""                # one line, truncated
    modifiers: tuple[str, ...] = ()    # public, static, async, abstract ...
    annotations: tuple[str, ...] = ()  # decorators / annotations / attributes, names only
    bases: tuple[str, ...] = ()        # extends / implements / base classes as written
    doc: str = ""                      # first line of the doc comment: UNTRUSTED text
    prov: Provenance


class Import(_F):
    source_path: str
    line: int
    target: str                        # module / package / path as written
    names: tuple[str, ...] = ()
    kind: Literal["import", "using", "using-static", "require", "dynamic-import", "re-export", "include", "from"] = "import"
    resolved_path: str | None = None   # repository file this import points at, when it does
    external: bool = False             # points outside the repository (third-party or standard library)
    prov: Provenance


class Call(_F):
    source_path: str
    line: int
    caller: str | None                 # qualified name of the enclosing function/method
    callee_text: str                   # as written, e.g. "self.repo.save" or "requests.get"
    resolved: str | None = None        # symbol id when resolved
    resolution: Literal["same-file", "import", "unresolved"] = "unresolved"
    receiver_type: str | None = None   # the class the receiver was assigned from (`x = Cls()`), as written; a hint for resolution, never a proof
    prov: Provenance


class Boundary(_F):
    id: str
    kind: BoundaryKind
    name: str                          # "GET /patients/{id}", a table, a topic, an env var name ...
    framework: str = "unknown"
    symbol: str | None = None          # enclosing symbol, qualified name
    details: dict[str, str | int | bool | list[str]] = Field(default_factory=dict)
    dynamic: bool = False              # the name was not a literal (a variable or an expression), so it is UNKNOWN
    prov: Provenance


class Dependency(_F):
    ecosystem: str                     # the package ecosystem as the manifest analyzer names it
    name: str
    version_spec: str = ""
    scope: Literal["runtime", "dev", "test", "build", "optional", "unknown"] = "unknown"
    manifest: str
    line: int = 1
    prov: Provenance


class Artifact(_F):
    """A non-code thing the inventory found: a manifest, config, CI file, DB schema, doc, test, container or IaC file."""
    kind: Literal["manifest", "config", "ci", "container", "iac", "db-schema", "api-spec", "doc", "test", "lockfile", "entry-point", "script", "other"]
    path: str
    detail: str = ""
    prov: Provenance


class FileFacts(_F):
    """Everything one analyzer found in one file. Serialisable so it can be cached by content hash."""
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[Import, ...] = ()
    calls: tuple[Call, ...] = ()
    boundaries: tuple[Boundary, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    warnings: tuple[str, ...] = ()     # anything that limited the analysis of this file
    parsed: bool = True                # False: the file could not be parsed, so its content is UNKNOWN, not absent


def clip(text: str, n: int = 160) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"
