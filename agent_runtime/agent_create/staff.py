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
    "idle_instances",
    "running_group_chat_seats",
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

    The ONE reuse rule (Eternia's ``reusableAgentInstance`` is the same rule over the directory
    it reads): newest ``last_used_at`` first, an instance never used last, the store's order
    breaking ties; a busy instance is never returned.
    """

    from .. import paths
    from ..gateway_identity import read_install_identity
    from ..mission_chat_turns import last_turn_started_by_instance
    from ..persona_assignments import PersonaInstanceStore, is_canonical_persona_channel

    store = PersonaInstanceStore()
    candidates = [
        instance
        for instance in store.list_all()
        if instance.persona_id == persona_id
        and instance.workspace_id == workspace_id
        and not is_canonical_persona_channel(instance)
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


def _spawn_review(asker: str, spawned: int) -> Any:
    """The coordinator budget for ONE more instance, for the asking instance's agent."""

    from ..config import load_agent_runtime_config
    from ..coordinator_permissions import review_coordinator_budget, scope_for_persona
    from ..persona_assignments import PersonaInstanceStore
    from .request import resolve_persona

    cfg = load_agent_runtime_config()
    try:
        asking = PersonaInstanceStore().get(asker)
    except Exception:
        asking = None
    persona = resolve_persona(asking.persona_id) if asking is not None else None
    already = sum(1 for instance in PersonaInstanceStore().list_all() if instance.spawned_by == asker)
    scope = (
        scope_for_persona(persona, config=getattr(cfg, "coordinator_permissions", None), spawns_used=already + spawned)
        if asking is not None
        else None
    )
    return review_coordinator_budget("persona.instance.create", scope, actor=asker, coordinator_id=asker)


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
    placed = 0
    while len(staffing.instances) < count:
        review = _spawn_review(requested_by, placed)
        if not review.ok:
            return staffing.answer(wanted=count, refusal={
                "reason": "needs_operator_confirm",
                "budget_reason": review.reason,
                "message": "Your budget for adding agent instances is used up; ask the operator to add the rest.",
            })
        outcome = _place(persona.id, workspace_id, requested_by=requested_by)
        if outcome.refusal is not None:
            return staffing.answer(wanted=count, refusal={
                "reason": (outcome.refusal.data or {}).get("reason") or "place_refused",
                "message": str(outcome.refusal.message),
            })
        placed += 1
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
