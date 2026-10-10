"""Go: package, imports, types, functions/methods, HTTP routing (net/http, gin, echo, chi, gorilla/mux, fiber), database/sql, gorm, Kafka/NATS,
http clients, os.Getenv. Lexical: no go/types, no build tags, no code generation expansion."""
from __future__ import annotations

from yuktiforge.docint.analyzers.lexfacts import Ctx, url_name

ROUTE_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "Get", "Post", "Put", "Delete", "Patch", "Head", "Options"}
ROUTER_HINT = ("r", "router", "mux", "e", "app", "g", "group", "api", "v1", "v2", "engine", "server", "srv", "rg", "chi", "gin", "echo", "fiber", "http")


def analyze(c: Ctx) -> None:
    toks, n = c.toks, len(c.toks)
    pkg = ""
    i = 0
    while i < n:
        t = toks[i]
        if t.kind == "id" and t.val == "package" and not pkg:
            pkg = toks[i + 1].val if i + 1 < n else ""
            c.add_symbol(pkg, pkg, "namespace", t.line, t.line, parent=None, signature=f"package {pkg}")
            i += 2
        elif t.kind == "id" and t.val == "import":
            if c.is_(i + 1, "("):
                close = c.match.get(i + 1, i + 1)
                j = i + 2
                while j < close:
                    if toks[j].kind == "str":
                        alias = toks[j - 1].val if j - 1 > i + 1 and toks[j - 1].kind in ("id",) or (j - 1 > i + 1 and toks[j - 1].val in (".", "_")) else None
                        c.add_import(toks[j].line, toks[j].val, (alias,) if alias else (), "import")
                    j += 1
                i = close + 1
            else:
                j = i + 1
                if j < n and toks[j].kind != "str":
                    j += 1
                if j < n and toks[j].kind == "str":
                    c.add_import(toks[j].line, toks[j].val, (), "import")
                i = j + 1
        elif t.kind == "id" and t.val == "func":
            i = func_decl(c, i, pkg)
        elif t.kind == "id" and t.val == "type":
            i = type_decl(c, i, pkg)
        elif t.kind == "id" and t.val in ("var", "const"):
            i = var_decl(c, i, pkg)
        else:
            i += 1
    boundaries(c)


def func_decl(c: Ctx, i: int, pkg: str) -> int:
    toks = c.toks
    start = toks[i]
    j = i + 1
    recv = ""
    if c.is_(j, "("):                                       # method receiver
        rt = [x.val for x in toks[j + 1:c.match.get(j, j)] if x.kind == "id"]
        recv = rt[-1] if rt else ""
        j = c.skip_group(j)
    if j >= len(toks) or toks[j].kind != "id":
        return i + 1                                        # func literal
    name = toks[j].val
    j += 1
    j = c.skip_generics(j) if c.is_(j, "[") is False else (c.skip_group(j) if c.is_(j, "[") else j)
    if not c.is_(j, "("):
        return i + 1
    pclose = c.match.get(j, j)
    k = pclose + 1
    while k < len(toks) and not (toks[k].kind == "punct" and toks[k].val == "{") and not (toks[k].line > toks[pclose].end + 0 and toks[k].kind == "id" and toks[k].val in ("func", "type", "var", "const", "package", "import") and False):
        if toks[k].kind == "punct" and toks[k].val == "(":
            k = c.skip_group(k)
            continue
        if toks[k].line > toks[pclose].end + 1 and not c.is_(k, "{"):
            break
        k += 1
    if k < len(toks) and c.is_(k, "{"):
        close = c.match.get(k, k)
        last, nxt = toks[close].end, close + 1
    else:
        last, nxt = toks[min(pclose, len(toks) - 1)].end, k
    q = f"{pkg}.{recv}.{name}" if recv else f"{pkg}.{name}"
    sig = " ".join(x.val for x in toks[i:pclose + 1] if x.kind in ("id", "punct"))
    exported = name[:1].isupper()
    c.add_symbol(q, name, "method" if recv else "function", start.line, last, parent=f"{pkg}.{recv}" if recv else pkg or None, signature=sig,
                 modifiers=("exported",) if exported else (), doc=start.doc)
    if name == "main" and not recv and pkg == "main":
        c.bnd("entry-point", "main", start.line, last, framework="go", symbol=q, details={"package": pkg}, confidence="high")
    return nxt


def type_decl(c: Ctx, i: int, pkg: str) -> int:
    toks = c.toks
    if c.is_(i + 1, "("):                                   # type ( ... ) group
        close = c.match.get(i + 1, i + 1)
        j = i + 2
        while j < close:
            j = _one_type(c, j, pkg, toks[j].doc)
        return close + 1
    return _one_type(c, i + 1, pkg, toks[i].doc, start_tok=toks[i])


