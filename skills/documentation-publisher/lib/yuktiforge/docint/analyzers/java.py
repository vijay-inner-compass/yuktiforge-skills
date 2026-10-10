"""Java: lexical declarations (package, imports, classes/interfaces/enums/records, methods, fields) and framework patterns (Spring, JAX-RS, JPA,
Spring Data, Kafka/Rabbit/JMS, RestTemplate/Feign, config). Pattern-level: no type resolution, no annotation processing, no Lombok expansion."""
from __future__ import annotations

from yuktiforge.docint.analyzers.lexfacts import Ann, Ctx, url_name
from yuktiforge.docint.model import clip

MODS = frozenset({"public", "private", "protected", "static", "final", "abstract", "synchronized", "native", "transient", "volatile", "strictfp", "default", "sealed", "non-sealed"})
TYPE_KW = ("class", "interface", "enum", "record")
SPRING_VERBS = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT", "DeleteMapping": "DELETE", "PatchMapping": "PATCH"}
JAXRS_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
REPO_BASES = ("JpaRepository", "CrudRepository", "PagingAndSortingRepository", "MongoRepository", "ReactiveCrudRepository", "R2dbcRepository", "ListCrudRepository", "Repository", "JpaSpecificationExecutor")


def analyze(c: Ctx) -> None:
    i, n = 0, len(c.toks)
    pkg = ""
    while i < n:
        t = c.toks[i]
        if t.val == "package" and t.kind == "id":
            pkg, i = c.dotted_at(i + 1)
            c.add_symbol(pkg, pkg.rsplit(".", 1)[-1], "namespace", t.line, t.line, parent=None, signature=f"package {pkg}")
            continue
        if t.val == "import" and t.kind == "id":
            j = i + 1
            static = c.is_(j, "static")
            j += 1 if static else 0
            name, k = c.dotted_at(j)
            wildcard = c.is_(k, ".") and c.is_(k + 1, "*")
            if wildcard:
                k += 2
            c.add_import(t.line, name + (".*" if wildcard else ""), (), "import", c.t(k).line if c.t(k) else t.line)
            i = k + 1
            continue
        if t.kind == "punct" and t.val == ";":
            i += 1
            continue
        break
    members(c, i, n, pkg or "", None, None)
    boundaries(c)


def read_annotations(c: Ctx, i: int) -> tuple[list[Ann], int]:
    anns: list[Ann] = []
    while c.is_(i, "@") and not c.is_(i + 1, "interface") and c.t(i + 1) is not None and c.toks[i + 1].kind == "id":
        name, j = c.dotted_at(i + 1)
        line = c.toks[i].line
        if c.is_(j, "("):
            a, j = c.parse_args_ann(name.rsplit(".", 1)[-1], j, line)
        else:
            a = Ann(name.rsplit(".", 1)[-1], [], {}, line, line)
        anns.append(a)
        i = j
    return anns, i


