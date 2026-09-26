"""The helpers every agent_chat handler shares: the refusal reply, the scope switch, the persona token, the chat-lane membership test, the limit clamp."""

from __future__ import annotations

import json
import os

from agent_runtime.serde import is_hex

__layer__ = "lanes"


def refusal_json(error: str, **extra) -> str:
    return json.dumps({"ok": False, "error": error, **extra})


def _looks_like_instance_handle(value) -> bool:
    """True when *value* is a ``personainst_*`` instance handle (not a bare
    persona id). A persona can run more than one live instance, so a handle in a
    persona slot must TARGET THAT INSTANCE — it is forwarded as the instance id
    rather than collapsed to the persona's canonical channel."""
    from agent_runtime.persona_assignments import safe_assignment_token

    return safe_assignment_token(value).startswith("personainst_")


#: The ``HERMES_AGENT_CHAT_SCOPE`` value that disables every agent_chat tool.
SCOPE_OFF = "off"


def scope_off() -> bool:
    """Is the agent-chat lane switched off on this runtime? The ONE reader of
    ``HERMES_AGENT_CHAT_SCOPE`` — the send lane and the three read tools ask it."""
    return (os.environ.get("HERMES_AGENT_CHAT_SCOPE") or "open").strip().lower() == SCOPE_OFF


def _canonical_persona_token(value) -> str:
    from agent_runtime.persona_assignments import safe_assignment_token

    return safe_assignment_token(value)


def session_belongs_to_chat_lane(session_id: str, *, handle: str, default_session: str | None) -> bool:
    """True when ``session_id`` is the target instance's chat lane.

    Tight by design (this is 'review OUR thread', not a transcript browser): the
    target instance's current default pointer, or a session minted for exactly
    that instance — ``persona_chat_<handle>_<12 hex>`` (see
    ``persona_chat_session_id_for``). The trailing segment MUST be a bare 12-hex
    suffix so a sibling's session (``persona_chat_<handle>_agent_2_<hex>``) is not
    swallowed by the primary's prefix: ``personainst_qa`` must not match
    ``personainst_qa_agent_2``'s session. Anything else — another teammate's or
    sibling's chat, a task/worker session — is foreign and refused.
    """
    if default_session and session_id == default_session:
        return True
    if not handle:
        return False
    prefix = f"persona_chat_{handle}_"
    if not session_id.startswith(prefix):
        return False
    tail = session_id[len(prefix):]
    return is_hex(tail.lower(), 12)


def _bounded_limit(value, *, default: int = 20) -> int:
    """``value`` as an int, or *default*. Never raises, never a string."""

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _chat_lane_session_ids(target) -> list:
    """Every session in the caller's chat lane with *target*, newest last.

    Derived from the SAME history projection ``agent_chat_threads`` reads and
    filtered through the SAME ``session_belongs_to_chat_lane`` guard, so
    ``all_threads`` can never widen the scope beyond what a single-thread
    request would allow — it only saves the caller from guessing which
    task-scoped thread a dispatch opened.
    """

    from agent_runtime.persona_chat_history import persona_chat_history_summary

    found: list[str] = []
    try:
        rows = persona_chat_history_summary(persona_instances=target.store.list_all())
    except Exception:  # pragma: no cover - a projection glitch must not blank the answer
        rows = []
    for row in rows or []:
        candidate = str((row or {}).get("session_id") or "")
        if not candidate or candidate in found:
            continue
        if session_belongs_to_chat_lane(
            candidate, handle=target.handle, default_session=target.default_session
        ):
            found.append(candidate)
    if target.default_session and target.default_session not in found:
        found.append(target.default_session)
    return found
