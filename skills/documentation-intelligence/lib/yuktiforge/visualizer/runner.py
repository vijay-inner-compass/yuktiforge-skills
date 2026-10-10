"""The ONLY place in the visualizer that launches external programs.

Goes through Phase 1 `ExecutionPolicy` (allow-list, default-deny) and `scrub_env`. No shell, fixed
argv, input via stdin/stdout, timeout, temp cwd. Note: this is policy enforcement, not an OS sandbox;
the allowed tools (dot, rsvg-convert) are not network programs but nothing here would stop a
compromised binary on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from yuktiforge.errors import YuktiForgeError
from yuktiforge.security import ExecutionPolicy, scrub_env

RENDER_POLICY = ExecutionPolicy(allow_network=False, allowed_commands=frozenset({"dot", "rsvg-convert"}))
TIMEOUT_S = 60


@dataclass(frozen=True)
class ToolResult:
    stdout: bytes
    stderr: str


def tool_path(name: str) -> str | None:
    return shutil.which(name, path=scrub_env(dict(os.environ)).get("PATH"))


def tool_version(name: str) -> str | None:
    p = tool_path(name)
    if p is None:
        return None
    flag = "-V" if name == "dot" else "--version"
    r = run_tool(name, [flag])
    return (r.stderr if name == "dot" else r.stdout.decode(errors="replace")).strip().splitlines()[0]


def run_tool(name: str, args: list[str], stdin: bytes | None = None,
             policy: ExecutionPolicy = RENDER_POLICY) -> ToolResult:
    policy.check_command([name]).require()
    path = tool_path(name)
    if path is None:
        raise YuktiForgeError(f"required tool not found on PATH: {name}")
    with tempfile.TemporaryDirectory(prefix="yuktiforge-") as cwd:
        try:
            r = subprocess.run([path, *args], input=stdin, capture_output=True, timeout=TIMEOUT_S,
                               env=scrub_env(dict(os.environ)), cwd=cwd, shell=False, check=False)
        except subprocess.TimeoutExpired as e:
            raise YuktiForgeError(f"{name} timed out after {TIMEOUT_S}s") from e
    err = r.stderr.decode(errors="replace")
    if r.returncode != 0:
        raise YuktiForgeError(f"{name} failed (exit {r.returncode}): {err.strip()[:500]}")
    return ToolResult(r.stdout, err)


def dot_to_svg(dot: str) -> ToolResult:
    return run_tool("dot", ["-Tsvg"], dot.encode("utf-8"))


def svg_to(fmt: str, svg: bytes, zoom: float = 2.0) -> ToolResult:
    if fmt not in ("png", "pdf"):
        raise YuktiForgeError(f"unsupported export format {fmt!r}")
    args = ["-f", fmt] + (["-z", f"{zoom:g}"] if fmt == "png" else [])
    return run_tool("rsvg-convert", args, svg)
