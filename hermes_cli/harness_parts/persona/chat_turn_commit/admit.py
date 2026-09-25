"""``TurnCommit`` phases before the context is built: bind the instance, settle any prior attempt.

Separate because everything here decides whether this turn RUNS at all. A
settled or replayable prior attempt answers from the journal and SessionDB and
returns an exit code; ``None`` means "no prior attempt spoke for this id, build
the turn".
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

from agent_runtime.mission_chat_outcome import ChatErrorKind, ExecutionState
from agent_runtime.mission_chat_turns.journal import transition_mission_chat_turn
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from agent_runtime.mission_chat_turns.states import (
    REPLY_RECOVERABLE_TURN_STATES,
    RESEND_BLOCKING_TURN_STATES,
    SETTLING_TURN_STATES,
    TURN_STATE_BUDGET_EXHAUSTED,
    TURN_STATE_EXECUTING,
    TURN_STATE_NATIVE_COMMITTED,
    TURN_STATE_OUTCOME_UNKNOWN,
    TURN_STATE_PENDING,
    TURN_STATE_PROJECTED,
    TURN_STATE_PROVIDER_REFUSED,
)
from agent_runtime.models import apply_instance_model_overrides
from agent_runtime.persona_assignments import (
    RetiredPersonaInstanceError,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError,
    ensure_persona_chat_session as _ensure_persona_chat_session,
)
from ..chat_events import _mission_chat_emit, _publish_persona_chat_projection_event
from ..chat_history_writes import (
    PERSONA_CHAT_REPLY_LIMIT,
    _persona_chat_existing_turn,
    _redact_persona_chat_text,
)
from ..chat_reply_stamps import _stamp_reply_media, _stamp_turn_visibility
from ..chat_request import (
    _invalid_chat_model_override_payload,
    _missing_chat_message_payload,
    _requested_chat_model_override,
    _retired_persona_instance_payload,
)
from ..chat_session import (
    _chat_effective_model_payload,
    _persona_chat_native_revision,
    _persona_chat_native_tip,
    _resolve_chat_model_override,
)

__layer__ = "lanes"
__all__ = ["_AdmitPhases"]


def _provider_refused_payload(turn) -> dict[str, Any]:
    # Settled and NOT ambiguous, exactly like the budget row below: the
    # provider refused this request, nothing ran, and there is nothing for
    # `turn-resolve` to adjudicate. The refusal block is replayed off the
    # record so a resend gets the same honest sentence the first attempt
    # got — including the reset, which by now may have passed.
    journal = turn.journal
    refusal_block = journal.get("provider_refusal")
    data = {
        "ok": False,
        "capability_id": "mission.chat.message",
        "execution_state": ExecutionState.FAILED,
        "error_kind": ChatErrorKind.CHAT_TURN_PROVIDER_REFUSED,
        "provider_refused": True,
        "turn_resolution_required": False,
        "journal_state": TURN_STATE_PROVIDER_REFUSED,
        "root_chat_session_id": turn.session_id,
        "session_id": turn.session_id,
        "client_message_id": turn.client_message_id,
        "turn_id": journal.get("turn_id") or turn.client_message_id,
        "error": "this turn was refused by the model provider and never ran; it is settled and needs no resolution",
        "next_expected": "send a new client_message_id once the provider will accept one; no turn-resolve is required",
    }
    if isinstance(refusal_block, dict):
        data["provider_refusal"] = refusal_block
    return data


def _budget_exhausted_payload(turn) -> dict[str, Any]:
    # Settled, NOT ambiguous: this turn ended on its wall clock and the
    # harness knows it. Never route the operator to turn-resolve (that verb
    # exists only for genuinely unknown provider outcomes) and never block
    # the lane — just say plainly that this id is spent.
    journal = turn.journal
    return {
        "ok": False,
        "capability_id": "mission.chat.message",
        "execution_state": ExecutionState.BUDGET_EXHAUSTED,
        "error_kind": ChatErrorKind.CHAT_TURN_BUDGET_EXHAUSTED,
        "budget_exhausted": True,
        "turn_resolution_required": False,
        "journal_state": TURN_STATE_BUDGET_EXHAUSTED,
        "root_chat_session_id": turn.session_id,
        "session_id": turn.session_id,
        "client_message_id": turn.client_message_id,
        "turn_id": journal.get("turn_id") or turn.client_message_id,
        "budget_summary": journal.get("budget_summary"),
        "error": "this turn already ended on its wall-clock budget; it is settled and needs no resolution",
        "next_expected": "send a new client_message_id to continue; no turn-resolve is required",
    }


def _outcome_unknown_payload(turn) -> dict[str, Any]:
    # No proven reply and the journal says a provider call may still be
    # outstanding: refuse the resend and route to the resolve verb.
    if turn.journal_state == TURN_STATE_EXECUTING:
        _settled = transition_mission_chat_turn(
            session_id=turn.session_id,
            client_message_id=turn.client_message_id,
            turn_id=turn.journal.get("turn_id") or turn.client_message_id,
            state=TURN_STATE_OUTCOME_UNKNOWN,
            metadata={"provider_submitted": True},
        )
        turn._route_turn_write(_settled, step="resend_settle_outcome_unknown")
    return {
        "ok": False,
        "capability_id": "mission.chat.message",
        "execution_state": ExecutionState.BLOCKED,
        "error_kind": ChatErrorKind.CHAT_TURN_OUTCOME_UNKNOWN,
        "root_chat_session_id": turn.session_id,
        "session_id": turn.session_id,
        "client_message_id": turn.client_message_id,
        "turn_id": turn.journal.get("turn_id") or turn.client_message_id,
        "error": "the prior provider outcome cannot be proven; resolve this turn before resending",
        "next_expected": "resolve the exact outcome_unknown turn with action=abandon, then send a new client_message_id",
    }


#: A prior attempt the journal has SETTLED as a refusal: its state -> the
#: refusal a resend of the same id is answered with. Every resend-blocking
#: state (``executing`` included) shares one refusal, which first settles an
#: ``executing`` record to ``outcome_unknown``. The two named states are spelled
#: after the set so that, were the store ever to put one of them in it too, the
#: named refusal still wins — the precedence the ``if`` chain this replaced had.
_SETTLED_REFUSALS: Final[Mapping[str, Callable[[Any], dict[str, Any]]]] = MappingProxyType(
    {
        **{state: _outcome_unknown_payload for state in sorted(RESEND_BLOCKING_TURN_STATES)},
        TURN_STATE_PROVIDER_REFUSED: _provider_refused_payload,
        TURN_STATE_BUDGET_EXHAUSTED: _budget_exhausted_payload,
    }
)


class _AdmitPhases:
    """The ``TurnCommit`` methods that run before the turn's context exists."""

    def _bind_instance(self) -> int | None:
        """``open_chat``, the chat-session ensure and the model override: the first writes under the lease."""

        args = self.args
        session_db = self.session_db
        session_id = self.session_id
        normalized_persona = self.normalized_persona
        persona = self.persona
        try:
            instance = self.instance_store.open_chat(
                persona_id=normalized_persona,
                persona_instance_id=self.persona_instance_id or None,
                session_id=session_id,
                # persona DEFAULT name, NOT authoritative: names a first-ever chat
                # holder but must never rename an existing instance — else the send
                # path clobbers a deliberate placement name ("QA Agent (2)"), folding
                # a sibling onto the primary's console channel. Explicit rename lives
                # in persona.instance.update_profile.
                default_display_name=self.display_name,
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
        self.instance = instance
        return self._select_model()

    def _select_model(self) -> int | None:
        """The chat-session model override, and the effective model this turn runs on."""

        args = self.args
        session_id = self.session_id
        instance = self.instance
        try:
            requested_override = _requested_chat_model_override(args)
            chat_override = _resolve_chat_model_override(
                session_db=self.session_db,
                session_id=session_id,
                requested_override=requested_override,
            )
            model_selection = _chat_effective_model_payload(
                persona=self.persona,
                config=self.cfg,
                override=chat_override,
                instance=instance,
            )
        except ValueError as exc:
            data = _invalid_chat_model_override_payload(
                exc,
                persona_id=self.normalized_persona,
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
                "persona_id": self.normalized_persona,
                "session_id": session_id,
                "chat_session_id": session_id,
                "next_expected": "inspect Harness session metadata storage; chat-scoped model override was not applied and Hermes profile defaults were not changed",
            }
            _mission_chat_emit(args, data)
            return 2
        self.model_selection = model_selection
        # Resolve the effective instance once. Prompt receipts and execution must
        # observe the same model and skill assignment authority.
        self.persona = apply_instance_model_overrides(self.persona, instance)
        message = safe_assignment_text(getattr(args, "message", None), limit=12000)
        if not message:
            data = _missing_chat_message_payload()
            _mission_chat_emit(args, data)
            return 2
        self.message = message
        return None

    def _read_prior_attempt(self) -> None:
        """What SessionDB and the turn journal already hold for this id, with the recovery walks applied."""

        session_db = self.session_db
        session_id = self.session_id
        client_message_id = self.client_message_id
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
            self._route_turn_write(_settled, step="reply_recovery_native_commit")
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
            self._route_turn_write(_settled, step="settling_projection_commit")
            journal = mission_chat_turn_record(
                session_id=session_id, client_message_id=client_message_id
            ) or {}
            journal_state = TURN_STATE_PROJECTED
        self.replay = replay
        self.journal = journal
        self.journal_state = journal_state

    def _answer_prior_attempt(self) -> int | None:
        """Answer from the prior attempt when it already speaks for this id; ``None`` to run the turn."""

        self._read_prior_attempt()
        refusal = _SETTLED_REFUSALS.get(self.journal_state)
        if refusal is not None:
            data = refusal(self)
            self._stamp_finalization(data)
            _mission_chat_emit(self.args, data)
            return 2
        if self.journal_state == TURN_STATE_PROJECTED and self.journal.get("stored_reply") is not None:
            return self._replay_projected()
        if self.replay.get("assistant"):
            return self._replay_from_transcript()
        return None

    def _replay_projected(self) -> int:
        """The journal already projected this id's reply: publish and answer it again."""

        args = self.args
        session_db = self.session_db
        session_id = self.session_id
        client_message_id = self.client_message_id
        normalized_persona = self.normalized_persona
        instance = self.instance
        journal = self.journal
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
            "session_established": self.session_established,
            "client_message_id": client_message_id,
            "turn_id": journal.get("turn_id") or client_message_id,
            "execution_state": ExecutionState.COMPLETED,
            "reply": reply_text,
            "idempotent_replay": True,
            "journal_state": TURN_STATE_PROJECTED,
        }
        _stamp_turn_visibility(data, reply_text)
        _stamp_reply_media(data, reply_text, args)
        self._stamp_finalization(data)
        _mission_chat_emit(args, data, f"mission chat reply for {normalized_persona}")
        return 0

    def _replay_from_transcript(self) -> int:
        """SessionDB holds this id's reply but the journal never recorded it: walk the journal, answer."""

        args = self.args
        session_db = self.session_db
        session_id = self.session_id
        client_message_id = self.client_message_id
        normalized_persona = self.normalized_persona
        instance = self.instance
        reply_text = _redact_persona_chat_text(
            self.replay["assistant"].get("content"), limit=PERSONA_CHAT_REPLY_LIMIT
        )
        for state, metadata, step in (
            (TURN_STATE_PENDING, {"root_chat_session_id": session_id, "pending_user_message": self.message}, "replay_walk_pending"),
            (TURN_STATE_EXECUTING, {"provider_submitted": True}, "replay_walk_executing"),
            (TURN_STATE_NATIVE_COMMITTED, {"native_committed": True, "stored_reply": reply_text}, "replay_walk_native_committed"),
            (TURN_STATE_PROJECTED, {"projection_committed": True, "stored_reply": reply_text}, "replay_walk_projected"),
        ):
            _settled = transition_mission_chat_turn(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=client_message_id,
                state=state,
                metadata=metadata,
            )
            self._route_turn_write(_settled, step=step)
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
            "session_established": self.session_established,
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
            "model_selection": self.model_selection,
            "idempotent_replay": True,
            "next_expected": "duplicate client message id replayed from the canonical Mission Control chat transcript",
        }
        _stamp_turn_visibility(data, reply_text)
        _stamp_reply_media(data, reply_text, args)
        self._stamp_finalization(data)
        _mission_chat_emit(args, data, f"mission chat reply for {normalized_persona}")
        return 0
