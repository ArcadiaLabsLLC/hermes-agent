"""``TurnCommit`` phases after the model returns or raises: settle a failure, commit, project.

Separate because everything here runs on a turn whose provider outcome is
already KNOWN — a returned reply to commit natively and project, or a raised
run to settle as a typed terminal state. Nothing here calls the provider.
"""

from __future__ import annotations

from typing import Any

from agent_runtime import turn_budget as _turn_budget
from agent_runtime.auxiliary_chat import auxiliary_result_metadata, is_auxiliary_chat
from agent_runtime.mission_chat_outcome import (
    ChatErrorKind,
    ExecutionState,
    FinalizationWarningKind,
    classify_turn_failure,
)
from agent_runtime.mission_chat_phases import (
    TURN_PHASES_KEY as MISSION_CHAT_TURN_PHASES_KEY,
    TURN_TIMING_KEY as MISSION_CHAT_TURN_TIMING_KEY,
    turn_timing_block,
)
from agent_runtime.mission_chat_turns.journal import transition_mission_chat_turn
from agent_runtime.mission_chat_turns.records import (
    TURN_PROFILE_TIMING_KEY as MISSION_CHAT_TURN_PROFILE_TIMING_KEY,
)
from agent_runtime.mission_chat_turns.states import (
    MissionChatTurnPersistOutcome,
    TURN_STATE_BUDGET_EXHAUSTED,
    TURN_STATE_NATIVE_COMMITTED,
    TURN_STATE_OUTCOME_UNKNOWN,
    TURN_STATE_PROJECTED,
    TURN_STATE_PROVIDER_REFUSED,
)
from agent_runtime.persona_assignments import safe_assignment_text, safe_assignment_token
from agent_runtime.persona_chat_durability import PersonaChatPersistenceError
from agent_runtime.prompt_observability import slim_chat_final_observability
from agent_runtime.run_budget import turn_run_budget_metadata
from agent_runtime.states import WorkerSessionState
from ..chat_events import (
    _mission_chat_emit,
    _publish_persona_chat_metadata_event,
    _publish_persona_chat_projection_event,
)
from ..chat_history_writes import (
    PERSONA_CHAT_REPLY_LIMIT,
    _chat_turn_tool_names,
    _mirror_persona_chat_message,
    _persona_chat_fault_injection,
    _redact_persona_chat_text,
)
from ..chat_reply_stamps import _stamp_reply_media, _stamp_turn_visibility
from ..chat_request import (
    _mission_chat_clarify_request_payload,
    _settle_mission_chat_clarify_binding,
)
from ..chat_session import _persona_chat_native_revision, _persona_chat_native_tip
from ..chat_target import _maybe_auto_title_persona_chat

__layer__ = "lanes"
__all__ = ["_SettlePhases"]


