"""TypeScript / JavaScript: imports/require, classes, functions, interfaces, types, enums, exported arrow functions; Express/Fastify/Koa-router, NestJS decorators,
TypeORM/Sequelize/Prisma/Mongoose, fetch/axios, Kafka/AMQP, process.env. Lexical: no type checker, no bundler resolution, JSX/TSX treated as tokens."""
from __future__ import annotations

from yuktiforge.docint.analyzers import sqlutil
from yuktiforge.docint.analyzers.lexfacts import Ann, Ctx, url_name

MODS = frozenset({"export", "default", "declare", "abstract", "public", "private", "protected", "static", "readonly", "async", "override", "get", "set", "accessor"})
NEST_VERBS = {"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE", "Patch": "PATCH", "Head": "HEAD", "Options": "OPTIONS", "All": "ANY"}
ROUTE_VERBS = {"get", "post", "put", "delete", "patch", "head", "options", "all"}
ROUTER_NAMES = ("app", "router", "route", "server", "api", "fastify", "express", "r", "routes", "koa")
HTTP_CLIENT_FNS = {"get", "post", "put", "delete", "patch", "request"}
PRISMA_OPS = {"findMany", "findUnique", "findFirst", "create", "update", "delete", "upsert", "count", "createMany", "updateMany", "deleteMany", "aggregate", "groupBy", "findUniqueOrThrow", "findFirstOrThrow"}


def decorators(c: Ctx, i: int) -> tuple[list[Ann], int]:
    out: list[Ann] = []
    while c.is_(i, "@") and c.t(i + 1) is not None and c.toks[i + 1].kind == "id":
        name, j = c.dotted_at(i + 1)
        line = c.toks[i].line
        if c.is_(j, "("):
            a, j = c.parse_args_ann(name.rsplit(".", 1)[-1], j, line)
        else:
            a = Ann(name.rsplit(".", 1)[-1], [], {}, line, line)
        out.append(a)
        i = j
    return out, i


def analyze(c: Ctx) -> None:
    members(c, 0, len(c.toks), "", None, top=True)
    boundaries(c)


