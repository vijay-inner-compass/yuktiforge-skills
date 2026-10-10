"""C#: namespaces, using directives, types, members, ASP.NET (attribute routing + minimal APIs), EF Core, messaging, HttpClient, configuration.
Lexical: no Roslyn, no source generators, no partial-class merging, preprocessor directives ignored."""
from __future__ import annotations

from yuktiforge.docint.analyzers import sqlutil
from yuktiforge.docint.analyzers.lexfacts import Ann, Ctx, url_name
from yuktiforge.docint.model import clip

MODS = frozenset({"public", "private", "protected", "internal", "static", "readonly", "abstract", "virtual", "override", "sealed", "async", "partial", "extern", "unsafe", "new", "const",
                  "volatile", "required", "file"})
TYPE_KW = {"class": "class", "interface": "interface", "struct": "struct", "enum": "enum", "record": "record"}
HTTP_ATTR = {"HttpGet": "GET", "HttpPost": "POST", "HttpPut": "PUT", "HttpDelete": "DELETE", "HttpPatch": "PATCH", "HttpHead": "HEAD", "HttpOptions": "OPTIONS"}
MINIMAL = {"MapGet": "GET", "MapPost": "POST", "MapPut": "PUT", "MapDelete": "DELETE", "MapPatch": "PATCH"}


def attrs(c: Ctx, i: int) -> tuple[list[Ann], int]:
    out: list[Ann] = []
    while c.is_(i, "["):
        close = c.match.get(i, i)
        j = i + 1
        while j < close:
            if c.toks[j].kind == "id":
                name, k = c.dotted_at(j)
                line = c.toks[j].line
                if c.is_(k, "("):
                    a, k = c.parse_args_ann(name.rsplit(".", 1)[-1].removesuffix("Attribute"), k, line)
                else:
                    a = Ann(name.rsplit(".", 1)[-1].removesuffix("Attribute"), [], {}, line, line)
                out.append(a)
                j = k
            else:
                j += 1
        i = close + 1
    return out, i


def analyze(c: Ctx) -> None:
    toks, n = c.toks, len(c.toks)
    i, ns = 0, ""
    while i < n:
        if c.is_(i, "using") and not c.is_(i + 1, "("):
            j = i + 1
            static = c.is_(j, "static")
            j += 1 if static else 0
            name, k = c.dotted_at(j)
            if c.is_(k, "="):                          # using Alias = X.Y;
                tgt, k = c.dotted_at(k + 1)
                name = tgt
            if name:
                c.add_import(toks[i].line, name, (), "using-static" if static else "using")
            while k < n and not c.is_(k, ";"):
                k += 1
            i = k + 1
            continue
        break
    members(c, i, n, "", None)
    boundaries(c)