class _SettlePhases:
    """The ``TurnCommit`` methods that settle what the provider returned or raised."""

    def _record_failure(self, exc, turn_outcome) -> Any:
        """The typed terminal journal state for a raised run; ``None`` when nothing crossed the boundary."""

        stream_emitter = self.stream_emitter
        wall_budget_exceeded = (
            turn_outcome.execution_state is ExecutionState.BUDGET_EXHAUSTED
        )
        refusal = turn_outcome.provider_refusal
        if wall_budget_exceeded:
            budget_block = dict(getattr(exc, "wall_budget", None) or {})
            checkpoint_summary = _turn_budget.synthesize_checkpoint_summary(
                None, tool_names=_chat_turn_tool_names(stream_emitter.elements)
            )
            state = TURN_STATE_BUDGET_EXHAUSTED
            metadata = {
                "provider_submitted": True,
                "budget_exhausted": True,
                "budget_trigger": safe_assignment_token(
                    budget_block.get("trigger")
                )
                or "wall_budget_hard_wall",
                "budget_summary": safe_assignment_text(str(exc), limit=400),
                "stored_reply": checkpoint_summary,
                # However far the turn got. A wall-budget death usually
                # HAS provider_first_byte (the agent replied, then ran out
                # of clock) and never has stream_done — the two together
                # are what say "the tokens were flowing when the wall
                # closed", which no prose line has ever said.
                MISSION_CHAT_TURN_PHASES_KEY: self.turn_phases.snapshot(),
            }
        elif refusal is not None:
            state = TURN_STATE_PROVIDER_REFUSED
            metadata = {
                "provider_submitted": True,
                "provider_refusal": refusal.as_dict(),
                MISSION_CHAT_TURN_PHASES_KEY: self.turn_phases.snapshot(),
            }
        elif self.provider_submitted:
            # A non-wall budget trip (read/search loop, api calls, tokens)
            # settles here, and it is bounded just as knowably. Yields {}
            # for any other exception, so absence stays absence.
            state = TURN_STATE_OUTCOME_UNKNOWN
            metadata = {
                "provider_submitted": True,
                MISSION_CHAT_TURN_PHASES_KEY: self.turn_phases.snapshot(),
            }
        else:
            return None
        return transition_mission_chat_turn(
            session_id=self.session_id,
            client_message_id=self.client_message_id,
            turn_id=stream_emitter.turn_id,
            elements=stream_emitter.elements,
            state=state,
            metadata={
                **metadata,
                # The WHOLE accounting block, verbatim. A raised run has no
                # result to carry it, so it rides the exception — and this
                # is the only place it can become durable, because a pure
                # chat turn writes no run record.
                **turn_run_budget_metadata(error=exc),
            },
        )

    def _settle_failure(self, exc) -> int:
        """A raised run: settle it as the typed terminal state it is, and say so."""

        stream_emitter = self.stream_emitter
        stream_emitter.finish(state="failed")
        # A wall-budget death is NOT an ambiguous provider outcome: the harness
        # knows exactly why the turn stopped. Settle it as the typed terminal
        # `budget_exhausted` (no operator turn-resolve, never a frozen console
        # row) and hand back an honest synthesized account of what did run —
        # the live 2026-07-26 failure mode this replaces froze both ends of a
        # relay at `outcome_unknown` and cost a full re-brief.
        # ONE decision, made by the owned vocabulary rather than a nested
        # conditional spelled inline three times (state, kind, exit code).
        turn_outcome = classify_turn_failure(exc, provider_submitted=self.provider_submitted)
        wall_budget_exceeded = (
            turn_outcome.execution_state is ExecutionState.BUDGET_EXHAUSTED
        )
        # The PROVIDER's own verdict, when it authored one. Same shape of fact
        # as the wall budget above — a KNOWN terminal cause — and it settles the
        # same way: terminal journal state, no turn-resolve, an honest sentence.
        # The 2026-09-11 incident is what this arm replaces: a Codex
        # `usage_limit_reached` 429 fell into the `outcome_unknown` row below,
        # and the operator was shown an abandon-and-resend banner for a request
        # that had never run.
        refusal = turn_outcome.provider_refusal
        provider_refused = refusal is not None
        failed_outcome = self._record_failure(exc, turn_outcome)
        if self.runtime_registry is not None:
            self.runtime_registry.transition(self.session_id, "failed")
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": turn_outcome.execution_state,
            "error_kind": turn_outcome.error_kind,
            "persona_instance_id": self.instance.id,
            "persona_id": self.normalized_persona,
            "session_id": self.session_id,
            "root_chat_session_id": self.session_id,
            "client_message_id": self.client_message_id,
            "turn_id": stream_emitter.turn_id,
            "blocker": safe_assignment_text(str(exc), limit=240),
            "prompt_context_id": self.prompt_context["context_id"],
            # C3: failure frames carry the SAME slim block, never the full row.
            "prompt_observability": slim_chat_final_observability(self.prompt_context),
            "model_selection": self.model_selection,
            "next_expected": (
                "send a new client_message_id with a smaller scope or a larger --max-seconds; this turn is settled and needs NO turn-resolve"
                if wall_budget_exceeded
                else refusal.next_expected()
                if provider_refused
                else (
                    "resolve the exact outcome_unknown turn with action=abandon, then send a new client_message_id"
                    if self.provider_submitted
                    else "retry this client_message_id; Hermes did not cross the provider boundary"
                )
            ),
        }
        if provider_refused:
            data.update(
                {
                    "provider_refused": True,
                    "turn_resolution_required": False,
                    "journal_state": TURN_STATE_PROVIDER_REFUSED,
                    # The typed block, so no consumer has to read the blocker
                    # prose. `reason` is the provider's OWN code; the launcher
                    # chooses its copy from that and never from the message.
                    "provider_refusal": refusal.as_dict(),
                }
            )
        self._stamp_finalization(data)
        if wall_budget_exceeded:
            data.update(
                {
                    "budget_exhausted": True,
                    "turn_resolution_required": False,
                    "journal_state": TURN_STATE_BUDGET_EXHAUSTED,
                    "wall_budget": dict(getattr(exc, "wall_budget", None) or {}),
                    "checkpoint_summary": _turn_budget.synthesize_checkpoint_summary(
                        None, tool_names=_chat_turn_tool_names(stream_emitter.elements)
                    ),
                }
            )
        if failed_outcome is not None and failed_outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            data["turn_persist_outcome"] = failed_outcome.value
        _mission_chat_emit(self.args, data, data["blocker"])
        return turn_outcome.exit_code

    def _budget_metadata(self) -> dict[str, object]:
        """What bounded this turn, for the native-commit record; the checkpoint provenance when one engaged."""

        # Graceful checkpoint: the wall budget ended this turn, but it ended it at a
        # boundary and the agent still produced a real, durable reply. That reply
        # MUST project like any other (the whole point of the checkpoint), so the
        # journal keeps its normal native_committed -> projected walk; the
        # budget provenance rides the record metadata and the terminal frame so
        # "why is this reply a checkpoint?" is answerable from the record.
        budget_checkpoint = (getattr(self.chat_result, "raw", None) or {}).get(
            "wall_budget_checkpoint"
        )
        budget_checkpoint = budget_checkpoint if isinstance(budget_checkpoint, dict) else None
        budget_engaged = bool(budget_checkpoint and budget_checkpoint.get("engaged"))
        self.budget_checkpoint = budget_checkpoint
        self.budget_engaged = budget_engaged
        budget_metadata: dict[str, object] = {
            # UNCONDITIONAL, unlike the checkpoint provenance below: the accounting
            # block is the answer to "what bounded this turn?" and an UNTRIPPED turn
            # answers it too ("nothing did, and here is the headroom"). Gating it on
            # `budget_engaged` would keep exactly the pre-2026-07-27 blindness — a
            # turn that stopped at its bound and one that finished with room to
            # spare would again be indistinguishable from the record. Yields {} when
            # the run declared no budget at all, so absence still means absence.
            **turn_run_budget_metadata(result=self.chat_result),
            **(
                {
                    "budget_exhausted": True,
                    "budget_trigger": safe_assignment_token(budget_checkpoint.get("trigger"))
                    or "wall_budget_checkpoint",
                    "budget_summary": safe_assignment_text(
                        f"wall budget checkpoint: "
                        f"{budget_checkpoint.get('remaining_at_checkpoint_seconds')}s left of "
                        f"{budget_checkpoint.get('total_seconds')}s when new tool work stopped",
                        limit=400,
                    ),
                }
                if budget_engaged
                else {}
            ),
        }
        return budget_metadata

    def _commit_native(self) -> None:
        """The reply is durable in SessionDB: journal it ``native_committed`` and mirror it. Marks ``native_committed``."""

        session_db = self.session_db
        session_id = self.session_id
        runtime_registry = self.runtime_registry
        stream_emitter = self.stream_emitter
        reply_text = _redact_persona_chat_text(getattr(self.chat_result, "final_response", "") or "", limit=PERSONA_CHAT_REPLY_LIMIT)
        active_session_id = _persona_chat_native_tip(session_db, session_id)
        native_revision = _persona_chat_native_revision(session_db, session_id)
        self.reply_text = reply_text
        self.active_session_id = active_session_id
        self.native_revision = native_revision
        run_budget_block = self._budget_metadata()
        if runtime_registry is not None:
            runtime_registry.finish(
                session_id,
                active_session_id=active_session_id,
                revision=native_revision,
            )
        self.turn_phases.mark("native_committed")
        _settled = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=self.client_message_id,
            turn_id=stream_emitter.turn_id,
            state=TURN_STATE_NATIVE_COMMITTED,
            elements=stream_emitter.elements,
            metadata={
                MISSION_CHAT_TURN_PHASES_KEY: self.turn_phases.snapshot(),
                "root_chat_session_id": session_id,
                "active_session_id": active_session_id,
                "continuity_runtime": (
                    runtime_registry.observation(session_id, owning_process=True)
                    if runtime_registry is not None
                    else {
                        "runtime_state": "unknown",
                        "runtime_observer_id": "external_cli",
                    }
                ),
                "native_revision": native_revision,
                "native_committed": True,
                # Persist with the native receipt, before the external owner receives
                # a callback. A crash must not lose a committed clarify question.
                **auxiliary_result_metadata(self.instance.id, session_id, getattr(self.chat_result, "raw", None)),
                "stored_reply": reply_text,
                **run_budget_block,
                # The runner's per-run timing breakdown, riding the SAME persist as
                # the run-budget block above and bounded by the same store-side
                # sanitizer (`mission_chat_turns.safe_turn_profile_timing`: `*_ms`
                # ints, `resident_actor_reused`, `resident_rebuild_*`, nothing
                # else). The phase block spans profile bootstrap in ONE number
                # (`write_ahead → agent_ready`); this says which part of it was
                # runtime resolution, MCP admission, or agent construction, so a
                # prep-cost remedy has a before/after receipt on the record instead
                # of a log-grep. Absent when the runner reported nothing — an empty
                # dict would claim an accounting nobody took.
                **(
                    {MISSION_CHAT_TURN_PROFILE_TIMING_KEY: dict(self.profile_timing)}
                    if self.profile_timing
                    else {}
                ),
            },
        )
        self._route_turn_write(_settled, step="native_commit")
        # The reply is durable in SessionDB (the runtime persisted it natively) and
        # in the turn journal — so mirror it now, at the one point on this lane that
        # KNOWS a real recorded reply exists. Deduped on (role, client_message_id),
        # which is what makes the recovery/replay walks above safe to re-enter.
        _mirror_persona_chat_message(
            session_db=session_db,
            session_id=session_id,
            role="assistant",
            text=reply_text,
            client_message_id=self.client_message_id,
            turn_id=stream_emitter.turn_id,
        )

    def _return_instance_to_idle(self) -> None:
        # Token accounting: NONE here, on purpose. This lane runs the agent
        # natively bound to the chat session (mission_chat_reply receives
        # session_id=active_session_id with persist_agent_session=True), so
        # conversation_loop/codex_runtime already record every API call's usage
        # onto the bound session row. Adding the turn totals again via
        # _update_persona_chat_token_counts double-counted every counter
        # (input/output/cache/reasoning/api_call_count) at exactly 2x — the
        # per-call runtime writes are the single usage authority on this lane.
        # The scratch-session assignment lane (session_id=None) keeps its
        # explicit post-turn write.
        instance = self.instance
        try:
            if not is_auxiliary_chat(instance.id, self.session_id):
                instance.active_run_id = None
                instance.current_assignment_id = None
                instance.state = WorkerSessionState.IDLE
                instance.default_chat_session_id = self.session_id
                self.instance_store.update(instance)
        except Exception as instance_commit_exc:
            # NOT silent any more. This write is what returns the agent to idle
            # and repoints its default thread; swallowing its failure is why a
            # cockpit could render an agent ``busy`` forever after a completed
            # turn with nothing anywhere saying so. It still must not fail the
            # turn — the reply is durable — so it becomes a typed warning.
            self._warn(
                FinalizationWarningKind.INSTANCE_STATE_COMMIT_FAILED,
                type(instance_commit_exc).__name__,
                step="return_instance_to_idle",
            )

    def _settle_clarify(self) -> Any:
        """Settle the question this turn answered, THEN mint a ticket for any it asks."""

        # Clarify accounting, in this order and only now that the reply is
        # durable: SETTLE the question this turn answered before MINTING a
        # ticket for any question it asks. Reversed, the tokenless settlement
        # would find the ticket this very turn just created and mark a brand-new
        # question answered by the turn that asked it.
        self.clarify_binding = _settle_mission_chat_clarify_binding(
            self.clarify_binding,
            session_id=self.session_id,
            client_message_id=self.client_message_id,
            explicit_session_id=self.stated_session_id,
        )
        return _mission_chat_clarify_request_payload(
            self.chat_result,
            session_id=self.session_id,
            persona_id=self.normalized_persona,
            persona_instance_id=self.instance.id,
            client_message_id=self.client_message_id,
            turn_id=self.stream_emitter.turn_id,
            requested_by_session=self.requested_by_session,
        )

    def _success_payload(self, clarify_request) -> dict[str, Any]:
        """The terminal frame of a turn that replied."""

        args = self.args
        chat_result = self.chat_result
        session_id = self.session_id
        instance = self.instance
        budget_engaged = self.budget_engaged
        clarify_binding = self.clarify_binding
        # RO-7, built HERE and not inside the payload: the block is a COPY of
        # what the ledger record carries, so it is read off the same two
        # instruments the terminal persist below writes — `turn_phases` for the
        # marks and counters, the handler's `_profile_timing` superset for the
        # runner's durations. Built at commit, from the record's own numbers,
        # so the frame and the file can never disagree about a turn.
        turn_timing = turn_timing_block(
            phases=self.turn_phases.snapshot(), profile_timing=self.profile_timing
        )
        return {
            "ok": True,
            "protocol_version": 2 if self.stream else None,
            "capability_id": "mission.chat.message",
            "agent_profile_id": instance.id,
            "persona_instance_id": instance.id,
            "persona_id": self.normalized_persona,
            "session_id": session_id,
            "chat_session_id": session_id,
            "root_chat_session_id": session_id,
            # How this turn's thread was established: {fresh, reason,
            # predecessor_session_id}. A dispatching agent reads it to know
            # whether it just opened a task-scoped thread (and which thread that
            # supersedes) or continued an existing one — the same lineage the
            # session meta records as `_dispatched_from`.
            "session_established": self.session_established,
            # Clarify binding — a TOP-LEVEL SIBLING of session_established, not a
            # field inside it: that block's shape is pinned by contract, and
            # nesting here would break it. Present only when this turn presented
            # a clarify token or settled an open ticket; absent means neither
            # happened, which is the whole normal path. `bound_via` is the
            # adoption signal (`clarify_token` = the runtime bound it,
            # `session_id` = the caller named the right thread themselves,
            # `none` = they landed there by inheritance).
            **({"clarify_binding": clarify_binding} if clarify_binding else {}),
            "active_session_id": self.active_session_id,
            # S30: no task binding key, retired with the replay envelope's
            # copy above.
            "relay_chain": list(self.turn_relay_chain),
            "client_message_id": self.client_message_id,
            # A checkpointed turn is a SUCCESS with a truncated scope, not a
            # failure: a real reply was produced and committed. `ok` stays true
            # so relay callers do not treat it as an error; the typed
            # `execution_state` + `budget_exhausted` flag carry the truncation,
            # and the operator is never told to run turn-resolve.
            "execution_state": (
                ExecutionState.BUDGET_EXHAUSTED
                if budget_engaged
                else ExecutionState.COMPLETED
            ),
            **(
                {
                    "budget_exhausted": True,
                    "turn_resolution_required": False,
                    "wall_budget": self.budget_checkpoint,
                }
                if budget_engaged
                else {}
            ),
            "kind": "mission_chat_message",
            "intent_hint": safe_assignment_token(getattr(args, "intent_hint", None)) or "chat",
            "surface_prompt": safe_assignment_text(getattr(args, "surface_prompt", ""), limit=4000) or "",
            "limiting_wrapper_active": False,
            "reply": self.reply_text,
            # Structured clarify-back (non-blocking clarify tool on this lane):
            # when present, the agent is asking a question whose answer is the
            # operator's / caller's next message in this same session. The HUD
            # renders `choices` as pickable rows; agent_chat_send forwards it up
            # the relay so a briefed child can surface context only it has.
            # `clarify_token` rides inside it: echo that token back on the reply
            # and the runtime — not the model's memory for opaque ids — puts the
            # answer in this thread.
            "clarify_request": clarify_request,
            "turn_id": safe_assignment_token(self.client_message_id),
            "run_ids": [],
            "input_tokens": getattr(chat_result, "input_tokens", None),
            "output_tokens": getattr(chat_result, "output_tokens", None),
            "total_tokens": getattr(chat_result, "total_tokens", None),
            # Turn latency accounting (see harness-serve brain note, 2026-07-08):
            # latency_ms is the whole runner.run wall; profile_timing carries the
            # per-phase breakdown (agent construct, provider dispatch, stream).
            # Without these, diagnosing a slow chat turn needs an in-process probe.
            "latency_ms": getattr(chat_result, "latency_ms", None),
            "profile_timing": dict(getattr(chat_result, "profile_timing", None) or {}) or None,
            # RO-7: the same numbers, joined and named for a person. The two
            # instruments above are the runner's own namespace and the record's
            # phase marks; this is the seven-key projection of them, and it is
            # what the launcher's `[MissionChatTiming]` line appends — so "where
            # did this turn's time go" is one grep instead of a script that
            # joins a diag line to a ledger file on the turn id. ABSENT when the
            # turn knew nothing, and each key absent when its own phase never
            # happened — never a zero. Additive: no key here moves and no
            # contract integer moves with it.
            **({MISSION_CHAT_TURN_TIMING_KEY: turn_timing} if turn_timing else {}),
            "resident_actor_reused": bool(
                (getattr(chat_result, "profile_timing", None) or {}).get(
                    "resident_actor_reused"
                )
            ),
            "rehydrated": not bool(
                (getattr(chat_result, "profile_timing", None) or {}).get(
                    "resident_actor_reused"
                )
            ),
            "prompt_context_id": self.prompt_context["context_id"],
            # C3 (2026-07-17): the terminal frame carries the turn's facts ONCE,
            # small — the slim typed subset (ruling §7.3), not the full ~26 KB
            # record-at-injection row. The launcher reads exactly these fields
            # off the live frame; the complete row stays on disk (persisted +
            # archived). Same slim shape on stream and non-stream (one dict).
            "prompt_observability": slim_chat_final_observability(self.prompt_context),
            "queued_skills_loaded": list(self.turn_context.skills.loaded),
            "queued_skills_missing": list(self.turn_context.skills.missing),
            "model_selection": self.model_selection,
            "next_expected": (
                "wall budget ran out: this is the agent's final checkpoint reply, "
                "already committed. Send a new client_message_id to continue "
                "(no turn-resolve required); raise --max-seconds or narrow the ask"
                if budget_engaged
                else "agent replied through the canonical Mission Control chat path; refresh Harness snapshot for transcript and Initial Chat Context"
            ),
        }

    def _project(self) -> int:
        """Return the agent to idle, settle clarify, journal ``projected``, emit the terminal frame. Marks ``projected``."""

        _persona_chat_fault_injection("after_native_commit")
        self._return_instance_to_idle()
        clarify_request = self._settle_clarify()
        data = self._success_payload(clarify_request)
        reply_text = self.reply_text
        _stamp_turn_visibility(data, reply_text, chat_result=self.chat_result)
        _stamp_reply_media(data, reply_text, self.args)
        self._stamp_finalization(data)
        stream_emitter = self.stream_emitter
        stream_emitter.finish(
            state="completed",
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            total_tokens=data.get("total_tokens"),
        )
        self.turn_phases.mark("projected")
        self.terminal_outcome = transition_mission_chat_turn(
            session_id=self.session_id,
            client_message_id=self.client_message_id,
            turn_id=stream_emitter.turn_id,
            elements=stream_emitter.elements,
            state=TURN_STATE_PROJECTED,
            metadata={
                # The complete block, on the terminal record. Every earlier
                # persist carried a prefix of it; this is the one a latency
                # audit reads.
                MISSION_CHAT_TURN_PHASES_KEY: self.turn_phases.snapshot(),
                "projection_committed": True,
                "stored_reply": reply_text,
                "active_session_id": self.active_session_id,
                "native_revision": self.native_revision,
            },
        )
        if self.terminal_outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            data["turn_persist_outcome"] = self.terminal_outcome.value
        else:
            _publish_persona_chat_projection_event(
                session_id=self.session_id,
                client_message_id=self.client_message_id,
                turn_id=stream_emitter.turn_id,
                persona_id=self.normalized_persona,
                persona_instance_id=self.instance.id,
                active_session_id=self.active_session_id,
                native_revision=self.native_revision,
            )
        if self.write_ahead_outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            data["turn_write_ahead_outcome"] = self.write_ahead_outcome.value
        # C3: `turn_elements` DROPPED from the terminal frame — the launcher
        # never decoded them (turn structure arrives via the incremental v2
        # frames), and the turn store is the element/replay authority for
        # reconnect. Emitting them here was a pure duplicate carriage.
        _mission_chat_emit(
            self.args,
            data,
            f"mission chat reply for {self.normalized_persona}",
            stream=self.stream,
        )
        self._defer_auto_title()
        return 0

    def _defer_auto_title(self) -> None:
        # Auto-title is a SessionDB-only side effect that NOTHING in the emitted
        # frame depends on, and it costs a synchronous auxiliary-LLM RTT on a
        # session's first turn — an RTT that walks the whole provider-resolution
        # chain and can lazily pip-install a provider on the way (2026-08-09:
        # 46 seconds of it, ending in a 401 on a revoked OAuth token).
        #
        # It was already placed AFTER the terminal frame so that RTT stayed off
        # the last-delta -> chat.final critical path. That was necessary and not
        # sufficient: it still ran inside the chat-root lease, so for those 46
        # seconds the root REFUSED the operator's next send with ``chat_busy``
        # while his answer sat on screen. Post-emit is not the same boundary as
        # post-lease, and the operator experiences the second one.
        #
        # So it is packaged, not run. The caller invokes this thunk once the
        # ``with persona_chat_root_lease(...)`` block has exited; nothing inside
        # it touches turn or transcript state, so the root does not need to be
        # serialised for any of it. The internal try/except stays: the helper
        # already swallows, and ``run_once`` swallows too, but a raise from here
        # while the thunk is being BUILT (not run) would still reach the
        # crash-tail guard below and corrupt the one-JSON-object stdout
        # contract.
        session_db = self.session_db
        session_id = self.session_id
        message = self.message
        reply_text = self.reply_text
        normalized_persona = self.normalized_persona
        instance_id = self.instance.id

        def _deferred_auto_title() -> None:
            title_before = session_db.get_session_title(session_id)
            _maybe_auto_title_persona_chat(
                session_db=session_db,
                session_id=session_id,
                user_message=message,
                assistant_response=reply_text,
            )
            if session_db.get_session_title(session_id) != title_before:
                _publish_persona_chat_metadata_event(
                    session_id=session_id,
                    persona_id=normalized_persona,
                    persona_instance_id=instance_id,
                )

        try:
            self.deferred.defer(_deferred_auto_title)
        except Exception:
            pass

    def _projection_failed(self, exc) -> int:
        """The reply is durable but its projection failed: leave ``native_committed`` for a repair retry."""

        if self.terminal_outcome is not None:
            # The record is already settled; stdout may be mid-write, so a
            # second JSON object would corrupt the contract. Crash honestly.
            # (Called from inside the ``except`` that caught it, so a bare
            # ``raise`` re-raises the handled exception with its traceback.)
            raise
        self.stream_emitter.finish(state="failed")
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.FAILED,
            "error_kind": ChatErrorKind.CHAT_PROJECTION_INCOMPLETE,
            "persistence_operation": (
                exc.operation if isinstance(exc, PersonaChatPersistenceError) else None
            ),
            "persona_instance_id": self.instance.id,
            "persona_id": self.normalized_persona,
            "session_id": self.session_id,
            "root_chat_session_id": self.session_id,
            "active_session_id": self.active_session_id,
            "client_message_id": self.client_message_id,
            "turn_id": self.stream_emitter.turn_id,
            "reply": self.reply_text,
            "blocker": safe_assignment_text(str(exc), limit=240),
            "prompt_context_id": self.prompt_context["context_id"],
            # C3: same slim block on this failure lane too, so the peek's live
            # fallback (situational HUD + turn usage) still resolves when the
            # agent replied but the record settle failed.
            "prompt_observability": slim_chat_final_observability(self.prompt_context),
            "model_selection": self.model_selection,
            "next_expected": "retry this client_message_id to repair projection from the native committed reply",
        }
        # The guarded block starts AFTER the run returns and after `reply_text`
        # is derived from it, so both names are bound on every path that
        # reaches this handler: a projection failure gets the same evidence the
        # success payload would have had. What failed here is persistence, not
        # the turn — the reply may well be real and visible, and saying so is
        # what lets a repair retry be told apart from a silent turn.
        _stamp_turn_visibility(data, self.reply_text, chat_result=self.chat_result)
        _stamp_reply_media(data, self.reply_text, self.args)
        self._stamp_finalization(data)
        _mission_chat_emit(self.args, data, data["blocker"])
        return 2
