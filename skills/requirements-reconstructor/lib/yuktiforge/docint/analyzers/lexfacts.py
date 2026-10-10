"""Machinery shared by the lexical (token-based) language analyzers: a context object that collects facts, annotation/attribute parsing,
call-pattern iteration and innermost-symbol lookup. Lexical analysis is pattern-level: confidence is `medium` for declarations and
`low`/`medium` for patterns, and every analyzer says so in its Capability."""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from yuktiforge.docint.analyzers import sqlutil
from yuktiforge.docint.analyzers.base import Capability, boundary_id, doc_line, prov, sym_id
from yuktiforge.docint.analyzers.lexer import Tok, lex
from yuktiforge.docint.model import Boundary, FileFacts, Import, Symbol, clip
from yuktiforge.docint.safety import redact_url


@dataclass
class Ann:
    name: str                          # last segment, e.g. GetMapping
    pos: list[str]                     # string literals passed positionally, in order
    kv: dict[str, list[str]]           # name = "x" / name: "x" / name = {"a","b"}
    line: int
    end: int

    def first(self, *keys: str) -> str | None:
        for k in keys:
            if self.kv.get(k):
                return self.kv[k][0]
        return self.pos[0] if self.pos else None


@dataclass
class Call:
    chain: list[str]                   # receiver chain + name, e.g. ["restTemplate", "getForObject"]
    lp: int                            # index of '('
    rp: int
    line: int
    end: int

    @property
    def name(self) -> str:
        return self.chain[-1]

    @property
    def receiver(self) -> str:
        return ".".join(self.chain[:-1])


