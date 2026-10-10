"""Extension registry for document types. Adding a type never touches the engine: write a `DocumentType`, call `register()` (or list its module in `load_plugins`)."""
from __future__ import annotations

import importlib

from yuktiforge.docint.docgen.spi import DocumentType, Registry
from yuktiforge.errors import YuktiForgeError

REGISTRY = Registry()
_LOADED = False


def register(dt: DocumentType, source: str = "plugin") -> DocumentType:
    for attr in ("id", "title", "version", "template_id", "sections"):
        if not getattr(dt, attr, None):
            raise YuktiForgeError(f"document type {type(dt).__name__} must define '{attr}'")
    if dt.id in REGISTRY.types:
        raise YuktiForgeError(f"document type '{dt.id}' is already registered")
    ids = [s.id for s in dt.sections]
    if len(ids) != len(set(ids)):
        raise YuktiForgeError(f"document type '{dt.id}' has duplicate section ids")
    REGISTRY.types[dt.id] = dt
    REGISTRY.sources[dt.id] = source
    return dt


def unregister(type_id: str) -> None:
    REGISTRY.types.pop(type_id, None)
    REGISTRY.sources.pop(type_id, None)


def load_builtin() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from yuktiforge.docint.docgen import types_arch, types_catalog, types_req
    for mod, names in ((types_req, ("CodeExplanation", "BRDDraft", "SRSDraft", "FunctionalSpec", "BusinessRuleCatalog", "UseCases")),
                       (types_arch, ("SystemArchitecture", "SolutionArchitecture", "TechnologyArchitecture", "HLD", "LLD")),
                       (types_catalog, ("ApiCatalog", "DataDictionary", "DatabaseDoc"))):
        for n in names:
            register(getattr(mod, n)(), "builtin")
    from yuktiforge.docint.docgen.extensions import EXTENSIONS          # extensions register through the same public function
    for modname in EXTENSIONS:
        importlib.import_module(modname)


def load_plugin(module: str) -> None:
    """Import a module that calls `register(...)` at import time."""
    load_builtin()
    importlib.import_module(module)


def get(type_id: str) -> DocumentType:
    load_builtin()
    if type_id not in REGISTRY.types:
        raise YuktiForgeError(f"unknown document type '{type_id}'; available: {', '.join(sorted(REGISTRY.types))}")
    return REGISTRY.types[type_id]


def all_types() -> list[DocumentType]:
    load_builtin()
    return [REGISTRY.types[k] for k in sorted(REGISTRY.types)]
