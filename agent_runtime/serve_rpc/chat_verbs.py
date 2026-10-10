"""The chat-family method twins: history, instance create, turn resolve, queue skill, delete.

Argv census rows 11-15 (launcher ``argv-census-full-2026-10-03.md``): every
chat open and first send rode argv, so none of them could reach a REMOTE aim
(R-D23 refuses argv to one). Each method calls the one implementation in
:mod:`agent_runtime.chat_verbs` and returns the argv verb's ``--json`` row
verbatim on success.

**Refusals.** The row's ``error`` is the message; ``data.reason`` is its
``error_kind`` (else its ``reason``, else its ``status``, else
``<verb>_refused``); every other key on the row rides ``data`` unchanged —
``next_expected``, ``lease_owner``, ``rejected_skills``. The code comes from
:data:`REFUSAL_CODES`; an untyped refusal is the request being wrong
(``ERR_INVALID_PARAMS``), the ``persona_open_chat`` rule.

**Tiers.** All five are ``console``. Four write. History is the one row worth
arguing: it writes nothing, but it hands back transcript text, and the read tier
is open to ``unknown`` — ``runtime.conversation.read`` says ``console`` for the
same reason. None is on ``LOCAL_CONSOLE_METHODS``: a paired console device
working the chats of the install it is aimed at is the feature.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "REFUSAL_CODES",
    "_runtime_chat_queue_skill",
    "_runtime_chat_turn_resolve",
    "_runtime_persona_chat_delete",
    "_runtime_persona_chat_history",
    "_runtime_persona_instance_create",
    "row_reply",
]

#: ``data.reason`` -> JSON-RPC code, for every typed reason the five rows carry.
REFUSAL_CODES: dict[str, int] = {
    "content_changed": ERR_CONFLICT,
    "content_unavailable": ERR_NOT_FOUND,
    "conversation_owner_changed": ERR_CONFLICT,
    "invalid_request": ERR_INVALID_PARAMS,
    "skills_not_loadable": ERR_INVALID_PARAMS,
    "placement_id_not_discriminable": ERR_INVALID_PARAMS,
    "not_found": ERR_NOT_FOUND,
    "persona_not_found": ERR_NOT_FOUND,
    "persona_instance_not_found": ERR_NOT_FOUND,
    "foreign_chat_session": ERR_CONFLICT,
    "chat_busy": ERR_CONFLICT,
    "chat_turn_resolution_mismatch": ERR_CONFLICT,
    "retired_persona_instance": ERR_CONFLICT,
    "needs_operator_confirm": ERR_CONFLICT,
    "chat_session_db_unavailable": ERR_HANDLER_FAILED,
    "chat_session_persist_failed": ERR_HANDLER_FAILED,
    "persona_roster_unavailable": ERR_HANDLER_FAILED,
    "session_db_unavailable": ERR_HANDLER_FAILED,
    "session_db_read_failed": ERR_HANDLER_FAILED,
    "chat_scope_unresolved": ERR_HANDLER_FAILED,
    "chat_scope_mismatch": ERR_CONFLICT,
    "invalid_history_cursor": ERR_INVALID_PARAMS,
    "mission_chat_door_unbound": ERR_HANDLER_FAILED,
    "chat_verb_payload_missing": ERR_HANDLER_FAILED,
}


def row_reply(rid: Any, row: dict, verb: str) -> dict:
    """The argv row as a frame: ``ok`` true is the result, anything else a refusal."""
    if row.get("ok") is True:
        return ok(rid, row)
    reason = str(row.get("error_kind") or row.get("reason") or row.get("status") or f"{verb}_refused")
    data = {key: value for key, value in row.items() if key not in {"ok", "error"}}
    data["reason"] = reason
    return err(rid, REFUSAL_CODES.get(reason, ERR_INVALID_PARAMS), str(row.get("error") or reason), data)


def _invalid(rid: Any, verb: str, message: str) -> dict:
    return row_reply(rid, {"ok": False, "error_kind": "invalid_request", "error": message}, verb)


def _params(params: Any) -> dict:
    return params if isinstance(params, dict) else {}


def _caller(context: RpcContext | None):
    return context.caller if context is not None else None


@method("runtime.persona.chat.history", tier=TIER_CONSOLE)
def _runtime_persona_chat_history(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness persona chat history``. Params: ``session_id`` (required),
    ``limit`` (int, clamped 1..40), ``before`` (the previous page's cursor)."""
    from agent_runtime.chat_verbs.history import persona_chat_history_page

    params = _params(params)
    session_id, limit, before = params.get("session_id"), params.get("limit"), params.get("before")
    if (
        not isinstance(session_id, str)
        or not session_id.strip()
        or (limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)))
        or (before is not None and not isinstance(before, str))
    ):
        return _invalid(rid, "history", "session_id (string) is required; limit is an integer, before a string")
    return row_reply(rid, persona_chat_history_page(session_id.strip(), limit=limit, before=before), "history")


@method("runtime.persona.instance.create", tier=TIER_CONSOLE)
def _runtime_persona_instance_create(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness persona instance create`` — see :mod:`agent_runtime.chat_verbs.instance_create`."""
    from agent_runtime.chat_verbs.instance_create import create_persona_instance

    row = create_persona_instance(_params(params), caller=_caller(context))
    return row_reply(rid, row, "instance_create")


@method("runtime.chat.turn.resolve", tier=TIER_CONSOLE)
def _runtime_chat_turn_resolve(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness mission-chat turn-resolve``. Params: ``session_id``,
    ``client_message_id``, ``turn_id``, ``action`` (``abandon``),
    ``persona_instance_id`` (all required); ``reason``."""
    from agent_runtime.chat_verbs.turn_resolve import resolve_chat_turn

    params = _params(params)
    row = resolve_chat_turn(
        session_id=params.get("session_id"),
        client_message_id=params.get("client_message_id"),
        turn_id=params.get("turn_id"),
        action=params.get("action"),
        persona_instance_id=params.get("persona_instance_id"),
        reason=params.get("reason"),
    )
    return row_reply(rid, row, "turn_resolve")


@method("runtime.chat.queue_skill", tier=TIER_CONSOLE)
def _runtime_chat_queue_skill(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness mission-chat queue-skill``. Params: ``persona_id``,
    ``session_id``, and ``skills`` (a list) or ``skill`` (one string), all
    required; ``persona_instance_id``."""
    from agent_runtime.chat_verbs.queue_skill import queue_skills_next_turn

    params = _params(params)
    skills, one = params.get("skills"), params.get("skill")
    if (skills is not None and not isinstance(skills, list)) or (one is not None and not isinstance(one, str)):
        return _invalid(rid, "queue_skill", "skills is a list and skill a string")
    row = queue_skills_next_turn(
        persona_id=params.get("persona_id"),
        session_id=params.get("session_id"),
        skills=[*([one] if one else []), *(skills or [])],
        persona_instance_id=params.get("persona_instance_id"),
    )
    return row_reply(rid, row, "queue_skill")


@method("runtime.persona.chat.delete", tier=TIER_CONSOLE)
def _runtime_persona_chat_delete(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """``harness persona chat delete`` — see :mod:`agent_runtime.chat_verbs.delete`."""
    from agent_runtime.chat_verbs.delete import delete_persona_chat

    return row_reply(rid, delete_persona_chat(_params(params), caller=_caller(context)), "delete")


@method("runtime.persona.chat.content", tier=TIER_CONSOLE)
def _runtime_persona_chat_content(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Read a bounded text window through the existing transcript authority."""
    from agent_runtime.persona_chat_history.content import read_chat_content

    return row_reply(rid, read_chat_content(_params(params)), "content")
