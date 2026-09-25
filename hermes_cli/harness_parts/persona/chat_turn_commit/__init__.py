"""The run-and-commit half of a mission-chat turn: ``TurnCommit``, one method per ledger phase.

``_mission_chat_commit_turn`` is the entry ``chat_turn_message`` calls under the
chat-root lease; it builds a ``TurnCommit`` and runs it. The phases are the
``turn_phases.mark`` names the ledger records
(``docs/agent-runtime-harness/05-chat-turn-lane.md``), in order:

* ``admit`` — bind the instance, then answer from any prior attempt of this id
  (a settled refusal, a projected reply, a transcript reply) or fall through;
* ``run`` — ``context_built``, ``observability_built``, ``emitter_created``,
  ``write_ahead`` and the provider call up to ``stream_done``;
* ``settle`` — a raised run's typed terminal state, or ``native_committed``
  then ``projected`` and the deferred auto-title.

The object's fields are the turn's locals; a phase reads what an earlier phase
set and never reaches back into the plan. Every durable write from
``open_chat`` onward is issued from here, so the lease that serialises a chat
root covers all of them.
"""

from __future__ import annotations

from agent_runtime.mission_chat_outcome import FinalizationWarning, FinalizationWarningKind
from agent_runtime.mission_chat_turns.states import MissionChatTurnPersistOutcome
from agent_runtime.persona_assignments import safe_assignment_text
from .admit import _AdmitPhases
from .run import _RunPhases
from .settle import _SettlePhases

__layer__ = "lanes"
__all__ = [
    "TurnCommit",
    "_mission_chat_commit_turn",
]


class TurnCommit(_AdmitPhases, _RunPhases, _SettlePhases):
    """One mission-chat turn under the chat-root lease: the SOLE writer of its durable state."""

    def __init__(self, plan, deferred, presence) -> None:
        # The unpack is deliberate and load-bearing: each planned value keeps
        # the name the turn body has always used, so no phase reaches back into
        # the plan for a value an earlier phase might have replaced.
        self.plan = plan
        self.deferred = deferred
        self.presence = presence
        self.args = plan.args
        self.cfg = plan.cfg
        self.session_db = plan.session_db
        self.instance_store = plan.instance_store
        self.persona = plan.persona
        self.normalized_persona = plan.normalized_persona
        self.persona_instance_id = plan.persona_instance_id
        self.display_name = plan.display_name
        self.session_id = plan.session_id
        self.client_message_id = plan.client_message_id
        self.session_established = plan.session_established
        self.clarify_binding = plan.clarify_binding
        self.stated_session_id = plan.stated_session_id
        self.requested_by_session = plan.requested_by_session
        self.turn_relay_chain = plan.turn_relay_chain
        self.relay_chain_in = plan.relay_chain_in
        self.relay_deadline = plan.relay_deadline
        # The turn's monotonic timeline, anchored at handler entry (see the plan's
        # ``phases`` field). Marked below at the boundaries the operator's TTFT is
        # actually made of; serialized onto the record by the persists that already
        # happen. Nothing in this object reads a mark back to decide anything.
        self.turn_phases = plan.phases
        # chat-turn-prep CP-7: the near end of the moved-key-component window,
        # sampled at the anchor by the plan phase (see the plan's own field).
        self.bundle_diff_cursor = plan.bundle_key_material_cursor
        # chat-turn-prep Stage 6 item 2: the two builders' sub-spans of the
        # pre-admit path, taken off the objects they ride out on and folded into
        # ``profile_timing`` beside ``session_db_open_ms``. Empty until each
        # builder returns, so a turn that dies before one of them records nothing
        # for it rather than a zero.
        self.pre_admit_timings: dict[str, int] = {}
        # ── finalization accounting ────────────────────────────────────────────
        # Bookkeeping that fails AFTER the reply is durable does not fail the turn —
        # and used to leave no trace at all. Two classes of silence lived here:
        #
        #   1. the instance-state commit (return the agent to idle, repoint its
        #      default chat thread) sat inside a bare ``except Exception: pass``, so
        #      a cockpit showing an agent stuck ``busy`` after a completed turn had
        #      no record anywhere of why;
        #   2. eight ``transition_mission_chat_turn`` calls DISCARDED their
        #      ``MissionChatTurnPersistOutcome``, so a skipped or rejected journal
        #      write (lock timeout, stale transition, invalid state) was
        #      indistinguishable from a clean one.
        #
        # Both now record a typed reason and ride the envelope as
        # ``finalization_warnings``. The key is ABSENT on a clean turn, so the wire
        # is unchanged for every healthy send — its presence is the whole signal.
        self.finalization_warnings: list[FinalizationWarning] = []
        self.provider_submitted = False
        self.terminal_outcome = None

    def _warn(self, kind, detail: object, *, step: str | None = None) -> None:
        self.finalization_warnings.append(
            FinalizationWarning(
                kind=kind,
                detail=safe_assignment_text(str(detail), limit=200) or "unknown",
                step=step,
            )
        )

    def _route_turn_write(self, outcome, *, step: str):
        """Account for a turn-journal transition. No write is lost silently."""

        if outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            self._warn(
                FinalizationWarningKind.TURN_RECORD_NOT_PERSISTED,
                getattr(outcome, "value", None) or "no_outcome",
                step=step,
            )
        return outcome

    def _stamp_finalization(self, data: dict) -> dict:
        if self.finalization_warnings:
            data["finalization_warnings"] = [
                warning.as_dict() for warning in self.finalization_warnings
            ]
        return data

    def commit(self) -> int:
        """Run the phases in ledger order; the first exit code a phase returns ends the turn."""

        code = self._bind_instance()
        if code is None:
            code = self._answer_prior_attempt()
        if code is not None:
            return code
        self._build_context()
        self._observe()
        self._open_stream()
        try:
            self._write_ahead()
            self._run_model()
            self._fold_profile_timing()
            self._attach_turn_results()
        except Exception as exc:
            return self._settle_failure(exc)
        self._commit_native()
        # The native reply is durable. Projection/bookkeeping failures deliberately
        # leave `native_committed` intact so an idempotent retry can repair the
        # projection without ever invoking the provider again.
        try:
            return self._project()
        except Exception as exc:
            return self._projection_failed(exc)


def _mission_chat_commit_turn(plan, deferred, presence) -> int:
    """The SOLE writer for a mission-chat turn. Runs under the chat-root lease.

    Every durable write from ``open_chat`` onward lives in ``TurnCommit``, so
    the lease that serialises a chat root actually covers them — before the
    plan/commit split the first three ran outside it, twice, on the way to
    acquiring it.

    ``deferred`` is the one value that flows back OUT: a
    ``MissionChatDeferredFinalization`` the caller runs after the ``with`` block
    exits. Nothing that writes the root's turn or transcript state may go in it;
    it exists for post-emit decoration whose only cost is time — today, the
    auxiliary-LLM auto-title and the metadata event that reports a title change.

    ``presence`` is a ``ChatTurnPresence`` the caller owns (C1h-bis). The turn
    publishes its START on it, one line after the write-ahead journal record
    that puts the turn in the ``running_work`` projection; the caller publishes
    the END from its ``finally``, because a turn has fourteen terminal
    transitions and no single exit.
    """

    return TurnCommit(plan, deferred, presence).commit()
