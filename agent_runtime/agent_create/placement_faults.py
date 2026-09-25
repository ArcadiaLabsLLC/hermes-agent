"""The placement-fault table: a store exception on the placement -> the
create's compensated refusal (layout sheet agent_create.md §2).

A TABLE module, exempt from the 100-line floor by kind: :data:`PLACEMENT_FAULTS`
and its three translators, plus :func:`refuse_placement`, the one door
``AgentCreate.place`` answers a fault through. Drawn in ``phases`` by the sheet;
it sits beside it because ``phases`` would otherwise cross the 500-line cap.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from ..errors import StaleRevision, SyncConflict
from ..office_class_key_guard import ClassKeyedPlacementRefused
from .outcome import ERR_CONFLICT, ERR_HANDLER_FAILED, PHASE_PLACEMENT, AgentCreateOutcome, refused
from .phases import compensate_failed_placement

__layer__ = "stores"


def _class_keyed_refusal(exc: Any) -> tuple[int, str, str, dict[str, Any]]:
    # ``placement_actor_payload`` is instance-keyed by construction, so the
    # store's class-key fence can never fire from this sequence AS IT STANDS —
    # and a defence that is only correct "by construction" is one refactor away
    # from being absent, so this row exists and is tested by injecting the
    # payload shape that refactor would produce (EG-6.6). It is a compensated
    # refusal like every other placement failure: the roster row this method
    # just minted must not outlive the placement it was minted for.
    #
    # ``placement_reason`` keeps the string it has always spent, and the fence's
    # own evidence rides beside it: a refusal that does not name the actor it
    # collided with is one nobody can act on, and this lane had been dropping
    # exactly that.
    return (
        ERR_CONFLICT,
        "class-keyed placement refused",
        "class_key_collision",
        {
            "reasons": exc.safe_details["reasons"],
            "class_actor_key": exc.safe_details["class_actor_key"],
            "conflicting_actor_keys": exc.safe_details["conflicting_actor_keys"],
        },
    )


def _store_conflict(exc: Any) -> tuple[int, str, str, dict[str, Any]]:
    return ERR_CONFLICT, str(exc), type(exc).__name__, {}


def _store_fault(exc: Any) -> tuple[int, str, str, dict[str, Any]]:
    # An unexpected store fault is still a placement that did not land, and the
    # roster row must not survive it. The RPC boundary would have turned this
    # into a -32000 with the instance stranded — which is R#37 with a nicer
    # error code.
    return ERR_HANDLER_FAILED, str(exc), type(exc).__name__, {}


#: A store exception on the placement -> ``(code, message, placement_reason,
#: evidence)``, looked up along the exception's MRO so a subclass answers as
#: its nearest listed base and ``Exception`` is the floor. Every row is a
#: COMPENSATED refusal (:func:`refuse_placement`).
PLACEMENT_FAULTS: Final[
    Mapping[type[BaseException], Callable[[Any], tuple[int, str, str, dict[str, Any]]]]
] = MappingProxyType(
    {
        ClassKeyedPlacementRefused: _class_keyed_refusal,
        StaleRevision: _store_conflict,
        SyncConflict: _store_conflict,
        ValueError: _store_conflict,
        Exception: _store_fault,
    }
)


def refuse_placement(
    exc: Exception, reservation: Any, *, instance_id: str, workspace_id: str
) -> AgentCreateOutcome:
    """One placement fault, compensated and answered through its table row."""

    translate = next(
        PLACEMENT_FAULTS[kind] for kind in type(exc).__mro__ if kind in PLACEMENT_FAULTS
    )
    code, message, placement_reason, evidence = translate(exc)
    data = compensate_failed_placement(
        reservation,
        instance_id=instance_id,
        failure={
            "reason": "placement_failed",
            "phase": PHASE_PLACEMENT,
            "placement_reason": placement_reason,
            "workspace_id": workspace_id,
            **evidence,
        },
    )
    return refused(code, message, data)
