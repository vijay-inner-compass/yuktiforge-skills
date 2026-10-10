"""Lexical analyzers for brace languages (Java, C#, Go, TypeScript/JavaScript). They read tokens, never run or compile anything, and report
pattern-level facts: no type resolution, no macro/preprocessor/code-generation expansion."""
from __future__ import annotations

from yuktiforge.docint.analyzers import csharp, golang, java, tsjs
from yuktiforge.docint.analyzers.base import Capability, FileAnalyzer, register
from yuktiforge.docint.analyzers.lexfacts import Ctx
from yuktiforge.docint.model import FileFacts

_COMMON = ("symbols are recognised from declaration syntax by a tokenizer (comments, strings and braces are handled), not a full parser: unusual formatting or macros can be missed",
           "no type or overload resolution; no call graph (imports and boundary patterns only)",
           "annotation/attribute values are read only when they are string literals; computed values are flagged dynamic or omitted")


class LexAnalyzer(FileAnalyzer):
    def __init__(self, cap: Capability, lang: str, mod):
        self.capability, self._lang, self._mod = cap, lang, mod

    def analyze(self, rel: str, text: str) -> FileFacts:
        c = Ctx(rel, text, self._lang, self.capability)
        try:
            self._mod.analyze(c)
        except RecursionError:
            c.warnings.append("nesting too deep for the lexical analyzer: partial result")
        except Exception as e:                      # one bad file must never stop a scan; the failure is recorded, not hidden
            c.warnings.append(f"analyzer error ({type(e).__name__}): partial result")
        return c.facts()


def _mk(aid, lang, pats, mod, depth, extra):
    register(LexAnalyzer(Capability(aid, "1.0", (lang,), pats, "lexical", depth, "medium", _COMMON + extra), lang, mod))


_mk("java-lexical", "java", ("*.java",), java, ("symbols", "imports", "routes", "db", "events", "http-clients", "config", "entry-points"),
    ("Spring, JAX-RS, JPA, Spring Data, Kafka/Rabbit/JMS and RestTemplate/Feign patterns only; Lombok-generated members and meta-annotations are not expanded",))
_mk("csharp-lexical", "csharp", ("*.cs",), csharp, ("symbols", "imports", "routes", "db", "events", "http-clients", "config", "entry-points"),
    ("ASP.NET attribute/minimal-API, EF Core, MassTransit/Service Bus patterns only; partial classes are reported per file, not merged; preprocessor directives are ignored",))
_mk("go-lexical", "go", ("*.go",), golang, ("symbols", "imports", "routes", "db", "events", "http-clients", "config", "entry-points"),
    ("net/http, gin, echo, chi, gorilla/mux, database/sql, gorm, Kafka/NATS patterns only; interface satisfaction is structural and not resolved",))
_mk("typescript-lexical", "typescript", ("*.ts", "*.tsx", "*.mts", "*.cts"), tsjs, ("symbols", "imports", "routes", "db", "events", "http-clients", "config", "entry-points"),
    ("Express/Fastify/NestJS, TypeORM/Prisma/Sequelize, fetch/axios and Kafka patterns only; types are copied as written",))
_mk("javascript-lexical", "javascript", ("*.js", "*.jsx", "*.mjs", "*.cjs"), tsjs, ("symbols", "imports", "routes", "db", "events", "http-clients", "config", "entry-points"),
    ("Express/Fastify, Sequelize/Prisma, fetch/axios and Kafka patterns only; dynamic require/import and prototype assignment are not followed",))
