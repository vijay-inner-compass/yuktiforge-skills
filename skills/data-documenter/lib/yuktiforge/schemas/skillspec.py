"""Versioned SkillSpec schema.

Language-agnostic by construction: nothing here names a programming language.
Language-specific analysis is an *optional* analyzer plug-in that must declare
the languages it covers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from yuktiforge.errors import SchemaError

SKILLSPEC_VERSION = "1.0"
SKILL_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

AgentTarget = Literal["claude-code", "antigravity", "github-copilot", "codex"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputSpec(_Strict):
    """What the skill consumes. `specification` means no source repository exists."""

    kind: Literal["repository", "specification"]
    # Empty means "unspecified / language-agnostic". Free-form identifiers; never an enum.
    languages: tuple[str, ...] = ()
    description: str = ""


class OutputSpec(_Strict):
    kind: str = Field(min_length=1)
    format: str = Field(min_length=1)


class AnalyzerSpec(_Strict):
    """Optional language-specific plug-in. Must declare coverage; can never be required."""

    id: Annotated[str, Field(pattern=SKILL_ID_PATTERN)]
    optional: Literal[True] = True
    languages: tuple[str, ...] = Field(min_length=1)
    coverage_notes: str = Field(min_length=1)


class PermissionRequest(_Strict):
    """Everything defaults to denied. A spec can only *request*; policy decides."""

    network: bool = False
    secrets: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    filesystem_write: tuple[str, ...] = ()


class DependencySpec(_Strict):
    name: str = Field(min_length=1)
    version_spec: str = Field(min_length=1)
    reason: str = Field(min_length=1)


AssertOp = Literal["equals", "contains", "min_len", "exists", "absent"]


class ExampleAssertion(_Strict):
    """One machine-checkable expectation about a skill's JSON output. `path` is dotted (`a.b.0.c`)."""

    path: str = Field(min_length=1)
    op: AssertOp
    value: str | int | float | bool | None = None


class ExampleSpec(_Strict):
    """A worked example: the skill is run on `input` and every assertion must hold. This is the skill's contract."""

    name: Annotated[str, Field(pattern=SKILL_ID_PATTERN, max_length=48)]
    input: str
    expect: tuple[ExampleAssertion, ...] = Field(min_length=1)


class SkillSpec(_Strict):
    schema_version: str = SKILLSPEC_VERSION
    skill_id: Annotated[str, Field(pattern=SKILL_ID_PATTERN, max_length=64)]
    version: str
    description: str = Field(min_length=1, max_length=1024)
    inputs: tuple[InputSpec, ...] = Field(min_length=1)
    outputs: tuple[OutputSpec, ...] = ()
    analyzers: tuple[AnalyzerSpec, ...] = ()
    permissions: PermissionRequest = PermissionRequest()
    dependencies: tuple[DependencySpec, ...] = ()
    targets: tuple[AgentTarget, ...] = Field(min_length=1)
    # Added for the creator (optional, so every 1.0 spec stays valid):
    assumptions: tuple[str, ...] = ()      # things the requirement did not say and the creator assumed, in plain words
    workflow: tuple[str, ...] = ()         # ordered steps an agent follows when using the skill
    examples: tuple[ExampleSpec, ...] = ()  # the checkable contract
    requirement: str = Field(default="", max_length=8000)   # the natural-language request this spec was drafted from

    @field_validator("schema_version")
    @classmethod
    def _major_supported(cls, v: str) -> str:
        if v.split(".")[0] != SKILLSPEC_VERSION.split(".")[0]:
            raise ValueError(f"unsupported schema_version {v!r}; this build supports {SKILLSPEC_VERSION!r}")
        return v

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError(f"version {v!r} is not semver")
        return v

    @model_validator(mode="after")
    def _unique(self) -> "SkillSpec":
        ids = [a.id for a in self.analyzers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate analyzer ids")
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("duplicate targets")
        names = [e.name for e in self.examples]
        if len(names) != len(set(names)):
            raise ValueError("duplicate example names")
        return self


def load_skillspec(path: str | Path) -> SkillSpec:
    """Load a SkillSpec from .json/.yaml/.yml, raising SchemaError with readable messages."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        data: Any = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise SchemaError(f"cannot read {p}: {e}") from e
    if not isinstance(data, dict):
        raise SchemaError(f"{p}: top level must be a mapping")
    try:
        return SkillSpec.model_validate(data)
    except ValidationError as e:
        raise SchemaError(_format(e)) from e


def _format(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or '<root>'}: {err['msg']}" for err in e.errors())
