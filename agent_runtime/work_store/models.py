"""Work's value types — the words the dispatcher's lower layers share (RT-BATCH-LAYER-TYPES).

The contracts (``source.py``, ``executor.py``) are ``lanes`` modules; the batch planner and state
table (``policy``) and the manifest and board source (``stores``) only need their value types. Those
live here, at the bottom layer, and the contracts re-export them so a caller's import is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__layer__ = "models"
__all__ = ["OPERATOR", "PERSONA_PREFIX", "Brief", "Claimant", "Domain", "Verdict"]

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
