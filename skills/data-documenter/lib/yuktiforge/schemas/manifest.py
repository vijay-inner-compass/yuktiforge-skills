"""Versioned package manifest: integrity record for a generated skill package."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from yuktiforge.errors import SchemaError
from yuktiforge.schemas.skillspec import SKILL_ID_PATTERN, AgentTarget

MANIFEST_VERSION = "1.1"      # 1.1 adds optional `license`; every 1.x manifest (incl. 1.0) is accepted
MANIFEST_FILENAME = "yuktiforge.manifest.json"
_SHA = r"^[0-9a-f]{64}$"


class ManifestFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    sha256: Annotated[str, Field(pattern=_SHA)]
    size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        pp = PurePosixPath(v)
        if pp.is_absolute() or ".." in pp.parts or "\\" in v or not v or v.startswith("./"):
            raise ValueError(f"unsafe manifest path {v!r}")
        return v


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    manifest_version: str = MANIFEST_VERSION
    skill_id: Annotated[str, Field(pattern=SKILL_ID_PATTERN)]
    skill_version: str
    spec_sha256: Annotated[str, Field(pattern=_SHA)]
    targets: tuple[AgentTarget, ...] = Field(min_length=1)
    created_at: datetime
    files: tuple[ManifestFile, ...] = Field(min_length=1)
    license: str | None = None        # SPDX identifier, "NOASSERTION" when undecided; None only in pre-1.1 manifests

    @field_validator("manifest_version")
    @classmethod
    def _major(cls, v: str) -> str:
        if v.split(".")[0] != MANIFEST_VERSION.split(".")[0]:
            raise ValueError(f"unsupported manifest_version {v!r}")
        return v

    @model_validator(mode="after")
    def _files_ok(self) -> "Manifest":
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate file paths")
        if "SKILL.md" not in paths:
            raise ValueError("manifest must include SKILL.md at the package root")
        if MANIFEST_FILENAME in paths:
            raise ValueError("manifest must not list itself")
        return self


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path, *, skill_id: str, skill_version: str, spec_sha256: str,
                   targets: tuple[AgentTarget, ...], created_at: datetime | None = None, license: str | None = None) -> Manifest:
    """`created_at` is injectable so packaging can be reproducible (callers pass a fixed time); default is now."""
    root = Path(root)
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise SchemaError(f"symlink not allowed in package: {p}")
        if p.is_file() and p.name != MANIFEST_FILENAME:
            files.append(ManifestFile(path=p.relative_to(root).as_posix(), sha256=sha256_file(p),
                                      size=p.stat().st_size))
    try:
        return Manifest(skill_id=skill_id, skill_version=skill_version, spec_sha256=spec_sha256,
                        targets=targets, created_at=created_at or datetime.now(UTC), files=tuple(files), license=license)
    except ValidationError as e:
        raise SchemaError(str(e)) from e


def verify_manifest(root: Path, manifest: Manifest) -> list[str]:
    """Return a list of problems (empty == package matches manifest exactly)."""
    root = Path(root)
    problems: list[str] = []
    listed = {f.path for f in manifest.files}
    for f in manifest.files:
        p = root / f.path
        if p.is_symlink() or not p.is_file():
            problems.append(f"missing or non-regular file: {f.path}")
        elif sha256_file(p) != f.sha256:
            problems.append(f"hash mismatch: {f.path}")
    for p in root.rglob("*"):
        if p.is_file() and p.name != MANIFEST_FILENAME and p.relative_to(root).as_posix() not in listed:
            problems.append(f"unlisted file: {p.relative_to(root).as_posix()}")
    return problems


def load_manifest(path: Path) -> Manifest:
    try:
        return Manifest.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        raise SchemaError(f"cannot load manifest {path}: {e}") from e
