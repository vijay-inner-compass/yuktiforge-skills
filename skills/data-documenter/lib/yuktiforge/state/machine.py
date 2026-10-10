"""Explicit pipeline state machine.

discover -> specify -> design -> generate -> execute -> evaluate -> (repair -> execute)* -> package

Only the transition rules exist in Phase 1. No stage has an implementation.
`failed` and `cancelled` are terminal and reachable from any non-terminal stage.
"""
from __future__ import annotations

from enum import StrEnum

from yuktiforge.errors import InvalidTransition


class Stage(StrEnum):
    DISCOVER = "discover"
    SPECIFY = "specify"
    DESIGN = "design"
    GENERATE = "generate"
    EXECUTE = "execute"
    EVALUATE = "evaluate"
    REPAIR = "repair"
    PACKAGE = "package"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_S = Stage
_PIPELINE: dict[Stage, frozenset[Stage]] = {
    _S.DISCOVER: frozenset({_S.SPECIFY}),
    _S.SPECIFY: frozenset({_S.DESIGN}),
    _S.DESIGN: frozenset({_S.GENERATE}),
    _S.GENERATE: frozenset({_S.EXECUTE}),
    _S.EXECUTE: frozenset({_S.EVALUATE}),
    _S.EVALUATE: frozenset({_S.REPAIR, _S.PACKAGE}),
    _S.REPAIR: frozenset({_S.EXECUTE}),
    _S.PACKAGE: frozenset(),
    _S.FAILED: frozenset(),
    _S.CANCELLED: frozenset(),
}
_ABORT = frozenset({_S.FAILED, _S.CANCELLED})
TERMINAL = frozenset({_S.PACKAGE, _S.FAILED, _S.CANCELLED})

TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    s: (nxt | _ABORT if s not in TERMINAL else nxt) for s, nxt in _PIPELINE.items()
}

DEFAULT_MAX_REPAIRS = 3


def next_stages(current: Stage) -> frozenset[Stage]:
    return TRANSITIONS[Stage(current)]


def can_transition(current: Stage, target: Stage) -> bool:
    return Stage(target) in TRANSITIONS[Stage(current)]


def validate_transition(current: Stage, target: Stage, *, repairs_done: int = 0,
                        max_repairs: int = DEFAULT_MAX_REPAIRS) -> None:
    current, target = Stage(current), Stage(target)
    if not can_transition(current, target):
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[current])) or "none (terminal)"
        raise InvalidTransition(f"cannot go {current.value} -> {target.value}; allowed: {allowed}")
    if target is Stage.REPAIR and repairs_done >= max_repairs:
        raise InvalidTransition(f"repair budget exhausted ({repairs_done}/{max_repairs}); fail or package instead")


def status_for(stage: Stage) -> RunStatus:
    return {
        Stage.PACKAGE: RunStatus.SUCCEEDED,
        Stage.FAILED: RunStatus.FAILED,
        Stage.CANCELLED: RunStatus.CANCELLED,
    }.get(Stage(stage), RunStatus.ACTIVE)
