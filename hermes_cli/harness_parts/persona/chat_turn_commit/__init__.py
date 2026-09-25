"""The run-and-commit half of a mission-chat turn: ``_mission_chat_commit_turn``.

Its phases are the ``turn_phases.mark`` names the ledger records
(``docs/agent-runtime-harness/05-chat-turn-lane.md``).
"""

from __future__ import annotations

import hashlib
from typing import Any
from agent_runtime import paths
from agent_runtime.cli_format import emit_json
from agent_runtime.config import resolve_mission_chat_max_seconds
from agent_runtime.mission_chat_steer import start_active_mission_chat_turn
from agent_runtime.mission_chat_turns import (
    MissionChatTurnPersistOutcome,
    REPLY_RECOVERABLE_TURN_STATES,
    RESEND_BLOCKING_TURN_STATES,
    SETTLING_TURN_STATES,
    TURN_STATE_ABANDONED,
    TURN_STATE_BUDGET_EXHAUSTED,
    TURN_STATE_EXECUTING,
    TURN_STATE_NATIVE_COMMITTED,
    TURN_STATE_OUTCOME_UNKNOWN,
    TURN_STATE_PENDING,
    TURN_STATE_PROJECTED,
    TURN_STATE_PROVIDER_REFUSED,
    mark_stale_inflight_turns_interrupted,
    mission_chat_turn_record,
    mission_chat_turn_records,
    persist_mission_chat_turn,
    transition_mission_chat_turn,
)
from agent_runtime.models import apply_instance_model_overrides
from agent_runtime.persona_assignments import (
    RetiredPersonaInstanceError,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_continuity import persona_chat_runtime_registry, safe_native_history
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError,
    ensure_persona_chat_session as _ensure_persona_chat_session,
)
from agent_runtime.persona_runtime import GPTPersonaRuntime
from agent_runtime.prompt_observability import (
    PROMPT_OBSERVABILITY_TIMINGS_KEY,
    attach_prompt_observability_turn_results,
    mission_chat_prompt_observability,
    persist_prompt_observability_context,
    slim_chat_final_observability,
    turn_usage_from_result,
)
from agent_runtime.states import WorkerSessionState
from agent_runtime.tool_turn_history import persist_tool_turn_actual
from ..chat_admission import (
    _prewarm_constructions_overlapped,
    _registry_probe_rounds,
    _safe_pre_admit_timings,
    _snapshot_builds_overlapped,
    _turn_skill_resolver,
    _visibility_bundle_builds,
    _visibility_bundle_rebuild_components,
)
from ..chat_events import (
    _ChatProtocolV2Emitter,
    _mission_chat_emit,
    _publish_persona_chat_metadata_event,
    _publish_persona_chat_projection_event,
)
from ..chat_history_writes import (
    PERSONA_CHAT_OPERATOR_MESSAGE_LIMIT,
    PERSONA_CHAT_REPLY_LIMIT,
    _chat_turn_tool_names,
    _mirror_persona_chat_message,
    _persona_chat_existing_turn,
    _persona_chat_fault_injection,
    _redact_persona_chat_text,
    _resolve_relay_sender_marker,
)
from ..chat_reply_stamps import _stamp_reply_media, _stamp_turn_visibility
from ..chat_request import (
    _invalid_chat_model_override_payload,
    _missing_chat_message_payload,
    _mission_chat_clarify_request_payload,
    _requested_chat_model_override,
    _retired_persona_instance_payload,
    _settle_mission_chat_clarify_binding,
)
from ..chat_session import (
    _chat_effective_model_payload,
    _persona_chat_native_history,
    _persona_chat_native_revision,
    _persona_chat_native_tip,
    _resolve_chat_model_override,
    _session_model_config,
)
from ..chat_target import _maybe_auto_title_persona_chat

__layer__ = "lanes"
__all__ = [
    "_mission_chat_commit_turn",
]


