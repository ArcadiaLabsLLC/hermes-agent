"""Staff a workspace with instances of an agent: reuse an idle one first, else place one more.

Row ``RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE`` (review w1118a.53 D8). Seen 2026-11-19: a lead agent
staffing a wave scripted ``hermes harness persona instance create --add-instance`` in its terminal,
chose placement ids by hand, named the seats "Launcher Dev Agent 2" / "3" itself and left no record of
who asked. :func:`staff_agent_instances` is the runtime's answer to "give me N instances of this agent
in this workspace": the agent tool (``tools/agent_chat/instances.py``) is a thin door over it.

* **Reuse idle, else new** (owner 2026-11-19, row ``MC-CHAT-LIST-GROUPS-CHATS-UNDER-THEIR-AGENT-INSTANCE``
  — the rule Eternia's ``reusableAgentInstance`` applies to a new chat): an instance of the agent
  already seated in the workspace and not busy is handed back before a new one is placed. Busy means
  a turn holds its chat root or a send waits on it, a live run binds it (``instance_busy_reason``), or
  it holds a seat in a running group chat. The most recently used idle instance comes first.
* **New ones go through ``runtime.agent.place``** (:func:`perform_agent_place`): the runtime names the
  seat (``numbered_instance_name``: "Launcher Dev · 2"), chooses the placement and the desk, and stamps
  ``spawned_by`` with the asking agent instance.
* **Gated like a coordinator's other spawns** (``coordinator_permissions.review_coordinator_budget``,
  the ``persona.instance.create`` budget): an agent whose budget does not cover one more instance is
  told to ask the operator, and nothing more is placed. A reused instance is no spawn.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__layer__ = "lanes"
__all__ = [
    "MAX_STAFF_COUNT",
    "StaffRefused",
    "coordinator_scope",
    "idle_instances",
    "reuse_or_place",
    "running_group_chat_seats",
    "spawn_refusal",
    "staff_agent_instances",
]

#: The most instances one call hands back: a wave's lane count, not a fleet.
MAX_STAFF_COUNT = 6


class StaffRefused(ValueError):
    """The call named no agent or workspace this runtime has, or asked for a count it does not take."""

    def __init__(self, reason: str, message: str, **data: Any) -> None:
        super().__init__(message)
        self.reason = reason
        self.data = data


@dataclass(slots=True)
class _Staffing:
    persona_id: str
    agent_name: str
    workspace_id: str
    requested_by: str
    instances: list[dict[str, Any]] = field(default_factory=list)

    def answer(self, *, wanted: int, refusal: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "agent_name": self.agent_name,
            "workspace_id": self.workspace_id,
            "requested_by": self.requested_by,
            "wanted": wanted,
            "instances": list(self.instances),
            "reused": sum(1 for row in self.instances if row["reused"]),
            "placed": sum(1 for row in self.instances if not row["reused"]),
            **({"stopped": refusal} if refusal is not None else {}),
        }


def running_group_chat_seats(install_id: str) -> frozenset[str] | None:
    """The bound discussion service's seated instances; ``None`` when this process holds none."""

    from ..discussions.run_values import DiscussionError
    from ..discussions.service import get_service

    try:
        service = get_service()
    except DiscussionError:
        return None
    return service.runs.seated_instances(install_id)


_IDLE_PROBE_OWNER = "agent-add-instance-idle-probe"


def _chat_root_busy(root: str | None) -> bool:
    """A turn holds the root's lease (the one busy check), or a send waits on it."""

    if not root:
        return False
    from ..chat_root_send_queue import has_entries
    from ..persona_chat_continuity import chat_root_is_busy

    return has_entries(root) or chat_root_is_busy(root, probe_owner=_IDLE_PROBE_OWNER)


def _instance_busy(store: Any, instance: Any, seated: frozenset[str]) -> bool:
    from ..persona_profile_binding import instance_busy_reason
    from ..serde import to_jsonable

    if instance.id in seated:
        return True
    try:
        live = store._has_live_binding(instance)  # the retire guard's own liveness read
    except Exception:
        live = True  # an instance whose run cannot be read is never handed out as idle
    if instance_busy_reason(to_jsonable(instance), live_binding=live) is not None:
        return True
    return _chat_root_busy(instance.default_chat_session_id)


