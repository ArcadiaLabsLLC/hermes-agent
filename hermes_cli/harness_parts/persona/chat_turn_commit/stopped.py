"""``TurnCommit``'s settle for a run that RETURNED but is not a reply: a stopped turn.

Separate from ``settle`` because that module settles the two outcomes the lane has always
had — a raised run and a reply — and a stop is neither: the run returned (nothing raised,
the agent is healthy, the transcript is consistent), and what it returned is not an answer.
Before this module an operator Stop settled as an ordinary reply whose text was the
literal ``None``, upstream's "Operation interrupted: waiting for model response" banner, or
the half-written text (RT-STOPPED-TURN-SETTLES-AS-A-REPLY).

What a stop is on the wire: the terminal frame is ``ok: true`` (the stop worked) with
``execution_state: "stopped"``, ``stopped: true``, ``journal_state: "interrupted"`` and
``reply`` = the text the model had already written, else ``""``; the journal record is
``interrupted`` with ``stopped: true`` (``mission_chat_turns.stop_mission_chat_turn``), so
history shows the ``turn_interrupted`` marker with the stopped sentence and ``retry_of``
re-runs it. The hard wall's interrupt never reaches here: the runner raises it.
Pinned by ``tests/agent_runtime/test_chat_turn_stopped_or_empty.py``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.mission_chat_outcome import ExecutionState, FinalizationWarningKind
from agent_runtime.mission_chat_phases import TURN_PHASES_KEY as MISSION_CHAT_TURN_PHASES_KEY
from agent_runtime.mission_chat_turns.journal import stop_mission_chat_turn
from agent_runtime.mission_chat_turns.states import (
    MissionChatTurnPersistOutcome,
    TURN_STATE_INTERRUPTED,
)
from agent_runtime.persona_chat_session import (
    _persona_chat_native_read,
    _persona_chat_native_revision_of_read,
)
from ..chat_events import _mission_chat_emit
from ..chat_history_writes import _mirror_persona_chat_message, _redact_persona_chat_text
from ..chat_reply_stamps import _stamp_turn_visibility

__layer__ = "lanes"
__all__ = ["_StoppedPhases", "stopped_partial_reply"]


def stopped_partial_reply(raw: Any) -> str:
    """The text the model had written when the stop landed, else ``""``.

    Upstream returns one of four things as an interrupted run's ``final_response``: nothing,
    its "waiting for model response" banner, its repetition-loop notice, or the streamed
    partial text. Only the last is something the model said.
    """

    from agent.conversation_loop import INTERRUPT_WAITING_FOR_MODEL_PREFIX
    from agent.repetition_guard import REPETITION_LOOP_INTERRUPTED

    text = raw.get("final_response") if isinstance(raw, dict) else None
    if not isinstance(text, str):
        return ""
    stripped = text.strip()
    if stripped.startswith(INTERRUPT_WAITING_FOR_MODEL_PREFIX) or stripped == REPETITION_LOOP_INTERRUPTED:
        return ""
    return stripped


class _StoppedPhases:
    """The ``TurnCommit`` methods that settle a run stopped through the agent's interrupt seam."""

    def _run_was_stopped(self) -> bool:
        raw = getattr(getattr(self, "chat_result", None), "raw", None)
        return isinstance(raw, dict) and raw.get("interrupted") is True

    def _settle_stopped(self) -> int:
        """Record the turn as stopped and say so; the partial reply, when there is one, is kept."""

        session_id = self.session_id
        stream_emitter = self.stream_emitter
        reply_text = _redact_persona_chat_text(stopped_partial_reply(self.chat_result.raw))
        # The transcript is consistent (upstream closed the interrupted tail and persisted it),
        # so the resident actor's snapshot advances exactly as it does after a reply.
        native_stamp, active_session_id, native_history = _persona_chat_native_read(self.session_db, session_id)
        native_revision = _persona_chat_native_revision_of_read(
            self.session_db, session_id, active_session_id, native_history)
        self.reply_text = reply_text
        self.active_session_id = active_session_id
        self.native_revision = native_revision
        run_budget_block = self._budget_metadata()
        if self.runtime_registry is not None:
            self.runtime_registry.finish(
                session_id, active_session_id=active_session_id, revision=native_revision,
                native_snapshot=(native_stamp, active_session_id, native_history),
            )
        stream_emitter.finish(state=TURN_STATE_INTERRUPTED)
        outcome = stop_mission_chat_turn(
            session_id=session_id,
            client_message_id=self.client_message_id,
            turn_id=stream_emitter.turn_id,
            elements=stream_emitter.elements,
            metadata={
                MISSION_CHAT_TURN_PHASES_KEY: self.turn_phases.snapshot(),
                "root_chat_session_id": session_id,
                "active_session_id": active_session_id,
                "native_revision": native_revision,
                "provider_submitted": True,
                # Absent when nothing was written: "no reply" and "an empty reply" stay distinct.
                **({"stored_reply": reply_text} if reply_text else {}),
                **run_budget_block,
            },
        )
        self._route_turn_write(outcome, step="stopped")
        if reply_text:
            _mirror_persona_chat_message(
                session_db=self.session_db, session_id=session_id, role="assistant", text=reply_text,
                client_message_id=self.client_message_id, turn_id=stream_emitter.turn_id,
            )
        self._queue_leftover_steer()
        self._return_instance_to_idle()
        try:
            clarify_request = self._settle_clarify()
        except Exception as exc:
            self._warn(FinalizationWarningKind.TURN_RECORD_NOT_PERSISTED, type(exc).__name__, step="stopped_clarify")
            clarify_request = None
        data = self._success_payload(clarify_request)
        data.update(
            {
                "execution_state": ExecutionState.STOPPED,
                "stopped": True,
                "turn_resolution_required": False,
                "journal_state": TURN_STATE_INTERRUPTED,
                "next_expected": (
                    "this turn was stopped and is settled; send a new client_message_id to continue, "
                    "or retry_of this one to run it again (no turn-resolve required)"
                ),
            }
        )
        _stamp_turn_visibility(data, reply_text, chat_result=self.chat_result)
        self._stamp_finalization(data)
        if outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            data["turn_persist_outcome"] = outcome.value
        if self.write_ahead_outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            data["turn_write_ahead_outcome"] = self.write_ahead_outcome.value
        _mission_chat_emit(self.args, data, "mission chat turn stopped", stream=self.stream)
        return 0
