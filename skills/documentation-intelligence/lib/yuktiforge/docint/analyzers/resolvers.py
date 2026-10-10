"""Second pass over the per-file facts: resolve imports to repository files and (for Python only) calls to symbols. Resolution is by NAME against the
facts already extracted: no code is run, nothing is guessed. A call or import that cannot be tied to a repository symbol stays `unresolved` /
`external`, which is a statement about the analysis, not about the program."""
from __future__ import annotations

import posixpath
import re

from yuktiforge.docint.model import Artifact, Call, Import, Symbol

_TS_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".json")


def _locals(imp: Import) -> dict[str, str]:
    """`from x import a, b as c` -> {local name: original name}."""
    return {n.split(" as ")[-1].strip(): n.split(" as ")[0].strip() for n in imp.names}


class Resolver:
    def __init__(self, files: set[str], symbols: list[Symbol], artifacts: list[Artifact], languages: dict[str, str | None]):
        self.files = files
        self.lang = languages
        self.go_modules: dict[str, str] = {}                # module path -> directory ("." for root), from go.mod
        for a in artifacts:
            m = re.fullmatch(r"go module (\S+)", a.detail)
            if a.path.endswith("go.mod") and m:
                self.go_modules[m.group(1)] = posixpath.dirname(a.path) or "."
        self.by_qname: dict[tuple[str, str], Symbol] = {}   # (language, qualified) -> symbol
        self.ns_files: dict[str, set[str]] = {}            # csharp/java namespace -> files declaring it
        self.pkg_dirs: dict[str, list[str]] = {}           # go dir -> files
        for s in symbols:
            self.by_qname.setdefault((s.language, s.qualified_name), s)
            if s.kind == "namespace" and s.language in ("csharp", "java"):
                self.ns_files.setdefault(s.qualified_name, set()).add(s.prov.path)
        for f in files:
            if f.endswith(".go"):
                self.pkg_dirs.setdefault(posixpath.dirname(f) or ".", []).append(f)
        self.py_roots = self._python_roots()

    def _python_roots(self) -> list[str]:
        """Directories that act as import roots: the repo root, and every directory that contains a top-level package which is not itself in a package."""
        roots = {""}
        for f in self.files:
            if f.endswith("/__init__.py"):
                d = posixpath.dirname(f)
                parent = posixpath.dirname(d)
                if not (parent and f"{parent}/__init__.py" in self.files):
                    roots.add(parent)
        for f in self.files:
            if f.endswith(".py") and f.count("/") >= 1 and f.split("/", 1)[0] in ("src", "lib", "app"):
                roots.add(f.split("/", 1)[0])
        return sorted(roots, key=lambda r: (r.count("/"), r))

    # ---------------------------------------------------------------- imports
    def resolve_import(self, imp: Import) -> Import:
        lang = self.lang.get(imp.source_path)
        path, external = None, True
        if lang == "python":
            path = self._py_module(imp)
        elif lang in ("typescript", "javascript"):
            path = self._ts(imp)
        elif lang == "go":
            path = self._go(imp.target)
        elif lang == "java":
            path = self._java(imp.target)
        elif lang == "csharp":
            ns = imp.target
            cands = sorted(self.ns_files.get(ns, ()))
            path = cands[0] if cands else None
        if path is not None:
            external = False
        elif lang == "python" and imp.target.startswith("."):
            external = False                               # a relative import that does not resolve is a broken/unknown internal reference, not a third party
        elif lang in ("typescript", "javascript") and imp.target.startswith((".", "/")):
            external = False
        return imp.model_copy(update=dict(resolved_path=path, external=external))

    def _py_candidates(self, mod: str) -> list[str]:
        out = []
        base = mod.replace(".", "/")
        for root in self.py_roots:
            pre = f"{root}/" if root else ""
            out += [f"{pre}{base}.py", f"{pre}{base}/__init__.py", f"{pre}{base}.pyi"]
        return out

    def _py_module(self, imp: Import) -> str | None:
        t = imp.target
        if t.startswith("."):
            dots = len(t) - len(t.lstrip("."))
            rest = t[dots:]
            d = posixpath.dirname(imp.source_path)
            for _ in range(dots - 1):
                d = posixpath.dirname(d)
            base = f"{d}/{rest.replace('.', '/')}" if rest else d
            if imp.kind == "from":                          # `from . import name`: when exactly one imported name is a submodule, that module is the dependency
                subs = [c for n in (x.split(" as ")[0] for x in imp.names) for c in (f"{base}/{n}.py", f"{base}/{n}/__init__.py") if c in self.files]
                if len(subs) == 1:
                    return subs[0]
            for c in (f"{base}.py", f"{base}/__init__.py"):
                if c in self.files:
                    return c
            return None
        parts = t.split(".")
        for k in range(len(parts), 0, -1):                 # longest module prefix that is a file (import a.b.c -> a/b/c.py or a/b.py)
            for c in self._py_candidates(".".join(parts[:k])):
                if c in self.files:
                    return c
        return None

    def _ts(self, imp: Import) -> str | None:
        t = imp.target
        if not t.startswith((".", "/")):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(imp.source_path), t)) if t.startswith(".") else t.lstrip("/")
        if base.startswith(".."):
            return None
        cands = [base] + [base + e for e in _TS_EXT] + [f"{base}/index{e}" for e in _TS_EXT]
        if base.endswith((".js", ".jsx", ".mjs")):             # TS ESM style: import './x.js' for x.ts
            stem = base.rsplit(".", 1)[0]
            cands += [stem + e for e in (".ts", ".tsx")]
        return next((c for c in cands if c in self.files), None)

    def _go(self, target: str) -> str | None:
        for mod, d in sorted(self.go_modules.items(), key=lambda kv: -len(kv[0])):
            if target == mod or target.startswith(mod + "/"):
                sub = target[len(mod):].lstrip("/")
                dirp = posixpath.normpath(posixpath.join(d, sub)) if d != "." else (sub or ".")
                files = sorted(self.pkg_dirs.get(dirp, []))
                return files[0] if files else None
        return None

    def _java(self, target: str) -> str | None:
        t = target[:-2] if target.endswith(".*") else target
        s = self.by_qname.get(("java", t))
        if s is not None:
            return s.prov.path
        files = sorted(self.ns_files.get(t, ()))
        return files[0] if files else None

    # ---------------------------------------------------------------- python calls
    def resolve_calls(self, calls: list[Call], imports: list[Import]) -> list[Call]:
        imp_by_file: dict[str, list[Import]] = {}
        for i in imports:
            imp_by_file.setdefault(i.source_path, []).append(i)
        mod_of: dict[str, str] = {}
        for (lang, q), s in self.by_qname.items():
            if lang == "python" and s.kind == "module":
                mod_of[s.prov.path] = q
        out = []
        for c in calls:
            if self.lang.get(c.source_path) != "python":
                out.append(c)
                continue
            out.append(self._py_call(c, imp_by_file.get(c.source_path, []), mod_of))
        return out

    def _typed_call(self, c: Call, method: str, imports: list[Import], mod: str, mod_of: dict[str, str]) -> Call | None:
        """`x = Cls(); x.m()` -> `Cls.m`, when `Cls` can be found in this file or through an import. A hint-based resolution, so it is only used when exactly that method exists."""
        tname = c.receiver_type or ""
        cands: list[tuple[str, str]] = []
        if "." not in tname:
            cands.append((mod, tname))
            for imp in imports:
                if imp.kind == "from" and imp.resolved_path:
                    loc = _locals(imp)
                    if tname in loc:
                        cands.append((mod_of.get(imp.resolved_path, ""), loc[tname]))
        else:
            head, _, rest = tname.partition(".")
            for imp in imports:
                if imp.kind == "import" and imp.resolved_path and head == (imp.names[0] if imp.names else imp.target.split(".")[0]):
                    cands.append((mod_of.get(imp.resolved_path, ""), rest))
                elif imp.kind == "from" and imp.resolved_path and head in _locals(imp):
                    sub = self._py_module(Import(source_path=c.source_path, line=imp.line, target=imp.target + "." + _locals(imp)[head], kind="import", prov=imp.prov))
                    if sub:
                        cands.append((mod_of.get(sub, ""), rest))
        for m, cls in cands:
            t = self.by_qname.get(("python", f"{m}.{cls}.{method}"))
            if t is not None and t.kind in ("method", "function"):
                return c.model_copy(update=dict(resolved=t.id, resolution="same-file" if t.prov.path == c.source_path else "import"))
        return None

    def _py_call(self, c: Call, imports: list[Import], mod_of: dict[str, str]) -> Call:
        text = c.callee_text
        if not re.fullmatch(r"[A-Za-z_][\w]*(\.[A-Za-z_]\w*)*", text):
            return c
        mod = mod_of.get(c.source_path, "")
        parts = text.split(".")
        if c.receiver_type and len(parts) >= 2:
            hit = self._typed_call(c, parts[-1], imports, mod, mod_of)
            if hit is not None:
                return hit
        caller = c.caller or mod
        # self.method / cls.method -> enclosing class
        if parts[0] in ("self", "cls") and len(parts) == 2 and c.caller:
            klass = c.caller.rsplit(".", 1)[0]
            s = self.by_qname.get(("python", f"{klass}.{parts[1]}"))
            if s is not None and s.kind in ("method", "function"):
                return c.model_copy(update=dict(resolved=s.id, resolution="same-file"))
            return c
        # bare name in the same module (function or class), then names from `from x import name`
        if len(parts) == 1:
            s = self.by_qname.get(("python", f"{mod}.{parts[0]}"))
            if s is not None and s.prov.path == c.source_path:
                return c.model_copy(update=dict(resolved=s.id, resolution="same-file"))
            for imp in imports:
                local = _locals(imp)
                if imp.kind == "from" and parts[0] in local and imp.resolved_path:
                    t = self.by_qname.get(("python", f"{mod_of.get(imp.resolved_path, '')}.{local[parts[0]]}"))
                    if t is not None:
                        return c.model_copy(update=dict(resolved=t.id, resolution="import"))
            return c
        # alias.name / module.name via `import a.b as alias` or `import a.b`
        head, tail = parts[0], parts[1:]
        for imp in imports:
            if imp.kind == "import" and imp.resolved_path:
                alias = imp.names[0] if imp.names else imp.target.split(".")[0]
                if head == alias and len(tail) >= 1:
                    q = f"{mod_of.get(imp.resolved_path, '')}.{'.'.join(tail)}"
                    t = self.by_qname.get(("python", q))
                    if t is not None:
                        return c.model_copy(update=dict(resolved=t.id, resolution="import"))
            elif imp.kind == "from" and head in _locals(imp) and imp.resolved_path:   # from pkg import module; module.func()
                orig = _locals(imp)[head]
                sub = self._py_module(Import(source_path=c.source_path, line=imp.line, target=imp.target + "." + orig if not imp.target.endswith(".") else imp.target + orig, kind="import",
                                             prov=imp.prov))
                if sub is not None:
                    t = self.by_qname.get(("python", f"{mod_of.get(sub, '')}.{'.'.join(tail)}"))
                    if t is not None:
                        return c.model_copy(update=dict(resolved=t.id, resolution="import"))
                t = self.by_qname.get(("python", f"{mod_of.get(imp.resolved_path, '')}.{orig}.{'.'.join(tail)}"))   # Class.method
                if t is not None:
                    return c.model_copy(update=dict(resolved=t.id, resolution="import"))
        return c