def members(c: Ctx, i: int, end: int, parent_q: str, class_name: str | None, parent_kind: str | None) -> None:
    toks = c.toks
    while i < end:
        t = toks[i]
        if t.kind == "punct" and t.val in (";", "}"):
            i += 1
            continue
        if t.kind == "punct" and t.val == "{":              # initializer block
            i = c.skip_group(i)
            continue
        doc0 = toks[i].doc
        anns, i = read_annotations(c, i)
        if i >= end:
            break
        start_tok = toks[i]
        if not start_tok.doc:
            start_tok.doc = doc0
        mods = []
        while i < end and toks[i].kind == "id" and toks[i].val in MODS:
            mods.append(toks[i].val)
            i += 1
        if i >= end:
            break
        is_ann_type = c.is_(i, "@") and c.is_(i + 1, "interface")
        if is_ann_type or (toks[i].kind == "id" and toks[i].val in TYPE_KW and c.t(i + 1) is not None and toks[i + 1].kind == "id"):
            i = type_decl(c, i + (1 if is_ann_type else 0), end, parent_q, anns, mods, start_tok.doc, start_tok.line)
            continue
        # method / constructor / field
        j, paren = i, None
        while j < end:
            v = toks[j]
            if v.kind == "punct" and v.val in ("{", ";", "=") :
                break
            if v.kind == "punct" and v.val == "(":
                if paren is None:
                    paren = j
                j = c.skip_group(j)
                continue
            if v.kind == "punct" and v.val == "<":
                j = c.skip_generics(j)
                continue
            if v.kind == "punct" and v.val in ("[", ):
                j = c.skip_group(j)
                continue
            j += 1
        if paren is not None and paren > i and toks[paren - 1].kind == "id":
            name = toks[paren - 1].val
            ret_tokens = [x.val for x in toks[i:paren - 1] if x.kind in ("id", "punct")]
            kind = "constructor" if name == class_name and not [r for r in ret_tokens if r not in ("<", ">", ",")] or (name == class_name and not ret_tokens) else "method"
            after = c.match.get(paren, paren) + 1
            k = after
            while k < end and not (toks[k].kind == "punct" and toks[k].val in ("{", ";")):
                k += 1
            if k < end and toks[k].val == "{":
                body_end = c.match.get(k, k)
                last = toks[body_end].end if body_end < len(toks) else toks[k].end
                nxt = body_end + 1
            else:
                last, nxt = (toks[k].line if k < end else toks[-1].end), k + 1
            q = f"{parent_q}.{name}" if parent_q else name
            sig = " ".join(x.val for x in toks[i:c.match.get(paren, paren) + 1] if x.kind in ("id", "punct", "str"))
            c.add_symbol(q, name, kind, start_tok.line, last, parent=parent_q or None, signature=sig, modifiers=mods, annotations=[a.name for a in anns], doc=start_tok.doc)
            method_boundaries(c, name, q, anns, start_tok.line, last)
            i = nxt
            continue
        # field (or enum constant list handled by type_decl)
        k = j
        depth_skip = k
        while depth_skip < end and not (toks[depth_skip].kind == "punct" and toks[depth_skip].val == ";"):
            if toks[depth_skip].kind == "punct" and toks[depth_skip].val in ("{", "(", "["):
                depth_skip = c.skip_group(depth_skip)
                continue
            depth_skip += 1
        names = [x for x in toks[i:k] if x.kind == "id" and x.val not in MODS]
        if names and k > i:
            fname = names[-1].val
            q = f"{parent_q}.{fname}" if parent_q else fname
            line_end = toks[min(depth_skip, len(toks) - 1)].line
            c.add_symbol(q, fname, "field", start_tok.line, line_end, parent=parent_q or None, signature=" ".join(x.val for x in toks[i:k] if x.kind in ("id", "punct")), modifiers=mods,
                         annotations=[a.name for a in anns], doc=start_tok.doc)
            field_boundaries(c, anns, fname, q, start_tok.line, line_end)
        i = max(depth_skip + 1, i + 1)


def type_decl(c: Ctx, i: int, end: int, parent_q: str, anns: list[Ann], mods: list[str], doc: str, start_line: int) -> int:
    toks = c.toks
    kw = toks[i].val
    kind = {"class": "class", "interface": "interface", "enum": "enum", "record": "record"}.get(kw, "interface")
    name = toks[i + 1].val
    j = i + 2
    j = c.skip_generics(j)
    if kw == "record" and c.is_(j, "("):
        comps = " ".join(x.val for x in toks[j:c.match.get(j, j) + 1] if x.kind in ("id", "punct"))
        j = c.skip_group(j)
    else:
        comps = ""
    bases: list[str] = []
    role = None
    while j < end and not (toks[j].kind == "punct" and toks[j].val in ("{", ";")):
        v = toks[j]
        if v.kind == "id" and v.val in ("extends", "implements", "permits"):
            role = v.val
            j += 1
            continue
        if v.kind == "punct" and v.val == "<":
            j = c.skip_generics(j)
            continue
        if v.kind == "id" and role in ("extends", "implements"):
            dotted, j2 = c.dotted_at(j)
            bases.append(dotted.rsplit(".", 1)[-1] if False else dotted)
            j = j2
            continue
        j += 1
    q = f"{parent_q}.{name}" if parent_q else name
    if j >= end or toks[j].val != "{":
        c.add_symbol(q, name, kind, start_line, toks[min(j, len(toks) - 1)].line, parent=parent_q or None, signature=f"{kw} {name}", modifiers=mods, annotations=[a.name for a in anns], bases=bases, doc=doc)
        return j + 1
    close = c.match.get(j, min(j, len(toks) - 1))
    last = toks[close].end
    c.add_symbol(q, name, kind, start_line, last, parent=parent_q or None, signature=f"{' '.join(mods)} {kw} {name}{comps}".strip(), modifiers=mods, annotations=[a.name for a in anns], bases=bases, doc=doc)
    c.class_anns[q] = anns
    class_boundaries(c, name, q, kw, anns, bases, start_line, last)
    body = j + 1
    if kw == "enum":
        body = enum_constants(c, body, close, q)
    members(c, body, close, q, name, kw)
    return close + 1


