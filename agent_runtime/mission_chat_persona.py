"""Which persona a mission-chat target names — the runtime's own resolver.

``resolve_mission_chat_persona_id`` used to live in the CLI part
``hermes_cli/harness_parts/persona/chat_target.py`` although it is a pure
composition of :mod:`agent_runtime.persona_assignments` primitives, so the
runtime's peer roster (``peer_directory``) reached UP into the CLI to call it.
It lives here now, beside the primitives it composes; ``chat_target`` binds its
historical private name to this function, so the CLI and the runtime resolve a
target through ONE implementation (lane W3-B).

Layer: ``stores`` — it reads :mod:`agent_runtime.persona_assignments` (stores).
"""

from __future__ import annotations

from agent_runtime.persona_assignments import (
    normalize_persona_or_template_id,
    persona_id_from_instance_id,
    safe_assignment_token,
)

__layer__ = "stores"
__all__ = ["resolve_mission_chat_persona_id"]


def resolve_mission_chat_persona_id(persona_id, persona_instance_id) -> str:
    """Resolve the chat target persona from whichever identity the caller sent.

    Prefer the persona id; when it is mangled (a stale instance-shaped id from a
    legacy SessionDB row, a display token, etc.) but the caller also supplied a
    resolvable persona_instance_id, the instance wins instead of failing the
    whole send. Raises ``ValueError`` when neither resolves.
    """
    try:
        return normalize_persona_or_template_id(persona_id)
    except ValueError:
        instance_token = safe_assignment_token(persona_instance_id)
        if instance_token:
            return persona_id_from_instance_id(instance_token)
        raise
