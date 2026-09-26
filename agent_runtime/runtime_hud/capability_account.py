"""The chat-side capability account: ``capability_block_for_persona``.

It does the lookups one mission-chat turn needs — the stored permission posture,
the chat-lane drops, the terminal-envelope view — then calls the pure
:func:`resolve_capability_block`. Every lookup is a store read or pure policy, so
this is a store; the lanes-level wrappers (the board digest, the paired installs,
the situational HUD) stay in ``ambient``. ``chat_lane_bundle`` (stores) resolves
the account through here, which is why it cannot live beside them.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.runtime_hud.capability import resolve_capability_block

__layer__ = "stores"


def capability_block_for_persona(
    persona: Any,
    *,
    session_id: str | None = None,
    permission_mode: str | None = None,
    lane: str | None = None,
) -> dict[str, Any]:
    """Chat-side convenience: resolve both capability accounts for one persona.

    The wrapper twin of :func:`situational_hud_for_instance` — it does the
    lookups a single mission-chat turn needs, then calls the same pure
    :func:`resolve_capability_block` (one authority). Both halves resolve the
    SAME functions the turn itself resolves (``chat_lane_capability_drops`` is
    the accounting twin of ``_enabled_toolsets_for_chat``;
    ``explain_terminal_envelope`` reads the same grants
    ``envelope_decision`` will), so what the agent is told and what the runtime
    then does cannot disagree.

    The two halves degrade INDEPENDENTLY: a fault resolving the drops must not
    blank the envelope posture, and vice versa. Best-effort overall — the
    capability account decorates a turn, it never blocks one.
    """

    if persona is None:
        return {}

    # The posture this turn runs under. Resolved through the ONE chokepoint (a
    # caller-supplied ``permission_mode`` still wins, for the hypothetical
    # ``persona tool-diff --permission-mode`` preview) and threaded into BOTH
    # halves: the envelope view is mode-aware since 2026-08-09, so reading it
    # without the mode would tell the agent classes are refused that its very
    # next command would run.
    mode = str(permission_mode or "").strip()
    source = ""
    if not mode:
        try:
            from ..tool_permissions import permission_options_for_chat

            resolved = permission_options_for_chat(persona, session_id=session_id)
            mode = str(resolved.permission_mode or "")
            source = str(resolved.permission_source or "")
        except Exception:
            mode = ""

    drops: tuple[Any, ...] = ()
    try:
        # Deferred: ``persona_runtime`` pulls the runtime graph (and imports this
        # module's siblings), so a module-level import here would be circular.
        from ..chat_lane_bundle import chat_lane_capability_drops

        drops = chat_lane_capability_drops(
            persona, session_id=session_id, permission_mode=permission_mode
        )
    except Exception:
        drops = ()

    envelope: dict[str, Any] | None = None
    try:
        from ..personas import role_or_attr
        from ..terminal_envelope.classes import LANE_MISSION_CHAT
        from ..terminal_envelope.decision import explain_terminal_envelope

        envelope = explain_terminal_envelope(
            role=role_or_attr(persona),
            lane=str(lane or "").strip() or LANE_MISSION_CHAT,
            permission_mode=mode,
        )
    except Exception:
        envelope = None

    return resolve_capability_block(
        drops=drops,
        envelope=envelope,
        permission_mode=mode,
        permission_source=source,
    )