def members(c: Ctx, i: int, end: int, parent_q: str, class_name: str | None) -> None:
    toks = c.toks
    while i < end:
        t = toks[i]
        if t.kind == "punct" and t.val in (";", "}"):
            i += 1
            continue
        if t.kind == "id" and t.val == "using" and not c.is_(i + 1, "("):
            j = i
            while j < end and not c.is_(j, ";"):
                j += 1
            name, _ = c.dotted_at(i + (2 if c.is_(i + 1, "static") else 1))
            if name:
                c.add_import(t.line, name, (), "using")
            i = j + 1
            continue
        if t.kind == "id" and t.val == "namespace":
            name, j = c.dotted_at(i + 1)
            q = f"{parent_q}.{name}" if parent_q else name
            if c.is_(j, "{"):
                close = c.match.get(j, j)
                c.add_symbol(q, name.rsplit(".", 1)[-1], "namespace", t.line, toks[close].end, parent=parent_q or None, signature=f"namespace {name}")
                members(c, j + 1, close, q, None)
                i = close + 1
            else:                                       # file-scoped: applies to the rest of the file
                c.add_symbol(q, name.rsplit(".", 1)[-1], "namespace", t.line, c.n_lines, parent=parent_q or None, signature=f"namespace {name}")
                members(c, j + 1, end, q, None)
                return
            continue
        doc0 = toks[i].doc
        anns, i = attrs(c, i)
        if i >= end:
            break
        start = toks[i]
        if not start.doc:
            start.doc = doc0
        mods: list[str] = []
        while i < end and toks[i].kind == "id" and toks[i].val in MODS and not (toks[i].val == "new" and c.is_(i + 1, "(")):
            mods.append(toks[i].val)
            i += 1
        if i >= end:
            break
        if toks[i].kind == "id" and toks[i].val in TYPE_KW and c.t(i + 1) is not None and toks[i + 1].kind == "id" or (
                toks[i].kind == "id" and toks[i].val in ("record",) and c.is_(i + 1, "struct")):
            i = type_decl(c, i, end, parent_q, anns, mods, start.doc, start.line)
            continue
        # member
        j, paren, arrow, brace = i, None, None, None
        while j < end:
            v = toks[j]
            if v.kind == "punct" and v.val in (";", "="):
                break
            if v.kind == "punct" and v.val == "=>":
                arrow = j
                break
            if v.kind == "punct" and v.val == "{":
                brace = j
                break
            if v.kind == "punct" and v.val == "(":
                if paren is None:
                    paren = j
                j = c.skip_group(j)
                continue
            if v.kind == "punct" and v.val == "<":
                j = c.skip_generics(j)
                continue
            if v.kind == "punct" and v.val == "[":
                j = c.skip_group(j)
                continue
            j += 1
        if paren is not None and paren > i and toks[paren - 1].kind == "id":
            name = toks[paren - 1].val
            ret = [x.val for x in toks[i:paren - 1] if x.kind in ("id",)]
            kind = "constructor" if name == class_name and not ret else "method"
            k = c.match.get(paren, paren) + 1
            while k < end and not (toks[k].kind == "punct" and toks[k].val in ("{", ";", "=>")):
                k += 1                                   # where-constraints, base(...) calls
            if k < end and toks[k].val == "{":
                body_end = c.match.get(k, k)
                last, nxt = toks[body_end].end, body_end + 1
            else:                                        # => expression or abstract ;
                m = k
                while m < end and not c.is_(m, ";"):
                    m = c.skip_group(m) if toks[m].kind == "punct" and toks[m].val in ("(", "{", "[") else m + 1
                last, nxt = toks[min(m, len(toks) - 1)].line, m + 1
            q = f"{parent_q}.{name}" if parent_q else name
            sig = " ".join(x.val for x in toks[i:c.match.get(paren, paren) + 1] if x.kind in ("id", "punct", "str"))
            c.add_symbol(q, name, kind, start.line, last, parent=parent_q or None, signature=sig, modifiers=mods, annotations=[a.name for a in anns], doc=start.doc)
            method_boundaries(c, name, q, anns, start.line, last)
            i = nxt
            continue
        # property / field / event
        ids = [x for x in toks[i:j] if x.kind == "id"]
        if ids:
            pname = ids[-1].val
            if brace is not None:
                close = c.match.get(brace, brace)
                last, nxt, kind = toks[close].end, close + 1, "property"
                if c.is_(nxt, "="):                      # { get; set; } = init;
                    while nxt < end and not c.is_(nxt, ";"):
                        nxt += 1
                    nxt += 1
            else:
                m = j
                while m < end and not c.is_(m, ";"):
                    m = c.skip_group(m) if toks[m].kind == "punct" and toks[m].val in ("(", "{", "[") else m + 1
                last, nxt = toks[min(m, len(toks) - 1)].line, m + 1
                kind = "property" if arrow is not None else "field"
            q = f"{parent_q}.{pname}" if parent_q else pname
            c.add_symbol(q, pname, kind, start.line, last, parent=parent_q or None, signature=" ".join(x.val for x in toks[i:j] if x.kind in ("id", "punct")), modifiers=mods,
                         annotations=[a.name for a in anns], doc=start.doc)
            if kind == "property":
                ptype = toks[i:j]
                if len(ptype) >= 3 and ptype[0].val in ("DbSet",) or any(x.val == "DbSet" for x in ptype[:3]):
                    k = next(x for x, tk in enumerate(ptype) if tk.val == "DbSet")
                    if k + 2 < len(ptype) and ptype[k + 1].val == "<":
                        c.bnd("db-table", ptype[k + 2].val, start.line, last, framework="efcore", symbol=q, details={"entity": ptype[k + 2].val, "dbset": pname}, confidence="high")
            i = max(nxt, i + 1)
            continue
        i = max(j + 1, i + 1)


def type_decl(c: Ctx, i: int, end: int, parent_q: str, anns: list[Ann], mods: list[str], doc: str, start_line: int) -> int:
    toks = c.toks
    kw = toks[i].val
    if kw == "record" and c.is_(i + 1, "struct"):
        i += 1
    kind = TYPE_KW.get(toks[i].val, "class")
    name = toks[i + 1].val
    j = c.skip_generics(i + 2)
    if c.is_(j, "("):                                    # primary constructor / record parameters
        j = c.skip_group(j)
    bases: list[str] = []
    if c.is_(j, ":"):
        j += 1
        while j < end and not (toks[j].kind == "punct" and toks[j].val in ("{", ";")) and not c.is_(j, "where"):
            if toks[j].kind == "id":
                dotted, j2 = c.dotted_at(j)
                if c.is_(j2, "<"):
                    j3 = c.skip_generics(j2)
                    dotted += "<" + " ".join(x.val for x in toks[j2 + 1:j3 - 1]) + ">"
                    j2 = j3
                bases.append(dotted)
                j = j2
                continue
            j += 1
    while j < end and not (toks[j].kind == "punct" and toks[j].val in ("{", ";")):
        j += 1
    q = f"{parent_q}.{name}" if parent_q else name
    sig = f"{' '.join(mods)} {kind} {name}".strip()
    if j >= end or toks[j].val != "{":
        c.add_symbol(q, name, kind, start_line, toks[min(j, len(toks) - 1)].line, parent=parent_q or None, signature=sig, modifiers=mods, annotations=[a.name for a in anns], bases=bases, doc=doc)
        return j + 1
    close = c.match.get(j, min(j, len(toks) - 1))
    c.add_symbol(q, name, kind, start_line, toks[close].end, parent=parent_q or None, signature=sig, modifiers=mods, annotations=[a.name for a in anns], bases=bases, doc=doc)
    c.class_anns[q] = anns
    for a in anns:
        if a.name == "Table":
            c.bnd("db-table", a.first("Name", "name") or name, start_line, toks[close].end, framework="efcore", symbol=q, details={"entity": name}, confidence="high")
    for b in bases:
        base_name = b.split("<", 1)[0].rsplit(".", 1)[-1]
        if base_name == "IConsumer" and "<" in b:
            msg = b.split("<", 1)[1].rstrip(">").strip()
            c.bnd("event-subscribe", msg, start_line, toks[close].end, framework="masstransit", symbol=q, details={"consumer": name, "message_type": msg}, confidence="high")
        elif base_name in ("ControllerBase", "Controller", "ApiController"):
            pass
    if kind == "enum":
        k = j + 1
        while k < close:
            if toks[k].kind == "id":
                c.add_symbol(f"{q}.{toks[k].val}", toks[k].val, "field", toks[k].line, toks[k].line, parent=q, signature=f"constant {toks[k].val}", modifiers=("enum-constant",))
                k += 1
                if c.is_(k, "="):
                    while k < close and not c.is_(k, ","):
                        k += 1
            else:
                k += 1
        return close + 1
    members(c, j + 1, close, q, name)
    return close + 1