def idle_instances(
    persona_id: str,
    workspace_id: str,
    *,
    seated: Callable[[str], frozenset[str] | None] | None = None,
) -> list[Any]:
    """The agent's idle instances seated in ``workspace_id``, the most recently used first.

    The ONE reuse rule: newest ``last_used_at`` first, an instance never used last, the store's
    order breaking ties; a busy instance is never returned. The ``agent_add_instance`` tool reads
    it here, and Eternia asks it over ``runtime.agent.idle_instances`` (row
    ``RT-ETERNIA-ASKS-THE-RUNTIME-WHICH-IDLE-INSTANCE-A-NEW-CHAT-REUSES``) instead of keeping a copy.
    """

    from .. import paths
    from ..gateway_identity import read_install_identity
    from ..mission_chat_turns import last_turn_started_by_instance
    from ..persona_assignments import PersonaInstanceStore

    store = PersonaInstanceStore()
    candidates = [
        instance
        for instance in store.list_all()
        if instance.persona_id == persona_id and instance.workspace_id == workspace_id
    ]
    if not candidates:
        return []
    install_id = read_install_identity(paths.store_root()).install_id or ""
    seats = (seated or running_group_chat_seats)(install_id) or frozenset()
    last_used = last_turn_started_by_instance()
    # The journal's stamps order lexically; a stable sort keeps the store's order among equals.
    used = sorted((i for i in candidates if last_used.get(i.id)), key=lambda i: last_used[i.id], reverse=True)
    ordered = used + [instance for instance in candidates if not last_used.get(instance.id)]
    # MUTATION: drop the busy test and test_a_busy_instance_is_never_reused reddens.
    return [instance for instance in ordered if not _instance_busy(store, instance, seats)]


def reuse_or_place(
    persona_id: str, *, place: bool = True, seated: Callable[[str], frozenset[str] | None] | None = None
) -> tuple[str | None, dict[str, Any] | None]:
    """The operator's own open of an agent with no instance in reach: ``(instance id, None)`` or ``(None, refusal)``.

    Row ``RT-A-SEND-TO-AN-AGENT-WITH-NO-INSTANCE-IN-REACH-IS-PLACED-OR-REFUSED`` (plan
    ``agent-template-vs-canonical-instance-2026-11-21`` §4): the ONE "reuse idle, else place" rule
    Eternia's New chat asks for, in the local Default workspace only — :func:`idle_instances`, then
    :func:`perform_agent_place` (the in-process body of ``runtime.agent.place``), never the hidden copy
    ``personainst_<persona>``. ``place=False`` is the read-only probe: an idle instance or ``(None, None)``
    ("the turn places one"). Only an operator door calls this; an agent's send never places.
    """

    from ..default_scope import DEFAULT_WORKSPACE_ID

    idle = idle_instances(persona_id, DEFAULT_WORKSPACE_ID, seated=seated)
    # MUTATION: drop the reuse and test_an_operator_send_from_another_workspace_reuses_the_idle_default_instance reddens.
    if idle:
        return idle[0].id, None
    if not place:  # MUTATION: drop it and test_the_read_only_admission_places_nothing reddens.
        return None, None
    outcome = _place(persona_id, DEFAULT_WORKSPACE_ID, requested_by="operator")
    if outcome.refusal is not None:
        return None, {
            "reason": (outcome.refusal.data or {}).get("reason") or "place_refused",
            "message": str(outcome.refusal.message),
        }
    return outcome.result["persona_instance_id"], None


def _resolve_agent(agent: str) -> Any:
    from ..persona_assignments import PersonaInstanceStore, safe_assignment_text
    from .request import persona_roster

    wanted = safe_assignment_text(agent, limit=160)
    if not wanted:
        raise StaffRefused("agent_required", "Name the agent to add an instance of.")
    roster = persona_roster()
    by_id = {persona.id: persona for persona in roster}
    if wanted in by_id:
        return by_id[wanted]
    if wanted.startswith("personainst_"):
        try:
            persona_id = PersonaInstanceStore().get(wanted).persona_id
        except Exception:
            persona_id = None
        if persona_id in by_id:
            return by_id[persona_id]
    folded = " ".join(wanted.split()).casefold()
    named = [persona for persona in roster if " ".join(str(persona.display_name or "").split()).casefold() == folded]
    if len(named) == 1:
        return named[0]
    raise StaffRefused(
        "agent_ambiguous" if named else "agent_not_found",
        f"No single agent is called {wanted!r}." if not named else f"Several agents are called {wanted!r}; name one by id.",
        agent=wanted,
        candidates=[persona.id for persona in named] or None,
    )