def enum_constants(c: Ctx, i: int, close: int, q: str) -> int:
    toks = c.toks
    while i < close:
        _, i = read_annotations(c, i)
        if toks[i].kind == "id":
            t = toks[i]
            i += 1
            if c.is_(i, "("):
                i = c.skip_group(i)
            if c.is_(i, "{"):
                i = c.skip_group(i)
            c.add_symbol(f"{q}.{t.val}", t.val, "field", t.line, t.line, parent=q, signature=f"constant {t.val}", modifiers=("enum-constant",))
        if i < close and toks[i].val == ",":
            i += 1
            continue
        if i < close and toks[i].val == ";":
            return i + 1
        if i >= close or toks[i].kind != "id":
            return i if i < close and toks[i].val != "," else i
    return i


# ---------------------------------------------------------------- boundaries
def _join(prefix: str | None, path: str | None) -> str:
    return "/" + "/".join(x.strip("/") for x in (prefix or "", path or "") if x and x.strip("/")) if (prefix or path) else "/"


def class_boundaries(c: Ctx, name: str, q: str, kw: str, anns: list[Ann], bases: list[str], start: int, end: int) -> None:
    names = {a.name for a in anns}
    for a in anns:
        if a.name == "Entity" or a.name == "Document":
            tbl = next((x.first("name", "value") for x in anns if x.name == "Table"), None) or a.first("name", "value") or name
            c.bnd("db-table", tbl, start, end, framework="jpa" if a.name == "Entity" else "mongodb", symbol=q, details={"entity": name}, confidence="high" if a.name == "Entity" else "medium")
        elif a.name == "FeignClient":
            url = a.first("url") or a.first("name", "value")
            c.bnd("http-client", url_name("HTTP", url, url is None), start, end, framework="feign", symbol=q, details={"client": name}, dynamic=url is None)
        elif a.name == "ConfigurationProperties":
            p = a.first("prefix", "value")
            if p:
                c.bnd("config-env", p + ".*", start, end, framework="spring", symbol=q, details={"access": "@ConfigurationProperties"})
        elif a.name == "SpringBootApplication":
            c.bnd("entry-point", "SpringBootApplication", start, end, framework="spring", symbol=q, details={"class": name}, confidence="high")
    if kw == "interface":
        for b in bases:
            base_simple = b.rsplit(".", 1)[-1]
            if base_simple in REPO_BASES and "<" not in b:
                ent = _repo_entity(c, q)
                if ent:
                    c.bnd("db-table", ent, start, end, framework="spring-data", symbol=q, details={"repository": name, "access": "spring-data"}, confidence="medium")
                break


def _repo_entity(c: Ctx, q: str) -> str | None:
    """Entity type argument of `extends JpaRepository<Entity, Id>`: look at the tokens of the declaration line."""
    sym = next((s for s in c.symbols if s.qualified_name == q), None)
    if sym is None:
        return None
    toks = [t for t in c.toks if sym.prov.start_line <= t.line <= sym.prov.start_line + 2]
    for k, t in enumerate(toks):
        if t.kind == "id" and t.val in REPO_BASES and k + 2 < len(toks) and toks[k + 1].val == "<" and toks[k + 2].kind == "id":
            return toks[k + 2].val
    return None


