"""The workspace pipeline a skill runs on its own from `--repo`: scan -> knowledge model -> documents (-> diagrams). Each step reuses the same command handlers as the `docs` CLI,
so a skill and the full CLI produce the same files. Layout: <out>/{scan,model,docs,diagrams}."""
from __future__ import annotations

import argparse
from pathlib import Path

from yuktiforge.docint import safety as S
from yuktiforge.docint.cmds import cmd_docs_scan
from yuktiforge.docint.docgen.cli import cmd_generate
from yuktiforge.docint.knowledge.cli import cmd_build
from yuktiforge.errors import YuktiForgeError


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def prepare(repo: str, out: Path) -> int:
    """scan + model build; returns non-zero when either step fails."""
    rc = cmd_docs_scan(_ns(repo=repo, out=str(out / "scan"), cache=None, no_cache=False, max_seconds=None, max_file_bytes=S.DEFAULT_LIMITS.max_file_bytes,
                           max_files=S.DEFAULT_LIMITS.max_files, include_generated=False))
    if rc:
        return rc
    return cmd_build(_ns(scan=str(out / "scan"), out=str(out / "model"), repo=repo))


def generate(out: Path, types: list[str], audience: str, depth: str, scope: str | None = None) -> int:
    if not types:
        raise YuktiForgeError("no document type to generate")
    return cmd_generate(_ns(model=str(out / "model"), out=str(out / "docs"), type=types, all=False, audience=audience, depth=depth, scope=scope, sections=None, plugin=None,
                            ai_provider=None, ai_model=None, ai_section=None, ai_base_url=None, ai_key_env=None, allow_network=False, approve_egress=False))


def run(repo: str, out: Path, types: list[str], audience: str, depth: str, scope: str | None = None) -> int:
    if not Path(repo).is_dir():
        raise YuktiForgeError(f"--repo {repo!r} is not a directory")
    out.mkdir(parents=True, exist_ok=True)
    rc = prepare(repo, out)
    return rc or generate(out, types, audience, depth, scope)
