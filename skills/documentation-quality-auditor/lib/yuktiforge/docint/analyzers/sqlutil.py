"""Table names and operation from an SQL string. Pattern-based, deliberately conservative: it reports only what the text literally names."""
from __future__ import annotations

import re

_IDENT = r"[`\"\[]?[A-Za-z_][\w$]*(?:[`\"\]]?\s*\.\s*[`\"\[]?[A-Za-z_][\w$]*)*[`\"\]]?"
SQL_START = re.compile(r"^\s*(select|insert\s+into|insert\s+or\s+\w+\s+into|update|delete\s+from|create\s+(?:or\s+replace\s+)?(?:temporary\s+)?(?:table|view|index|unique\s+index|procedure|function|trigger)|alter\s+table|drop\s+(?:table|view|index)|truncate\s+table|merge\s+into|with\s+\w+\s+as|exec(?:ute)?\s+\w+)\b", re.I)
_TABLE_AFTER = re.compile(r"\b(?:from|join|into|update|table|truncate\s+table|merge\s+into)\s+(?:if\s+(?:not\s+)?exists\s+)?(" + _IDENT + r")", re.I)
_SQL_WORDS = {"select", "set", "values", "where", "as", "on", "using", "lateral", "unnest", "dual", "inserted", "deleted"}      # `order`/`group` stay: `FROM Order o` is a common entity name


def clean_ident(x: str) -> str:
    return re.sub(r"[`\"\[\]\s]", "", x)


def sql_tables(sql: str) -> list[str]:
    out: list[str] = []
    for m in _TABLE_AFTER.finditer(sql[:20_000]):
        t = clean_ident(m.group(1))
        if t and t.lower() not in _SQL_WORDS and not t.startswith(("(", "@", "#", ":")) and t not in out:
            out.append(t)
    return out


def sql_operation(sql: str) -> str:
    m = SQL_START.match(sql)
    if not m:
        return "unknown"
    w = m.group(1).lower().split()
    return {"insert": "INSERT", "update": "UPDATE", "delete": "DELETE", "select": "SELECT", "with": "SELECT", "alter": "ALTER", "drop": "DROP", "truncate": "TRUNCATE",
            "merge": "MERGE", "exec": "EXEC", "execute": "EXEC", "create": "CREATE"}.get(w[0], w[0].upper())


def looks_like_sql(s: str) -> bool:
    return len(s) >= 12 and bool(SQL_START.match(s)) and (" " in s.strip()) and bool(re.search(r"\b(from|into|table|set|values|where|join|view|index|procedure|function|trigger|as)\b", s, re.I))
