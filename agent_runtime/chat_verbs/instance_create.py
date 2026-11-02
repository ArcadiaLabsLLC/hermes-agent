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
    "persona_id", "display_name", "title", "session_id", "add_instance",
    "placement_id", "workspace_id", "realm_id", "client_message_id", "requested_by",
)


def create_persona_instance(params: dict, *, caller: Any | None = None) -> dict:
    """Params: ``persona_id`` and ``display_name`` (required by the verb —
    ``title`` is its fallback); ``session_id``,
    ``add_instance`` with ``placement_id`` / ``workspace_id`` / ``realm_id``,
    ``client_message_id``, ``requested_by``. Row: ``persona_instance_id``,
    ``session_id`` (= ``default_chat_session_id``), ``display_name``, ``mode``,
    ``placement_id`` and the rest of the argv row."""
    from ..mission_chat_door import INSTANCE_CREATE_VERB
    from ..persona_open_chat import KILL_ACTIVE_RETIRED, KILL_ACTIVE_RETIRED_MESSAGE, _first_text
    from .door import COORDINATOR_ARGS_CLOSED, caller_requester, run_cli_chat_verb

    if "kill_active" in params:  # RT-KILL-ACTIVE-REFUSE: retired, refused -32602
        return {"ok": False, "error_kind": KILL_ACTIVE_RETIRED, "error": KILL_ACTIVE_RETIRED_MESSAGE}
    persona_id = _first_text(params, "persona_id")
    if not persona_id:
        return {"ok": False, "error_kind": "invalid_request", "error": "persona_id is required"}
    return run_cli_chat_verb(
        INSTANCE_CREATE_VERB,
        persona_id=persona_id,
        title=_first_text(params, "title") or "New operator chat",
        display_name=_first_text(params, "display_name"),
        session_id=_first_text(params, "session_id"),
        add_instance=params.get("add_instance") is True,
        placement_id=_first_text(params, "placement_id"),
        workspace_id=_first_text(params, "workspace_id"),
        realm_id=_first_text(params, "realm_id"),
        client_message_id=_first_text(params, "client_message_id"),
        requested_by=caller_requester(params, caller),
        **COORDINATOR_ARGS_CLOSED,
    )
