"""Section-level regeneration: only sections whose input facts changed are replaced; everything else (including any reviewed or AI-narrated content) is kept as it was."""
from __future__ import annotations

from yuktiforge.docint.docgen.doc import Document


def regenerate(prev: Document | None, new: Document, only: set[str] | None = None) -> tuple[Document, dict[str, list[str]]]:
    stats: dict[str, list[str]] = {"unchanged": [], "changed": [], "added": [], "removed": [], "held_back": []}
    if prev is None:
        stats["added"] = [s.id for s in new.sections]
        return new, stats
    old = {s.id: s for s in prev.sections}
    out = []
    for s in new.sections:
        p = old.get(s.id)
        if p is None:
            stats["added"].append(s.id)
            out.append(s)
        elif p.input_hash == s.input_hash:
            stats["unchanged"].append(s.id)
            out.append(p)                                       # keep the existing section object, with anything added to it since
        elif only is not None and s.id not in only:
            stats["held_back"].append(s.id)                     # its inputs changed but regeneration was limited to other sections: it is now known to be out of date
            out.append(p)
        else:
            stats["changed"].append(s.id)
            out.append(s)
    stats["removed"] = sorted(set(old) - {s.id for s in new.sections})
    gaps = tuple(g for s in out for g in s.gaps)
    return new.model_copy(update={"sections": tuple(out), "gaps": gaps}), stats
