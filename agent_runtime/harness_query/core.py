"""The harness query core: four read-only questions, small typed answers.

One authority for the questions an agent or an operator asks before acting:
who is on the roster, what one instance is, which chat sessions it holds and
whether each is hot/busy/cold, and whether a live QA session exists — each
answered with the exact instance and session ids it rests on.

Reads only the first-class readers the CLI verbs already call:
``PersonaInstanceStore.scan_all`` / ``.get`` (the roster rows),
``persona_chat_history_summary`` (the chat directory, including the runtime
observation), ``AgentStore`` + ``resolve_mcp_admission`` (the MCP resolution an
instance would get). Writes nothing: no ``ensure_*``, no mint, no event.

Runtime state is observed, not inferred. Only the process that owns the
resident-actor registry (the serve) can say ``hot`` / ``busy`` / ``cold``; any
other process answers ``unknown`` and every answer names its observer, so a
reply read off a CLI one-shot can never be mistaken for a live observation.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Final

__layer__ = "lanes"

__all__ = [
    "LIVE_RUNTIME_STATES",
    "QA_PERSONA_ID",
    "QUESTIONS",
    "answer",
    "observer",
    "resolve_instance",
]

#: The runtime states that mean an actor is resident in the serve right now.
LIVE_RUNTIME_STATES: Final[frozenset[str]] = frozenset({"hot", "busy"})
#: The persona whose sessions ``live_qa`` reports.
QA_PERSONA_ID: Final = "qa"
#: Default and ceiling for how many sessions one answer hydrates.
DEFAULT_SESSION_LIMIT: Final = 10
MAX_SESSION_LIMIT: Final = 50


def observer() -> dict[str, Any]:
    """Who is answering, and whether it can see resident actors at all."""

    from hermes_constants import get_hermes_home

    from .. import paths
    from ..persona_chat_continuity import persona_chat_runtime_registry

    owns_registry = persona_chat_runtime_registry() is not None
    return {
        "runtime_observer_id": f"serve:{os.getpid()}" if owns_registry else "external_cli",
        "observes_runtime_state": owns_registry,
        # Which store and which home produced this answer: roster answers are
        # home-independent, admission answers are not (operations.md, "Roots").
        "store_root": str(paths.store_root()),
        "hermes_home": str(get_hermes_home()),
    }


def _instance_row(instance: Any) -> dict[str, Any]:
    state = getattr(instance, "state", None)
    return {
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "role": instance.role,
        "display_name": instance.display_name,
        "state": getattr(state, "value", state),
        "mode": instance.mode,
        "profile_id": instance.profile_id,
        "workspace_id": instance.workspace_id,
        "default_chat_session_id": instance.default_chat_session_id,
    }


def resolve_instance(token: str | None) -> Any | None:
    """The stored instance a token names: an instance id, or a persona id.

    The same rule ``persona show`` applies: a ``personainst_`` token is read
    verbatim (the store resolves legacy spellings), anything else is a persona
    id mapped to its canonical instance id. ``None`` on a miss — never a write.
    """

    from ..persona_assignments import (
        PersonaInstanceStore,
        normalize_persona_id,
        persona_instance_id_for,
    )

    value = str(token or "").strip()
    if not value:
        return None
    instance_id = value if value.startswith("personainst_") else persona_instance_id_for(normalize_persona_id(value))
    try:
        return PersonaInstanceStore().get(instance_id)
    except Exception:  # noqa: BLE001 - a miss is an answer, not a crash
        return None


def _roster(_args: dict[str, Any]) -> dict[str, Any]:
    from ..persona_assignments import PersonaInstanceStore

    scan = PersonaInstanceStore().scan_all()
    rows = [_instance_row(instance) for instance in scan.instances]
    return {"instances": rows, "count": len(rows), "unreadable_rows": scan.unreadable}


def _mcp_resolution(instance: Any) -> dict[str, Any]:
    """CONFIGURED and ADMITTED as resolved now, under ``observer.hermes_home``.

    Never EXERCISED: whether a turn actually called a server is on that turn's
    receipt (``profile_timing.mcp_calls_spent`` in ``persona chat history``),
    and this answer says so rather than standing in for it.
    """

    from ..mcp_admission import resolve_mcp_admission
    from ..store import AgentStore

    base = {
        "basis": "resolved_now",
        "exercised":"not_answered_here: cite a turn's profile_timing.mcp_calls_spent",
    }
    persona = next((item for item in AgentStore().list_all() if item.id == instance.persona_id), None)
    if persona is None:
        return {**base, "basis": "unresolved", "reason": "persona_not_in_agent_store"}
    admission = resolve_mcp_admission(persona)
    return {
        **base,
        "enabled": admission.enabled,
        "configured": list(admission.requested),
        "admitted": list(admission.server_names),
        "denied": [row.get("code") for row in admission.denial_rows()],
    }


def _instance(args: dict[str, Any]) -> dict[str, Any]:
    instance = resolve_instance(args.get("instance"))
    if instance is None:
        return _miss(args)
    return {
        "instance": {
            **_instance_row(instance),
            "steered_by": list(instance.steered_by),
            "chat_head_home": instance.chat_head_home,
            "model": instance.model,
            "provider": instance.provider,
            "reasoning_effort": instance.reasoning_effort,
        },
        "mcp": _mcp_resolution(instance),
    }


def _session_rows(instance_ids: frozenset[str], limit: int) -> list[dict[str, Any]]:
    from ..persona_assignments import PersonaInstanceStore
    from ..persona_chat_history import persona_chat_history_summary

    rows = persona_chat_history_summary(
        persona_instances=PersonaInstanceStore().list_all(),
        limit=limit,
        message_tail=1,
        only_instance_ids=instance_ids,
    )
    return [
        {
            "persona_instance_id": row.get("persona_instance_id"),
            "session_id": row.get("session_id"),
            "active_session_id": row.get("active_session_id"),
            "title": row.get("title"),
            "state": row.get("state"),
            "runtime_state": row.get("runtime_state"),
            "runtime_observer_id": row.get("runtime_observer_id"),
            "message_count": row.get("message_count"),
            "updated_at": row.get("updated_at"),
        }
        for row in rows
    ]


def _limit(args: dict[str, Any]) -> int:
    try:
        value = int(args.get("limit") or DEFAULT_SESSION_LIMIT)
    except (TypeError, ValueError):
        value = DEFAULT_SESSION_LIMIT
    return min(max(value, 1), MAX_SESSION_LIMIT)


def _sessions(args: dict[str, Any]) -> dict[str, Any]:
    instance = resolve_instance(args.get("instance"))
    if instance is None:
        return _miss(args)
    rows = _session_rows(frozenset({instance.id}), _limit(args))
    for row in rows:
        row["is_default"] = row["session_id"] == instance.default_chat_session_id
    return {"persona_instance_id": instance.id, "sessions": rows, "count": len(rows)}


def _live_qa(args: dict[str, Any]) -> dict[str, Any]:
    """Is there a QA session an agent can USE right now — by id, or no.

    ``live`` holds sessions the serve observes resident (hot/busy). ``resumable``
    holds open sessions that exist but are not resident (or whose state this
    process cannot see). A persona definition, or a grep hit for ``qa``, is
    neither.
    """

    from ..persona_assignments import PersonaInstanceStore
    from ..persona_chat_history import canonical_chat_persona_id

    qa_ids = frozenset(
        instance.id
        for instance in PersonaInstanceStore().list_all()
        if canonical_chat_persona_id(instance.persona_id) == QA_PERSONA_ID
    )
    rows = _session_rows(qa_ids, _limit(args)) if qa_ids else []
    open_rows = [row for row in rows if row["state"] == "open"]
    live = [row for row in open_rows if row["runtime_state"] in LIVE_RUNTIME_STATES]
    resumable = [row for row in open_rows if row["runtime_state"] not in LIVE_RUNTIME_STATES]
    return {
        "qa_instance_ids": sorted(qa_ids),
        "live": live,
        "resumable": resumable,
        "verdict": _qa_verdict(live, resumable, observes=observer()["observes_runtime_state"]),
    }


def _qa_verdict(live: list, resumable: list, *, observes: bool) -> str:
    if live:
        return "live_session"
    if not resumable:
        return "no_qa_session"
    if not observes:
        return "runtime_state_unobservable_here"
    return "no_live_session"


def _miss(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "not_found",
        "detail": f"no persona instance resolves from {args.get('instance')!r}",
    }


#: Routing is data: one handler per question, and the tuple below is its keys.
_HANDLERS: Final[dict[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "roster": _roster,
    "instance": _instance,
    "sessions": _sessions,
    "live_qa": _live_qa,
}
QUESTIONS: Final[tuple[str, ...]] = tuple(_HANDLERS)


def answer(question: str, **args: Any) -> dict[str, Any]:
    """Answer one question; the envelope always names the question and observer."""

    handler = _HANDLERS.get(str(question or "").strip())
    if handler is None:
        return {"ok": False, "error": "unknown_question", "question": question, "questions": list(QUESTIONS)}
    body = handler(args)
    return {"ok": True, **body, "question": question, "observer": observer()}