def _resolve_workspace(workspace: str | None, *, asking_session: str | None) -> str:
    from ..persona_assignments import safe_assignment_text, sender_scope_workspace_id
    from ..store import WorkspaceStore

    wanted = safe_assignment_text(workspace, limit=160) if workspace else ""
    if not wanted:
        resolved = sender_scope_workspace_id(asking_session)
        if resolved:
            return resolved
        raise StaffRefused("workspace_required", "Name the workspace to staff; you are in none.")
    workspaces = WorkspaceStore().list_all()
    for item in workspaces:
        if wanted == item.id:
            return item.id
    folded = wanted.casefold()
    named = [item for item in workspaces if folded in (str(item.name or "").casefold(), str(item.slug or "").casefold())]
    if len(named) == 1:
        return named[0].id
    raise StaffRefused("workspace_not_found", f"No single workspace is called {wanted!r}.", workspace=wanted)


#: Where the person grants an agent a spawn budget: the agent's own autonomy, and the install's cap.
SPAWN_BUDGET_SETTINGS = ("autonomy", "agent_runtime.coordinator_permissions.max_spawns")


def _budget_refusal(review: Any, asker: str, *, wanted: int, have: int) -> dict[str, Any]:
    """The ``needs_operator_confirm`` answer: which setting grants a budget, and what is still wanted.

    Row ``RT-A-SHIPPED-LEAD-AGENT-CANNOT-ADD-ANY-INSTANCE-WITHOUT-ASKING-YOU`` (RULED (b): the shipped
    lead keeps its zero budget; the person grants one). Every number is the budget owner's
    (``coordinator_permissions.scope_for_persona``, carried on the review), never a copy.
    """

    from ..models import AutonomyLevel

    scope = getattr(review, "scope", None)
    autonomy = _asker_autonomy(asker)
    still_wanted = wanted - have
    if scope is None:
        why = "Your agent instance could not be read, so no spawn budget applies."
    elif autonomy is AutonomyLevel.PROPOSE_ONLY:
        why = (f"Your agent's autonomy is {autonomy.value}, which allows no new instances; set it to "
               f"{AutonomyLevel.AUTONOMOUS.value} and {SPAWN_BUDGET_SETTINGS[1]} to grant a budget.")
    else:
        why = (f"Your spawn budget is {scope.max_spawns} and you have used {scope.spawns_used}; raise "
               f"{SPAWN_BUDGET_SETTINGS[1]} to grant more.")
    return {
        "reason": "needs_operator_confirm",
        "budget_reason": review.reason,
        "still_wanted": still_wanted,
        "settings": {
            "autonomy": autonomy.value if autonomy is not None else None,
            "max_spawns": scope.max_spawns if scope is not None else None,
            "spawns_used": scope.spawns_used if scope is not None else None,
        },
        "message": f"{why} Ask the person to change it or to add the other {still_wanted} themselves.",
    }


def _asker_autonomy(asker: str) -> Any:
    from ..models import AutonomyLevel
    from ..persona_assignments import PersonaInstanceStore
    from .request import resolve_persona

    try:
        persona = resolve_persona(PersonaInstanceStore().get(asker).persona_id)
    except Exception:
        return None
    return AutonomyLevel(getattr(persona, "autonomy", None) or AutonomyLevel.PROPOSE_ONLY) if persona else None


def coordinator_scope(asker: str) -> Any:
    """The asking instance's coordinator scope, read only from the store and the settings.

    Its agent's autonomy and ``agent_runtime.coordinator_permissions`` (``scope_for_persona``), with
    used = every instance the asker ever spawned, re-read each time, so seats already placed are
    counted once (they carry ``spawned_by``), never again on top. ``None`` when the asker is no
    instance. The one scope the add-instance tool and every CLI coordinator door are held to (row
    ``RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET``, review w1118a.62
    D1): nothing a caller types widens it.
    """

    from ..config import load_agent_runtime_config
    from ..coordinator_permissions import scope_for_persona
    from ..persona_assignments import PersonaInstanceStore
    from .request import resolve_persona

    try:
        asking = PersonaInstanceStore().get(asker)
    except Exception:
        return None
    cfg = load_agent_runtime_config()
    already = sum(1 for instance in PersonaInstanceStore().list_all() if instance.spawned_by == asker)
    # MUTATION: add this call's placed count again and test_a_budget_of_three_places_three reddens.
    return scope_for_persona(
        resolve_persona(asking.persona_id), config=getattr(cfg, "coordinator_permissions", None), spawns_used=already
    )


