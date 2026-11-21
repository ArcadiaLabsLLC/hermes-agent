"""``runtime.persona.instance.create`` — mint an operator chat channel for a known agent.

The sequence is ``lifecycle_commands._cmd_persona_instance_create`` (known
persona, ``create_operator_chat``, the chat root persisted before the row says
ok); this door runs it through the mission-chat door and returns its row. The
coordinator-budget flags are closed (:data:`door.COORDINATOR_ARGS_CLOSED`).

It no longer places or copies an agent (RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT,
review w1118a.74): ``add_instance`` and ``independent_agent`` are refused
``placing_door_moved`` before anything is written, naming ``runtime.agent.place``
/ ``runtime.agent.create`` (``agent_create.perform``, the one owner). Eternia sends
neither since onepath-el2 (89bb9c84fdd).
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"
__all__ = ["create_persona_instance"]


def create_persona_instance(params: dict, *, caller: Any | None = None) -> dict:
    """Params: ``persona_id`` and ``display_name`` (required by the verb —
    ``title`` is its fallback); ``session_id``,
    ``client_message_id``, ``requested_by``, ``client_scope`` (the account's
    64-hex digest the new chat is stamped with; ``invalid_client_scope`` before
    any write when malformed; echoed on the row when sent). Row: ``persona_instance_id``,
    ``session_id`` (= ``default_chat_session_id``), ``display_name``, ``mode``,
    the rest of the argv row. ``add_instance`` / ``independent_agent`` true: refused
    ``placing_door_moved``."""
    from ..agent_create.outcome import PLACING_DOORS, placing_door_moved
    from ..conversation_owner import ConversationOwnerError, request_client_scope
    from ..mission_chat_door import INSTANCE_CREATE_VERB
    from ..persona_open_chat import KILL_ACTIVE_RETIRED, KILL_ACTIVE_RETIRED_MESSAGE, _first_text
    from .door import COORDINATOR_ARGS_CLOSED, caller_requester, run_cli_chat_verb

    if "kill_active" in params:  # RT-KILL-ACTIVE-REFUSE: retired, refused -32602
        return {"ok": False, "error_kind": KILL_ACTIVE_RETIRED, "error": KILL_ACTIVE_RETIRED_MESSAGE}
    # MUTATION: drop this refusal and
    # test_a_create_that_asks_to_place_or_copy_is_refused_naming_the_door reddens.
    # Refused, not honoured: read the way ``kill_active`` is, so the manifest's honoured
    # keys stay exactly the ones the verb acts on.
    for key in PLACING_DOORS:
        if key in params and params[key] is True:
            return placing_door_moved(key)
    # RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT: validated the way
    # ``runtime.agent.create`` validates it, before anything is written.
    try:
        owner = request_client_scope(params)
    except ConversationOwnerError as exc:
        return {"ok": False, "error_kind": exc.reason, "error": "Invalid conversation owner."}
    persona_id = _first_text(params, "persona_id")
    if not persona_id:
        return {"ok": False, "error_kind": "invalid_request", "error": "persona_id is required"}
    return run_cli_chat_verb(
        INSTANCE_CREATE_VERB,
        persona_id=persona_id,
        title=_first_text(params, "title") or "New operator chat",
        display_name=_first_text(params, "display_name"),
        session_id=_first_text(params, "session_id"),
        add_instance=False,
        independent_agent=False,
        client_message_id=_first_text(params, "client_message_id"),
        requested_by=caller_requester(params, caller),
        client_scope=owner,
        **COORDINATOR_ARGS_CLOSED,
    )