def members(c: Ctx, i: int, end: int, parent_q: str, class_name: str | None, top: bool = False) -> None:
    toks = c.toks
    while i < end:
        t = toks[i]
        if t.kind == "punct" and t.val in (";", "}", ","):
            i += 1
            continue
        if t.kind == "id" and t.val == "import" and not c.is_(i + 1, "("):
            i = import_stmt(c, i, end)
            continue
        if t.kind == "id" and t.val == "export" and (c.is_(i + 1, "*") or c.is_(i + 1, "{")):
            j = i + 1
            names, src = [], None
            if c.is_(j, "{"):
                names = [x.val for x in toks[j + 1:c.match.get(j, j)] if x.kind == "id" and x.val not in ("as", "type")]
                j = c.skip_group(j)
            else:
                j += 1
            if j < end and toks[j].val == "from" and j + 1 < end and toks[j + 1].kind == "str":
                c.add_import(t.line, toks[j + 1].val, names, "re-export")
                j += 2
            i = j
            continue
        doc0 = toks[i].doc
        anns, i = decorators(c, i)
        if i >= end:
            break
        start = toks[i]
        if not start.doc:
            start.doc = doc0
        mods = []
        while i < end and toks[i].kind == "id" and toks[i].val in MODS and not (toks[i].val in ("get", "set", "async", "static", "readonly") and (c.is_(i + 1, "(") or c.is_(i + 1, ":") or c.is_(i + 1, "="))):
            mods.append(toks[i].val)
            i += 1
        if i >= end:
            break
        v = toks[i]
        if v.kind == "id" and v.val in ("class", "interface", "enum") and c.t(i + 1) is not None and toks[i + 1].kind == "id":
            i = type_decl(c, i, end, parent_q, anns, mods, start.doc, start.line)
            continue
        if v.kind == "id" and v.val == "type" and c.t(i + 1) is not None and toks[i + 1].kind == "id" and (c.is_(i + 2, "=") or c.is_(i + 2, "<")):
            j = i + 2
            while j < end and not c.is_(j, ";") and not (toks[j].line > toks[i].line and j > i + 3 and toks[j].kind == "id" and toks[j].val in ("export", "type", "const", "function", "class", "interface") ):
                j = c.skip_group(j) if toks[j].kind == "punct" and toks[j].val in ("{", "(", "[") else j + 1
            name = toks[i + 1].val
            c.add_symbol(f"{parent_q}.{name}" if parent_q else name, name, "type", start.line, toks[min(j, len(toks) - 1)].line, parent=parent_q or None, signature=f"type {name}", modifiers=mods, doc=start.doc)
            i = j + 1
            continue
        if v.kind == "id" and v.val == "namespace" or v.kind == "id" and v.val == "module" and c.t(i + 1) is not None and toks[i + 1].kind in ("id", "str"):
            nm = toks[i + 1].val
            j = i + 2
            while j < end and not c.is_(j, "{"):
                j += 1
            if j < end:
                close = c.match.get(j, j)
                q = f"{parent_q}.{nm}" if parent_q else nm
                c.add_symbol(q, nm, "namespace", start.line, toks[close].end, parent=parent_q or None, signature=f"namespace {nm}", modifiers=mods)
                members(c, j + 1, close, q, None)
                i = close + 1
                continue
        if v.kind == "id" and v.val == "function":
            j = i + 1
            if c.is_(j, "*"):
                j += 1
            if j < end and toks[j].kind == "id":
                name = toks[j].val
                i = func_like(c, i, j + 1, end, name, parent_q, "function", start, mods, anns)
                continue
        if v.kind == "id" and v.val in ("const", "let", "var") and top_like(parent_q, class_name):
            j = i + 1
            if j < end and toks[j].kind == "id":
                name = toks[j].val
                k = j + 1
                while k < end and not c.is_(k, "=") and not c.is_(k, ";"):
                    k = c.skip_group(k) if toks[k].kind == "punct" and toks[k].val in ("<", "(", "[", "{") and False else k + 1
                    if k - j > 40:
                        break
                if c.is_(k, "=") and is_function_value(c, k + 1, end):
                    i = func_like(c, i, k + 1, end, name, parent_q, "function", start, mods, anns, value=True)
                    continue
                if "export" in mods or True:
                    last = skip_statement(c, k, end)
                    c.add_symbol(f"{parent_q}.{name}" if parent_q else name, name, "variable", start.line, toks[min(last, len(toks) - 1)].line, parent=parent_q or None,
                                 signature=f"{v.val} {name}", modifiers=mods, doc=start.doc)
                    i = max(last + 1, i + 1)
                    continue
        if class_name is not None and v.kind == "id" and (c.is_(i + 1, "(") or (c.is_(i + 1, "<") and False)):
            name = v.val
            kind = "constructor" if name == "constructor" else "method"
            i = func_like(c, i, i + 1, end, name, parent_q, kind, start, mods, anns)
            continue
        if class_name is not None and v.kind == "id" and (c.is_(i + 1, ":") or c.is_(i + 1, "=") or c.is_(i + 1, "?") or c.is_(i + 1, "!")):
            last = skip_statement(c, i + 1, end)
            q = f"{parent_q}.{v.val}"
            c.add_symbol(q, v.val, "field", start.line, toks[min(last, len(toks) - 1)].line, parent=parent_q, signature=v.val, modifiers=mods, annotations=[a.name for a in anns], doc=start.doc)
            if any(a.name in ("Column", "PrimaryGeneratedColumn") for a in anns):
                pass
            i = max(last + 1, i + 1)
            continue
        i = skip_statement(c, i, end) + 1 if top_like(parent_q, class_name) else i + 1


def top_like(parent_q: str, class_name: str | None) -> bool:
    return class_name is None


def is_function_value(c: Ctx, i: int, end: int) -> bool:
    j = i
    if c.is_(j, "async"):
        j += 1
    if c.is_(j, "function"):
        return True
    if c.is_(j, "("):
        k = c.skip_group(j)
        while k < end and not c.is_(k, "=>") and k - j < 80 and not c.is_(k, ";") and not c.is_(k, "{"):
            k += 1                                     # return type annotation
        return c.is_(k, "=>")
    if j < end and c.toks[j].kind == "id" and c.is_(j + 1, "=>"):
        return True
    return False


def skip_statement(c: Ctx, i: int, end: int) -> int:
    j = i
    toks = c.toks
    first_line = toks[i].line if i < len(toks) else 0
    while j < end:
        v = toks[j]
        if v.kind == "punct" and v.val == ";":
            return j
        if v.kind == "punct" and v.val in ("{", "(", "["):
            j = c.skip_group(j)
            continue
        if v.kind == "punct" and v.val == "}":
            return j - 1
        if j > i and v.line > toks[j - 1].end and v.kind == "id" and v.val in ("export", "const", "let", "var", "function", "class", "interface", "type", "enum", "import", "async") and toks[j - 1].val not in ("=", ",", "(", "=>", "?", ":", "&&", "||"):
            return j - 1
        j += 1
    return max(end - 1, i)