def spawn_refusal(review: Any, asker: str) -> dict[str, Any]:
    """The CLI door's half of :func:`_budget_refusal` for one seat: the sentence and the settings."""

    refusal = _budget_refusal(review, asker, wanted=1, have=0)
    return {"message": refusal["message"], "settings": refusal["settings"]}


def _spawn_review(asker: str) -> Any:
    """The coordinator budget for ONE more instance, for the asking instance's agent."""

    from ..coordinator_permissions import review_coordinator_budget

    return review_coordinator_budget(
        "persona.instance.create", coordinator_scope(asker), actor=asker, coordinator_id=asker
    )


def staff_agent_instances(
    agent: str,
    *,
    workspace: str | None = None,
    count: int = 1,
    requested_by: str,
    asking_session: str | None = None,
    seated: Callable[[str], frozenset[str] | None] | None = None,
) -> dict[str, Any]:
    """``count`` instances of ``agent`` seated in ``workspace``: idle ones first, then new placements.

    ``agent`` is an agent id, its name, or one of its instance handles; ``workspace`` an id or a
    name, else the asking session's own. ``requested_by`` is the asking agent instance
    (``agent_runtime.request_actor``). The answer lists every instance handed back (``reused`` true
    for an idle one), and ``stopped`` when the budget or a placement refused before ``count`` was met.
    Raises :class:`StaffRefused` before anything is read for a bad agent, workspace or count.
    """

    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_STAFF_COUNT:
        raise StaffRefused("count_invalid", f"count must be a whole number from 1 to {MAX_STAFF_COUNT}.")
    persona = _resolve_agent(agent)
    workspace_id = _resolve_workspace(workspace, asking_session=asking_session)
    staffing = _Staffing(persona.id, persona.display_name, workspace_id, requested_by)
    for instance in idle_instances(persona.id, workspace_id, seated=seated)[:count]:
        staffing.instances.append(_row(instance, reused=True))
    while len(staffing.instances) < count:
        review = _spawn_review(requested_by)
        if not review.ok:
            # MUTATION: answer the old fixed sentence and test_a_shipped_leads_refusal_names_the_setting_and_what_was_left reddens.
            refusal = _budget_refusal(review, requested_by, wanted=count, have=len(staffing.instances))
            return staffing.answer(wanted=count, refusal=refusal)
        outcome = _place(persona.id, workspace_id, requested_by=requested_by)
        if outcome.refusal is not None:
            return staffing.answer(wanted=count, refusal={
                "reason": (outcome.refusal.data or {}).get("reason") or "place_refused",
                "message": str(outcome.refusal.message),
            })
        staffing.instances.append(_placed_row(outcome.result))
    return staffing.answer(wanted=count)


def _place(persona_id: str, workspace_id: str, *, requested_by: str) -> Any:
    from .perform import perform_agent_place

    # No name, no placement id, no position: the runtime numbers the seat, mints the placement and
    # picks the desk. The key is fresh per seat — each loop turn is one more instance by design.
    return perform_agent_place(
        {"persona_id": persona_id, "workspace_id": workspace_id, "idempotency_key": f"staff-{uuid.uuid4().hex}"},
        requested_by=requested_by,
    )


def _row(instance: Any, *, reused: bool) -> dict[str, Any]:
    return {
        "persona_instance_id": instance.id,
        "display_name": instance.display_name,
        "default_chat_session_id": instance.default_chat_session_id,
        "spawned_by": instance.spawned_by,
        "reused": reused,
    }


def _placed_row(result: dict[str, Any]) -> dict[str, Any]:
    from ..persona_assignments import PersonaInstanceStore

    instance = PersonaInstanceStore().get(result["persona_instance_id"])
    return _row(instance, reused=False)
