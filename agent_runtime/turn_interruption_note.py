"""A message that cut off the agent's spoken reply tells the model so, on that turn only
(RT-FU-ETERNIAS-AGENT-CALL-CAN-USE-HERMES-OWN-INTERRUPT-RULES).

When the user talks over a reply in a voice call, the model should know its last answer was not heard
to the end. Hermes already says it: ``tools.tts_streaming.SPEECH_INTERRUPTED_NOTE``. Its own surfaces
carry the fact two ways: the CLI and TUI set a process-wide mark (``mark_speech_interrupted``), and the
gateway's ``prompt.submit`` takes ``interrupted: true`` per turn (``gateway/session_surface.py``). A
served runtime runs many chats in one process, where a process-wide mark could land on another chat, so
a serve turn carries it the gateway's way: ``runtime.chat.message`` ``interrupted`` -> ``--interrupted``
-> this callback, which stages hermes's note on the turn's one-shot must-deliver channel
(:func:`agent_runtime.surface_prompt_note.stage_turn_note`), first, ahead of the fork's surface-prompt
note (the gateway's ``surface_note`` also puts the interruption first among its notes). The note is stamped into that user row's ``api_content`` sidecar, so a later turn
replays it unchanged and the operator's visible row stays the words they said.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.surface_prompt_note import stage_turn_note

__layer__ = "policy"

__all__ = ["with_interruption_note"]

ReadyCallback = Callable[[Any], Callable[[], None] | None]


def with_interruption_note(callback: ReadyCallback | None, *, interrupted: bool) -> ReadyCallback | None:
    """Wrap the turn's agent-ready callback so an interrupting message stages hermes's note before
    ``callback`` runs (so before any note ``callback`` stages); unchanged when not ``interrupted``."""
    if not interrupted:
        return callback

    def ready(agent: Any) -> Callable[[], None] | None:
        from tools.tts_streaming import SPEECH_INTERRUPTED_NOTE

        stage_turn_note(agent, SPEECH_INTERRUPTED_NOTE)
        return callback(agent) if callback is not None else None

    return ready