class Ctx:
    def __init__(self, rel: str, text: str, lang: str, cap: Capability):
        self.rel, self.lang, self.cap = rel, lang, cap
        self.toks, self.match, self.truncated = lex(text, lang)
        self.symbols: list[Symbol] = []
        self.imports: list[Import] = []
        self.boundaries: list[Boundary] = []
        self.warnings: list[str] = []
        self.taken: set[str] = set()
        self.class_anns: dict[str, list] = {}
        self._sym_lines: list[tuple[int, int, str]] = []       # (start, end, qualified) for innermost lookup
        self.n_lines = (self.toks[-1].end if self.toks else 1)
        if self.truncated:
            self.warnings.append("file is very large: only the first tokens were analyzed")

    # ------------------------------------------------------------------ symbols
    def add_symbol(self, qualified: str, name: str, kind: str, start: int, end: int, *, parent: str | None, signature: str = "", modifiers=(), annotations=(), bases=(),
                   doc: str = "") -> str:
        sid = sym_id(self.rel, qualified, kind, start, self.taken)
        self.symbols.append(Symbol(id=sid, name=name, qualified_name=qualified, kind=kind, language=self.lang, parent=parent, signature=clip(signature), modifiers=tuple(modifiers),
                                   annotations=tuple(annotations), bases=tuple(bases), doc=doc_line(doc) if doc else "", prov=prov(self.rel, start, end, self.cap)))
        if kind not in ("module",):
            self._sym_lines.append((start, end, qualified))
        return qualified

    def enclosing(self, line: int) -> str | None:
        best, span = None, 10**9
        for s, e, q in self._sym_lines:
            if s <= line <= e and (e - s) < span and q.count(".") >= 0:
                best, span = q, e - s
        return best

    def add_import(self, line: int, target: str, names=(), kind="import", end: int | None = None) -> None:
        self.imports.append(Import(source_path=self.rel, line=line, target=target, names=tuple(names), kind=kind, prov=prov(self.rel, line, end, self.cap)))

    def bnd(self, kind: str, name: str, line: int, end: int | None = None, *, framework: str = "unknown", symbol: str | None = None, details=None, dynamic: bool = False,
            method: str | None = None, confidence: str | None = None) -> None:
        if len(self.boundaries) > 20_000:
            return
        self.boundaries.append(Boundary(id=boundary_id(self.rel, kind, name, line), kind=kind, name=clip(name, 200), framework=framework, symbol=symbol or self.enclosing(line),
                                        details=details or {}, dynamic=dynamic,
                                        prov=prov(self.rel, line, end, self.cap, **({"method": method} if method else {}), **({"confidence": confidence} if confidence else {}))))

    def facts(self) -> FileFacts:
        return FileFacts(symbols=tuple(self.symbols), imports=tuple(self.imports), boundaries=tuple(self.boundaries), warnings=tuple(self.warnings))

    # ------------------------------------------------------------------ token helpers
    def t(self, i: int) -> Tok | None:
        return self.toks[i] if 0 <= i < len(self.toks) else None

    def is_(self, i: int, val: str) -> bool:
        t = self.t(i)
        return t is not None and t.kind in ("id", "punct") and t.val == val

    def skip_group(self, i: int) -> int:
        """Index just after the bracket group starting at i (or i+1 when unmatched)."""
        j = self.match.get(i)
        return (j + 1) if j is not None and j > i else i + 1

    def skip_generics(self, i: int) -> int:
        """If toks[i] is '<', index after the matching '>' (token-level angle matching; tolerant)."""
        if not self.is_(i, "<"):
            return i
        depth, j = 0, i
        while j < len(self.toks):
            v = self.toks[j].val if self.toks[j].kind == "punct" else ""
            if v == "<":
                depth += 1
            elif v == ">":
                depth -= 1
                if depth == 0:
                    return j + 1
            elif v in (";", "{", "}") or (v == "(" and False):
                return i + 1
            j += 1
        return i + 1

    def dotted_at(self, i: int) -> tuple[str, int]:
        """`a.b.c` starting at i -> ('a.b.c', next index)."""
        parts = []
        while self.t(i) is not None and self.toks[i].kind == "id":
            parts.append(self.toks[i].val)
            if self.is_(i + 1, ".") and self.t(i + 2) is not None and self.toks[i + 2].kind == "id":
                i += 2
            else:
                i += 1
                break
        return ".".join(parts), i

    def strings_in(self, lo: int, hi: int) -> list[str]:
        return [t.val for t in self.toks[lo:hi] if t.kind == "str"]

    def parse_args_ann(self, name: str, lp: int, line: int) -> tuple[Ann, int]:
        """Annotation/attribute argument list at toks[lp] == '(' -> (Ann, index after ')')."""
        rp = self.match.get(lp, lp)
        pos: list[str] = []
        kv: dict[str, list[str]] = {}
        j = lp + 1
        depth_key: str | None = None
        while j < rp:
            t = self.toks[j]
            if t.kind == "id" and (self.is_(j + 1, "=") or self.is_(j + 1, ":")) and not self.is_(j + 1, "=>"):
                depth_key = t.val
                j += 2
                continue
            if t.kind == "str":
                (kv.setdefault(depth_key, []) if depth_key else pos).append(t.val)
            elif t.kind == "punct" and t.val == ",":
                if self.is_(j, ",") and not (depth_key and self._in_array(lp, j)):
                    depth_key = None
            j += 1
        return Ann(name, pos, kv, line, self.toks[rp].end if rp < len(self.toks) else line), rp + 1

    def _in_array(self, lp: int, j: int) -> bool:
        # inside {...} or [...] within the argument list
        k = j
        while k > lp:
            if self.toks[k].kind == "punct" and self.toks[k].val in ("}", "]"):
                return False
            if self.toks[k].kind == "punct" and self.toks[k].val in ("{", "["):
                return True
            k -= 1
        return False

    def calls(self) -> list[Call]:
        """Every `a.b.c(` pattern with its argument range."""
        out = []
        toks = self.toks
        for i, t in enumerate(toks):
            if t.kind == "punct" and t.val == "(" and i > 0 and toks[i - 1].kind == "id":
                j = i - 1
                chain = [toks[j].val]
                while j >= 2 and toks[j - 1].kind == "punct" and toks[j - 1].val in (".", "?.", "::") and toks[j - 2].kind == "id":
                    chain.append(toks[j - 2].val)
                    j -= 2
                rp = self.match.get(i, i)
                out.append(Call(list(reversed(chain)), i, rp, toks[i - 1].line, toks[min(rp, len(toks) - 1)].end))
        return out

    def first_str(self, c: Call) -> tuple[str | None, bool]:
        """(literal, dynamic) for the first argument."""
        t = self.t(c.lp + 1)
        if t is None or c.rp <= c.lp + 1:
            return None, False
        if t.kind == "str" and not t.interp:
            nxt = self.t(c.lp + 2)
            if nxt is not None and c.lp + 2 < c.rp and not (nxt.kind == "punct" and nxt.val == ","):
                return t.val, True                 # a literal prefix of a longer expression: the full value is UNKNOWN
            return t.val, False
        return None, True

    def kw_str(self, c: Call, *keys: str) -> str | None:
        j = c.lp + 1
        while j < c.rp:
            t = self.toks[j]
            if t.kind == "id" and t.val in keys and (self.is_(j + 1, ":") or self.is_(j + 1, "=")):
                v = self.t(j + 2)
                if v is not None and v.kind == "str":
                    return v.val
            j += 1
        return None

    def sql_literals(self) -> None:
        for t in self.toks:
            if t.kind == "str" and not t.interp and sqlutil.looks_like_sql(t.val):
                tables = sqlutil.sql_tables(t.val)
                op = sqlutil.sql_operation(t.val)
                self.bnd("db-query", f"{op} {','.join(tables) or '?'}", t.line, t.end, framework="sql", details={"operation": op, "tables": tables, "statement": clip(t.val, 120)},
                         method="pattern", confidence="medium")


def url_name(verb: str, url: str | None, dyn: bool) -> str:
    if not url:
        return f"{verb} <dynamic>"
    return f"{verb} {redact_url(url)}" + ("…<dynamic>" if dyn else "")
