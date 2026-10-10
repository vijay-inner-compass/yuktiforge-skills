"""Python analyzer: the standard-library `ast` parser (parse only: the code is never compiled, imported or run). Symbols, imports, calls,
HTTP routes, SQL/ORM tables, messaging and environment access, all with exact line ranges."""
from __future__ import annotations

import ast
import types
import builtins

from yuktiforge.docint.analyzers import base, sqlutil
from yuktiforge.docint.analyzers.base import Capability, FileAnalyzer, boundary_id, doc_line, prov, sym_id
from yuktiforge.docint.model import Boundary, Call, FileFacts, Import, Symbol, clip
from yuktiforge.docint.safety import redact_url

CAP = Capability(
    "python-ast", "1.0", ("python",), ("*.py", "*.pyi"), "ast",
    ("symbols", "imports", "calls", "routes", "db", "events", "http-clients", "config", "entry-points"), "high",
    ("static parse only: dynamic imports, getattr/setattr dispatch, monkey-patching, decorators that rewrite routes and framework wiring are not seen",
     "calls are matched by name: a call through a variable, a callback or inheritance is `unresolved`, never guessed",
     "route/table/topic names are recorded only when they are string literals; computed names are flagged `dynamic`",
     "type annotations are copied as written, not evaluated"))

_BUILTINS = frozenset(dir(builtins))
_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}
_ROUTE_ATTRS = {"route", "get", "post", "put", "delete", "patch", "head", "options", "websocket", "api_route", "add_url_rule"}
_FW_IMPORT = {"flask": "flask", "fastapi": "fastapi", "starlette": "starlette", "django": "django", "sanic": "sanic", "quart": "quart", "bottle": "bottle", "aiohttp": "aiohttp",
              "falcon": "falcon", "tornado": "tornado", "pyramid": "pyramid"}
_CLIENT_MODS = ("requests", "httpx", "aiohttp", "urllib3")
_EVENT_PATTERNS = [
    # (framework, required import module prefixes, attr names, role, kind of first arg)
    ("kafka", ("kafka", "confluent_kafka", "aiokafka"), {"send", "produce", "send_and_wait"}, "publish"),
    ("kafka", ("kafka", "confluent_kafka", "aiokafka"), {"subscribe"}, "subscribe"),
    ("rabbitmq", ("pika", "aio_pika", "kombu"), {"basic_publish"}, "publish"),
    ("rabbitmq", ("pika", "aio_pika", "kombu"), {"basic_consume", "queue_declare"}, "subscribe"),
    ("redis", ("redis", "aioredis"), {"publish"}, "publish"),
    ("redis", ("redis", "aioredis"), {"subscribe", "psubscribe"}, "subscribe"),
    ("aws-sns", ("boto3", "aioboto3", "botocore"), {"publish"}, "publish"),
    ("aws-sqs", ("boto3", "aioboto3", "botocore"), {"send_message", "send_message_batch"}, "publish"),
    ("aws-sqs", ("boto3", "aioboto3", "botocore"), {"receive_message"}, "subscribe"),
    ("nats", ("nats",), {"publish"}, "publish"),
    ("nats", ("nats",), {"subscribe"}, "subscribe"),
]
_MAX_CALLS = 20_000


def module_name(rel: str) -> str:
    p = rel[:-3] if rel.endswith(".py") else rel[:-4] if rel.endswith(".pyi") else rel
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.replace("/", ".") or "__init__"


def dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def const_str(node: ast.AST | None) -> tuple[str | None, bool]:
    """(value, dynamic). A literal string -> (s, False); an f-string, a name or an expression -> (None, True)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if node is None:
        return None, False
    return None, True


def _unparse(node: ast.AST | None, n: int = 120) -> str:
    if node is None:
        return ""
    try:
        return clip(ast.unparse(node), n)
    except Exception:       # noqa: BLE001 - ast.unparse can recurse deeply on hostile input
        return "<unprintable>"


class _Visitor:
    def __init__(self, rel: str, tree: ast.Module, text_lines: list[str]):
        self.rel, self.tree = rel, tree
        self.mod = module_name(rel)
        self.symbols: list[Symbol] = []
        self.imports: list[Import] = []
        self.calls: list[Call] = []
        self.boundaries: list[Boundary] = []
        self.taken: set[str] = set()
        self.imported: set[str] = set()      # top-level module names imported anywhere in the file
        self.fw: str | None = None
        self.stack: list[tuple[str, str]] = []   # (kind, qualified name)
        self.var_types: dict[tuple[str, str], str] = {}     # (scope, variable) -> class name it was assigned from; scope is a function's qualified name, a class's (for self.x) or ""

    # ---------------------------------------------------------------- helpers
    def qn(self, name: str) -> str:
        return ".".join([self.mod] + [q.rsplit(".", 1)[-1] for _, q in self.stack] + [name]) if self.stack else f"{self.mod}.{name}"

    def collect_types(self, body: list[ast.stmt], names: list[tuple[str, str]]) -> None:
        """`x = Cls(...)`, `x: Cls = ...` and `self.x = Cls(...)`: remember the class so `x.m()` can be tied to `Cls.m`. Parsing only; a heuristic hint recorded as such."""
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.collect_types(n.body, names + [("class" if isinstance(n, ast.ClassDef) else "function", n.name)])
                continue
            nested = [x for blk in ("body", "orelse", "finalbody") for x in (getattr(n, blk, None) or []) if isinstance(x, ast.stmt)]
            nested += [y for h in getattr(n, "handlers", []) or [] for y in h.body]
            if nested:
                self.collect_types(nested, names)
                continue
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.value, ast.Call):
                tgt, cls = n.targets[0], dotted(n.value.func)
            elif isinstance(n, ast.AnnAssign):
                tgt = n.target
                cls = dotted(n.annotation) if isinstance(n.annotation, (ast.Name, ast.Attribute)) else (dotted(n.value.func) if isinstance(n.value, ast.Call) else None)
            else:
                continue
            if not cls or cls.split(".")[-1][:1].islower():
                continue                                         # `x = make_thing()`: a factory, not a constructor (class names are capitalised by convention)
            func_scope = next((i for i in range(len(names) - 1, -1, -1) if names[i][0] == "function"), None)
            if isinstance(tgt, ast.Name):
                scope = ".".join([self.mod] + [nm for _, nm in names[:func_scope + 1]]) if func_scope is not None else ""
                self.var_types.setdefault((scope, tgt.id), cls)
            elif isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self" and func_scope is not None and func_scope >= 1 and names[func_scope - 1][0] == "class":
                self.var_types.setdefault((".".join([self.mod] + [nm for _, nm in names[:func_scope]]), "self." + tgt.attr), cls)

    def receiver_type(self, text: str) -> str | None:
        parts = text.split(".")
        cur = self.current()
        if len(parts) == 2:
            return self.var_types.get((cur or "", parts[0])) or self.var_types.get(("", parts[0]))
        if len(parts) == 3 and parts[0] == "self" and cur and "." in cur:
            return self.var_types.get((cur.rsplit(".", 1)[0], "self." + parts[1]))
        return None

    def current(self) -> str | None:
        for k, q in reversed(self.stack):
            if k in ("function", "method", "constructor"):
                return q
        return None

    def bnd(self, kind, name, node, **kw) -> None:
        line, end = getattr(node, "lineno", 1), getattr(node, "end_lineno", None)
        self.boundaries.append(Boundary(id=boundary_id(self.rel, kind, name, line), kind=kind, name=clip(name, 200), framework=kw.pop("framework", "unknown"),
                                        symbol=kw.pop("symbol", None) or self.current(), details=kw.pop("details", {}), dynamic=kw.pop("dynamic", False),
                                        prov=prov(self.rel, line, end, CAP, **({"method": kw["method"]} if "method" in kw else {}), **({"confidence": kw["confidence"]} if "confidence" in kw else {}))))

    # ---------------------------------------------------------------- walk
    def run(self) -> None:
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.imported.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                self.imported.add(n.module.split(".")[0])
        self.fw = next((v for k, v in _FW_IMPORT.items() if k in self.imported), None)
        doc = ast.get_docstring(self.tree) or ""
        end = max([getattr(n, "end_lineno", 1) or 1 for n in self.tree.body] or [1])
        self.symbols.append(Symbol(id=sym_id(self.rel, self.mod, "module", 1, self.taken), name=self.mod.rsplit(".", 1)[-1], qualified_name=self.mod, kind="module", language="python",
                                   doc=doc_line(doc.strip().splitlines()[0]) if doc.strip() else "", prov=prov(self.rel, 1, end, CAP)))
        self.collect_types(self.tree.body, [])
        self.visit_body(self.tree.body)

    def visit_body(self, body: list[ast.stmt]) -> None:
        for n in body:
            self.visit(n)

    def visit(self, n: ast.AST) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.function(n)
        elif isinstance(n, ast.ClassDef):
            self.klass(n)
        elif isinstance(n, ast.Import):
            for a in n.names:
                self.imports.append(Import(source_path=self.rel, line=n.lineno, target=a.name, names=(a.asname,) if a.asname else (), kind="import",
                                           prov=prov(self.rel, n.lineno, n.end_lineno, CAP)))
        elif isinstance(n, ast.ImportFrom):
            self.imports.append(Import(source_path=self.rel, line=n.lineno, target="." * n.level + (n.module or ""), names=tuple(a.name + (f" as {a.asname}" if a.asname else "") for a in n.names), kind="from",
                                       prov=prov(self.rel, n.lineno, n.end_lineno, CAP)))
        else:
            if isinstance(n, ast.If) and self.is_main_guard(n):
                self.bnd("entry-point", "__main__ guard", n, framework="python", symbol=self.mod, details={"module": self.mod})
            self.scan_expressions(n)
            for child in ast.iter_child_nodes(n):
                if isinstance(child, ast.stmt):
                    self.visit(child)

    def is_main_guard(self, n: ast.If) -> bool:
        t = n.test
        return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__" and len(t.comparators) == 1
                and isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value == "__main__")

    def decorator_names(self, n) -> tuple[str, ...]:
        out = []
        for d in n.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            out.append(dotted(target) or _unparse(target, 60))
        return tuple(out)

    def klass(self, n: ast.ClassDef) -> None:
        q = self.qn(n.name)
        bases = tuple(_unparse(b, 80) for b in n.bases)
        doc = ast.get_docstring(n) or ""
        parent = self.stack[-1][1] if self.stack else self.mod
        self.symbols.append(Symbol(id=sym_id(self.rel, q, "class", n.lineno, self.taken), name=n.name, qualified_name=q, kind="class", language="python", parent=parent,
                                   signature=clip(f"class {n.name}({', '.join(bases)})" if bases else f"class {n.name}"), bases=bases, annotations=self.decorator_names(n),
                                   doc=doc_line(doc.strip().splitlines()[0]) if doc.strip() else "", prov=prov(self.rel, n.lineno, n.end_lineno, CAP)))
        self.orm_boundaries(n, q, bases)
        for d in n.decorator_list:
            self.scan_expressions(d)
        self.stack.append(("class", q))
        for child in n.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                fq = f"{q}.{child.target.id}"
                self.symbols.append(Symbol(id=sym_id(self.rel, fq, "field", child.lineno, self.taken), name=child.target.id, qualified_name=fq, kind="field", language="python", parent=q,
                                           signature=clip(f"{child.target.id}: {_unparse(child.annotation, 80)}"), prov=prov(self.rel, child.lineno, child.end_lineno, CAP)))
            self.visit(child)
        self.stack.pop()

    def function(self, n: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        in_class = bool(self.stack) and self.stack[-1][0] == "class"
        q = self.qn(n.name)
        kind = "constructor" if in_class and n.name == "__init__" else "method" if in_class else "function"
        decos = self.decorator_names(n)
        mods = tuple(m for m in (("async",) if isinstance(n, ast.AsyncFunctionDef) else ()) + tuple(d for d in decos if d in ("staticmethod", "classmethod", "property", "abstractmethod")))
        doc = ast.get_docstring(n) or ""
        parent = self.stack[-1][1] if self.stack else self.mod
        ret = f" -> {_unparse(n.returns, 60)}" if n.returns else ""
        self.symbols.append(Symbol(id=sym_id(self.rel, q, kind, n.lineno, self.taken), name=n.name, qualified_name=q, kind=kind, language="python", parent=parent,
                                   signature=clip(f"{'async ' if isinstance(n, ast.AsyncFunctionDef) else ''}def {n.name}({_unparse(n.args, 100)}){ret}"), modifiers=mods, annotations=decos,
                                   doc=doc_line(doc.strip().splitlines()[0]) if doc.strip() else "", prov=prov(self.rel, n.lineno, n.end_lineno, CAP)))
        for d in n.decorator_list:
            self.decorator_boundaries(d, n, q)
        for d in n.decorator_list:
            self.scan_expressions(d, in_decorator=True)
        self.stack.append((kind, q))
        for child in n.body:
            self.visit(child)
        self.stack.pop()

    # ---------------------------------------------------------------- boundaries
    def decorator_boundaries(self, d: ast.expr, fn, q: str) -> None:
        """The evidence for a decorator-declared route or task is the decorator AND the function it decorates: the cited range starts at the decorator line."""
        fn = types.SimpleNamespace(lineno=d.lineno, end_lineno=getattr(fn, "end_lineno", d.lineno))
        if isinstance(d, ast.Call):
            f = d.func
            attr = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            full = dotted(f) or ""
            if attr in _ROUTE_ATTRS and d.args or (attr == "route" and not d.args and any(k.arg in ("path", "rule") for k in d.keywords)):
                path, dyn = const_str(d.args[0] if d.args else next((k.value for k in d.keywords if k.arg in ("path", "rule")), None))
                methods = []
                for k in d.keywords:
                    if k.arg == "methods" and isinstance(k.value, (ast.List, ast.Tuple, ast.Set)):
                        methods = [e.value.upper() for e in k.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                verb = (attr or "").upper() if attr in _HTTP_VERBS else None
                verbs = [verb] if verb else (methods or ["GET" if self.fw == "flask" else "ANY"])
                for m in verbs:                                                  # one operation per HTTP verb: that is what a document lists
                    self.bnd("http-route", f"{m} {path if path is not None else '<dynamic>'}", fn, framework=self.fw or "unknown", symbol=q,
                             details={"handler": q, "decorator": clip(full or str(attr), 60), **({"methods_default": True} if not verb and not methods and self.fw == "flask" else {})}, dynamic=dyn,
                             method="ast", confidence="high" if self.fw else "medium")
            if attr in ("task", "shared_task") or full.endswith(".task") or full in ("shared_task", "celery.shared_task"):
                self.bnd("event-subscribe", f"task:{q}", fn, framework="celery", symbol=q, details={"handler": q}, confidence="high" if "celery" in self.imported else "medium")
        else:
            full = dotted(d) or ""
            if full in ("shared_task", "celery.shared_task") or full.endswith(".task"):
                self.bnd("event-subscribe", f"task:{q}", fn, framework="celery", symbol=q, details={"handler": q}, confidence="high" if "celery" in self.imported else "medium")

    def orm_boundaries(self, n: ast.ClassDef, q: str, bases: tuple[str, ...]) -> None:
        for child in n.body:
            if isinstance(child, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in child.targets):
                val, dyn = const_str(child.value)
                self.bnd("db-table", val or "<dynamic>", child, framework="sqlalchemy", symbol=q, dynamic=dyn, details={"entity": n.name}, confidence="high" if "sqlalchemy" in self.imported else "medium")
            if isinstance(child, ast.ClassDef) and child.name == "Meta":
                for m in child.body:
                    if isinstance(m, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "db_table" for t in m.targets):
                        val, dyn = const_str(m.value)
                        self.bnd("db-table", val or "<dynamic>", m, framework="django", symbol=q, dynamic=dyn, details={"entity": n.name})
        if "django" in self.imported and any(b.endswith("Model") for b in bases) and not any(
                b.kind == "db-table" and b.symbol == q and b.framework == "django" for b in self.boundaries):
            self.bnd("db-table", f"{n.name} (django model; table name not stated)", n, framework="django", symbol=q, details={"entity": n.name}, confidence="medium")

    def scan_expressions(self, node: ast.AST, in_decorator: bool = False) -> None:
        """Calls and boundary patterns in the expressions of ONE statement (nested statements are visited separately)."""
        stack = [node]
        first = True
        while stack:
            cur = stack.pop()
            if not first and isinstance(cur, (ast.stmt, ast.Lambda)) and not isinstance(cur, ast.Lambda):
                continue
            first = False
            if isinstance(cur, ast.Call):
                self.call(cur)
            elif isinstance(cur, ast.Constant) and isinstance(cur.value, str) and sqlutil.looks_like_sql(cur.value):
                self.sql_literal(cur)
            elif isinstance(cur, ast.Subscript):
                d = dotted(cur.value)
                if d in ("os.environ", "environ"):
                    v, dyn = const_str(cur.slice)
                    if v:
                        self.bnd("config-env", v, cur, framework="python", details={"access": "environ[]"})
            stack.extend(reversed(list(ast.iter_child_nodes(cur))))

    def sql_literal(self, c: ast.Constant) -> None:
        sql = c.value
        tables = sqlutil.sql_tables(sql)
        op = sqlutil.sql_operation(sql)
        self.bnd("db-query", f"{op} {','.join(tables) or '?'}", c, framework="sql", details={"operation": op, "tables": tables, "statement": clip(sql, 120)}, method="pattern", confidence="medium")

    def call(self, c: ast.Call) -> None:
        text = dotted(c.func) or (_unparse(c.func, 60) if isinstance(c.func, (ast.Attribute, ast.Name)) else "")
        attr = c.func.attr if isinstance(c.func, ast.Attribute) else None
        if text and text not in _BUILTINS and len(self.calls) < _MAX_CALLS:
            self.calls.append(Call(source_path=self.rel, line=c.lineno, caller=self.current(), callee_text=clip(text, 100), receiver_type=self.receiver_type(text), prov=prov(self.rel, c.lineno, c.end_lineno, CAP)))
        # environment
        if text in ("os.getenv", "getenv", "os.environ.get", "environ.get") and c.args:
            v, dyn = const_str(c.args[0])
            if v:
                self.bnd("config-env", v, c, framework="python", details={"access": text})
        # HTTP clients
        root = text.split(".", 1)[0] if text else ""
        if root in _CLIENT_MODS and attr in _HTTP_VERBS | {"request", "stream"} and c.args:
            idx = 1 if attr == "request" and len(c.args) > 1 else 0
            url, dyn = const_str(c.args[idx])
            self.bnd("http-client", f"{(attr or '').upper()} {redact_url(url) if url else '<dynamic>'}", c, framework=root, dynamic=dyn or url is None, details={"library": root})
        elif text in ("urllib.request.urlopen", "urlopen") and c.args:
            url, dyn = const_str(c.args[0])
            self.bnd("http-client", f"GET {redact_url(url) if url else '<dynamic>'}", c, framework="urllib", dynamic=dyn or url is None, details={"library": "urllib"})
        # Django url patterns
        if text in ("path", "re_path", "url") and c.args and "django" in self.imported | {"urls"}:
            p, dyn = const_str(c.args[0])
            if p is not None or dyn:
                self.bnd("http-route", f"ANY {p if p is not None else '<dynamic>'}", c, framework="django", dynamic=dyn, details={"view": _unparse(c.args[1], 80) if len(c.args) > 1 else ""})
        if attr and attr.startswith("add_") and attr[4:] in _HTTP_VERBS and "aiohttp" in self.imported and c.args:
            p, dyn = const_str(c.args[0])
            self.bnd("http-route", f"{attr[4:].upper()} {p if p is not None else '<dynamic>'}", c, framework="aiohttp", dynamic=dyn, details={"handler": _unparse(c.args[1], 60) if len(c.args) > 1 else ""})
        # messaging
        if attr:
            for fw, mods, attrs, role in _EVENT_PATTERNS:
                if attr in attrs and any(m in self.imported for m in mods):
                    name, dyn = self.event_name(c, attr)
                    self.bnd(f"event-{role}", name or "<dynamic>", c, framework=fw, dynamic=dyn or name is None, details={"call": clip(text, 60)})
                    break
            if attr in ("delay", "apply_async") and "celery" in self.imported:
                self.bnd("event-publish", f"task call: {clip(text.rsplit('.', 1)[0], 80)}", c, framework="celery", details={"call": clip(text, 60)}, confidence="medium")
        if text in ("KafkaConsumer", "kafka.KafkaConsumer", "AIOKafkaConsumer") and c.args:
            name, dyn = const_str(c.args[0])
            self.bnd("event-subscribe", name or "<dynamic>", c, framework="kafka", dynamic=dyn)

    def event_name(self, c: ast.Call, attr: str) -> tuple[str | None, bool]:
        kws = {k.arg: k.value for k in c.keywords if k.arg}
        for key in ("routing_key", "queue", "topic", "TopicArn", "QueueUrl", "channel", "subject"):
            if key in kws:
                v, dyn = const_str(kws[key])
                return (redact_url(v) if v and "://" in v else v), dyn
        if c.args:
            a = c.args[0]
            if isinstance(a, (ast.List, ast.Tuple)) and a.elts:
                a = a.elts[0]
            v, dyn = const_str(a)
            return v, dyn
        return None, True


class PythonAnalyzer(FileAnalyzer):
    capability = CAP

    def analyze(self, rel: str, text: str) -> FileFacts:
        try:
            tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError, RecursionError, MemoryError, OverflowError) as e:
            line = getattr(e, "lineno", None)
            return FileFacts(parsed=False, warnings=(f"cannot parse ({type(e).__name__}{f' at line {line}' if line else ''}): the file's content is UNKNOWN, not absent",))
        v = _Visitor(rel, tree, base.split_lines(text))
        try:
            v.run()
        except RecursionError:
            return FileFacts(parsed=False, warnings=("analysis stopped: expression nesting too deep; the file's content is UNKNOWN, not absent",))
        return FileFacts(symbols=tuple(v.symbols), imports=tuple(v.imports), calls=tuple(v.calls), boundaries=tuple(v.boundaries))


base.register(PythonAnalyzer())
