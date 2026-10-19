"""Work's value types — the words the dispatcher's lower layers share (RT-BATCH-LAYER-TYPES).

The contracts (``source.py``, ``executor.py``) are ``lanes`` modules; the batch planner and state
table (``policy``) and the manifest and board source (``stores``) only need their value types. Those
live here, at the bottom layer, and the contracts re-export them so a caller's import is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__layer__ = "models"
__all__ = ["OPERATOR", "PERSONA_PREFIX", "Brief", "Claimant", "Domain", "GateReceipt", "Verdict"]

#: A persona's claim mark: ``persona:<instance_id>``.
PERSONA_PREFIX = "persona:"
#: The ``who`` the operator's console overrides a claim with (§8: release / re-status another's row).
OPERATOR = "operator"


class Verdict(StrEnum):
    DONE = "done"
    BLOCKED = "blocked"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class Brief:
    title: str
    objective: str
    inputs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    acceptance: str = ""
    #: The test commands the brief names; with ``goal_mode=UNTIL_DONE`` each becomes a goal gate.
    tests: tuple[str, ...] = ()


@dataclass(frozen=True)
class Domain:
    """The batching key (plan §3.1): one thick lane per (slot, note, heading)."""

    slot: str
    note: str
    heading: str


@dataclass(frozen=True)
class Claimant:
    """Who writes a claim mark: ``persona:<instance_id>`` for a persona, ``operator`` for the console."""

    who: str

    @classmethod
    def persona(cls, instance_id: str) -> Claimant:
        return cls(f"{PERSONA_PREFIX}{instance_id}")

    @classmethod
    def operator(cls) -> Claimant:
        return cls(OPERATOR)

    @property
    def persona_instance_id(self) -> str | None:
        return self.who[len(PERSONA_PREFIX):] if self.who.startswith(PERSONA_PREFIX) else None


@dataclass(frozen=True)
class GateReceipt:
    """One code-run landing gate in one slot's landing worktree (row RT-BATCH-GATE-RECEIPT, owner 2026-10-18).

    ``sha`` is the worktree HEAD the gate ran on, read before it started; ``approve`` pushes only a HEAD
    some green receipt names. ``exit_code`` 0 is green; anything else (a test red, a missing command,
    a timeout, a dirty tree) is red.
    """

    slot: str
    command: str
    exit_code: int
    summary: str
    sha: str
    seconds: float = 0.0

    @property
    def green(self) -> bool:
        return self.exit_code == 0

    def wire(self) -> dict[str, Any]:
        return {"slot": self.slot, "command": self.command, "exit_code": self.exit_code, "summary": self.summary,
                "sha": self.sha, "seconds": round(self.seconds, 1)}

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> GateReceipt:
        return cls(str(raw.get("slot") or ""), str(raw.get("command") or ""), int(raw.get("exit_code", -1)),
                   str(raw.get("summary") or ""), str(raw.get("sha") or ""), float(raw.get("seconds") or 0.0))