def _mission_chat_commit_turn(plan, deferred, presence) -> int:
    """The SOLE writer for a mission-chat turn. Runs under the chat-root lease.

    Every durable write from ``open_chat`` onward lives here, so the lease that
    serialises a chat root actually covers them — before the plan/commit split
    the first three ran outside it, twice, on the way to acquiring it.

    The unpack below is deliberate and load-bearing: it rebinds each planned
    value to the name the turn body has always used, so the body itself is
    unchanged by the extraction. A renaming pass through 1,000 lines of the
    most-live code in the harness is a separate risk from moving the lease, and
    they do not have to be taken together.

    ``deferred`` is the one value that flows back OUT: a
    ``MissionChatDeferredFinalization`` the caller runs after the ``with`` block
    exits. Nothing that writes the root's turn or transcript state may go in it;
    it exists for post-emit decoration whose only cost is time — today, the
    auxiliary-LLM auto-title and the metadata event that reports a title change.

    ``presence`` is a ``ChatTurnPresence`` the caller owns (C1h-bis). This
    function publishes the turn's START on it, one line after the write-ahead
    journal record that puts the turn in the ``running_work`` projection; the
    caller publishes the END from its ``finally``, because this function has
    fourteen terminal transitions and no single exit.
    """

    # Function-local, like the rest of this file. ``relay_policy`` is here rather than
    # inherited, because the plan phase's own local import does NOT reach across
    # the split — a free name here would be a NameError on a LIVE turn and
    # nothing but a live turn would find it.
    from agent_runtime import relay_policy
    from agent_runtime.mission_chat_outcome import (
        ChatErrorKind,
        ExecutionState,
        FinalizationWarning,
        FinalizationWarningKind,
        classify_turn_failure,
    )
    from agent_runtime.mission_chat_phases import (
        TURN_PHASES_KEY as MISSION_CHAT_TURN_PHASES_KEY,
        TURN_TIMING_KEY as MISSION_CHAT_TURN_TIMING_KEY,
        mark_from_trace_payload as _mark_turn_phase_from_trace_payload,
        turn_timing_block,
    )
    from agent_runtime.mission_chat_turns import (
        TURN_PROFILE_TIMING_KEY as MISSION_CHAT_TURN_PROFILE_TIMING_KEY,
    )

    from agent_runtime.auxiliary_chat import is_auxiliary_chat, auxiliary_result_metadata

    args = plan.args
    cfg = plan.cfg
    session_db = plan.session_db
    instance_store = plan.instance_store
    persona = plan.persona
    normalized_persona = plan.normalized_persona
    persona_instance_id = plan.persona_instance_id
    display_name = plan.display_name
    session_id = plan.session_id
    client_message_id = plan.client_message_id
    session_established = plan.session_established
    clarify_binding = plan.clarify_binding
    stated_session_id = plan.stated_session_id
    requested_by_session = plan.requested_by_session
    turn_relay_chain = plan.turn_relay_chain
    relay_chain_in = plan.relay_chain_in
    relay_deadline = plan.relay_deadline
    # The turn's monotonic timeline, anchored at handler entry (see the plan's
    # ``phases`` field). Marked below at the boundaries the operator's TTFT is
    # actually made of; serialized onto the record by the persists that already
    # happen. Nothing in this function reads a mark back to decide anything.
    turn_phases = plan.phases
    # chat-turn-prep CP-7: the near end of the moved-key-component window,
    # sampled at the anchor by the plan phase (see the plan's own field).
    _bundle_diff_cursor = plan.bundle_key_material_cursor
    # chat-turn-prep Stage 6 item 2: the two builders' sub-spans of the
    # pre-admit path, taken off the objects they ride out on and folded into
    # ``profile_timing`` beside ``session_db_open_ms`` below. Empty until each
    # builder returns, so a turn that dies before one of them records nothing
    # for it rather than a zero.
    _pre_admit_timings: dict[str, int] = {}
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
    finalization_warnings: list[FinalizationWarning] = []

    def _warn(kind, detail: object, *, step: str | None = None) -> None:
        finalization_warnings.append(
            FinalizationWarning(
                kind=kind,
                detail=safe_assignment_text(str(detail), limit=200) or "unknown",
                step=step,
            )
        )

    def _route_turn_write(outcome, *, step: str):
        """Account for a turn-journal transition. No write is lost silently."""

        if outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            _warn(
                FinalizationWarningKind.TURN_RECORD_NOT_PERSISTED,
                getattr(outcome, "value", None) or "no_outcome",
                step=step,
            )
        return outcome

    def _stamp_finalization(data: dict) -> dict:
        if finalization_warnings:
            data["finalization_warnings"] = [
                warning.as_dict() for warning in finalization_warnings
            ]
        return data

    try:
        instance = instance_store.open_chat(
            persona_id=normalized_persona,
            persona_instance_id=persona_instance_id or None,
            session_id=session_id,
            # persona DEFAULT name, NOT authoritative: names a first-ever chat
            # holder but must never rename an existing instance — else the send
            # path clobbers a deliberate placement name ("QA Agent (2)"), folding
            # a sibling onto the primary's console channel. Explicit rename lives
            # in persona.instance.update_profile.
            default_display_name=display_name,
            profile_id=safe_assignment_token(getattr(persona, "hermes_profile", None)),
            kill_active=False,
        )
    except RetiredPersonaInstanceError as exc:
        # A placement retired between this turn's thread being established and
        # this bind. Defense in depth rather than the litter site it used to be:
        # the mint now binds before its first session-visible write, so a
        # retirement that beats the mint leaves nothing behind, and one that
        # lands after it archives a row that legitimately owned the thread
        # (`retire` preserves chat history by contract). This still refuses, and
        # still refuses with the same typed error.
        data = _retired_persona_instance_payload(exc)
        _mission_chat_emit(args, data)
        return 2
    except ValueError as exc:
        data = {"ok": False, "error": safe_assignment_text(str(exc), limit=240)}
        _mission_chat_emit(args, data)
        return 2

    # The retired mission lane's re-entry point used to live here: --task/--goal
    # wrote instance.current_task_id/goal_id and flipped instance.mode to the
    # RETIRED "task_bound", then persisted the row. A chat send must never arm
    # retired runtime state. Both flags are gone from the parser (contract 45);
    # arming a row is `persona instance steer --goal`, which is untouched.

    try:
        _ensure_persona_chat_session(
            session_db=session_db,
            session_id=session_id,
            persona_id=normalized_persona,
            title=f"{instance.display_name} chat",
            required=True,
        )
    except PersonaChatPersistenceError as exc:
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.FAILED,
            "error_kind": ChatErrorKind.CHAT_SESSION_PERSIST_FAILED,
            "persistence_operation": exc.operation,
            "error": str(exc),
            "persona_id": normalized_persona,
            "session_id": session_id,
            "persona_instance_id": instance.id,
            "next_expected": "restore canonical persona chat transcript storage and retry the message",
        }
        _mission_chat_emit(args, data)
        return 2
    try:
        requested_override = _requested_chat_model_override(args)
        chat_override = _resolve_chat_model_override(
            session_db=session_db,
            session_id=session_id,
            requested_override=requested_override,
        )
        model_selection = _chat_effective_model_payload(
            persona=persona,
            config=cfg,
            override=chat_override,
            instance=instance,
        )
    except ValueError as exc:
        data = _invalid_chat_model_override_payload(
            exc,
            persona_id=normalized_persona,
            persona_instance_id=instance.id,
            session_id=session_id,
        )
        _mission_chat_emit(args, data)
        return 2
    except Exception as exc:
        data = {
            "ok": False,
            "error_kind": ChatErrorKind.CHAT_MODEL_OVERRIDE_PERSIST_FAILED,
            "error": safe_assignment_text(str(exc), limit=320) or type(exc).__name__,
            "persona_instance_id": instance.id,
            "persona_id": normalized_persona,
            "session_id": session_id,
            "chat_session_id": session_id,
            "next_expected": "inspect Harness session metadata storage; chat-scoped model override was not applied and Hermes profile defaults were not changed",
        }
        _mission_chat_emit(args, data)
        return 2
    # Resolve the effective instance once. Prompt receipts and execution must
    # observe the same model and skill assignment authority.
    persona = apply_instance_model_overrides(persona, instance)
    message = safe_assignment_text(getattr(args, "message", None), limit=12000)
    if not message:
        data = _missing_chat_message_payload()
        _mission_chat_emit(args, data)
        return 2

    replay = _persona_chat_existing_turn(
        session_db=session_db,
        session_id=session_id,
        client_message_id=client_message_id,
    )
    journal = mission_chat_turn_record(
        session_id=session_id, client_message_id=client_message_id
    ) or {}
    journal_state = safe_assignment_token(journal.get("state"))
    # A durable reply already in SessionDB outranks whatever the journal thinks
    # happened. The recoverable set is the turn store's (a view of its own
    # transition table), never a literal spelled here — the wall-budget state
    # was invisible to exactly this kind of inline set until 2026-07-26.
    if journal_state in REPLY_RECOVERABLE_TURN_STATES and replay.get("assistant"):
        recovered_reply = _redact_persona_chat_text(
            replay["assistant"].get("content"), limit=PERSONA_CHAT_REPLY_LIMIT
        )
        _settled = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=journal.get("turn_id") or client_message_id,
            state=TURN_STATE_NATIVE_COMMITTED,
            metadata={
                "root_chat_session_id": session_id,
                "active_session_id": _persona_chat_native_tip(
                    session_db, session_id
                ),
                "native_revision": _persona_chat_native_revision(
                    session_db, session_id
                ),
                "native_committed": True,
                "stored_reply": recovered_reply,
            },
            elements=journal.get("elements") or [],
        )
        _route_turn_write(_settled, step="reply_recovery_native_commit")
        journal = mission_chat_turn_record(
            session_id=session_id, client_message_id=client_message_id
        ) or {}
        journal_state = safe_assignment_token(journal.get("state"))
    # Settling: the reply is durable, the projection is not. Finish the walk.
    if journal_state in SETTLING_TURN_STATES:
        stored_reply = journal.get("stored_reply")
        if stored_reply is None and replay.get("assistant"):
            stored_reply = _redact_persona_chat_text(
                replay["assistant"].get("content"),
                limit=PERSONA_CHAT_REPLY_LIMIT,
            )
        _settled = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=journal.get("turn_id") or client_message_id,
            state=TURN_STATE_PROJECTED,
            metadata={
                "stored_reply": stored_reply,
                "projection_committed": True,
            },
            elements=journal.get("elements") or [],
        )
        _route_turn_write(_settled, step="settling_projection_commit")
        journal = mission_chat_turn_record(
            session_id=session_id, client_message_id=client_message_id
        ) or {}
        journal_state = TURN_STATE_PROJECTED
    if journal_state == TURN_STATE_PROVIDER_REFUSED:
        # Settled and NOT ambiguous, exactly like the budget row below: the
        # provider refused this request, nothing ran, and there is nothing for
        # `turn-resolve` to adjudicate. The refusal block is replayed off the
        # record so a resend gets the same honest sentence the first attempt
        # got — including the reset, which by now may have passed.
        refusal_block = journal.get("provider_refusal")
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.FAILED,
            "error_kind": ChatErrorKind.CHAT_TURN_PROVIDER_REFUSED,
            "provider_refused": True,
            "turn_resolution_required": False,
            "journal_state": TURN_STATE_PROVIDER_REFUSED,
            "root_chat_session_id": session_id,
            "session_id": session_id,
            "client_message_id": client_message_id,
            "turn_id": journal.get("turn_id") or client_message_id,
            "error": "this turn was refused by the model provider and never ran; it is settled and needs no resolution",
            "next_expected": "send a new client_message_id once the provider will accept one; no turn-resolve is required",
        }
        if isinstance(refusal_block, dict):
            data["provider_refusal"] = refusal_block
        _stamp_finalization(data)
        _mission_chat_emit(args, data)
        return 2
    if journal_state == TURN_STATE_BUDGET_EXHAUSTED:
        # Settled, NOT ambiguous: this turn ended on its wall clock and the
        # harness knows it. Never route the operator to turn-resolve (that verb
        # exists only for genuinely unknown provider outcomes) and never block
        # the lane — just say plainly that this id is spent.
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.BUDGET_EXHAUSTED,
            "error_kind": ChatErrorKind.CHAT_TURN_BUDGET_EXHAUSTED,
            "budget_exhausted": True,
            "turn_resolution_required": False,
            "journal_state": TURN_STATE_BUDGET_EXHAUSTED,
            "root_chat_session_id": session_id,
            "session_id": session_id,
            "client_message_id": client_message_id,
            "turn_id": journal.get("turn_id") or client_message_id,
            "budget_summary": journal.get("budget_summary"),
            "error": "this turn already ended on its wall-clock budget; it is settled and needs no resolution",
            "next_expected": "send a new client_message_id to continue; no turn-resolve is required",
        }
        _stamp_finalization(data)
        _mission_chat_emit(args, data)
        return 2
    # No proven reply and the journal says a provider call may still be
    # outstanding: refuse the resend and route to the resolve verb.
    if journal_state in RESEND_BLOCKING_TURN_STATES:
        if journal_state == TURN_STATE_EXECUTING:
            _settled = transition_mission_chat_turn(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=journal.get("turn_id") or client_message_id,
                state=TURN_STATE_OUTCOME_UNKNOWN,
                metadata={"provider_submitted": True},
            )
            _route_turn_write(_settled, step="resend_settle_outcome_unknown")
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.BLOCKED,
            "error_kind": ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN,
            "root_chat_session_id": session_id,
            "session_id": session_id,
            "client_message_id": client_message_id,
            "turn_id": journal.get("turn_id") or client_message_id,
            "error": "the prior provider outcome cannot be proven; resolve this turn before resending",
            "next_expected": "resolve the exact outcome_unknown turn with action=abandon, then send a new client_message_id",
        }
        _stamp_finalization(data)
        _mission_chat_emit(args, data)
        return 2
    if journal_state == TURN_STATE_PROJECTED and journal.get("stored_reply") is not None:
        _publish_persona_chat_projection_event(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=journal.get("turn_id") or client_message_id,
            persona_id=normalized_persona,
            persona_instance_id=instance.id,
            active_session_id=journal.get("active_session_id")
            or _persona_chat_native_tip(session_db, session_id),
            native_revision=journal.get("native_revision")
            or _persona_chat_native_revision(session_db, session_id),
        )
        reply_text = _redact_persona_chat_text(
            journal.get("stored_reply"), limit=PERSONA_CHAT_REPLY_LIMIT
        )
        data = {
            "ok": True,
            "capability_id": "mission.chat.message",
            "persona_instance_id": instance.id,
            "persona_id": normalized_persona,
            "root_chat_session_id": session_id,
            "active_session_id": journal.get("active_session_id") or _persona_chat_native_tip(session_db, session_id),
            "session_id": session_id,
            "chat_session_id": session_id,
            # Same lineage the live envelope reports. A replay is the SAME turn
            # answered again (the mint receipt is idempotency-keyed, so a
            # retried dispatch lands back in the thread it established), so it
            # must report the same {fresh, reason, predecessor_session_id} —
            # a caller that reads `session_established` to decide where its
            # follow-up goes cannot have that answer disappear on a retry.
            "session_established": session_established,
            "client_message_id": client_message_id,
            "turn_id": journal.get("turn_id") or client_message_id,
            "execution_state": ExecutionState.COMPLETED,
            "reply": reply_text,
            "idempotent_replay": True,
            "journal_state": TURN_STATE_PROJECTED,
        }
        _stamp_turn_visibility(data, reply_text)
        _stamp_reply_media(data, reply_text, args)
        _stamp_finalization(data)
        _mission_chat_emit(args, data, f"mission chat reply for {normalized_persona}")
        return 0
    if replay.get("assistant"):
        reply_text = _redact_persona_chat_text(
            replay["assistant"].get("content"), limit=PERSONA_CHAT_REPLY_LIMIT
        )
        _settled = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=client_message_id,
            state=TURN_STATE_PENDING,
            metadata={"root_chat_session_id": session_id, "pending_user_message": message},
        )
        _route_turn_write(_settled, step="replay_walk_pending")
        _settled = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=client_message_id,
            state=TURN_STATE_EXECUTING,
            metadata={"provider_submitted": True},
        )
        _route_turn_write(_settled, step="replay_walk_executing")
        _settled = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=client_message_id,
            state=TURN_STATE_NATIVE_COMMITTED,
            metadata={"native_committed": True, "stored_reply": reply_text},
        )
        _route_turn_write(_settled, step="replay_walk_native_committed")
        _settled = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=client_message_id,
            state=TURN_STATE_PROJECTED,
            metadata={"projection_committed": True, "stored_reply": reply_text},
        )
        _route_turn_write(_settled, step="replay_walk_projected")
        _publish_persona_chat_projection_event(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=client_message_id,
            persona_id=normalized_persona,
            persona_instance_id=instance.id,
            active_session_id=_persona_chat_native_tip(session_db, session_id),
            native_revision=_persona_chat_native_revision(session_db, session_id),
        )
        data = {
            "ok": True,
            "capability_id": "mission.chat.message",
            "agent_profile_id": instance.id,
            "persona_instance_id": instance.id,
            "persona_id": normalized_persona,
            "session_id": session_id,
            "chat_session_id": session_id,
            # See the projected-replay envelope above: a replay reports the same
            # thread lineage the original turn did.
            "session_established": session_established,
            # S30: no task binding key. It was kept only because the Launcher
            # parsed it, and that parse fed a field which was never read -- a
            # dead key held alive by a dead reader. The Launcher dropped the
            # reader first (23bd05c6); the goal key went the same way in S26.
            "client_message_id": client_message_id,
            "execution_state": ExecutionState.COMPLETED,
            "kind": "mission_chat_message",
            "intent_hint": safe_assignment_token(getattr(args, "intent_hint", None))
            or "chat",
            "surface_prompt": safe_assignment_text(
                getattr(args, "surface_prompt", ""), limit=4000
            )
            or "",
            "limiting_wrapper_active": False,
            "reply": reply_text,
            "turn_id": safe_assignment_token(client_message_id),
            "run_ids": [],
            "model_selection": model_selection,
            "idempotent_replay": True,
            "next_expected": "duplicate client message id replayed from the canonical Mission Control chat transcript",
        }
        _stamp_turn_visibility(data, reply_text)
        _stamp_reply_media(data, reply_text, args)
        _stamp_finalization(data)
        _mission_chat_emit(args, data, f"mission chat reply for {normalized_persona}")
        return 0

    # SessionDB's native structured lineage is the sole continuation authority.
    # The Mission Control projection is never folded into this input.
    active_session_id = _persona_chat_native_tip(session_db, session_id)
    native_history = _persona_chat_native_history(session_db, active_session_id)
    abandoned_ids = {
        str(record.get("client_message_id") or "")
        for record in mission_chat_turn_records(session_id=session_id)
        if record.get("state") == TURN_STATE_ABANDONED
    }
    native_history = safe_native_history(
        [
            item
            for item in (native_history or [])
            if not any(
                str(item.get("platform_message_id") or "") == abandoned_id
                or str(item.get("platform_message_id") or "").startswith(
                    f"{abandoned_id}:"
                )
                for abandoned_id in abandoned_ids
            )
        ]
    )
    native_revision_before = _persona_chat_native_revision(session_db, session_id)
    runtime_registry = persona_chat_runtime_registry()
    chat_message = message
    # Relay sender attribution: resolve who sent this incoming message ONCE
    # (agent_chat_send relays carry requested_by="agent:<caller session>") and
    # hand the typed marker to the runtime, which stamps it on the native user
    # row it persists for this turn. Without it the target's transcript renders
    # a relayed message as the OPERATOR. Operator/CLI sends resolve to None →
    # no marker → byte-identical persistence.
    #
    # This lane stopped appending the incoming row itself when native session
    # continuity landed (c60413e17); the marker therefore rides
    # `mission_chat_reply(relay_sender_marker=)` down to the single seam that
    # types the row the RUNTIME writes (profile_runner.
    # stage_persona_chat_user_row_marker) rather than a second write here.
    relay_sender_marker = _resolve_relay_sender_marker(
        getattr(args, "requested_by", None),
        instance_store=instance_store,
        relay_chain_in=relay_chain_in,
    )
    from agent_runtime import turn_budget as _turn_budget
    from agent_runtime.mission_chat_turn_context import build_mission_chat_turn_context
    # Function-local, like the rest of this file.
    from agent_runtime.run_budget import turn_run_budget_metadata

    # The WHOLE per-turn context — wall budget, capability account, situational
    # HUD + delivery, skill preload envelope, workspace AGENTS.md, runtime
    # signature, volatile tail — is assembled by one unit-testable builder
    # (`agent_runtime.mission_chat_turn_context`). Assembled there, it is
    # guarded by tests that assert the composed bytes. What remains here is
    # composition: gather the turn's inputs, call the builder, send.
    #
    # G10: an explicit --max-seconds ALWAYS wins; only its absence (None) falls
    # through to the operator's configured lane default
    # (agent_runtime.mission_chat.default_max_seconds, itself 240s when unset),
    # so the deployment sets the work-shaped window once instead of every caller
    # remembering a flag.
    # chat-turn-prep CP-5, Stage 8: ONE registry snapshot per physical root for
    # the whole turn. The preload policy walks the roots first and fills this
    # map; the prompt-observability resolver below is constructed around the
    # same object, so its ``resolve()`` and its per-name
    # ``_resolved_skill_receipt`` calls read what the preload already took
    # instead of re-walking.
    #
    # Keyed by RESOLVED ROOT PATH, which is what makes the hand-off safe: the
    # observability row runs inside ``persona_profile_scope`` and this builder
    # does not, so the two lanes can legitimately enumerate different root
    # LISTS. A per-path key needs no agreement about the list — a root both
    # lanes see is walked once, a root only one lane sees is walked by that
    # lane, and a registry is a pure function of its root's contents either way.
    #
    # Turn-local by construction: born here, dies with this frame, never
    # attached to the context, the row, a persisted record or a wire frame.
    _turn_root_registries: dict[str, Any] = {}

    turn_context = build_mission_chat_turn_context(
        persona=persona,
        instance=instance,
        config=cfg,
        session_id=session_id,
        native_history=native_history,
        model_selection=model_selection,
        session_model_config=_session_model_config(session_db, session_id),
        max_seconds=resolve_mission_chat_max_seconds(getattr(args, "max_seconds", None)),
        relay_deadline_epoch=relay_deadline,
        relay_chain=turn_relay_chain,
        min_relay_seconds=relay_policy.MIN_RELAY_BUDGET_SECONDS,
        agents_file=getattr(args, "agents_file", None),
        surface_prompt=getattr(args, "surface_prompt", "") or "",
        root_registries=_turn_root_registries,
    )
    turn_phases.mark("context_built")
    # Stage 6 item 2: taken off the built context, not re-measured. The builder
    # timed its own three sub-spans (`mission_chat_turn_context`.
    # ``CONTEXT_TIMING_KEYS``) because only it can see them; this is the fold.
    _pre_admit_timings.update(_safe_pre_admit_timings(getattr(turn_context, "timings", None)))
    # The same object the runner's checkpoint clamp is armed from below, so the
    # number the agent was told and the number the runtime enforces cannot drift.
    wall_budget = turn_context.wall_budget
    workspace_id = safe_assignment_token(getattr(args, "workspace_id", None))
    workspace_name = safe_assignment_text(
        getattr(args, "workspace_name", None), limit=120
    )
    # Record-at-injection: the observability row carries the very HUD dict that
    # was rendered into the fed block, so the operator's CONTEXT peek shows
    # exactly what the agent was told — never a later re-derivation.
    prompt_context = mission_chat_prompt_observability(
        persona=persona,
        persona_instance_id=instance.id,
        session_id=session_id,
        # task_id/goal_id intentionally not passed: both are defaulted kwargs and
        # the retired mission lane was their only source on this path.
        turn_id=safe_assignment_token(client_message_id),
        surface_prompt=getattr(args, "surface_prompt", "") or "",
        limiting_wrapper_active=False,
        session_db=session_db,
        current_message=message,
        model_selection=model_selection,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        workspace_agents=turn_context.workspace_agents,
        situational_hud=turn_context.situational_hud,
        situational_hud_revision=turn_context.situational_hud_revision,
        situational_hud_delivery=turn_context.situational_hud_delivery,
        queued_skills=list(turn_context.skills.queued),
        required_preload_skills=list(turn_context.skills.required),
        preloaded_skills_loaded=list(turn_context.skills.loaded),
        preloaded_skills_missing=list(turn_context.skills.missing),
        instance_skill_overrides=(
            list(instance.skill_overrides)
            if instance.skill_overrides is not None
            else None
        ),
        skill_resolver=_turn_skill_resolver(_turn_root_registries),
    )
    turn_phases.mark("observability_built")
    # Stage 6 item 2, the row's half — POPPED, not read: the mapping exists to
    # reach this fold and nothing downstream may see it. The row travels on to
    # the terminal frame's echo and to the persist chokepoint, and neither is a
    # place for a second copy of a number the ledger already carries.
    _pre_admit_timings.update(
        _safe_pre_admit_timings(
            prompt_context.pop(PROMPT_OBSERVABILITY_TIMINGS_KEY, None)
            if isinstance(prompt_context, dict)
            else None
        )
    )
    # The envelope is rendered last because it needs the observability row's
    # context_id; body and volatile tail both come from the one built context.
    situational_hud_content = turn_context.runtime_context_envelope(
        context_id=str(prompt_context["context_id"])
    )
    instance.skill_manifest_hash = safe_assignment_token(
        prompt_context.get("skill_manifest_hash")
    )
    if not is_auxiliary_chat(instance.id, session_id):
        instance = instance_store.update(instance)
    stream = bool(getattr(args, "stream", False))
    stream_emitter = _ChatProtocolV2Emitter(
        turn_id=safe_assignment_token(client_message_id),
        client_message_id=client_message_id,
        emit_frames=stream,
        on_update=lambda emitter: persist_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=emitter.turn_id,
            elements=emitter.elements,
        ),
        # The emitter owns exactly ONE phase mark: the first token off the
        # provider. It is taken there because `delta()` is the first site in
        # this process that has seen a provider byte, and taking it there costs
        # no provider-client surgery. Guarded by a boolean read so the cost is
        # per TURN, not per token.
        turn_phases=turn_phases,
    )
    turn_phases.mark("emitter_created")

    # C8: the legacy `chat.delta` lane is RETIRED (ruling 0 — one wire shape per
    # token). Deltas ride the v2 `segment.delta` frame only; the emitter runs
    # every frame inside the captured request context, so worker-thread deltas
    # keep their serve request id.
    _stream_delta = stream_emitter.delta

    trace_payloads: list[dict[str, object]] = []

    def _stream_progress(payload: dict[str, object] | None) -> None:
        if payload:
            trace_payloads.append(payload)
            # The conversation loop's dispatch-start marker becomes the
            # `request_assembled` phase mark here — the loop cannot hold the
            # turn's TurnPhaseMarks itself (it lives a layer below the
            # harness), so the mark rides the trace payload it already emits.
            # Same-process, synchronous callback chain: the receipt instant IS
            # the emission instant to within the callback's own cost.
            _mark_turn_phase_from_trace_payload(turn_phases, payload)
        stream_emitter.progress(payload)

    def _agent_ready_for_steer(agent):
        # ── the two marks that bracket profile bootstrap ───────────────────
        # The runner calls this the instant the agent object exists and
        # IMMEDIATELY starts the conversation when it returns, so `agent_ready`
        # is the end of profile bootstrap (tool-registry probe rounds, plugin
        # discovery, auxiliary-client probes — the ~5.4 s that gap G1 said
        # nothing on the record could see) and `provider_request_started` is
        # the handoff to the model turn.
        #
        # Stated exactly, because the name is generous: prompt assembly inside
        # ``run_conversation`` happens AFTER this mark, so it lands inside the
        # span this mark opens. `request_assembled` (marked from the loop's
        # dispatch-start trace payload in `_stream_progress`) closes that
        # honestly WITHOUT provider-client surgery: request_started →
        # request_assembled is hermes assembly, request_assembled →
        # provider_first_byte is client init + network + provider. Both marks
        # here are ABSENT when the runner never reached agent construction — a
        # cold-init failure reports no agent_ready, which is the truth about
        # it.
        turn_phases.mark("agent_ready")
        turn_phases.count_delta("registry_probe_rounds", _registry_probe_rounds())
        turn_phases.count_delta("visibility_bundle_builds", _visibility_bundle_builds())
        try:
            if not getattr(args, "stream", False):
                return None
            handle = start_active_mission_chat_turn(
                runtime_root=paths.store_root(),
                session_id=session_id,
                agent=agent,
                persona_id=normalized_persona,
                persona_instance_id=instance.id,
                client_message_id=client_message_id,
            )
            return handle.close
        finally:
            turn_phases.mark("provider_request_started")

    provider_submitted = False
    try:
        mark_stale_inflight_turns_interrupted(
            session_id=session_id,
            active_client_message_id=client_message_id,
        )
        # Marked BEFORE the write it names, on purpose: the write-ahead record
        # is the first durable trace of this turn, and it has to be able to
        # describe its own admission. Every phase mark that names a PERSIST is
        # taken at the moment the persist is issued, so the block a record
        # carries is always complete as of that record.
        turn_phases.mark("write_ahead")
        write_ahead_outcome = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=stream_emitter.turn_id,
            state=TURN_STATE_PENDING,
            elements=stream_emitter.elements,
            metadata={
                "root_chat_session_id": session_id,
                "active_session_id": active_session_id,
                "persona_instance_id": instance.id,
                "pending_user_message": message,
                "provider_submitted": False,
                # Rides the persist that already happens — no new write. On a
                # turn that dies before the provider this is the ONLY phase
                # block that ever lands, and its provider_* keys are absent.
                MISSION_CHAT_TURN_PHASES_KEY: turn_phases.snapshot(),
            },
        )
        # C1h-bis: the turn's START, published the moment its row is real and
        # not one line earlier. The hub builds a FRESH projection when the event
        # log moves, so an event appended before this record exists produces a
        # frame with no row on it — indistinguishable, to a second console, from
        # never publishing at all. Gated on the record actually persisting for
        # the same reason: a skipped or rejected journal write leaves nothing for
        # the projection to carry, and announcing it would be a claim about a row
        # that is not there.
        if write_ahead_outcome is MissionChatTurnPersistOutcome.PERSISTED:
            presence.publish_started(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=stream_emitter.turn_id,
                persona_id=normalized_persona,
                persona_instance_id=instance.id,
                active_session_id=active_session_id,
            )
        # Live-log mirror, at the write-ahead point ON PURPOSE: this lane does
        # not append the operator row itself (native continuity: the runtime
        # persists it with the turn), and a head agent checking on a teammate
        # MID-TASK needs to see the order it was given before the turn ends —
        # not only once the reply lands. Redacted through the same write
        # boundary the persisted row crosses; deduped on
        # (role, client_message_id) so a resend of this turn cannot double it.
        # The relay marker rides along so a teammate's relayed message is
        # attributed to the SENDER in the grep file instead of reading as the
        # operator — the same attribution the conversation projection carries.
        _mirror_persona_chat_message(
            session_db=session_db,
            session_id=session_id,
            role="user",
            text=_redact_persona_chat_text(
                message, limit=PERSONA_CHAT_OPERATOR_MESSAGE_LIMIT
            ),
            client_message_id=client_message_id,
            turn_id=stream_emitter.turn_id,
            relay_marker=relay_sender_marker,
        )
        # Chained relays share one deadline: this hop's wall budget is capped
        # by the time left on the chain, and the deadline is seeded (root
        # turns mint it) so deeper hops inherit the same clock. Both facts come
        # from the ONE `wall_budget` object resolved above — the same object the
        # agent's HUD line was rendered from, so the number the model was told
        # and the number the runner enforces can never drift apart.
        # Relative window handed to the runner: time from NOW to the same
        # absolute deadline the agent's HUD line quoted, so prompt assembly
        # cannot let the enforced wall outlive the shared chain deadline.
        relay_wall_seconds = max(
            relay_policy.MIN_RELAY_BUDGET_SECONDS,
            wall_budget.remaining_seconds(),
        )
        _relay_chain_token = relay_policy.RELAY_CHAIN.set(turn_relay_chain)
        _relay_deadline_token = relay_policy.RELAY_DEADLINE.set(
            wall_budget.deadline_epoch
        )
        # situational_hud / situational_hud_content were resolved once above
        # (record-at-injection): the write-ahead row, the fed block here, and
        # the post-turn row all carry the same object.
        try:
            request_fingerprint = hashlib.sha256(
                emit_json(
                    {
                        "root": session_id,
                        "client": client_message_id,
                        "turn": stream_emitter.turn_id,
                        "model": model_selection.get("effective_model"),
                        "message": message,
                    }
                ).encode("utf-8")
            ).hexdigest()
            executing_outcome = transition_mission_chat_turn(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=stream_emitter.turn_id,
                state=TURN_STATE_EXECUTING,
                metadata={
                    "provider_submitted": True,
                    "provider_request_fingerprint": request_fingerprint,
                },
                elements=stream_emitter.elements,
            )
            if executing_outcome is not MissionChatTurnPersistOutcome.PERSISTED:
                raise RuntimeError(
                    f"provider boundary journal transition failed: {executing_outcome.value}"
                )
            provider_submitted = True
            if runtime_registry is not None:
                runtime_registry.transition(session_id, "busy")
            _persona_chat_fault_injection("after_provider_boundary")
            chat_result = GPTPersonaRuntime(
                default_provider=cfg.default_provider,
                default_model=cfg.default_model,
                session_db=session_db,
                persist_agent_session=True,
            ).mission_chat_reply(
                # Instance model-override tier folded in (api_mode included);
                # the chat-session override still wins via the explicit
                # provider_override/model_override args below.
                persona,
                chat_message,
                session_id=active_session_id,
                permission_session_id=session_id,
                persona_instance_id=instance.id,
                conversation_history=native_history,
                reuse_current_user_message=(
                    journal_state == TURN_STATE_PENDING and bool(replay.get("operator"))
                ),
                relay_sender_marker=relay_sender_marker,
                root_chat_session_id=session_id,
                client_message_id=client_message_id,
                runtime_registry=runtime_registry,
                runtime_signature=turn_context.runtime_signature,
                # Receipt-only: lets a refused reuse name the component that
                # moved (`resident_rebuild_component_*` on the turn record)
                # rather than only reporting that the composite key changed.
                runtime_signature_components=turn_context.runtime_signature_digests,
                native_revision=native_revision_before,
                compression_threshold_tokens_override=getattr(
                    args, "compression_threshold_tokens", None
                ),
                compression_protect_first_n_override=getattr(
                    args, "compression_protect_first_n", None
                ),
                compression_protect_last_n_override=getattr(
                    args, "compression_protect_last_n", None
                ),
                provider_override=model_selection.get("effective_provider"),
                model_override=model_selection.get("effective_model"),
                # Per-instance reasoning-effort override for this turn (None =
                # inherit the runtime default). Applied to the model call by the
                # transport; unsupported/absent values fall back to the default.
                reasoning_effort=getattr(instance, "reasoning_effort", None),
                surface_prompt=getattr(args, "surface_prompt", "") or "",
                max_wall_seconds=relay_wall_seconds,
                stream_callback=_stream_delta if getattr(args, "stream", False) else None,
                # C8: pre-trace acks are presentation-only. The emitter turns the
                # payload into a v2 `turn.ack` stream frame — never a SessionDB
                # row, never a turn-store element; replay never shows it.
                pre_trace_callback=stream_emitter.ack,
                trace_callback=_stream_progress,
                agent_ready_callback=_agent_ready_for_steer,
                preloaded_skill_prompt=turn_context.skill_preload_prompt,
                workspace_agents_content=turn_context.workspace_agents_content,
                # The workspace POINTER (G6): the loaded AGENTS.md's own path, from
                # the receipt the loader already produced. Only a file that actually
                # LOADED points at a real workspace root — an invalid/missing/too
                # large selection must not ground the turn somewhere it never read.
                workspace_agents_path=turn_context.workspace_agents_path,
                situational_hud_content=situational_hud_content,
                turn_id=safe_assignment_token(client_message_id),
            )
        finally:
            relay_policy.RELAY_CHAIN.reset(_relay_chain_token)
            relay_policy.RELAY_DEADLINE.reset(_relay_deadline_token)
        # The model turn is over — every token that was going to arrive has.
        # Only reached when the run RETURNED; a turn that raised (wall budget,
        # provider failure) leaves `stream_done` absent, and with it the Stage 4
        # overlap count whose window it defines.
        turn_phases.mark("stream_done")
        # A COPY, not the runner's dict: the handler folds its own Stage-4
        # measurement in below, and the live result frame further down reads
        # ``chat_result.profile_timing`` directly. Copying keeps the frame the
        # runner's own accounting, byte-for-byte as it was, while the DURABLE
        # RECORD carries the turn's — which is a superset, and which is where
        # Stage 4's receipt was asked for.
        _profile_timing = dict(getattr(chat_result, "profile_timing", None) or {})
        # chat-turn-prep Stage 4: the handler's SessionDB open, folded into the
        # same block the runner's phases ride. ``safe_turn_profile_timing``
        # admits any ``*_ms`` int, so this needs no schema change — but it is
        # bounded there rather than trusted from here. It arrives on the turn
        # PLAN, which is the declared boundary between the phase that paid this
        # cost and this one. ABSENT when the plan carried no measurement (an
        # unavailable store returns before the plan is built), never a zero.
        _session_db_open_ms = getattr(plan, "session_db_open_ms", None)
        if isinstance(_session_db_open_ms, int) and not isinstance(
            _session_db_open_ms, bool
        ):
            _profile_timing["session_db_open_ms"] = _session_db_open_ms
        # chat-turn-prep Stage 6 item 2: the pre-admit sub-spans, folded BESIDE
        # it and for the same reason. ``context_built`` and
        # ``observability_built`` are one number each on the phase block, and
        # §0.3 had to profile a sandbox copy of the live root to learn that
        # ≥ 60 % of both is one skill-directory walk performed three ways.
        # Stage 8's remedy is judged on these keys, so they have to be on the
        # record the re-take reads. Absent for a span nobody measured.
        _profile_timing.update(_pre_admit_timings)
        # CP-7: WHICH bundle key component moved on this turn. The names only —
        # every value in that key material is a content hash, a session id, a
        # store path or a permission record, and the same disclosure rule
        # ``ChatLaneBundle.degraded`` follows applies here.
        for _component in _visibility_bundle_rebuild_components(
            _bundle_diff_cursor
        ):
            _profile_timing[
                f"visibility_bundle_rebuild_component_{_component}"
            ] = 1
        # Cold/warm, from the runner's own receipt rather than a guess here.
        # `resident_actor_reused` is written by the resident-actor registry on
        # every acquire; a turn whose runner reported none (no registry on this
        # path) leaves `agent_init_cold` ABSENT rather than claiming either.
        turn_phases.flag(
            "agent_init_cold",
            (not bool(_profile_timing.get("resident_actor_reused")))
            if "resident_actor_reused" in _profile_timing
            else None,
        )
        turn_phases.count(
            "builds_overlapped",
            _snapshot_builds_overlapped(
                turn_phases, until_ms=turn_phases.get("stream_done")
            ),
        )
        # chat-turn-prep Stage 6 (CP-2): the other competitor for the same GIL.
        # §0.2 measured a chat-open actor prewarm for the operator's OWN root
        # running 5,750 ms across the entire pre-admit span of turn 1, with the
        # record saying nothing about it. Recorded here, decided on nowhere.
        turn_phases.count(
            "prewarm_overlapped",
            _prewarm_constructions_overlapped(
                turn_phases, until_ms=turn_phases.get("stream_done")
            ),
        )
        final_model_input = (getattr(chat_result, "raw", {}) or {}).get("model_input_observability")
        # C1 build-once: the row was built ONCE before the turn (record-at-
        # injection: history, skills, context files, the very situational_hud
        # dict rendered into the fed block). Attach the turn's results onto that
        # object instead of a full rebuild — the pre-C1 second build re-read
        # SessionDB history and re-scanned the skill catalog per turn. The
        # metered turn_usage is recorded at the injection site next to the
        # context it describes (never key-matched back on later).
        prompt_context = attach_prompt_observability_turn_results(
            prompt_context,
            final_model_input=final_model_input,
            model_selection=model_selection,
            turn_usage=turn_usage_from_result(chat_result),
            trace_events=trace_payloads,
        )
        if turn_context.skills.missing:
            prompt_context["queued_skill_load_errors"] = [
                {
                    "name": safe_assignment_token(skill) or str(skill),
                    "status": "missing",
                    "source": "queued_next_turn_skill",
                }
                for skill in turn_context.skills.missing
            ]
        persist_tool_turn_actual(
            persona_id=normalized_persona,
            session_id=session_id,
            # task_id/goal_id intentionally not passed: defaulted kwargs whose
            # only source on this path was the retired mission lane.
            turn_id=safe_assignment_token(client_message_id),
            model_input=prompt_context.get("final_model_input"),
        )
        try:
            persist_prompt_observability_context(prompt_context)
        except Exception as persist_exc:
            prompt_context = {
                **prompt_context,
                "observability_persist_error": safe_assignment_text(type(persist_exc).__name__, limit=80),
            }
    except Exception as exc:
        stream_emitter.finish(state="failed")
        # A wall-budget death is NOT an ambiguous provider outcome: the harness
        # knows exactly why the turn stopped. Settle it as the typed terminal
        # `budget_exhausted` (no operator turn-resolve, never a frozen console
        # row) and hand back an honest synthesized account of what did run —
        # the live 2026-07-26 failure mode this replaces froze both ends of a
        # relay at `outcome_unknown` and cost a full re-brief.
        # ONE decision, made by the owned vocabulary rather than a nested
        # conditional spelled inline three times (state, kind, exit code).
        turn_outcome = classify_turn_failure(exc, provider_submitted=provider_submitted)
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
        refusal_block = refusal.as_dict() if refusal is not None else None
        failed_outcome = None
        if wall_budget_exceeded:
            budget_block = dict(getattr(exc, "wall_budget", None) or {})
            checkpoint_summary = _turn_budget.synthesize_checkpoint_summary(
                None, tool_names=_chat_turn_tool_names(stream_emitter.elements)
            )
            failed_outcome = transition_mission_chat_turn(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=stream_emitter.turn_id,
                elements=stream_emitter.elements,
                state=TURN_STATE_BUDGET_EXHAUSTED,
                metadata={
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
                    MISSION_CHAT_TURN_PHASES_KEY: turn_phases.snapshot(),
                    # The WHOLE accounting block, verbatim. A raised run has no
                    # result to carry it, so it rides the exception — and this
                    # is the only place it can become durable, because a pure
                    # chat turn writes no run record.
                    **turn_run_budget_metadata(error=exc),
                },
            )
        elif provider_refused:
            failed_outcome = transition_mission_chat_turn(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=stream_emitter.turn_id,
                elements=stream_emitter.elements,
                state=TURN_STATE_PROVIDER_REFUSED,
                metadata={
                    "provider_submitted": True,
                    "provider_refusal": refusal_block,
                    MISSION_CHAT_TURN_PHASES_KEY: turn_phases.snapshot(),
                    **turn_run_budget_metadata(error=exc),
                },
            )
        elif provider_submitted:
            failed_outcome = transition_mission_chat_turn(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=stream_emitter.turn_id,
                elements=stream_emitter.elements,
                state=TURN_STATE_OUTCOME_UNKNOWN,
                # A non-wall budget trip (read/search loop, api calls, tokens)
                # settles here, and it is bounded just as knowably. Yields {}
                # for any other exception, so absence stays absence.
                metadata={
                    "provider_submitted": True,
                    MISSION_CHAT_TURN_PHASES_KEY: turn_phases.snapshot(),
                    **turn_run_budget_metadata(error=exc),
                },
            )
        if runtime_registry is not None:
            runtime_registry.transition(session_id, "failed")
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": turn_outcome.execution_state,
            "error_kind": turn_outcome.error_kind,
            "persona_instance_id": instance.id,
            "persona_id": normalized_persona,
            "session_id": session_id,
            "root_chat_session_id": session_id,
            "client_message_id": client_message_id,
            "turn_id": stream_emitter.turn_id,
            "blocker": safe_assignment_text(str(exc), limit=240),
            "prompt_context_id": prompt_context["context_id"],
            # C3: failure frames carry the SAME slim block, never the full row.
            "prompt_observability": slim_chat_final_observability(prompt_context),
            "model_selection": model_selection,
            "next_expected": (
                "send a new client_message_id with a smaller scope or a larger --max-seconds; this turn is settled and needs NO turn-resolve"
                if wall_budget_exceeded
                else refusal.next_expected()
                if provider_refused
                else (
                    "resolve the exact outcome_unknown turn with action=abandon, then send a new client_message_id"
                    if provider_submitted
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
                    "provider_refusal": refusal_block,
                }
            )
        _stamp_finalization(data)
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
        _mission_chat_emit(args, data, data["blocker"])
        return turn_outcome.exit_code

    reply_text = _redact_persona_chat_text(getattr(chat_result, "final_response", "") or "", limit=PERSONA_CHAT_REPLY_LIMIT)
    active_session_id = _persona_chat_native_tip(session_db, session_id)
    native_revision = _persona_chat_native_revision(session_db, session_id)
    # Graceful checkpoint: the wall budget ended this turn, but it ended it at a
    # boundary and the agent still produced a real, durable reply. That reply
    # MUST project like any other (the whole point of the checkpoint), so the
    # journal keeps its normal native_committed -> projected walk; the
    # budget provenance rides the record metadata and the terminal frame so
    # "why is this reply a checkpoint?" is answerable from the record.
    budget_checkpoint = (getattr(chat_result, "raw", None) or {}).get(
        "wall_budget_checkpoint"
    )
    budget_checkpoint = budget_checkpoint if isinstance(budget_checkpoint, dict) else None
    budget_engaged = bool(budget_checkpoint and budget_checkpoint.get("engaged"))
    budget_metadata: dict[str, object] = {
        # UNCONDITIONAL, unlike the checkpoint provenance below: the accounting
        # block is the answer to "what bounded this turn?" and an UNTRIPPED turn
        # answers it too ("nothing did, and here is the headroom"). Gating it on
        # `budget_engaged` would keep exactly the pre-2026-07-27 blindness — a
        # turn that stopped at its bound and one that finished with room to
        # spare would again be indistinguishable from the record. Yields {} when
        # the run declared no budget at all, so absence still means absence.
        **turn_run_budget_metadata(result=chat_result),
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
    if runtime_registry is not None:
        runtime_registry.finish(
            session_id,
            active_session_id=active_session_id,
            revision=native_revision,
        )
    turn_phases.mark("native_committed")
    _settled = transition_mission_chat_turn(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=stream_emitter.turn_id,
        state=TURN_STATE_NATIVE_COMMITTED,
        elements=stream_emitter.elements,
        metadata={
            MISSION_CHAT_TURN_PHASES_KEY: turn_phases.snapshot(),
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
            **auxiliary_result_metadata(instance.id, session_id, getattr(chat_result, "raw", None)),
            "stored_reply": reply_text,
            **budget_metadata,
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
                {MISSION_CHAT_TURN_PROFILE_TIMING_KEY: dict(_profile_timing)}
                if _profile_timing
                else {}
            ),
        },
    )
    _route_turn_write(_settled, step="native_commit")
    # The reply is durable in SessionDB (the runtime persisted it natively) and
    # in the turn journal — so mirror it now, at the one point on this lane that
    # KNOWS a real recorded reply exists. Deduped on (role, client_message_id),
    # which is what makes the recovery/replay walks above safe to re-enter.
    _mirror_persona_chat_message(
        session_db=session_db,
        session_id=session_id,
        role="assistant",
        text=reply_text,
        client_message_id=client_message_id,
        turn_id=stream_emitter.turn_id,
    )
    # The native reply is durable. Projection/bookkeeping failures deliberately
    # leave `native_committed` intact so an idempotent retry can repair the
    # projection without ever invoking the provider again.
    terminal_outcome: MissionChatTurnPersistOutcome | None = None
    try:
        _persona_chat_fault_injection("after_native_commit")
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
        try:
            if not is_auxiliary_chat(instance.id, session_id):
                instance.active_run_id = None
                instance.current_assignment_id = None
                instance.state = WorkerSessionState.IDLE
                instance.default_chat_session_id = session_id
                instance_store.update(instance)
        except Exception as instance_commit_exc:
            # NOT silent any more. This write is what returns the agent to idle
            # and repoints its default thread; swallowing its failure is why a
            # cockpit could render an agent ``busy`` forever after a completed
            # turn with nothing anywhere saying so. It still must not fail the
            # turn — the reply is durable — so it becomes a typed warning.
            _warn(
                FinalizationWarningKind.INSTANCE_STATE_COMMIT_FAILED,
                type(instance_commit_exc).__name__,
                step="return_instance_to_idle",
            )

        # Clarify accounting, in this order and only now that the reply is
        # durable: SETTLE the question this turn answered before MINTING a
        # ticket for any question it asks. Reversed, the tokenless settlement
        # would find the ticket this very turn just created and mark a brand-new
        # question answered by the turn that asked it.
        clarify_binding = _settle_mission_chat_clarify_binding(
            clarify_binding,
            session_id=session_id,
            client_message_id=client_message_id,
            explicit_session_id=stated_session_id,
        )
        clarify_request = _mission_chat_clarify_request_payload(
            chat_result,
            session_id=session_id,
            persona_id=normalized_persona,
            persona_instance_id=instance.id,
            client_message_id=client_message_id,
            turn_id=stream_emitter.turn_id,
            requested_by_session=requested_by_session,
        )

        # RO-7, built HERE and not inside the payload: the block is a COPY of
        # what the ledger record carries, so it is read off the same two
        # instruments the terminal persist below writes — `turn_phases` for the
        # marks and counters, the handler's `_profile_timing` superset for the
        # runner's durations. Built at commit, from the record's own numbers,
        # so the frame and the file can never disagree about a turn.
        turn_timing = turn_timing_block(
            phases=turn_phases.snapshot(), profile_timing=_profile_timing
        )
        data = {
            "ok": True,
            "protocol_version": 2 if stream else None,
            "capability_id": "mission.chat.message",
            "agent_profile_id": instance.id,
            "persona_instance_id": instance.id,
            "persona_id": normalized_persona,
            "session_id": session_id,
            "chat_session_id": session_id,
            "root_chat_session_id": session_id,
            # How this turn's thread was established: {fresh, reason,
            # predecessor_session_id}. A dispatching agent reads it to know
            # whether it just opened a task-scoped thread (and which thread that
            # supersedes) or continued an existing one — the same lineage the
            # session meta records as `_dispatched_from`.
            "session_established": session_established,
            # Clarify binding — a TOP-LEVEL SIBLING of session_established, not a
            # field inside it: that block's shape is pinned by contract, and
            # nesting here would break it. Present only when this turn presented
            # a clarify token or settled an open ticket; absent means neither
            # happened, which is the whole normal path. `bound_via` is the
            # adoption signal (`clarify_token` = the runtime bound it,
            # `session_id` = the caller named the right thread themselves,
            # `none` = they landed there by inheritance).
            **({"clarify_binding": clarify_binding} if clarify_binding else {}),
            "active_session_id": active_session_id,
            # S30: no task binding key, retired with the replay envelope's
            # copy above.
            "relay_chain": list(turn_relay_chain),
            "client_message_id": client_message_id,
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
                    "wall_budget": budget_checkpoint,
                }
                if budget_engaged
                else {}
            ),
            "kind": "mission_chat_message",
            "intent_hint": safe_assignment_token(getattr(args, "intent_hint", None)) or "chat",
            "surface_prompt": safe_assignment_text(getattr(args, "surface_prompt", ""), limit=4000) or "",
            "limiting_wrapper_active": False,
            "reply": reply_text,
            # Structured clarify-back (non-blocking clarify tool on this lane):
            # when present, the agent is asking a question whose answer is the
            # operator's / caller's next message in this same session. The HUD
            # renders `choices` as pickable rows; agent_chat_send forwards it up
            # the relay so a briefed child can surface context only it has.
            # `clarify_token` rides inside it: echo that token back on the reply
            # and the runtime — not the model's memory for opaque ids — puts the
            # answer in this thread.
            "clarify_request": clarify_request,
            "turn_id": safe_assignment_token(client_message_id),
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
            "prompt_context_id": prompt_context["context_id"],
            # C3 (2026-07-17): the terminal frame carries the turn's facts ONCE,
            # small — the slim typed subset (ruling §7.3), not the full ~26 KB
            # record-at-injection row. The launcher reads exactly these fields
            # off the live frame; the complete row stays on disk (persisted +
            # archived). Same slim shape on stream and non-stream (one dict).
            "prompt_observability": slim_chat_final_observability(prompt_context),
            "queued_skills_loaded": list(turn_context.skills.loaded),
            "queued_skills_missing": list(turn_context.skills.missing),
            "model_selection": model_selection,
            "next_expected": (
                "wall budget ran out: this is the agent's final checkpoint reply, "
                "already committed. Send a new client_message_id to continue "
                "(no turn-resolve required); raise --max-seconds or narrow the ask"
                if budget_engaged
                else "agent replied through the canonical Mission Control chat path; refresh Harness snapshot for transcript and Initial Chat Context"
            ),
        }
        _stamp_turn_visibility(data, reply_text, chat_result=chat_result)
        _stamp_reply_media(data, reply_text, args)
        _stamp_finalization(data)
        stream_emitter.finish(
            state="completed",
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            total_tokens=data.get("total_tokens"),
        )
        turn_phases.mark("projected")
        terminal_outcome = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=stream_emitter.turn_id,
            elements=stream_emitter.elements,
            state=TURN_STATE_PROJECTED,
            metadata={
                # The complete block, on the terminal record. Every earlier
                # persist carried a prefix of it; this is the one a latency
                # audit reads.
                MISSION_CHAT_TURN_PHASES_KEY: turn_phases.snapshot(),
                "projection_committed": True,
                "stored_reply": reply_text,
                "active_session_id": active_session_id,
                "native_revision": native_revision,
            },
        )
        if terminal_outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            data["turn_persist_outcome"] = terminal_outcome.value
        else:
            _publish_persona_chat_projection_event(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=stream_emitter.turn_id,
                persona_id=normalized_persona,
                persona_instance_id=instance.id,
                active_session_id=active_session_id,
                native_revision=native_revision,
            )
        if write_ahead_outcome is not MissionChatTurnPersistOutcome.PERSISTED:
            data["turn_write_ahead_outcome"] = write_ahead_outcome.value
        # C3: `turn_elements` DROPPED from the terminal frame — the launcher
        # never decoded them (turn structure arrives via the incremental v2
        # frames), and the turn store is the element/replay authority for
        # reconnect. Emitting them here was a pure duplicate carriage.
        _mission_chat_emit(
            args,
            data,
            f"mission chat reply for {normalized_persona}",
            stream=stream,
        )
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
                    persona_instance_id=instance.id,
                )

        try:
            deferred.defer(_deferred_auto_title)
        except Exception:
            pass
        return 0
    except Exception as exc:
        if terminal_outcome is not None:
            # The record is already settled; stdout may be mid-write, so a
            # second JSON object would corrupt the contract. Crash honestly.
            raise
        stream_emitter.finish(state="failed")
        data = {
            "ok": False,
            "capability_id": "mission.chat.message",
            "execution_state": ExecutionState.FAILED,
            "error_kind": ChatErrorKind.CHAT_PROJECTION_INCOMPLETE,
            "persistence_operation": (
                exc.operation if isinstance(exc, PersonaChatPersistenceError) else None
            ),
            "persona_instance_id": instance.id,
            "persona_id": normalized_persona,
            "session_id": session_id,
            "root_chat_session_id": session_id,
            "active_session_id": active_session_id,
            "client_message_id": client_message_id,
            "turn_id": stream_emitter.turn_id,
            "reply": reply_text,
            "blocker": safe_assignment_text(str(exc), limit=240),
            "prompt_context_id": prompt_context["context_id"],
            # C3: same slim block on this failure lane too, so the peek's live
            # fallback (situational HUD + turn usage) still resolves when the
            # agent replied but the record settle failed.
            "prompt_observability": slim_chat_final_observability(prompt_context),
            "model_selection": model_selection,
            "next_expected": "retry this client_message_id to repair projection from the native committed reply",
        }
        # The guarded block starts AFTER the run returns and after `reply_text`
        # is derived from it, so both names are bound on every path that
        # reaches this handler: a projection failure gets the same evidence the
        # success payload would have had. What failed here is persistence, not
        # the turn — the reply may well be real and visible, and saying so is
        # what lets a repair retry be told apart from a silent turn.
        _stamp_turn_visibility(data, reply_text, chat_result=chat_result)
        _stamp_reply_media(data, reply_text, args)
        _stamp_finalization(data)
        _mission_chat_emit(args, data, data["blocker"])
        return 2
