"""Security baseline: default-deny.

Phase 1 *decides*; it does not execute. No code path in this package launches a subprocess
for generated content. Later phases must route every execution through ExecutionPolicy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from yuktiforge.errors import PolicyDenied
from yuktiforge.schemas.skillspec import PermissionRequest
from yuktiforge.store.db import RunStore

_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|SESSION|COOKIE)", re.I)
_SAFE_ENV = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM", "TZ"})


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str

    def require(self) -> None:
        if not self.allowed:
            raise PolicyDenied(self.reason)


@dataclass(frozen=True)
class ExecutionPolicy:
    """Grants are explicit allow-lists. The default instance grants nothing."""

    allow_network: bool = False
    allowed_commands: frozenset[str] = frozenset()
    allowed_secrets: frozenset[str] = frozenset()
    allowed_write_prefixes: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=(), compare=False)

    def check_network(self) -> Decision:
        return Decision(self.allow_network, "network allowed" if self.allow_network
                        else "network access denied by default")

    def check_command(self, argv: list[str]) -> Decision:
        if not argv:
            return Decision(False, "empty command")
        exe = argv[0]
        if exe in self.allowed_commands:
            return Decision(True, f"{exe} is on the allow-list")
        return Decision(False, f"command {exe!r} is not on the allow-list (default-deny)")

    def check_secret(self, name: str) -> Decision:
        if name in self.allowed_secrets:
            return Decision(True, f"secret {name} explicitly granted")
        return Decision(False, f"secret {name!r} not granted (default-deny)")

    def evaluate_request(self, req: PermissionRequest) -> list[Decision]:
        """Judge what a spec *asks for* against this policy. A request never grants anything itself."""
        out: list[Decision] = []
        if req.network:
            d = self.check_network()
            out.append(Decision(d.allowed, f"requested network: {d.reason}"))
        for name in req.secrets:
            d = self.check_secret(name)
            out.append(Decision(d.allowed, f"requested secret: {d.reason}"))
        for cmd in req.commands:
            d = self.check_command([cmd])
            out.append(Decision(d.allowed, f"requested command: {d.reason}"))
        for p in req.filesystem_write:
            ok = (not p.startswith("/") and ".." not in p.split("/")
                  and any(p == pre or p.startswith(pre.rstrip("/") + "/") for pre in self.allowed_write_prefixes))
            out.append(Decision(ok, f"requested write {p!r}: " + ("within granted prefix" if ok else "not granted")))
        return out


def scrub_env(env: dict[str, str], allow: frozenset[str] = frozenset()) -> dict[str, str]:
    """Return a minimal environment: safe names only, never anything secret-looking unless explicitly allowed."""
    return {k: v for k, v in env.items()
            if k in allow or (k in _SAFE_ENV and not _SECRET_NAME.search(k))}


def authorize_dependency_install(store: RunStore, run_id: str, package: str, version_spec: str) -> Decision:
    """Dependencies may be installed only after a recorded human approval for that exact package+spec."""
    status = store.dependency_status(run_id, package, version_spec)
    if status == "approved":
        return Decision(True, f"{package}{version_spec} approved")
    if status is None:
        return Decision(False, f"{package}{version_spec} has no review record; request review first")
    return Decision(False, f"{package}{version_spec} review status is {status!r}")
