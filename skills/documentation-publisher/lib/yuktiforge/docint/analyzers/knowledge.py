"""Ecosystem and language knowledge used by the language-neutral core (inventory, scan): which file names are manifests, which paths are tests,
which dependencies imply which framework. Lives with the analyzer plug-ins so the core itself names no language or ecosystem."""
from __future__ import annotations

import re

MANIFEST_NAMES = {"package.json": "npm", "pom.xml": "maven", "build.gradle": "gradle", "build.gradle.kts": "gradle", "settings.gradle": "gradle", "settings.gradle.kts": "gradle",
                  "go.mod": "go", "go.work": "go", "Cargo.toml": "cargo", "pyproject.toml": "python", "setup.py": "python", "setup.cfg": "python", "Pipfile": "python",
                  "composer.json": "composer", "Gemfile": "bundler", "mix.exs": "mix", "CMakeLists.txt": "cmake", "pubspec.yaml": "pub", "Package.swift": "swiftpm"}
MANIFEST_GLOBS = {"*.csproj": "dotnet", "*.fsproj": "dotnet", "*.vbproj": "dotnet", "*.sln": "dotnet", "requirements*.txt": "python"}
WORKSPACE_MARKERS = ("pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json", "go.work", "rush.json")
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|specs|e2e|integration-tests?)/|(^|/)test_[^/]*\.py$|_test\.(go|py)$|(Test|Tests|IT|Spec)\.(java|kt|cs|scala)$|\.(test|spec)\.(js|jsx|ts|tsx|mjs)$", re.I)

FRAMEWORKS: list[tuple[str, str, str]] = [          # (ecosystem, dependency-name regex, framework)
    ("maven", r"spring-boot", "Spring Boot"), ("maven", r"spring-(web|webmvc|webflux)", "Spring MVC"), ("maven", r"jakarta\.persistence|hibernate|javax\.persistence", "JPA/Hibernate"),
    ("maven", r"spring-kafka|kafka-clients", "Kafka"), ("maven", r"quarkus", "Quarkus"), ("maven", r"micronaut", "Micronaut"), ("maven", r"junit", "JUnit"),
    ("nuget", r"Microsoft\.AspNetCore|Microsoft\.NET\.Sdk\.Web", "ASP.NET Core"), ("nuget", r"EntityFramework", "Entity Framework"), ("nuget", r"MassTransit", "MassTransit"),
    ("nuget", r"xunit|NUnit|MSTest", "xUnit/NUnit/MSTest"),
    ("npm", r"^express$", "Express"), ("npm", r"^@nestjs/", "NestJS"), ("npm", r"^fastify$", "Fastify"), ("npm", r"^react(-dom)?$", "React"), ("npm", r"^next$", "Next.js"),
    ("npm", r"^vue$", "Vue"), ("npm", r"^@angular/core$", "Angular"), ("npm", r"^typeorm$|^@prisma/client$|^sequelize$|^mongoose$", "ORM (JS)"), ("npm", r"^kafkajs$", "KafkaJS"),
    ("npm", r"^jest$|^vitest$|^mocha$", "JS test framework"),
    ("pypi", r"^fastapi$", "FastAPI"), ("pypi", r"^flask$", "Flask"), ("pypi", r"^django$", "Django"), ("pypi", r"^sqlalchemy$", "SQLAlchemy"), ("pypi", r"^pydantic$", "Pydantic"),
    ("pypi", r"^celery$", "Celery"), ("pypi", r"^pytest$", "pytest"),
    ("go", r"github\.com/gin-gonic/gin", "Gin"), ("go", r"github\.com/labstack/echo", "Echo"), ("go", r"github\.com/go-chi/chi", "chi"), ("go", r"gorm\.io/gorm", "GORM"),
    ("go", r"github\.com/gorilla/mux", "gorilla/mux"), ("go", r"segmentio/kafka-go|confluent-kafka-go|sarama", "Kafka (Go)"),
    ("cargo", r"^(actix-web|axum|rocket)$", "Rust web framework"),
]
BUILD_BY_ECO = {"maven": "Maven", "gradle": "Gradle", "npm": "npm/Node", "dotnet": ".NET (MSBuild)", "go": "Go modules", "cargo": "Cargo", "python": "Python packaging", "cmake": "CMake",
                 "composer": "Composer", "bundler": "Bundler", "mix": "Mix", "pub": "pub", "swiftpm": "SwiftPM"}


