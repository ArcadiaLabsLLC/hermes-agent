"""The snapshot contract version and the build context: ``SNAPSHOT_CONTRACT_VERSION``,
``SnapshotSummary``, ``SnapshotBuildContext`` and its scope.

A leaf, so the contract version is readable (``core_cache.contract_versions``)
without importing the builder.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

__layer__ = "models"

__all__ = [
    "SNAPSHOT_CONTRACT_VERSION",
    "SnapshotBuildContext",
    "SnapshotSummary",
    "_SNAPSHOT_BUILD_CONTEXT",
    "logger",
    "snapshot_build_context_scope",
]


#: THE snapshot wire contract version — the single producer-side authority.
#:
#: Every consumer of this number, in this repo and in the Launcher, derives it
#: from here rather than restating it. That rule exists because restating it is
#: what kept breaking: the contract-53 landing moved two of six hermes test
#: literals and left four red on ``main`` for five days, and the 53 -> 54 sweep
#: then found eleven more still pinned at 52. Each of those was a *negative*
#: gate — "this cut did NOT move the contract" — expressed as an absolute
#: number, so every unrelated bump made a true statement go red and taught
#: readers that a contract failure is routine noise.
#:
#: Consequently:
#:
#: * production reads :data:`SNAPSHOT_CONTRACT_VERSION` (see the parity envelope
#:   in :func:`parity_envelope`, whose comment block carries the full
#:   version-by-version history and the bump/keep rulings behind it);
#: * tests import it and assert RELATIVE to it (``== SNAPSHOT_CONTRACT_VERSION``,
#:   ``- 1``, ``+ 1``) so a bump moves them for free;
#: * exactly ONE test states the literal —
#:   ``test_snapshot_contract_version_authority.py`` — because the number is a
#:   cross-repo lockstep with the Launcher's ``kSupportedMissionContractVersion``
#:   and moving it must be a deliberate, reviewed edit rather than a silent
#:   consequence of a refactor;
#: * a structural (AST) gate in that same file fails if any other test states it.
SNAPSHOT_CONTRACT_VERSION = 54


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    """The frame's ``summary`` block, as a CLOSED set of fields.

    ``summary`` was a bare dict literal, and two parity warnings kept reading
    ``open_tasks`` / ``open_incidents`` out of it for the two contract versions
    after the mission-row removal stopped emitting them — a dict answers
    ``.get()`` for any key, so the branches read ``None``, evaluated false, and
    the warnings simply never fired. Nothing failed; the checks just quietly
    stopped existing. Declaring the field set here means a reader of a field the
    summary does not emit is an ``AttributeError`` where it is written, not a
    silent no-op that survives audits.
    """

    persona_instances: int

    def as_dict(self) -> dict[str, int]:
        return {"persona_instances": int(self.persona_instances)}


@dataclass(slots=True)
class SnapshotBuildContext:
    """Reusable, non-wire caches owned by one long-lived serve process."""

    skill_root_registries: dict[str, object] = field(default_factory=dict)


_SNAPSHOT_BUILD_CONTEXT: ContextVar[SnapshotBuildContext | None] = ContextVar(
    "snapshot_build_context", default=None
)


@contextmanager
def snapshot_build_context_scope(context: SnapshotBuildContext):
    token = _SNAPSHOT_BUILD_CONTEXT.set(context)
    try:
        yield context
    finally:
        _SNAPSHOT_BUILD_CONTEXT.reset(token)
