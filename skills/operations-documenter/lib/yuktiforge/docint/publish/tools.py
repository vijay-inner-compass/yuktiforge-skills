"""The only place the publishing stage starts other programs (pandoc, Node + Chromium, LibreOffice, a small native PDF reader). Fixed argument lists, no shell, a time limit,
a scrubbed environment, and every missing tool reported as UNAVAILABLE with the reason: an export that cannot be produced is never faked."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from yuktiforge.errors import YuktiForgeError
from yuktiforge.security import scrub_env

ASSETS = Path(__file__).parent / "assets"
_ENV_ALLOW = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME", "DEVELOPER_DIR", "SDKROOT", "XDG_CACHE_HOME", "PLAYWRIGHT_BROWSERS_PATH")


@dataclass
class Run:
    returncode: int
    stdout: str
    stderr: str


def run(argv: list[str], *, timeout: int = 180, cwd: Path | None = None, stdin: str | None = None) -> Run:
    env = scrub_env(dict(os.environ), allow=_ENV_ALLOW)
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None, env=env, shell=False)
    except subprocess.TimeoutExpired as e:
        raise YuktiForgeError(f"{Path(argv[0]).name} timed out after {timeout}s") from e
    except OSError as e:
        raise YuktiForgeError(f"cannot start {argv[0]}: {e}") from e
    return Run(p.returncode, p.stdout, p.stderr)


def which(name: str) -> str | None:
    return shutil.which(name)


def version(argv: list[str]) -> str:
    try:
        r = run(argv, timeout=20)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "unknown"
    except YuktiForgeError:
        return "unknown"


def tool_report() -> dict[str, dict[str, str | None]]:
    out: dict[str, dict[str, str | None]] = {}
    for name, vcmd in (("pandoc", ["pandoc", "--version"]), ("node", ["node", "--version"]), ("soffice", ["soffice", "--version"]), ("dot", ["dot", "-V"]), ("rsvg-convert", ["rsvg-convert", "--version"])):
        p = which(name)
        out[name] = {"path": p, "version": version(vcmd) if p else None}
    pw = playwright_root()
    out["playwright-chromium"] = {"path": str(pw) if pw else None, "version": None}
    sw = which("xcrun")
    out["native-pdf-reader"] = {"path": sw, "version": None}
    return out


def playwright_root() -> Path | None:
    env = os.environ.get("YUKTIFORGE_PLAYWRIGHT")
    cands = [Path(env)] if env else []
    if which("npm"):
        try:
            r = run(["npm", "root", "-g"], timeout=20)
            if r.returncode == 0:
                cands.append(Path(r.stdout.strip()))
        except YuktiForgeError:
            pass
    for c in cands:
        if (c / "@playwright" / "test").is_dir():
            return c
    return None


def pdf_reader(cache: Path) -> Path | None:
    """Compile the small PDF reader (macOS PDFKit) once and reuse it; returns None when it cannot be built (other platforms, no developer tools)."""
    src = ASSETS / "pdf_tool.src"
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
    exe = cache / f"pdf_tool-{digest}"
    if exe.is_file():
        return exe
    if not which("xcrun"):
        return None
    cache.mkdir(parents=True, exist_ok=True)
    tmp_src = cache / f"pdf_tool-{digest}.swift"          # the compiler insists on its own file extension
    tmp_src.write_bytes(src.read_bytes())
    r = run(["xcrun", "swiftc", "-O", str(tmp_src), "-o", str(exe)], timeout=300)
    return exe if r.returncode == 0 and exe.is_file() else None


_GIT_SUBCOMMANDS = frozenset({"diff", "ls-files", "rev-parse", "cat-file", "show", "log"})
_GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never", "-c", "core.pager=cat"]


def git(repo: Path, *args: str, timeout: int = 60) -> Run:
    """Read-only git for change detection. Only a fixed set of read subcommands; external diff drivers, text conversion filters, hooks and the file-system monitor of the
    (untrusted) repository are switched off, so scanning a hostile checkout cannot run its configured programs."""
    if not args or args[0] not in _GIT_SUBCOMMANDS:
        raise YuktiForgeError(f"git subcommand {args[:1]} is not allowed here")
    extra = ["--no-ext-diff", "--no-textconv"] if args[0] in ("diff", "show", "log") else []
    return run(["git", *_GIT_SAFE, "-C", str(repo), args[0], *extra, *args[1:]], timeout=timeout)
