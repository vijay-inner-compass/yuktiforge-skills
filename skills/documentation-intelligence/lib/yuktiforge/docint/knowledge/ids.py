"""Deterministic identifiers: the same fact in the same repository always gets the same id, on any machine and in any run order.
`<type>:<readable slug>-<8 hex of sha1(type | canonical key)>`; the canonical key per type is fixed here and documented in docs/documentation-intelligence.md."""
from __future__ import annotations

import hashlib
import re

_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str, n: int = 40) -> str:
    s = _SLUG.sub("-", text.lower()).strip("-")
    return (s[:n].strip("-")) or "x"


def make_id(kind: str, key: str) -> str:
    return f"{kind}:{slug(key.rsplit('::', 1)[-1] if kind in ('symbol', 'interface', 'field') else key)}-{hashlib.sha1(f'{kind}|{key}'.encode()).hexdigest()[:8]}"


def evidence_id(path: str | None, start: int | None, end: int | None, analyzer: str, method: str, note: str = "") -> str:
    return "ev:" + hashlib.sha1(f"{path}|{start}|{end}|{analyzer}|{method}|{note}".encode()).hexdigest()[:12]


def rel_id(kind: str, source: str, target: str, discriminator: str = "") -> str:
    return "rel:" + hashlib.sha1(f"{kind}|{source}|{target}|{discriminator}".encode()).hexdigest()[:12]


_PARAM = re.compile(r"\{[^}/]*\}|:[A-Za-z_]\w*|<[^>/]*>")


def norm_route(path: str) -> str:
    """`/orders/{id}`, `/orders/:id` and `/orders/<int:id>` are the same route."""
    p = _PARAM.sub("{}", path.strip())
    p = re.sub(r"/+", "/", p)
    return (p.rstrip("/") or "/")
