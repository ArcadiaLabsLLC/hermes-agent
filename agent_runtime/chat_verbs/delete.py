"""``persona chat delete`` / ``runtime.persona.chat.delete`` — retire one chat root and its bindings.

The sequence is ``chat_delete._cmd_persona_chat_delete`` (ownership fence, the
root lease, compression-lineage delete, every dangling binding cleared, the
``persona_chat.deleted`` event); this door runs it through the mission-chat
door and returns its row.
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"
__all__ = ["delete_persona_chat"]


def delete_persona_chat(params: dict, *, caller: Any | None = None) -> dict:
    """Params: ``session_id`` (required); ``persona_id``, ``persona_instance_id``,
    ``requested_by``. Row: ``session_id``, ``deleted_session``,
    ``cleared_bindings``, ``cleared_binding_count``, ``closed_assignment_ids``.
    Refusals: ``foreign_chat_session``, ``chat_busy``,
    ``chat_session_db_unavailable``, ``status: not_found``."""
    from ..mission_chat_door import CHAT_DELETE_VERB
    from ..persona_open_chat import _text
    from .door import caller_requester, run_cli_chat_verb

    return run_cli_chat_verb(
        CHAT_DELETE_VERB,
        session_id=_text(params, "session_id"),
        persona_id=_text(params, "persona_id"),
        persona_instance_id=_text(params, "persona_instance_id"),
        requested_by=caller_requester(params, caller),
    )
