"""``persona instance create`` / ``runtime.persona.instance.create`` — mint an Agent Profile or a placement.

The sequence is ``lifecycle_commands._cmd_persona_instance_create`` (known
persona, ``create_operator_chat`` or the ``add_instance`` placement mint, the
chat root persisted before the row says ok); this door runs it through the
mission-chat door and returns its row. The coordinator-budget flags are closed
(:data:`door.COORDINATOR_ARGS_CLOSED`).
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"
__all__ = ["INSTANCE_CREATE_PARAMS", "create_persona_instance"]

INSTANCE_CREATE_PARAMS = (
    "persona_id", "display_name", "title", "session_id", "kill_active", "add_instance",
    "placement_id", "workspace_id", "realm_id", "client_message_id", "requested_by",
)


def create_persona_instance(params: dict, *, caller: Any | None = None) -> dict:
    """Params: ``persona_id`` and ``display_name`` (required by the verb —
    ``title`` is its fallback); ``session_id``, ``kill_active``,
    ``add_instance`` with ``placement_id`` / ``workspace_id`` / ``realm_id``,
    ``client_message_id``, ``requested_by``. Row: ``persona_instance_id``,
    ``session_id`` (= ``default_chat_session_id``), ``display_name``, ``mode``,
    ``placement_id`` and the rest of the argv row."""
    from ..mission_chat_door import INSTANCE_CREATE_VERB
    from ..persona_open_chat import _text
    from .door import COORDINATOR_ARGS_CLOSED, caller_requester, run_cli_chat_verb

    persona_id = _text(params, "persona_id")
    if not persona_id:
        return {"ok": False, "error_kind": "invalid_request", "error": "persona_id is required"}
    return run_cli_chat_verb(
        INSTANCE_CREATE_VERB,
        persona_id=persona_id,
        title=_text(params, "title") or "New operator chat",
        display_name=_text(params, "display_name"),
        session_id=_text(params, "session_id"),
        kill_active=params.get("kill_active") is True,
        add_instance=params.get("add_instance") is True,
        placement_id=_text(params, "placement_id"),
        workspace_id=_text(params, "workspace_id"),
        realm_id=_text(params, "realm_id"),
        client_message_id=_text(params, "client_message_id"),
        requested_by=caller_requester(params, caller),
        **COORDINATOR_ARGS_CLOSED,
    )
