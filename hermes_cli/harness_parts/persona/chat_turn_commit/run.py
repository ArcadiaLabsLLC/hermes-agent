"""``TurnCommit`` phases from ``context_built`` to ``stream_done``: build, observe, stream, run the model.

Separate because this is the half of the turn that crosses the provider
boundary. Everything before it can still answer from the journal; everything
after it settles what the provider returned (``settle``).
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent_runtime import paths, relay_policy
from agent_runtime.auxiliary_chat import is_auxiliary_chat
from agent_runtime.cli_format import emit_json
from agent_runtime.config import resolve_mission_chat_max_seconds
from agent_runtime.mission_chat_phases import (
    TURN_PHASES_KEY as MISSION_CHAT_TURN_PHASES_KEY,
    mark_from_trace_payload as _mark_turn_phase_from_trace_payload,
)
from agent_runtime.mission_chat_steer import start_active_mission_chat_turn
from agent_runtime.mission_chat_turns import (
    MissionChatTurnPersistOutcome,
    TURN_STATE_ABANDONED,
    TURN_STATE_EXECUTING,
    TURN_STATE_PENDING,
    mark_stale_inflight_turns_interrupted,
    mission_chat_turn_records,
    persist_mission_chat_turn,
    transition_mission_chat_turn,
)
from agent_runtime.persona_assignments import safe_assignment_text, safe_assignment_token
from agent_runtime.persona_chat_continuity import persona_chat_runtime_registry, safe_native_history
from agent_runtime.persona_runtime import GPTPersonaRuntime
from agent_runtime.prompt_observability import (
    PROMPT_OBSERVABILITY_TIMINGS_KEY,
    attach_prompt_observability_turn_results,
    mission_chat_prompt_observability,
    persist_prompt_observability_context,
    turn_usage_from_result,
)
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
from ..chat_events import _ChatProtocolV2Emitter
from ..chat_history_writes import (
    PERSONA_CHAT_OPERATOR_MESSAGE_LIMIT,
    _mirror_persona_chat_message,
    _persona_chat_fault_injection,
    _redact_persona_chat_text,
    _resolve_relay_sender_marker,
)
from ..chat_session import (
    _persona_chat_native_history,
    _persona_chat_native_revision,
    _persona_chat_native_tip,
    _session_model_config,
)

__layer__ = "lanes"
__all__ = ["_RunPhases"]


class _RunPhases:
    """The ``TurnCommit`` methods that build the turn and run it through the provider."""

    def _build_context(self) -> None:
        """Native history, the relay marker and the WHOLE per-turn context. Marks ``context_built``."""

        # Function-local: the builder's module is not on the harness import path.
        from agent_runtime.mission_chat_turn_context import build_mission_chat_turn_context

        args = self.args
        session_db = self.session_db
        session_id = self.session_id
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
        self.active_session_id = active_session_id
        self.native_history = native_history
        self.native_revision_before = _persona_chat_native_revision(session_db, session_id)
        self.runtime_registry = persona_chat_runtime_registry()
        self.chat_message = self.message
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
            instance_store=self.instance_store,
            relay_chain_in=self.relay_chain_in,
        )
        self.relay_sender_marker = relay_sender_marker

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
        # Turn-local by construction: born here, dies with this object, never
        # attached to the context, the row, a persisted record or a wire frame.
        self.turn_root_registries: dict[str, Any] = {}

        self.turn_context = build_mission_chat_turn_context(
            persona=self.persona,
            instance=self.instance,
            config=self.cfg,
            session_id=session_id,
            native_history=native_history,
            model_selection=self.model_selection,
            session_model_config=_session_model_config(session_db, session_id),
            max_seconds=resolve_mission_chat_max_seconds(getattr(args, "max_seconds", None)),
            relay_deadline_epoch=self.relay_deadline,
            relay_chain=self.turn_relay_chain,
            min_relay_seconds=relay_policy.MIN_RELAY_BUDGET_SECONDS,
            agents_file=getattr(args, "agents_file", None),
            surface_prompt=getattr(args, "surface_prompt", "") or "",
            root_registries=self.turn_root_registries,
        )
        self.turn_phases.mark("context_built")

    def _observe(self) -> None:
        """The record-at-injection observability row and the fed envelope. Marks ``observability_built``."""

        args = self.args
        turn_context = self.turn_context
        instance = self.instance
        # Stage 6 item 2: taken off the built context, not re-measured. The builder
        # timed its own three sub-spans (`mission_chat_turn_context`.
        # ``CONTEXT_TIMING_KEYS``) because only it can see them; this is the fold.
        self.pre_admit_timings.update(_safe_pre_admit_timings(getattr(turn_context, "timings", None)))
        # The same object the runner's checkpoint clamp is armed from below, so the
        # number the agent was told and the number the runtime enforces cannot drift.
        wall_budget = turn_context.wall_budget
        self.wall_budget = wall_budget
        workspace_id = safe_assignment_token(getattr(args, "workspace_id", None))
        workspace_name = safe_assignment_text(
            getattr(args, "workspace_name", None), limit=120
        )
        # Record-at-injection: the observability row carries the very HUD dict that
        # was rendered into the fed block, so the operator's CONTEXT peek shows
        # exactly what the agent was told — never a later re-derivation.
        prompt_context = mission_chat_prompt_observability(
            persona=self.persona,
            persona_instance_id=instance.id,
            session_id=self.session_id,
            # task_id/goal_id intentionally not passed: both are defaulted kwargs and
            # the retired mission lane was their only source on this path.
            turn_id=safe_assignment_token(self.client_message_id),
            surface_prompt=getattr(args, "surface_prompt", "") or "",
            limiting_wrapper_active=False,
            session_db=self.session_db,
            current_message=self.message,
            model_selection=self.model_selection,
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
            skill_resolver=_turn_skill_resolver(self.turn_root_registries),
        )
        self.turn_phases.mark("observability_built")
        # Stage 6 item 2, the row's half — POPPED, not read: the mapping exists to
        # reach this fold and nothing downstream may see it. The row travels on to
        # the terminal frame's echo and to the persist chokepoint, and neither is a
        # place for a second copy of a number the ledger already carries.
        self.pre_admit_timings.update(
            _safe_pre_admit_timings(
                prompt_context.pop(PROMPT_OBSERVABILITY_TIMINGS_KEY, None)
                if isinstance(prompt_context, dict)
                else None
            )
        )
        # The envelope is rendered last because it needs the observability row's
        # context_id; body and volatile tail both come from the one built context.
        self.situational_hud_content = turn_context.runtime_context_envelope(
            context_id=str(prompt_context["context_id"])
        )
        self.prompt_context = prompt_context
        instance.skill_manifest_hash = safe_assignment_token(
            prompt_context.get("skill_manifest_hash")
        )
        if not is_auxiliary_chat(instance.id, self.session_id):
            self.instance = self.instance_store.update(instance)

    def _open_stream(self) -> None:
        """The protocol-v2 emitter and the turn's trace buffer. Marks ``emitter_created``."""

        session_id = self.session_id
        client_message_id = self.client_message_id
        self.stream = bool(getattr(self.args, "stream", False))
        self.stream_emitter = _ChatProtocolV2Emitter(
            turn_id=safe_assignment_token(client_message_id),
            client_message_id=client_message_id,
            emit_frames=self.stream,
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
            turn_phases=self.turn_phases,
        )
        self.turn_phases.mark("emitter_created")
        self.trace_payloads: list[dict[str, object]] = []

    def _stream_progress(self, payload: dict[str, object] | None) -> None:
        if payload:
            self.trace_payloads.append(payload)
            # The conversation loop's dispatch-start marker becomes the
            # `request_assembled` phase mark here — the loop cannot hold the
            # turn's TurnPhaseMarks itself (it lives a layer below the
            # harness), so the mark rides the trace payload it already emits.
            # Same-process, synchronous callback chain: the receipt instant IS
            # the emission instant to within the callback's own cost.
            _mark_turn_phase_from_trace_payload(self.turn_phases, payload)
        self.stream_emitter.progress(payload)

    def _agent_ready_for_steer(self, agent):
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
        turn_phases = self.turn_phases
        turn_phases.mark("agent_ready")
        turn_phases.count_delta("registry_probe_rounds", _registry_probe_rounds())
        turn_phases.count_delta("visibility_bundle_builds", _visibility_bundle_builds())
        try:
            if not getattr(self.args, "stream", False):
                return None
            handle = start_active_mission_chat_turn(
                runtime_root=paths.store_root(),
                session_id=self.session_id,
                agent=agent,
                persona_id=self.normalized_persona,
                persona_instance_id=self.instance.id,
                client_message_id=self.client_message_id,
            )
            return handle.close
        finally:
            turn_phases.mark("provider_request_started")

    def _write_ahead(self) -> None:
        """The turn's first durable record, its START, and the live-log mirror. Marks ``write_ahead``."""

        session_id = self.session_id
        client_message_id = self.client_message_id
        stream_emitter = self.stream_emitter
        mark_stale_inflight_turns_interrupted(
            session_id=session_id,
            active_client_message_id=client_message_id,
        )
        # Marked BEFORE the write it names, on purpose: the write-ahead record
        # is the first durable trace of this turn, and it has to be able to
        # describe its own admission. Every phase mark that names a PERSIST is
        # taken at the moment the persist is issued, so the block a record
        # carries is always complete as of that record.
        self.turn_phases.mark("write_ahead")
        self.write_ahead_outcome = transition_mission_chat_turn(
            session_id=session_id,
            client_message_id=client_message_id,
            turn_id=stream_emitter.turn_id,
            state=TURN_STATE_PENDING,
            elements=stream_emitter.elements,
            metadata={
                "root_chat_session_id": session_id,
                "active_session_id": self.active_session_id,
                "persona_instance_id": self.instance.id,
                "pending_user_message": self.message,
                "provider_submitted": False,
                # Rides the persist that already happens — no new write. On a
                # turn that dies before the provider this is the ONLY phase
                # block that ever lands, and its provider_* keys are absent.
                MISSION_CHAT_TURN_PHASES_KEY: self.turn_phases.snapshot(),
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
        if self.write_ahead_outcome is MissionChatTurnPersistOutcome.PERSISTED:
            self.presence.publish_started(
                session_id=session_id,
                client_message_id=client_message_id,
                turn_id=stream_emitter.turn_id,
                persona_id=self.normalized_persona,
                persona_instance_id=self.instance.id,
                active_session_id=self.active_session_id,
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
            session_db=self.session_db,
            session_id=session_id,
            role="user",
            text=_redact_persona_chat_text(
                self.message, limit=PERSONA_CHAT_OPERATOR_MESSAGE_LIMIT
            ),
            client_message_id=client_message_id,
            turn_id=stream_emitter.turn_id,
            relay_marker=self.relay_sender_marker,
        )

    def _cross_provider_boundary(self) -> None:
        """Journal ``executing`` with the request fingerprint; only then is the provider submitted."""

        stream_emitter = self.stream_emitter
        request_fingerprint = hashlib.sha256(
            emit_json(
                {
                    "root": self.session_id,
                    "client": self.client_message_id,
                    "turn": stream_emitter.turn_id,
                    "model": self.model_selection.get("effective_model"),
                    "message": self.message,
                }
            ).encode("utf-8")
        ).hexdigest()
        executing_outcome = transition_mission_chat_turn(
            session_id=self.session_id,
            client_message_id=self.client_message_id,
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
        self.provider_submitted = True
        if self.runtime_registry is not None:
            self.runtime_registry.transition(self.session_id, "busy")
        _persona_chat_fault_injection("after_provider_boundary")

    def _run_model(self) -> None:
        """The model turn itself, under the relay chain's shared deadline. Marks ``stream_done``."""

        args = self.args
        turn_context = self.turn_context
        model_selection = self.model_selection
        stream_emitter = self.stream_emitter
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
            self.wall_budget.remaining_seconds(),
        )
        _relay_chain_token = relay_policy.RELAY_CHAIN.set(self.turn_relay_chain)
        _relay_deadline_token = relay_policy.RELAY_DEADLINE.set(
            self.wall_budget.deadline_epoch
        )
        # situational_hud / situational_hud_content were resolved once above
        # (record-at-injection): the write-ahead row, the fed block here, and
        # the post-turn row all carry the same object.
        try:
            self._cross_provider_boundary()
            self.chat_result = GPTPersonaRuntime(
                default_provider=self.cfg.default_provider,
                default_model=self.cfg.default_model,
                session_db=self.session_db,
                persist_agent_session=True,
            ).mission_chat_reply(
                # Instance model-override tier folded in (api_mode included);
                # the chat-session override still wins via the explicit
                # provider_override/model_override args below.
                self.persona,
                self.chat_message,
                session_id=self.active_session_id,
                permission_session_id=self.session_id,
                persona_instance_id=self.instance.id,
                conversation_history=self.native_history,
                reuse_current_user_message=(
                    self.journal_state == TURN_STATE_PENDING and bool(self.replay.get("operator"))
                ),
                relay_sender_marker=self.relay_sender_marker,
                root_chat_session_id=self.session_id,
                client_message_id=self.client_message_id,
                runtime_registry=self.runtime_registry,
                runtime_signature=turn_context.runtime_signature,
                # Receipt-only: lets a refused reuse name the component that
                # moved (`resident_rebuild_component_*` on the turn record)
                # rather than only reporting that the composite key changed.
                runtime_signature_components=turn_context.runtime_signature_digests,
                native_revision=self.native_revision_before,
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
                reasoning_effort=getattr(self.instance, "reasoning_effort", None),
                surface_prompt=getattr(args, "surface_prompt", "") or "",
                max_wall_seconds=relay_wall_seconds,
                # C8: the legacy `chat.delta` lane is RETIRED (ruling 0 — one
                # wire shape per token). Deltas ride the v2 `segment.delta` frame
                # only; the emitter runs every frame inside the captured request
                # context, so worker-thread deltas keep their serve request id.
                stream_callback=stream_emitter.delta if getattr(args, "stream", False) else None,
                # C8: pre-trace acks are presentation-only. The emitter turns the
                # payload into a v2 `turn.ack` stream frame — never a SessionDB
                # row, never a turn-store element; replay never shows it.
                pre_trace_callback=stream_emitter.ack,
                trace_callback=self._stream_progress,
                agent_ready_callback=self._agent_ready_for_steer,
                preloaded_skill_prompt=turn_context.skill_preload_prompt,
                workspace_agents_content=turn_context.workspace_agents_content,
                # The workspace POINTER (G6): the loaded AGENTS.md's own path, from
                # the receipt the loader already produced. Only a file that actually
                # LOADED points at a real workspace root — an invalid/missing/too
                # large selection must not ground the turn somewhere it never read.
                workspace_agents_path=turn_context.workspace_agents_path,
                situational_hud_content=self.situational_hud_content,
                turn_id=safe_assignment_token(self.client_message_id),
            )
        finally:
            relay_policy.RELAY_CHAIN.reset(_relay_chain_token)
            relay_policy.RELAY_DEADLINE.reset(_relay_deadline_token)
        # The model turn is over — every token that was going to arrive has.
        # Only reached when the run RETURNED; a turn that raised (wall budget,
        # provider failure) leaves `stream_done` absent, and with it the Stage 4
        # overlap count whose window it defines.
        self.turn_phases.mark("stream_done")

    def _fold_profile_timing(self) -> None:
        """The turn's timing superset of the runner's own, and the overlap receipts."""

        turn_phases = self.turn_phases
        # A COPY, not the runner's dict: the handler folds its own Stage-4
        # measurement in below, and the live result frame further down reads
        # ``chat_result.profile_timing`` directly. Copying keeps the frame the
        # runner's own accounting, byte-for-byte as it was, while the DURABLE
        # RECORD carries the turn's — which is a superset, and which is where
        # Stage 4's receipt was asked for.
        _profile_timing = dict(getattr(self.chat_result, "profile_timing", None) or {})
        # chat-turn-prep Stage 4: the handler's SessionDB open, folded into the
        # same block the runner's phases ride. ``safe_turn_profile_timing``
        # admits any ``*_ms`` int, so this needs no schema change — but it is
        # bounded there rather than trusted from here. It arrives on the turn
        # PLAN, which is the declared boundary between the phase that paid this
        # cost and this one. ABSENT when the plan carried no measurement (an
        # unavailable store returns before the plan is built), never a zero.
        _session_db_open_ms = getattr(self.plan, "session_db_open_ms", None)
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
        _profile_timing.update(self.pre_admit_timings)
        # CP-7: WHICH bundle key component moved on this turn. The names only —
        # every value in that key material is a content hash, a session id, a
        # store path or a permission record, and the same disclosure rule
        # ``ChatLaneBundle.degraded`` follows applies here.
        for _component in _visibility_bundle_rebuild_components(
            self.bundle_diff_cursor
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
        self.profile_timing = _profile_timing

    def _attach_turn_results(self) -> None:
        """Attach the turn's results to the one observability row, and persist it."""

        chat_result = self.chat_result
        turn_context = self.turn_context
        final_model_input = (getattr(chat_result, "raw", {}) or {}).get("model_input_observability")
        # C1 build-once: the row was built ONCE before the turn (record-at-
        # injection: history, skills, context files, the very situational_hud
        # dict rendered into the fed block). Attach the turn's results onto that
        # object instead of a full rebuild — the pre-C1 second build re-read
        # SessionDB history and re-scanned the skill catalog per turn. The
        # metered turn_usage is recorded at the injection site next to the
        # context it describes (never key-matched back on later).
        prompt_context = attach_prompt_observability_turn_results(
            self.prompt_context,
            final_model_input=final_model_input,
            model_selection=self.model_selection,
            turn_usage=turn_usage_from_result(chat_result),
            trace_events=self.trace_payloads,
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
        self.prompt_context = prompt_context
        persist_tool_turn_actual(
            persona_id=self.normalized_persona,
            session_id=self.session_id,
            # task_id/goal_id intentionally not passed: defaulted kwargs whose
            # only source on this path was the retired mission lane.
            turn_id=safe_assignment_token(self.client_message_id),
            model_input=prompt_context.get("final_model_input"),
        )
        try:
            persist_prompt_observability_context(prompt_context)
        except Exception as persist_exc:
            self.prompt_context = {
                **prompt_context,
                "observability_persist_error": safe_assignment_text(type(persist_exc).__name__, limit=80),
            }
