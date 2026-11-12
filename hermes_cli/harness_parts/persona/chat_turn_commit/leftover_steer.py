"""A steer the turn finished before absorbing becomes this chat root's next turn.

Upstream's ``agent/turn_finalizer.py`` drains the steer buffer once more at the end
of a turn and hands what is left back as ``result["pending_steer"]`` — input that
arrived after the final tool batch, so no tool result carried it. Every upstream
consumer delivers it as the next user turn (``gateway/run_turn.py``,
``cli_chat_turn_mixin``, ``tui_gateway/prompt_turn.py``). The Mission Control lane
acknowledged that input as ACCEPTED (``agent_runtime.mission_chat_steer``) and,
before this module, dropped it.

Owner ruling 2026-10-15: pass it to the next turn, as upstream does; never drop
what the operator typed. That hand-back only exists when the run RETURNS: a turn that
raises, or that the hard wall ends (the runner discards the interrupted result), took the
agent's steer buffer with it. ``requeue_undelivered_steers`` closes that from the steer
watcher's own on-disk ledger of what it accepted (RT-STEER-LOST-WHEN-TURN-FAILS). The next turn rides the busy-root send queue
(``agent_runtime.chat_root_send_queue``), the one door that already runs a send
after the turn holding the root, in arrival order, with the sender's origin.
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"
__all__ = ["leftover_steer_client_message_id", "queue_leftover_steer", "requeue_undelivered_steers"]

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


def requeue_undelivered_steers(
    args: Any, *, session_id: str, client_message_id: str, session_db: Any, turn_returned: bool,
) -> list[str]:
    """Queue every accepted steer that reached neither the transcript nor a next turn. Returns their ids.

    Reads (and so clears) the root's accepted-steer ledger. A steer of THIS turn is already
    accounted for when the run returned: it was drained into the turn or handed back as
    ``pending_steer`` (``queue_leftover_steer``). Every other record — this turn's when it
    raised, an earlier turn's whose executor died — is re-delivered unless its own row is in
    the transcript (the model was given it). Process-completion notices are not operator
    input and are not re-sent. Called under the chat-root lease, like ``queue_leftover_steer``.
    """

    from agent_runtime import chat_root_send_queue, paths
    from agent_runtime.mission_chat_steer import take_accepted_steers
    from hermes_cli.harness_parts.serve.queued_turn_origin import send_origin

    from ..chat_history_writes import _persona_chat_existing_turn

    queued: list[str] = []
    if not session_id:
        return queued
    for steer in take_accepted_steers(runtime_root=paths.store_root(), session_id=session_id):
        steer_id = str(steer.get("client_message_id") or "").strip()
        text = str(steer.get("message") or "").strip()
        if not steer_id or not text or steer.get("notification") is True:
            continue
        if turn_returned and steer.get("turn") == client_message_id:
            continue
        if _persona_chat_existing_turn(
            session_db=session_db, session_id=session_id, client_message_id=steer_id,
        ).get("operator"):
            continue
        next_id = NEXT_TURN_PREFIX + steer_id
        persisted = chat_root_send_queue.persistable_args(args, origin=send_origin())
        persisted.update(
            message=text, client_message_id=next_id, session_id=session_id, new_session=False,
            clarify_token=None, retry_of=None, title=None, idempotency_key=None,
        )
        chat_root_send_queue.enqueue(session_id, next_id, persisted)
        queued.append(next_id)
    return queued