def method_boundaries(c: Ctx, name: str, q: str, anns: list[Ann], start: int, end: int) -> None:
    cls_q = q.rsplit(".", 1)[0]
    cls_anns = _class_annotations(c, cls_q)
    prefix = None
    for a in cls_anns:
        if a.name in ("RequestMapping", "Path"):
            prefix = a.first("value", "path")
    for a in anns:
        if a.name in SPRING_VERBS:
            c.bnd("http-route", f"{SPRING_VERBS[a.name]} {_join(prefix, a.first('value', 'path'))}", start, end, framework="spring", symbol=q, details={"handler": q}, confidence="high")
        elif a.name == "RequestMapping":
            verbs = [v.rsplit(".", 1)[-1] for v in a.kv.get("method", [])] or ["ANY"]
            c.bnd("http-route", f"{'/'.join(verbs)} {_join(prefix, a.first('value', 'path'))}", start, end, framework="spring", symbol=q, details={"handler": q}, confidence="high")
        elif a.name in JAXRS_VERBS:
            mpath = next((x.first("value") for x in anns if x.name == "Path"), None)
            c.bnd("http-route", f"{a.name} {_join(prefix, mpath)}", start, end, framework="jax-rs", symbol=q, details={"handler": q}, confidence="high")
        elif a.name in ("KafkaListener", "RabbitListener", "JmsListener", "SqsListener", "StreamListener", "EventListener", "TransactionalEventListener"):
            key = {"KafkaListener": ("topics", "topicPattern", "value"), "RabbitListener": ("queues", "value"), "JmsListener": ("destination", "value"), "SqsListener": ("value", "queueNames")}.get(a.name, ("value",))
            for dest in (a.kv.get(key[0]) or a.kv.get(key[-1]) or a.pos or ["<dynamic>"]):
                c.bnd("event-subscribe", dest, start, end, framework=a.name.replace("Listener", "").lower() or "spring", symbol=q, details={"handler": q, "annotation": a.name},
                      dynamic=dest == "<dynamic>")
        elif a.name == "Value":
            v = a.first("value")
            if v and v.startswith("${"):
                c.bnd("config-env", v[2:].split(":", 1)[0].rstrip("}"), start, end, framework="spring", symbol=q, details={"access": "@Value"})
    if name == "main" and "static" in c.symbols[-1].modifiers:
        c.bnd("entry-point", "main", start, end, framework="java", symbol=q, details={"class": cls_q}, confidence="high")


def field_boundaries(c: Ctx, anns: list[Ann], fname: str, q: str, start: int, end: int) -> None:
    for a in anns:
        if a.name == "Value":
            v = a.first("value")
            if v and v.startswith("${"):
                c.bnd("config-env", v[2:].split(":", 1)[0].rstrip("}"), start, end, framework="spring", symbol=q, details={"access": "@Value"})


def _class_annotations(c: Ctx, cls_q: str) -> list[Ann]:
    return c.class_anns.get(cls_q, [])


def boundaries(c: Ctx) -> None:
    for call in c.calls():
        name, recv = call.name, call.receiver.lower()
        lit, dyn = c.first_str(call)
        if name in ("getForObject", "getForEntity", "postForObject", "postForEntity", "exchange", "put", "delete", "patchForObject", "postForLocation") and "resttemplate" in recv.replace("_", ""):
            verb = {"getForObject": "GET", "getForEntity": "GET", "postForObject": "POST", "postForEntity": "POST", "put": "PUT", "delete": "DELETE", "patchForObject": "PATCH"}.get(name, "HTTP")
            c.bnd("http-client", url_name(verb, lit, dyn), call.line, call.end, framework="resttemplate", dynamic=dyn or lit is None)
        elif name == "uri" and "webclient" in recv.replace("_", "") or (name == "uri" and "client" in recv):
            c.bnd("http-client", url_name("HTTP", lit, dyn), call.line, call.end, framework="webclient", dynamic=dyn or lit is None)
        elif name == "create" and call.receiver == "URI" and lit and lit.startswith("http"):
            c.bnd("http-client", url_name("HTTP", lit, False), call.line, call.end, framework="java.net.http")
        elif name in ("send", "sendDefault") and ("kafka" in recv or "template" in recv and "kafka" in recv):
            c.bnd("event-publish", lit or "<dynamic>", call.line, call.end, framework="kafka", dynamic=dyn or lit is None)
        elif name in ("convertAndSend", "send") and ("rabbit" in recv or "amqp" in recv):
            c.bnd("event-publish", lit or "<dynamic>", call.line, call.end, framework="rabbitmq", dynamic=dyn or lit is None)
        elif name in ("convertAndSend", "send") and "jms" in recv:
            c.bnd("event-publish", lit or "<dynamic>", call.line, call.end, framework="jms", dynamic=dyn or lit is None)
        elif name == "getenv" and call.receiver == "System" and lit:
            c.bnd("config-env", lit, call.line, call.end, framework="java", details={"access": "System.getenv"})
        elif name in ("getProperty", "getRequiredProperty") and "env" in recv and lit:
            c.bnd("config-env", lit, call.line, call.end, framework="spring", details={"access": "Environment.getProperty"})
        elif name in ("createQuery", "createNativeQuery", "prepareStatement", "createStatement") and lit:
            pass       # the SQL literal itself is picked up below
    c.sql_literals()