def import_stmt(c: Ctx, i: int, end: int) -> int:
    toks = c.toks
    line = toks[i].line
    j = i + 1
    names: list[str] = []
    if c.is_(j, "type"):
        j += 1
    while j < end and toks[j].kind != "str" and not c.is_(j, ";"):
        if c.is_(j, "{"):
            names += [x.val for x in toks[j + 1:c.match.get(j, j)] if x.kind == "id" and x.val not in ("as", "type")]
            j = c.skip_group(j)
            continue
        if toks[j].kind == "id" and toks[j].val != "from":
            names.append(toks[j].val)
        j += 1
    if j < end and toks[j].kind == "str":
        c.add_import(line, toks[j].val, names, "import", toks[j].line)
        j += 1
    return j + (1 if c.is_(j, ";") else 0)


def func_like(c: Ctx, i: int, j: int, end: int, name: str, parent_q: str, kind: str, start, mods, anns, value: bool = False) -> int:
    toks = c.toks
    k = j
    if c.is_(k, "<"):
        k = c.skip_generics(k)
    if value:
        while k < end and not c.is_(k, "=>") and not c.is_(k, "{") and not (c.is_(k, "(") and False):
            k = c.skip_group(k) if c.is_(k, "(") else k + 1
            if k - j > 200:
                break
        if c.is_(k, "=>"):
            k += 1
    else:
        if c.is_(k, "("):
            k = c.skip_group(k)
        while k < end and not c.is_(k, "{") and not c.is_(k, ";"):
            k = c.skip_group(k) if toks[k].kind == "punct" and toks[k].val in ("(", "[") else k + 1
            if k - j > 200:
                break
    if k < end and c.is_(k, "{"):
        close = c.match.get(k, k)
        last, nxt = toks[close].end, close + 1
    else:
        last_i = skip_statement(c, min(k, end - 1), end)
        last, nxt = toks[min(last_i, len(toks) - 1)].line, last_i + 1
    q = f"{parent_q}.{name}" if parent_q else name
    sig = " ".join(x.val for x in toks[i:min(j + 40, k)] if x.kind in ("id", "punct"))[:200]
    c.add_symbol(q, name, kind, start.line, last, parent=parent_q or None, signature=sig, modifiers=mods, annotations=[a.name for a in anns], doc=start.doc)
    for a in anns:
        if a.name in NEST_VERBS:
            cls_anns = c.class_anns.get(parent_q, [])
            prefix = next((x.first("path", "value") for x in cls_anns if x.name == "Controller"), None)
            path = a.first("path", "value")
            r = "/" + "/".join(p.strip("/") for p in (prefix or "", path or "") if p and p.strip("/"))
            c.bnd("http-route", f"{NEST_VERBS[a.name]} {r if r != '/' or (prefix or path) else '/'}", start.line, last, framework="nestjs", symbol=q, details={"handler": q}, confidence="high")
        elif a.name in ("MessagePattern", "EventPattern", "SubscribeMessage"):
            c.bnd("event-subscribe", a.first("cmd", "value") or "<dynamic>", start.line, last, framework="nestjs", symbol=q, details={"handler": q, "decorator": a.name})
    if kind == "function" and name == "main" and not parent_q:
        c.bnd("entry-point", "main", start.line, last, framework="node", symbol=q, details={})
    return nxt


def type_decl(c: Ctx, i: int, end: int, parent_q: str, anns: list[Ann], mods, doc: str, start_line: int) -> int:
    toks = c.toks
    kw = toks[i].val
    name = toks[i + 1].val
    j = c.skip_generics(i + 2)
    bases: list[str] = []
    role = None
    while j < end and not c.is_(j, "{"):
        v = toks[j]
        if v.kind == "id" and v.val in ("extends", "implements"):
            role = v.val
        elif v.kind == "id" and role:
            d, j2 = c.dotted_at(j)
            bases.append(d)
            j = j2
            continue
        elif c.is_(j, "<"):
            j = c.skip_generics(j)
            continue
        j += 1
    kind = {"class": "class", "interface": "interface", "enum": "enum"}[kw]
    q = f"{parent_q}.{name}" if parent_q else name
    if j >= end:
        c.add_symbol(q, name, kind, start_line, start_line, parent=parent_q or None, signature=f"{kw} {name}", modifiers=mods, annotations=[a.name for a in anns], bases=bases, doc=doc)
        return end
    close = c.match.get(j, j)
    c.add_symbol(q, name, kind, start_line, toks[close].end, parent=parent_q or None, signature=f"{kw} {name}", modifiers=mods, annotations=[a.name for a in anns], bases=bases, doc=doc)
    c.class_anns[q] = anns
    for a in anns:
        if a.name == "Entity":
            c.bnd("db-table", a.first("name", "value") or name, start_line, toks[close].end, framework="typeorm", symbol=q, details={"entity": name}, confidence="high")
        elif a.name == "Controller":
            pass
        elif a.name == "Injectable" or a.name == "Module":
            pass
    if kw == "enum":
        k = j + 1
        while k < close:
            if toks[k].kind == "id":
                c.add_symbol(f"{q}.{toks[k].val}", toks[k].val, "field", toks[k].line, toks[k].line, parent=q, signature=f"constant {toks[k].val}", modifiers=("enum-constant",))
                k += 1
                while k < close and not c.is_(k, ","):
                    k = c.skip_group(k) if toks[k].kind == "punct" and toks[k].val in ("(", "{", "[") else k + 1
            else:
                k += 1
        return close + 1
    members(c, j + 1, close, q, name)
    return close + 1