def _route(prefix: str | None, path: str | None, cls: str) -> str:
    parts = [x.strip("/") for x in (prefix, path) if x is not None and x.strip("/")]
    r = "/" + "/".join(parts) if parts else "/"
    return r.replace("[controller]", cls.removesuffix("Controller").lower())


def method_boundaries(c: Ctx, name: str, q: str, anns: list[Ann], start: int, end: int) -> None:
    cls_q = q.rsplit(".", 1)[0]
    cls = cls_q.rsplit(".", 1)[-1]
    cls_anns = c.class_anns.get(cls_q, [])
    prefix = next((a.first("template", "Template") for a in cls_anns if a.name == "Route"), None)
    for a in anns:
        if a.name in HTTP_ATTR:
            c.bnd("http-route", f"{HTTP_ATTR[a.name]} {_route(prefix, a.first('template', 'Template'), cls)}", start, end, framework="aspnet", symbol=q, details={"handler": q}, confidence="high")
        elif a.name == "Route" and not any(x.name in HTTP_ATTR for x in anns):
            c.bnd("http-route", f"ANY {_route(prefix, a.first('template', 'Template'), cls)}", start, end, framework="aspnet", symbol=q, details={"handler": q}, confidence="medium")
    if name == "Main" and "static" in c.symbols[-1].modifiers:
        c.bnd("entry-point", "Main", start, end, framework="dotnet", symbol=q, details={"class": cls_q}, confidence="high")


def boundaries(c: Ctx) -> None:
    for call in c.calls():
        name, recv = call.name, call.receiver.lower()
        lit, dyn = c.first_str(call)
        if name in MINIMAL:
            c.bnd("http-route", f"{MINIMAL[name]} {lit or '<dynamic>'}", call.line, call.end, framework="aspnet-minimal", dynamic=bool(dyn or lit is None))
        elif name in ("GetAsync", "PostAsync", "PutAsync", "DeleteAsync", "PatchAsync", "GetStringAsync", "GetFromJsonAsync", "PostAsJsonAsync", "PutAsJsonAsync", "SendAsync") and (
                "client" in recv or "http" in recv):
            verb = {"GetAsync": "GET", "GetStringAsync": "GET", "GetFromJsonAsync": "GET", "PostAsync": "POST", "PostAsJsonAsync": "POST", "PutAsync": "PUT", "PutAsJsonAsync": "PUT",
                    "DeleteAsync": "DELETE", "PatchAsync": "PATCH"}.get(name, "HTTP")
            c.bnd("http-client", url_name(verb, lit, dyn), call.line, call.end, framework="httpclient", dynamic=bool(dyn or lit is None))
        elif name in ("Publish", "Send", "PublishAsync", "SendAsync") and ("bus" in recv or "endpoint" in recv or "publish" in recv):
            c.bnd("event-publish", lit or "<message>", call.line, call.end, framework="masstransit", dynamic=bool(dyn or lit is None))
        elif name == "GetEnvironmentVariable" and lit:
            c.bnd("config-env", lit, call.line, call.end, framework="dotnet", details={"access": "Environment.GetEnvironmentVariable"})
        elif name in ("GetConnectionString", "GetSection", "GetValue") and "config" in recv and lit:
            c.bnd("config-env", lit, call.line, call.end, framework="dotnet", details={"access": f"IConfiguration.{name}"})
        elif name in ("FromSqlRaw", "ExecuteSqlRaw", "Query", "QueryAsync", "Execute", "ExecuteAsync", "ExecuteSqlInterpolated") and lit and sqlutil.looks_like_sql(lit):
            pass                                          # picked up by the SQL-literal pass
    c.sql_literals()
