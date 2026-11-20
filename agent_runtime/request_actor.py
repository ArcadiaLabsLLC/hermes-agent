"""Who asked for an agent-lifecycle write: the ONE actor every retire, removal and placement records.

Rows ``RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT`` and ``RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE``
(review w1118a.53 D8, D9). Seen 2026-11-19: the owner removed Base Agent from the testv4 level and its
retire receipt read ``requested_by: null``, so the removal read as possibly the agent's own doing.

The actor is, in this order:

1. what the caller NAMED (``requested_by``): the agent instance whose tool call asked, or an operator
   lane's own name (``harness persona instance retire --requested-by``);
2. otherwise what the TRANSPORT proved (:class:`agent_runtime.call_authorization.RpcCaller`, never a
   param): the machine owner at its own console or Eternia over the install's socket is
   :data:`OPERATOR_ACTOR`; a paired device ``device:<id>``; another install ``install:<id>``;
3. otherwise :data:`UNKNOWN_ACTOR` — never ``None``, so a record always says who, or that nobody knows.

:func:`removal_activity` is the one sentence a removal's record and event carry ("You removed Base
Agent from testv4").
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .call_authorization import CALLER_DEVICE, CALLER_LOCAL_CONSOLE, CALLER_PEER, CALLER_STDIO_OWNER

__layer__ = "stores"
__all__ = [
    "OPERATOR_ACTOR",
    "REALM_SYNC_ACTOR",
    "UNKNOWN_ACTOR",
    "actor_from_caller",
    "actor_label",
    "removal_activity",
    "request_actor",
]

#: The machine owner: at its own shell, over the install's socket (Eternia), or on the serve's pipe.
OPERATOR_ACTOR = "operator"
#: Nobody named an actor and no transport proved one.
UNKNOWN_ACTOR = "unknown"
#: A removal another machine made, arriving through the realm's sync.
REALM_SYNC_ACTOR = "realm_sync"
#: The record's cap, the length the retire receipt always kept.
_ACTOR_LIMIT = 80


def _named(prefix: str, field: str) -> Callable[[Any], str]:
    def actor(caller: Any) -> str:
        value = getattr(caller, field, None)
        return _capped(f"{prefix}:{value}") if value else UNKNOWN_ACTOR

    return actor


#: Caller kind -> the actor it is. A kind not listed (``unknown``) is :data:`UNKNOWN_ACTOR`.
_CALLER_ACTORS: dict[str, Callable[[Any], str]] = {
    CALLER_LOCAL_CONSOLE: lambda _caller: OPERATOR_ACTOR,
    CALLER_STDIO_OWNER: lambda _caller: OPERATOR_ACTOR,
    CALLER_DEVICE: _named("device", "device_id"),
    CALLER_PEER: _named("install", "peer_install_id"),
}


def actor_from_caller(caller: Any) -> str:
    """The actor a transport-proven caller is; :data:`UNKNOWN_ACTOR` for none or an unplaced one."""

    actor = _CALLER_ACTORS.get(getattr(caller, "kind", None) or "")
    return actor(caller) if actor is not None else UNKNOWN_ACTOR


def request_actor(requested_by: Any = None, *, caller: Any = None) -> str:
    """The actor a lifecycle write records: named, else proven, else :data:`UNKNOWN_ACTOR`."""

    from .persona_assignments import safe_assignment_text

    # MUTATION: return requested_by unchanged and test_a_removal_nobody_named_records_unknown reddens.
    named = safe_assignment_text(requested_by, limit=_ACTOR_LIMIT) if requested_by is not None else ""
    return named or actor_from_caller(caller)


def actor_label(actor: str | None) -> str:
    """How a record names ``actor`` to a person: "You", the asking agent's name, a device, or "Someone"."""

    from .coordinator_permissions import OPERATOR_ACTORS

    text = str(actor or "").strip()
    if not text or text == UNKNOWN_ACTOR:
        return "Someone"
    if text in OPERATOR_ACTORS:
        return "You"
    if text == REALM_SYNC_ACTOR:
        return "A realm sync"
    if text.startswith("device:"):
        return f"A paired device ({text.split(':', 1)[1]})"
    if text.startswith("install:"):
        return f"Another install ({text.split(':', 1)[1]})"
    if text.startswith("personainst_"):
        return _instance_name(text) or text
    return text


def removal_activity(actor: str | None, *, agent_name: str | None, workspace_id: str | None) -> str:
    """"<who> removed <agent> from <workspace>" — the line a removal's record and event carry."""

    who = actor_label(actor)
    agent = str(agent_name or "").strip() or "an agent"
    workspace = _workspace_name(workspace_id)
    return f"{who} removed {agent} from {workspace}" if workspace else f"{who} removed {agent}"


def _capped(text: str) -> str:
    return text[:_ACTOR_LIMIT]


def _instance_name(instance_id: str) -> str | None:
    """The asking instance's name — live, else as it was archived; ``None`` when neither reads."""

    from .persona_assignments import PersonaInstanceStore

    store = PersonaInstanceStore()
    try:
        return store.get(instance_id).display_name or None
    except Exception:
        pass
    try:
        import json

        tombstone = store.retired_instance_archive_path(instance_id)
        if tombstone is not None:
            return json.loads(tombstone.read_text(encoding="utf-8")).get("display_name") or None
    except Exception:
        pass
    return None


def _workspace_name(workspace_id: str | None) -> str | None:
    if not workspace_id:
        return None
    try:
        from .store import WorkspaceStore

        return WorkspaceStore().get(workspace_id).name or workspace_id
    except Exception:
        return workspace_id
