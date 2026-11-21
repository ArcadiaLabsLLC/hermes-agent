"""An agent instance added to a workspace stands on that workspace's office level.

Seen 2026-11-20 on the owner's install (Eternia row
``MC-AGENTS-A-LEAD-ADDED-LAST-NIGHT-ARE-NOT-ON-THE-OFFICE-LEVEL``): Neko Mission
Lead Beta ran ``hermes harness persona instance create --persona dev --add-instance
--placement-id dev_agent_<hex> --workspace-id ws_testv4_afb811 ...`` from its
terminal. The instance record landed with ``workspace_id: ws_testv4_afb811`` and
no office actor did, so Launcher Dev Agent 2 and 3 were teammates in every list
and absent from the testv4 level. ``runtime.agent.place`` (the
``agent_add_instance`` tool's door) wrote the actor; the two argv doors
(``persona instance create --add-instance`` and ``persona instance open-chat
--add-instance``) stopped at the instance record.

This module is the ONE seating write: :func:`write_seat` builds the actor payload
and lets the store pick the free desk inside its lock. ``AgentCreate.place`` calls
it; :func:`seat_added_instance` calls it for the repair (:func:`unseated_instances` /
:func:`seat_unseated`) of what the old argv doors left. Those doors no longer mint on their own
(RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT): ``persona instance create --add-instance``
runs ``runtime.agent.place``'s sequence, and ``open-chat --add-instance`` is refused. An instance
already standing in its workspace is never seated twice, so a re-bind, a resumed
create, or a launcher upsert onto the same actor key never makes a second desk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .phases import placement_actor_payload, placement_position_policy

__layer__ = "stores"
__all__ = [
    "SEATED",
    "SeatOutcome",
    "seat_added_instance",
    "seat_unseated",
    "unseated_instances",
    "write_seat",
]

#: The outcome reasons. ``seated`` and ``would_seat`` are the two that act; the rest
#: say why nothing was written.
SEATED = "seated"
WOULD_SEAT = "would_seat"
ALREADY_SEATED = "already_seated"
NO_WORKSPACE = "no_workspace"
WORKSPACE_NOT_FOUND = "workspace_not_found"
NOT_A_PLACEMENT = "not_a_placement"
REFUSED = "refused"


@dataclass(frozen=True)
class SeatOutcome:
    """What seating one instance did (or, on a dry run, would do)."""

    instance_id: str
    workspace_id: str | None
    reason: str
    actor_key: str | None = None
    error: str | None = None

    @property
    def seated(self) -> bool:
        return self.reason == SEATED

    def receipt(self) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "instance_id": self.instance_id,
            "workspace_id": self.workspace_id,
            "seated": self.seated,
            "reason": self.reason,
        }
        if self.actor_key:
            receipt["actor_key"] = self.actor_key
        if self.error:
            receipt["error"] = self.error
        return receipt


def write_seat(
    store: Any,
    request: Any,
    *,
    display_name: str,
    persona_id: str,
    profile_id: str | None,
    updated_by: str,
) -> Any:
    """Write ``request``'s instance's actor on ``request.workspace_id``; the stored actor.

    The aim when the request has one, else the layout policy, resolved by the store
    inside ``office_lock`` against the actors this write lands beside
    (``placement_position_policy``). Store faults propagate: the caller decides
    whether one compensates a mint (``AgentCreate.place``) or is reported.
    """

    payload = placement_actor_payload(
        request, display_name=display_name, position=request.position,
        persona_id=persona_id, profile_id=profile_id,
    )
    position_policy = None if request.position is not None else placement_position_policy(request)
    return store.upsert_actor(
        request.workspace_id,
        payload,
        updated_by=updated_by,
        correlation_id=request.correlation_id,
        position_policy=position_policy,
    )


def _seat_request(instance: Any, *, correlation_id: str | None) -> Any | None:
    """The placement request that names ``instance``; ``None`` for an id no placement mints."""

    from ..persona_assignments.identity import PERSONA_INSTANCE_ID_PREFIX
    from .request import DEFAULT_AGENT_FOLDER, AgentCreateRequest

    instance_id = str(instance.id or "")
    if not instance_id.startswith(PERSONA_INSTANCE_ID_PREFIX):
        return None
    request = AgentCreateRequest(
        persona_id=instance.persona_id,
        workspace_id=instance.workspace_id,
        position=None,
        skills=None,
        idempotency_key="seat",
        placement_id=instance_id[len(PERSONA_INSTANCE_ID_PREFIX):],
        display_name=instance.display_name,
        default_display_name=instance.display_name or "",
        realm_id=instance.realm_id,
        folder=DEFAULT_AGENT_FOLDER,
        correlation_id=correlation_id,
    )
    # The actor is keyed by the instance the request derives; one that would key
    # another instance is not seated under a guessed key.
    return request if request.persona_instance_id == instance_id else None


def _stands_in(office: Any, workspace_id: str, instance_id: str) -> bool:
    return any(
        getattr(actor, "persona_instance_id", None) == instance_id
        for actor in office.scan_actors(workspace_id).actors
    )


def seat_added_instance(
    instance: Any,
    *,
    updated_by: str = "harness",
    correlation_id: str | None = None,
    dry_run: bool = False,
    office: Any = None,
) -> SeatOutcome:
    """Seat ``instance`` on its workspace's level unless it already stands there.

    Nothing is written for an instance with no workspace, an unknown workspace, or
    one already standing on it; a refused write is returned (``reason: refused``)
    rather than raised, so the mint it follows stays and the refusal is named.
    """

    from ..office_store.store import OfficeStore

    workspace_id = getattr(instance, "workspace_id", None) or None

    def outcome(reason: str, **extra: Any) -> SeatOutcome:
        return SeatOutcome(instance.id, workspace_id, reason, **extra)

    if not workspace_id:
        return outcome(NO_WORKSPACE)
    office = office or OfficeStore()
    if not office.workspace_resolves(workspace_id):
        return outcome(WORKSPACE_NOT_FOUND)
    # MUTATION: drop this check and test_a_reseat_of_a_standing_instance_writes_nothing reddens.
    if _stands_in(office, workspace_id, instance.id):
        return outcome(ALREADY_SEATED)
    request = _seat_request(instance, correlation_id=correlation_id)
    if request is None:
        return outcome(NOT_A_PLACEMENT)
    if dry_run:
        return outcome(WOULD_SEAT)
    try:
        actor = write_seat(
            office, request, display_name=instance.display_name or "",
            persona_id=instance.persona_id, profile_id=instance.profile_id, updated_by=updated_by,
        )
    except Exception as exc:  # the mint stays; the refusal is named on the reply
        return outcome(REFUSED, error=f"{type(exc).__name__}: {exc}")
    return outcome(SEATED, actor_key=getattr(actor, "actor_key", None))


def unseated_instances() -> list[SeatOutcome]:
    """Read only: every live placed instance whose workspace's level does not show it."""

    from ..office_store.store import OfficeStore
    from ..persona_assignments import PersonaInstanceStore, is_canonical_persona_channel

    office = OfficeStore()
    found = []
    for instance in PersonaInstanceStore().scan_all().instances:
        if is_canonical_persona_channel(instance):
            continue  # an agent's global channel is not a placement
        seat = seat_added_instance(instance, dry_run=True, office=office)
        if seat.reason == WOULD_SEAT:
            found.append(seat)
    return sorted(found, key=lambda seat: seat.instance_id)


def seat_unseated(*, dry_run: bool) -> list[SeatOutcome]:
    """Seat every instance :func:`unseated_instances` finds; ``dry_run`` writes nothing."""

    from ..persona_assignments import PersonaInstanceStore

    found = unseated_instances()
    if dry_run:
        return found
    store = PersonaInstanceStore()
    return [seat_added_instance(store.get(seat.instance_id)) for seat in found]