def boundaries(c: Ctx) -> None:
    toks = c.toks
    for call in c.calls():
        name, recv = call.name, call.receiver
        rl = recv.lower().split(".")[-1] if recv else ""
        lit, dyn = c.first_str(call)
        if name in ROUTE_VERBS and lit is not None and lit.startswith("/") and (rl in ROUTER_NAMES or rl.endswith("router") or rl.endswith("app") or rl.endswith("routes")):
            c.bnd("http-route", f"{name.upper() if name != 'all' else 'ANY'} {lit}", call.line, call.end, framework="express-like", details={"router": recv})
        elif name == "route" and lit is not None and lit.startswith("/") and rl in ROUTER_NAMES:
            c.bnd("http-route", f"ANY {lit}", call.line, call.end, framework="express-like", details={"router": recv})
        elif name == "fetch" and not recv:
            c.bnd("http-client", url_name("HTTP", lit, dyn), call.line, call.end, framework="fetch", dynamic=bool(dyn or lit is None))
        elif name in HTTP_CLIENT_FNS and rl in ("axios", "http", "httpclient", "got", "superagent", "request", "client", "api") and (lit is not None or dyn):
            c.bnd("http-client", url_name(name.upper() if name != "request" else "HTTP", lit, dyn), call.line, call.end, framework="axios-like", dynamic=bool(dyn or lit is None), confidence="medium")
        elif name == "send" and ("producer" in rl or "kafka" in rl):
            topic = next((toks[k + 2].val for k in range(call.lp, call.rp) if toks[k].kind == "id" and toks[k].val == "topic" and c.is_(k + 1, ":") and toks[k + 2].kind == "str"), None)
            c.bnd("event-publish", topic or "<dynamic>", call.line, call.end, framework="kafkajs", dynamic=topic is None)
        elif name == "subscribe" and "consumer" in rl:
            topic = next((toks[k + 2].val for k in range(call.lp, call.rp) if toks[k].kind == "id" and toks[k].val in ("topic",) and c.is_(k + 1, ":") and toks[k + 2].kind == "str"), None)
            c.bnd("event-subscribe", topic or "<dynamic>", call.line, call.end, framework="kafkajs", dynamic=topic is None)
        elif name in PRISMA_OPS and rl.startswith("prisma") or (name in PRISMA_OPS and "." in recv and recv.split(".")[0].lower().startswith("prisma")):
            model = recv.split(".")[-1]
            c.bnd("db-table", model, call.line, call.end, framework="prisma", details={"operation": name}, confidence="medium")
        elif name in ("query", "execute", "raw") and lit and sqlutil.looks_like_sql(lit):
            pass
        elif name in ("define",) and "sequelize" in rl and lit:
            c.bnd("db-table", lit, call.line, call.end, framework="sequelize", confidence="medium")
        elif name in ("model",) and "mongoose" in rl and lit:
            c.bnd("db-table", lit, call.line, call.end, framework="mongoose", confidence="medium")
        elif name == "require" and not recv and lit:
            c.add_import(call.line, lit, (), "require")
        elif name == "import" and not recv and lit:
            c.add_import(call.line, lit, (), "dynamic-import")
    for i, t in enumerate(toks):                      # process.env.NAME / process.env["NAME"]
        if t.kind == "id" and t.val == "env" and i >= 2 and toks[i - 1].val == "." and toks[i - 2].val == "process":
            if c.is_(i + 1, ".") and i + 2 < len(toks) and toks[i + 2].kind == "id":
                c.bnd("config-env", toks[i + 2].val, t.line, t.end, framework="node", details={"access": "process.env"})
            elif c.is_(i + 1, "[") and i + 2 < len(toks) and toks[i + 2].kind == "str":
                c.bnd("config-env", toks[i + 2].val, t.line, t.end, framework="node", details={"access": "process.env"})
        if t.kind == "id" and t.val == "createServer" and False:
            pass
    c.sql_literals()
