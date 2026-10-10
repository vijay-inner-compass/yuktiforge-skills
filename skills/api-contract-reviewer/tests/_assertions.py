"""Tiny, closed assertion language over a skill's JSON output. Standard library only and no eval: this exact file is
copied into every generated package (tests/_assertions.py) so the package's own tests and the creator judge identically.

path: dotted keys / list indexes, with `*` meaning "every element", e.g. `findings.0.code` or `findings.*.code`.
ops : equals | contains | min_len | exists | absent
"""
from __future__ import annotations

_MISSING = object()


def _walk(obj, parts):
    """Yield every value reached by the path (more than one when `*` is used); nothing if the path does not exist."""
    if not parts:
        yield obj
        return
    head, rest = parts[0], parts[1:]
    if head == "*":
        if isinstance(obj, list):
            for item in obj:
                yield from _walk(item, rest)
        elif isinstance(obj, dict):
            for item in obj.values():
                yield from _walk(item, rest)
        return
    if isinstance(obj, dict) and head in obj:
        yield from _walk(obj[head], rest)
    elif isinstance(obj, list) and head.isdigit() and int(head) < len(obj):
        yield from _walk(obj[int(head)], rest)


def values_at(output, path):
    return list(_walk(output, path.split(".")))


def _eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return a == b


def check(output, path, op, value=None):
    """Return None when the assertion holds, else a one-line explanation."""
    found = values_at(output, path)
    wild = "*" in path.split(".")
    if op == "exists":
        return None if found and all(v is not None for v in found) else f"{path}: expected to exist"
    if op == "absent":
        return None if not found else f"{path}: expected to be absent but found {found[0]!r}"
    if not found:
        return f"{path}: not present in the output"
    if op == "equals":
        ok = any(_eq(v, value) for v in found) if wild else _eq(found[0], value)
        return None if ok else f"{path}: expected {value!r}, got {found[0] if not wild else found!r}"
    if op == "min_len":
        v = found[0]
        try:
            n = len(v)
        except TypeError:
            return f"{path}: has no length"
        if wild:
            n = len(found)
        return None if n >= int(value) else f"{path}: expected length >= {value}, got {n}"
    if op == "contains":
        pool = found if wild else found[0]
        if isinstance(pool, str):
            ok = isinstance(value, str) and value in pool
        elif isinstance(pool, list):
            ok = any(_eq(i, value) or (isinstance(i, str) and isinstance(value, str) and value in i) for i in pool)
        else:
            ok = False
        return None if ok else f"{path}: expected to contain {value!r}"
    return f"{path}: unknown op {op!r}"
