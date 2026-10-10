"""A small lexer for C-family languages (Java, C#, Go, TypeScript/JavaScript). It is NOT a parser: it removes comments, keeps string literals as
single tokens (so braces and keywords inside strings and comments cannot confuse structure), tracks exact line numbers and matches brackets.
Doc comments are kept (attached to the next token) as UNTRUSTED text."""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r'''
  (?P<nl>\n) | (?P<ws>[ \t\r\f\v]+) |
  (?P<dcom>///[^\n]*|/\*\*(?!/).*?\*/) |
  (?P<lcom>//[^\n]*) |
  (?P<bcom>/\*.*?\*/) |
  (?P<pp>^[ \t]*\#[^\n]*) |
  (?P<tstr>"""(?:.|\n)*?""") |
  (?P<vstr>@"(?:[^"]|"")*") |
  (?P<istr>\$@?"(?:[^"\\\n]|\\.)*") |
  (?P<str>"(?:[^"\\\n]|\\.)*") |
  (?P<chr>'(?:[^'\\\n]|\\.)*') |
  (?P<tpl>`(?:[^`\\]|\\.)*`) |
  (?P<num>\d[\w.]*) |
  (?P<id>[^\W\d][\w$]*) |
  (?P<punct>=>|->|::|\?\.|\?\?|\.\.\.|[{}()\[\];,.<>=!&|+\-*/%^~?:@\#]) |
  (?P<other>.)
''', re.X | re.S | re.M)
_REGEX_PREV_ID = frozenset({"return", "typeof", "case", "in", "of", "void", "delete", "throw", "new", "else", "do", "yield", "await"})
_OPEN, _CLOSE = "{([", "})]"
MAX_TOKENS = 400_000


@dataclass(slots=True)
class Tok:
    kind: str      # id num str punct regex other
    val: str       # for str: the literal's CONTENT (no quotes)
    line: int
    end: int       # last line of the token
    doc: str = ""  # first line of the doc comment immediately before this token (untrusted)
    interp: bool = False


def _doc_first_line(raw: str) -> str:
    if raw.startswith("///"):
        return raw[3:].strip().lstrip("<summary>").strip()
    body = raw[3:-2] if raw.endswith("*/") else raw[3:]
    for ln in body.splitlines():
        t = ln.strip().lstrip("*").strip()
        if t and not t.startswith("@") and not t.startswith("<"):
            return t
    return ""


def lex(text: str, lang: str) -> tuple[list[Tok], dict[int, int], bool]:
    """(tokens, bracket matches by token index, truncated)."""
    toks: list[Tok] = []
    line = 1
    pending_doc = ""
    prev_sig: Tok | None = None
    pos, n = 0, len(text)
    truncated = False
    while pos < n:
        if len(toks) >= MAX_TOKENS:
            truncated = True
            break
        m = _TOKEN.match(text, pos)
        if m is None:           # cannot happen (`other` matches any char) but never loop forever
            pos += 1
            continue
        kind, val = m.lastgroup, m.group()
        start_line = line
        line += val.count("\n")
        pos = m.end()
        if kind in ("nl", "ws", "lcom", "bcom", "pp"):
            if kind == "pp" and lang != "csharp":
                toks.append(Tok("punct", "#", start_line, start_line))      # '#' is meaningful elsewhere (Go: none; JS: private fields)
            continue
        if kind == "dcom":
            d = _doc_first_line(val)
            pending_doc = d if d else pending_doc
            continue
        if kind in ("str", "chr", "tpl", "tstr", "vstr", "istr"):
            if kind == "tstr":
                content = val[3:-3]
            elif kind == "vstr":
                content = val[2:-1].replace('""', '"')
            elif kind == "istr":
                content = val[2:-1] if val.startswith("$@") else val[2:-1]
            elif kind == "tpl":
                content = val[1:-1]
            else:
                content = val[1:-1]
            t = Tok("str", content, start_line, line, pending_doc, interp=(kind == "istr") or (kind == "tpl" and "${" in content))
        elif kind == "punct" and val == "/" and lang in ("typescript", "javascript") and (
                prev_sig is None or (prev_sig.kind == "punct" and prev_sig.val not in (")", "]", "}")) or (prev_sig.kind == "id" and prev_sig.val in _REGEX_PREV_ID)):
            j, in_class, ok = pos, False, False
            while j < n and text[j] != "\n":
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    ok = True
                    break
                j += 1
            if ok:
                j += 1
                while j < n and (text[j].isalpha()):
                    j += 1
                t = Tok("regex", text[pos:j], start_line, start_line, pending_doc)
                pos = j
            else:
                t = Tok("punct", val, start_line, line, pending_doc)
        else:
            t = Tok("id" if kind == "id" else kind, val, start_line, line, pending_doc)
        pending_doc = ""
        toks.append(t)
        prev_sig = t
    match: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    for i, t in enumerate(toks):
        if t.kind == "punct" and len(t.val) == 1:
            if t.val in _OPEN:
                stack.append((t.val, i))
            elif t.val in _CLOSE:
                want = _OPEN[_CLOSE.index(t.val)]
                while stack and stack[-1][0] != want:
                    stack.pop()                       # tolerate unbalanced brackets in broken files
                if stack:
                    j = stack.pop()[1]
                    match[j], match[i] = i, j
    return toks, match, truncated
