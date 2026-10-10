"""Built-in analyzers register themselves here (once). Third-party analyzers call `base.register`."""
from __future__ import annotations

_LOADED = False


def load_builtin() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from yuktiforge.docint.analyzers import clike, manifests, python_ast, structured   # noqa: F401  (import registers)
