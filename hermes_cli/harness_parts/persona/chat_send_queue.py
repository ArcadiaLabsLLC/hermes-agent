"""Accept and queue an operator send whose chat root is busy — never refuse it.

Owner ruling 2026-10-10: busy is not a reason to refuse. A send that finds its root
held by another turn (or other sends already waiting on it) is persisted in
``agent_runtime.chat_root_send_queue`` and answered "queued"; the serve's
queued-send runner (``agent_runtime.dispatch_delivery.queued_sends``) runs it after
the current turn, in arrival order. Contract:
``docs/agent-runtime-harness/planned/busy-root-queue-2026-10-10.md``.

Who queues: an OPERATOR send — one with no ``requested_by_session`` and no
in-process ``payload_sink``. An agent relay and a delivery forge name their
sender's root there; both keep ``chat_busy``, because both already retry from a
queue of their own (``dispatch_store``) or need the reply inside the calling turn
(``agent_chat_send`` wait=true). Every other in-process door caller (a discussion
member turn) keeps it for the second reason.
"""

from __future__ import annotations

from typing import Any

from agent_runtime import chat_root_send_queue
from agent_runtime.mission_chat_outcome import ExecutionState
from .chat_events import _mission_chat_emit

__layer__ = "lanes"
__all__ = [
    "_busy_root_queues",
    "_mission_chat_enqueue_busy",
    "_mission_chat_queue_gate",
    "_wake_queued_send_runner",
]


def _busy_root_queues(args: Any) -> bool:
    """True when a busy root queues this send rather than refusing ``chat_busy``.

    The runner's own run converges on its entry. Otherwise an operator send: no
    ``requested_by_session`` AND no in-process ``payload_sink`` — a door caller
    (a discussion member turn, an agent relay with no sender root) takes its
    reply inside its own call, so a "queued" answer would strand it and run the
    turn later outside the caller's scope.
    """

    if getattr(args, chat_root_send_queue.QUEUED_RUN_ARG, False):
        return True
    if str(getattr(args, "requested_by_session", None) or "").strip():
        return False
    return not callable(getattr(args, "payload_sink", None))


def _mission_chat_queue_gate(args: Any, *, session_id: str, client_message_id: str) -> int | None:
    """Before the lease: keep arrival order on a root that already has a queue.

    Returns an exit code when the send was answered "queued", ``None`` to go on
    to the lease. A send the runner is executing goes on. The same id still
    waiting is answered from its entry (no second entry, no second turn); the
    same id already RUNNING goes on, so the lease and the journal answer it
    (duplicate in flight, or the replay). A new id behind waiting sends queues
    behind them even when the lease happens to be free — otherwise it would
    overtake them.
    """

    if getattr(args, chat_root_send_queue.QUEUED_RUN_ARG, False) or not _busy_root_queues(args):
        return None
    if not session_id or not chat_root_send_queue.has_entries(session_id):
        return None
    existing = chat_root_send_queue.find(session_id, client_message_id)
    if existing is not None and existing.state == chat_root_send_queue.STATE_RUNNING:
        return None
    return _enqueue_and_answer(args, session_id=session_id, client_message_id=client_message_id)


def _mission_chat_enqueue_busy(args: Any, *, session_id: str, client_message_id: str) -> int:
    """The root is busy with somebody else's turn: queue this send, answer "queued".

    Also the answer for the runner's own run that lost a race for the lease: the
    entry is already there, so the enqueue converges on it and the runner leaves
    it for the next pass.
    """

    return _enqueue_and_answer(args, session_id=session_id, client_message_id=client_message_id)


def _enqueue_and_answer(args: Any, *, session_id: str, client_message_id: str) -> int:
    from hermes_cli.harness_parts.serve.queued_turn_origin import send_origin

    entry, position, replay = chat_root_send_queue.enqueue(
        session_id,
        client_message_id,
        chat_root_send_queue.persistable_args(args, origin=send_origin()),
    )
    data = {
        "ok": True,
        "capability_id": "mission.chat.message",
        "execution_state": ExecutionState.ACCEPTED,
        "queued": True,
        "queue_position": position,
        "client_message_id": entry.client_message_id,
        "turn_id": entry.client_message_id,
        "root_chat_session_id": session_id,
        "session_id": session_id,
        "queued_at": entry.queued_at,
        "idempotent_replay": replay,
        "next_expected": (
            "the message is queued behind the turn running on this chat root; it runs "
            "next in arrival order and its turn_settled push carries the outcome"
        ),
    }
    if not replay:
        _wake_queued_send_runner()
    _mission_chat_emit(args, data, "message queued behind the current turn")
    return 0


def _wake_queued_send_runner() -> None:
    try:
        from agent_runtime.chat_root_send_runner import wake_queued_send_runner

        wake_queued_send_runner()
    except Exception:  # a wake is an optimisation; the runner also ticks
        pass