def _one_type(c: Ctx, j: int, pkg: str, doc: str, start_tok=None) -> int:
    toks = c.toks
    if j >= len(toks) or toks[j].kind != "id":
        return j + 1
    name = toks[j].val
    line = (start_tok or toks[j]).line
    k = j + 1
    if c.is_(k, "["):
        k = c.skip_group(k)
    if k < len(toks) and toks[k].kind == "id" and toks[k].val in ("struct", "interface") and c.is_(k + 1, "{"):
        close = c.match.get(k + 1, k + 1)
        kind = "struct" if toks[k].val == "struct" else "interface"
        q = f"{pkg}.{name}"
        c.add_symbol(q, name, kind, line, toks[close].end, parent=pkg or None, signature=f"type {name} {toks[k].val}", modifiers=("exported",) if name[:1].isupper() else (), doc=doc or toks[j].doc)
        m = k + 2
        while m < close:                                    # fields / interface methods: one per line
            if toks[m].kind == "id" and (m == k + 2 or toks[m].line > toks[m - 1].end):
                ln = toks[m].line
                names = [toks[m].val]
                e = m + 1
                while e < close and toks[e].line == ln:
                    e += 1
                if kind == "interface" and c.is_(m + 1, "("):
                    c.add_symbol(f"{q}.{toks[m].val}", toks[m].val, "method", ln, ln, parent=q, signature=" ".join(x.val for x in toks[m:e] if x.kind in ("id", "punct")))
                elif kind == "struct" and not c.is_(m + 1, "."):
                    tag = next((x.val for x in toks[m:e] if x.kind == "str"), "")
                    c.add_symbol(f"{q}.{names[0]}", names[0], "field", ln, ln, parent=q, signature=" ".join(x.val for x in toks[m:e] if x.kind in ("id", "punct")), annotations=((tag,) if tag else ()))
                    if "gorm" in tag and "primaryKey" in tag:
                        pass
                m = e
                continue
            if toks[m].kind == "punct" and toks[m].val in ("{", "(", "["):
                m = c.skip_group(m)
                continue
            m += 1
        return close + 1
    # alias / defined type
    e = k
    while e < len(toks) and toks[e].line == toks[j].line and not c.is_(e, ";"):
        e += 1
    c.add_symbol(f"{pkg}.{name}", name, "type", line, toks[j].line, parent=pkg or None, signature=f"type {name} " + " ".join(x.val for x in toks[k:e] if x.kind in ("id", "punct")), doc=doc)
    return max(e, j + 1)


def var_decl(c: Ctx, i: int, pkg: str) -> int:
    toks = c.toks
    if c.is_(i + 1, "("):
        return c.skip_group(i + 1)
    return i + 2


def boundaries(c: Ctx) -> None:
    sql_funcs = {"Query", "QueryRow", "Exec", "QueryContext", "QueryRowContext", "ExecContext", "Prepare", "PrepareContext"}
    for call in c.calls():
        name, recv = call.name, call.receiver
        rl = recv.lower().split(".")[-1] if recv else ""
        lit, dyn = c.first_str(call)
        if name in ROUTE_VERBS and rl and lit and lit.startswith("/") and not recv.startswith("http."):
            c.bnd("http-route", f"{name.upper()} {lit}", call.line, call.end, framework="go-router", details={"router": recv})
        elif name in ("HandleFunc", "Handle") and lit is not None and lit.startswith(("/", "GET ", "POST ", "PUT ", "DELETE ", "PATCH ")):
            parts = lit.split(" ", 1)
            c.bnd("http-route", (f"{parts[0]} {parts[1]}" if len(parts) == 2 else f"ANY {lit}"), call.line, call.end, framework="net/http", details={"router": recv or "http"})
        elif name in ("Get", "Post", "Head", "PostForm") and recv == "http":
            c.bnd("http-client", url_name(name.upper(), lit, dyn), call.line, call.end, framework="net/http", dynamic=bool(dyn or lit is None))
        elif name in ("NewRequest", "NewRequestWithContext") and recv == "http":
            t = [x for x in c.toks[call.lp + 1:call.rp] if x.kind == "str"]
            if len(t) >= 2:
                c.bnd("http-client", url_name(t[0].val, t[1].val, False), call.line, call.end, framework="net/http")
            else:
                c.bnd("http-client", "HTTP <dynamic>", call.line, call.end, framework="net/http", dynamic=True)
        elif name in ("Getenv", "LookupEnv") and recv == "os" and lit:
            c.bnd("config-env", lit, call.line, call.end, framework="go", details={"access": f"os.{name}"})
        elif name in ("GetString", "GetInt", "GetBool") and "viper" in rl and lit:
            c.bnd("config-env", lit, call.line, call.end, framework="viper", details={"access": f"viper.{name}"})
        elif name == "Table" and lit and ("db" in rl or "gorm" in rl or "tx" in rl):
            c.bnd("db-table", lit, call.line, call.end, framework="gorm", details={"access": "gorm.Table"}, confidence="medium")
        elif name == "AutoMigrate":
            for x in c.toks[call.lp + 1:call.rp]:
                if x.kind == "id" and x.val[:1].isupper() and x.val not in ("AutoMigrate",):
                    c.bnd("db-table", x.val, call.line, call.end, framework="gorm", details={"access": "AutoMigrate"}, confidence="medium")
        elif name in ("Publish", "PublishMsg", "Produce", "WriteMessages") and rl in ("nc", "js", "conn", "producer", "writer", "p", "w", "kafkawriter") or name in ("Subscribe", "QueueSubscribe", "ChanSubscribe"):
            role = "event-subscribe" if "Subscribe" in name else "event-publish"
            c.bnd(role, lit or "<dynamic>", call.line, call.end, framework="nats/kafka", dynamic=bool(dyn or lit is None), confidence="low")
        elif name in sql_funcs:
            pass
    # kafka-go struct literal: kafka.Writer{Topic: "x"} / kafka.ReaderConfig{Topic: "x"}
    toks = c.toks
    for i, t in enumerate(toks):
        if t.kind == "id" and t.val == "Topic" and c.is_(i + 1, ":") and i + 2 < len(toks) and toks[i + 2].kind == "str":
            c.bnd("event-publish", toks[i + 2].val, t.line, t.end, framework="kafka-go", confidence="low", details={"note": "Topic field; publish vs consume depends on the enclosing Writer/Reader type"})
    c.sql_literals()
