"""A steer the turn finished before absorbing becomes this chat root's next turn.

Upstream's ``agent/turn_finalizer.py`` drains the steer buffer once more at the end
of a turn and hands what is left back as ``result["pending_steer"]`` — input that
arrived after the final tool batch, so no tool result carried it. Every upstream
consumer delivers it as the next user turn (``gateway/run_turn.py``,
``cli_chat_turn_mixin``, ``tui_gateway/prompt_turn.py``). The Mission Control lane
acknowledged that input as ACCEPTED (``agent_runtime.mission_chat_steer``) and,
before this module, dropped it.

Owner ruling 2026-10-15: pass it to the next turn, as upstream does; never drop
what the operator typed. The next turn rides the busy-root send queue
(``agent_runtime.chat_root_send_queue``), the one door that already runs a send
after the turn holding the root, in arrival order, with the sender's origin.
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"
__all__ = ["leftover_steer_client_message_id", "queue_leftover_steer"]

#: Prefix of the queued turn's ``client_message_id``. Derived from the steer's own
#: id, so a replay of the same turn converges on the one queue entry.
NEXT_TURN_PREFIX = "steer-next-"


def leftover_steer_client_message_id(pending: Any, turn_client_message_id: str) -> str:
    """The next turn's id: the first addressed input's id, else the turn's own."""

    for item in getattr(pending, "inputs", ()) or ():
        platform_id = str(getattr(item, "platform_id", None) or "").strip()
        if platform_id:
            return NEXT_TURN_PREFIX + platform_id
    return NEXT_TURN_PREFIX + str(turn_client_message_id or "").strip()


def queue_leftover_steer(args: Any, *, session_id: str, client_message_id: str, raw: Any) -> str | None:
    """Queue ``raw["pending_steer"]`` as the root's next operator send. Returns its id.

    ``None`` when the turn left nothing over. Called under the chat-root lease, so the
    entry is on disk before the root frees; the lease release wakes the runner.
    """

    from agent_runtime import chat_root_send_queue
    from hermes_cli.harness_parts.serve.queued_turn_origin import send_origin

    pending = raw.get("pending_steer") if isinstance(raw, dict) else None
    text = str(pending or "").strip()
    if not text or not session_id:
        return None
    next_id = leftover_steer_client_message_id(pending, client_message_id)
    persisted = chat_root_send_queue.persistable_args(args, origin=send_origin())
    # The same root, as a plain follow-up: never a new thread, a clarify answer, a
    # retry, a title or a second use of the first send's idempotency key.
    persisted.update(
        message=text, client_message_id=next_id, session_id=session_id, new_session=False,
        clarify_token=None, retry_of=None, title=None, idempotency_key=None,
    )
    chat_root_send_queue.enqueue(session_id, next_id, persisted)
    return next_id
