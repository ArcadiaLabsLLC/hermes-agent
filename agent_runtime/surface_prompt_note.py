"""A changed surface prompt reaches the model on its own turn (RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN).

The persona chat puts an Eternia surface's prompt (Home's draft address, Edu's tutor brief, ...)
in the system message. On a continuing chat upstream reuses the system prompt stored on the
chat's first turn (``agent/conversation_loop.py``: the stored bytes are kept unless model,
provider, session or cwd moved), so a later turn's surface prompt never reached the model.

Rebuilding the prompt on every change is refused (T5: Home's prompt changes every request, so
every request would re-bill the whole prefix). Instead, upstream's surface-switch pattern
(#104414): the current surface prompt rides the turn's tail on the gateway's must-deliver note
channel (``agent._gateway_turn_context_notes``), which lands behind the cached prefix and is
stamped into the user row's ``api_content`` sidecar, so later turns replay it unchanged and the
operator's visible row is untouched. The stored system prompt and tools stay byte-identical.

What the model was last told is the newest note in the transcript, else the prompt in force.
A note that would repeat the newest one is not sent, so an unchanged surface prompt adds nothing.
"""

from __future__ import annotations

from typing import Any, Callable

from agent.message_content import flatten_message_text

NOTE_OPEN = (
    "[System: Surface instructions for this turn. They replace the surface instructions in the "
    "system prompt above and any given earlier in this conversation:]"
)
NOTE_CLOSE = "[End of surface instructions.]"
_NO_SURFACE = "None. Earlier surface instructions no longer apply."
# Only the newest note matters; the bound keeps a long chat from walking its whole transcript.
_NOTE_SCAN_TAIL = 200


def render_surface_note(surface_prompt: str | None) -> str:
    body = (surface_prompt or "").strip() or _NO_SURFACE
    return f"{NOTE_OPEN}\n{body}\n{NOTE_CLOSE}"


def _newest_note(conversation_history: Any) -> str:
    """The newest surface note the transcript carries ("" when none)."""
    for msg in reversed((conversation_history or [])[-_NOTE_SCAN_TAIL:]):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        sidecar = msg.get("api_content")
        text = (sidecar if isinstance(sidecar, str) else "") + "\n" + flatten_message_text(msg.get("content"))
        if NOTE_OPEN not in text:
            continue
        tail = NOTE_OPEN + text.rsplit(NOTE_OPEN, 1)[1]
        end = tail.find(NOTE_CLOSE)
        # A note cut short (bounded or redacted) reads as different, so it is re-sent: never lost.
        return tail[: end + len(NOTE_CLOSE)] if end >= 0 else tail
    return ""


def surface_prompt_note(
    *,
    surface_prompt: str | None,
    system_message: str,
    prompt_in_force: str,
    conversation_history: Any,
) -> str:
    """The note this turn must carry, or "" when the model already has this surface prompt.

    ``prompt_in_force`` is the system prompt the turn will send ("" when upstream will build a
    fresh one from ``system_message``, which then carries the surface prompt itself)."""
    if not conversation_history or not prompt_in_force:
        return ""
    note = render_surface_note(surface_prompt)
    told = _newest_note(conversation_history)
    if told:
        return "" if told == note else note
    if not (surface_prompt or "").strip():
        # The composed message without a surface prompt is a prefix of one with it, so the prompt
        # cannot say whether a first-turn surface prompt was cleared since; nothing is sent.
        return ""
    return "" if system_message in prompt_in_force else note


def prompt_in_force(agent: Any) -> str:
    """The system prompt this agent's turn will send, as far as the fork can read it before the run:
    a warm agent's cached prompt, else the stored prompt a continuing session restores."""
    cached = getattr(agent, "_cached_system_prompt", None)
    if isinstance(cached, str) and cached:
        return cached
    session_db = getattr(agent, "_session_db", None)
    session_id = getattr(agent, "session_id", None)
    if session_db is None or not session_id:
        return ""
    try:
        row = session_db.get_session(session_id)
    except Exception:
        return ""
    prompt = row.get("system_prompt") if isinstance(row, dict) else None
    return prompt if isinstance(prompt, str) else ""


def stage_turn_note(agent: Any, note: str) -> None:
    """Queue ``note`` on upstream's one-shot must-deliver channel, after any note already staged."""
    prior = getattr(agent, "_gateway_turn_context_notes", "") or ""
    agent._gateway_turn_context_notes = f"{prior}\n\n{note}" if prior else note


def with_surface_prompt_note(
    callback: Callable[[Any], Callable[[], None] | None] | None,
    *,
    surface_prompt: str | None,
    system_message: str,
    conversation_history: Any,
) -> Callable[[Any], Callable[[], None] | None] | None:
    """Wrap the turn's agent-ready callback so the note is staged on the agent before it converses."""
    if not conversation_history:
        return callback

    def ready(agent: Any) -> Callable[[], None] | None:
        note = surface_prompt_note(
            surface_prompt=surface_prompt,
            system_message=system_message,
            prompt_in_force=prompt_in_force(agent),
            conversation_history=conversation_history,
        )
        if note:
            stage_turn_note(agent, note)
        return callback(agent) if callback is not None else None

    return ready
