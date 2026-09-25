"""``ProfileAgentRunner`` — admit MCP servers, execute one agent run, tear down;
moved whole in the MOVE (ruling Q8), its ``_execute_agent_run`` becomes
``execute.AgentRunExecution`` in the CHANGE.
"""

from __future__ import annotations

from contextlib import ExitStack
from threading import Event, Timer
import time
from typing import Any, Callable

from agent_runtime import turn_budget
from agent_runtime.profile_context import PersonaProfileBinding, persona_profile_context
from agent_runtime.run_budget import (
    UNIT_CALLS,
    UNIT_SECONDS,
    RunBudgetEnforcement,
    RunBudgetKind,
    RunBudgetLedger,
    RunBudgetTripReason,
)

from agent_runtime.profile_runner.toolsets import (
    _blocked_tool_names_for_run,
    _enabled_toolsets_for_run,
)
from agent_runtime.profile_runner.errors import (
    ProfileRunnerError,
    RunBudgetExceeded,
    _NO_WALL_BUDGET_SECONDS,
    _ProviderErrorCapture,
    _capture_provider_errors,
)
from agent_runtime.profile_runner.models import (
    AgentRunRequest,
    AgentRunResult,
    _positive_int,
)
from agent_runtime.profile_runner.budget import (
    WallBudgetCheckpoint,
    _ToolBudgetGuard,
    _emit_budget_pressure_warning,
    _enforce_result_budgets,
)
from agent_runtime.profile_runner.resident_actor import (
    _finish_resident_persona_chat_agent,
    _prepare_resident_persona_chat_agent,
    stage_persona_chat_user_row_marker,
)
from agent_runtime.profile_runner.execute import (
    _cleanup_agent_ready,
    _notify_agent_ready,
    _run_conversation_with_usage_ledger,
)
from agent_runtime.profile_runner.mcp_lane import (
    _on_mcp_budget_exhausted,
    _steer_mcp_admission_notice,
)
from agent_runtime.profile_runner.workdir import (
    _WORKDIR_LOCK,
    _agent_workdir,
    _counted_agent_run,
    _validate_workdir,
)
from agent_runtime.profile_runner.status import (
    _binding_for_profile,
    _elapsed_ms,
    _emit_request_timing,
    _positive_float,
    _profile_status_callback,
)
from agent_runtime.profile_runner.runtime_resolve import _resolve_request_runtime
from agent_runtime.profile_runner.progress import _progress_adapter
from agent_runtime.profile_runner.model_input_observability import (
    _apply_chat_compaction_threshold,
    _attach_model_input_observability,
)

__layer__ = "lanes"

__all__ = [
    "ProfileAgentRunner",
    "_default_agent_factory",
    "_normalize_result",
]


class ProfileAgentRunner:
    def __init__(self, *, agent_factory: Callable[..., Any] | None = None, credential_pool=None, session_db=None):
        self._uses_default_agent_factory = agent_factory is None
        self._agent_factory = agent_factory or _default_agent_factory
        self._credential_pool = credential_pool
        self._session_db = session_db

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Execute one turn.

        Every harness lane — operator mission chat, mission-run workers, and
        dispatch — reaches the agent through this method. The 2026-08-09 rule
        (a live turn never mutates the venv it is running in) is upstream's
        lazy-install door now, defaulted shut by the eternia-harness plugin
        (``HERMES_DISABLE_LAZY_INSTALLS``); see ``hermes_cli.runtime_environment``.
        """
        # ``_counted_agent_run`` covers the whole method: a background prewarm
        # must see this run from its first instruction, not from the point it
        # reaches the workdir lock.
        from ..local_llama_adapter.provider import turn_scope
        with _counted_agent_run(), turn_scope(request):
            return self._run(request)

    def prewarm(self, request: AgentRunRequest) -> dict[str, Any]:
        """Construct and register this chat root's resident actor. No turn runs.

        The ONLY entry point for ``prewarm_only`` requests, and deliberately not
        ``run``: ``run`` normalizes a result, finishes the resident agent and
        enforces post-run budgets, none of which exist for a construction. What
        it DOES share is everything that decides what the agent IS —
        ``_execute_agent_run``'s whole scope stack and its ``acquire()`` call —
        so the actor this leaves in the registry is the actor the next real turn
        would have built for itself.

        Returns the run's ``profile_timing`` dict; ``resident_actor_reused``
        tells the caller whether it built (``0``) or found one already resident
        (``1``). Raises exactly what a run raises — the caller owns the swallow,
        because a prewarm failure is latency, never correctness.

        NOT counted by ``_counted_agent_run``: this is the work a real run is
        allowed to displace, so counting it would make one prewarm suppress the
        next and (worse) make a prewarm look like a turn to anything reading
        that gauge.
        """

        if not request.prewarm_only:
            raise ProfileRunnerError("prewarm requires a prewarm_only request")
        _validate_workdir(request.workdir)
        binding = _binding_for_profile(request.profile)
        if binding.readiness != "ready":
            raise ProfileRunnerError(binding.summary)
        _, _, profile_timing = self._execute_agent_run(binding, request)
        return profile_timing

    def _run(self, request: AgentRunRequest) -> AgentRunResult:
        _validate_workdir(request.workdir)
        binding = _binding_for_profile(request.profile)
        if binding.readiness != "ready":
            raise ProfileRunnerError(binding.summary)
        started = time.perf_counter()
        resident = bool(
            request.persona_chat_runtime_registry is not None
            and request.root_chat_session_id
        )
        # ONE ledger per run, minted here so the post-run budgets enforced below
        # land in the same accounting block as the in-run ones. Every mechanism
        # keeps its own enforcement; only the bookkeeping is shared.
        ledger = RunBudgetLedger()
        provider_errors = _ProviderErrorCapture()
        try:
            raw_result, agent, profile_timing = self._execute_agent_run(
                binding, request, ledger=ledger, provider_errors=provider_errors
            )
        except Exception:
            if resident:
                request.persona_chat_runtime_registry.evict(
                    request.root_chat_session_id
                )
            raise
        normalize_started = time.perf_counter()
        try:
            result = _normalize_result(raw_result, agent=agent)
            profile_timing["result_normalize_ms"] = _emit_request_timing(
                request, "result_normalize", normalize_started
            )
        finally:
            if resident:
                _finish_resident_persona_chat_agent(agent)
        result.latency_ms = _elapsed_ms(started)
        profile_timing["run_budget"] = ledger.accounting()
        result.profile_timing = profile_timing
        if isinstance(result.raw, dict):
            result.raw["profile_timing"] = dict(profile_timing)
        budget_started = time.perf_counter()
        _emit_budget_pressure_warning(result, request)
        _enforce_result_budgets(result, request, ledger=ledger)
        profile_timing["budget_checks_ms"] = _emit_request_timing(request, "budget_checks", budget_started)
        # Re-rendered AFTER the post-run budgets so the block an operator reads
        # covers every bound this turn had, not only the in-run ones.
        profile_timing["run_budget"] = ledger.accounting()
        result.profile_timing = profile_timing
        if isinstance(result.raw, dict):
            result.raw["profile_timing"] = dict(profile_timing)
        if result.raw.get("failed") and result.raw.get("error"):
            detail = str(result.raw.get("error"))
            raise ProfileRunnerError(
                detail,
                provider_error=provider_errors.block_for(detail, result.raw),
            )
        return result

    def _admit_mcp_servers(
        self,
        request: AgentRunRequest,
        timing: dict[str, Any],
        *,
        ledger: RunBudgetLedger | None = None,
    ):
        """Register this run's admitted MCP servers; return the typed outcome.

        Never raises and never blocks past the admission budget — the outcome is
        typed either way, and an empty ``admitted`` simply means "this run gets
        no MCP tools", which is the state every run is in today.

        ``ledger`` is accounting only, and only for the ONE fact this function
        can observe that the caller cannot: the per-run MCP call budget trips
        mid-turn, on whichever thread dispatched the tool, so its trip has to be
        recorded from the exhaustion callback installed here. The budget's
        limit/consumption rows are declared by the caller.
        """

        admission = request.mcp_admission
        if admission is None or getattr(admission, "is_empty", True):
            return None
        from ..mcp_admission import admit_mcp_servers

        started = time.perf_counter()
        try:
            outcome = admit_mcp_servers(
                admission,
                # The per-run MCP call budget trips DURING the turn, long after
                # this function has returned, so the operator-facing half of that
                # event rides this callback rather than the outcome. The
                # agent-facing half is the refused tool's own typed result — the
                # one surface a looping model cannot miss.
                on_budget_exhausted=lambda denial, snapshot: _on_mcp_budget_exhausted(
                    request, denial, snapshot, ledger=ledger
                ),
            )
        except Exception:  # pragma: no cover - admit_mcp_servers already swallows
            timing["mcp_admission_ms"] = _emit_request_timing(
                request, "mcp_admission", started, status="failed"
            )
            return None
        timing["mcp_admission_ms"] = _emit_request_timing(request, "mcp_admission", started)
        timing["mcp_admitted_servers"] = len(outcome.admitted)
        # T2 (2026-08-09): WHY this turn's admission cost what it did. The
        # millisecond count alone cannot distinguish "MCP admission is
        # expensive" from "one server had to be started", so the LABEL is
        # recorded per server and as a count, and the label is read off the live
        # transport map, never off the clock. The one measured cold spawn
        # (~3,200 ms, one 60-tool stdio server) is NOT a threshold either way:
        # launcher_qa is a compiled Dart exe that spawns cold in ~100 ms, and
        # reading that as a fast failure sent a whole investigation down the
        # wrong branch (corrected 2026-08-26; see mcp_admission.TRANSPORT_COLD).
        # The honest discriminator is the admitted SET below.
        transport_paths = dict(getattr(outcome, "transport_paths", None) or {})
        if transport_paths:
            from ..mcp_admission import TRANSPORT_COLD

            timing["mcp_admission_transport"] = transport_paths
            timing["mcp_admission_cold_servers"] = sum(
                1 for path in transport_paths.values() if path == TRANSPORT_COLD
            )
        timing["mcp_call_budget"] = int(getattr(admission, "max_tool_calls_per_run", 0) or 0)
        if request.progress_callback is not None and (outcome.admitted or outcome.denied):
            try:
                request.progress_callback(
                    {
                        "type": "run.progress",
                        "phase": "mcp_admission",
                        "severity": "info" if outcome.admitted else "warning",
                        "step": "mcp_admission_resolved",
                        "status": "ok" if outcome.admitted else "warning",
                        "summary": (
                            "MCP admission: "
                            + (", ".join(outcome.admitted) if outcome.admitted else "nothing admitted")
                        ),
                        "mcp_admission": {
                            "admitted": list(outcome.admitted),
                            "denied": outcome.denial_rows(),
                            "duration_ms": outcome.duration_ms,
                            "transport": transport_paths,
                        },
                    }
                )
            except Exception:
                pass
        return outcome

    def _teardown_mcp_admission(
        self,
        request: AgentRunRequest,
        servers: tuple[str, ...],
        timing: dict[str, Any],
        budget: Any | None = None,
    ) -> None:
        """Remove this run's MCP registry scope. Advisory — never fails the turn.

        Runs on the way out of ``_execute_agent_run`` for BOTH the completed and
        the raised path, while the run still holds ``_WORKDIR_LOCK`` and is still
        inside ``persona_profile_context``, so no other persona's run can observe
        the scope between the last tool call and its removal. The transport stays
        warm; only the registry entries and the toolset alias go.

        ``budget`` is this run's call meter, read here for its final accounting:
        the meter dies with the scope, so end-of-run is the last moment "how many
        admitted MCP calls did this turn actually make" is answerable.
        """

        if not servers:
            return
        if budget is not None:
            try:
                snapshot = budget.snapshot()
                timing["mcp_calls_spent"] = int(snapshot.get("spent") or 0)
                timing["mcp_calls_refused"] = int(snapshot.get("refused") or 0)
            except Exception:  # pragma: no cover - accounting must never fail a turn
                pass
        from ..mcp_admission import teardown_mcp_admission

        started = time.perf_counter()
        try:
            outcome = teardown_mcp_admission(servers)
        except Exception:  # pragma: no cover - teardown_mcp_admission already swallows
            timing["mcp_teardown_ms"] = _emit_request_timing(
                request, "mcp_teardown", started, status="failed"
            )
            return
        timing["mcp_teardown_ms"] = _emit_request_timing(
            request, "mcp_teardown", started, status="ok" if outcome.ok else "warning"
        )
        timing["mcp_teardown_tools"] = len(outcome.removed_tool_names)
        if request.progress_callback is None:
            return
        try:
            request.progress_callback(
                {
                    "type": "run.progress",
                    "phase": "mcp_admission",
                    "severity": "info" if outcome.ok else "warning",
                    "step": "mcp_admission_torn_down",
                    "status": "ok" if outcome.ok else "warning",
                    "summary": (
                        "MCP admission scope removed: "
                        + ", ".join(outcome.servers)
                        + f" ({len(outcome.removed_tool_names)} tool(s))"
                    ),
                    "mcp_teardown": {
                        "servers": list(outcome.servers),
                        "removed_tool_names": list(outcome.removed_tool_names),
                        "failures": outcome.failure_rows(),
                        "duration_ms": outcome.duration_ms,
                    },
                }
            )
        except Exception:
            pass

    def _execute_agent_run(
        self,
        binding: PersonaProfileBinding,
        request: AgentRunRequest,
        *,
        ledger: RunBudgetLedger | None = None,
        provider_errors: "_ProviderErrorCapture | None" = None,
    ) -> tuple[Any, Any, dict[str, Any]]:
        timing: dict[str, Any] = {}
        ledger = ledger if ledger is not None else RunBudgetLedger()
        from ..persona_chat_continuity import (
            chat_root_session_key_scope,
            tool_execution_scope,
        )
        from ..terminal_envelope import terminal_envelope_scope
        from agent_runtime.skill_resolution import skill_runtime_scope
        from ..local_llama_adapter.provider import prewarm_scope, construction_kwargs, actor_signature

        with (
            _WORKDIR_LOCK,
            persona_profile_context(binding, runtime_root=request.runtime_root),
            prewarm_scope(request),
            _agent_workdir(request.workdir),
            tool_execution_scope(request.tool_execution_scope_id),
            # Same identity, second consumer: the container scope above keys
            # sandbox reuse by the chat root; this one hands the SAME root to
            # tools.approval's session-key surface, so background spawns and
            # delegations from this run carry a session_key the completion
            # drain can resolve to a chat root (see chat_root_session_key_scope).
            chat_root_session_key_scope(request.tool_execution_scope_id),
            # Bound for the whole run so the terminal tool can resolve which
            # lane/role it is executing under. Deliberately INSIDE
            # persona_profile_context but independent of it: the envelope's
            # historical activation signal (HERMES_AGENT_RUNTIME_ROOT, exported
            # only when the persona binds a Hermes profile) is exactly what made
            # enforcement nondeterministic on this lane.
            terminal_envelope_scope(request.terminal_envelope_scope),
            skill_runtime_scope(
                surface=request.skill_surface,
                root_node_mode=request.skill_root_node_mode,
            ),
            # The admitted MCP registry scope belongs to THIS run. Entered last
            # so it unwinds FIRST — teardown therefore runs while the run still
            # holds _WORKDIR_LOCK and is still inside persona_profile_context,
            # on the raised path as well as the returned one. Using a stack
            # rather than a try/finally keeps the (large) run body unindented.
            ExitStack() as mcp_scope,
        ):
            try:
                runtime_started = time.perf_counter()
                runtime = _resolve_request_runtime(request, timing)
                timing["runtime_resolve_ms"] = _emit_request_timing(request, "runtime_resolve", runtime_started)
            except Exception:
                if self._uses_default_agent_factory:
                    raise
                runtime = {}
                timing["runtime_resolve_ms"] = _emit_request_timing(request, "runtime_resolve", runtime_started, status="failed")
            budget_guard = _ToolBudgetGuard(ledger=ledger)
            # Wall-clock checkpoint. Built even when the run carries no wall
            # budget (deadline in the far future ⇒ it never engages) so the
            # tool-start gate below has one unconditional shape. The clock
            # starts HERE — agent construction and the resident-registry probe
            # are on the turn's wall, so the countdown the agent sees must
            # include them.
            wall_checkpoint = WallBudgetCheckpoint(
                turn_budget.TurnWallBudget(
                    total_seconds=_positive_float(request.max_wall_seconds) or _NO_WALL_BUDGET_SECONDS,
                    deadline_epoch=time.time()
                    + (_positive_float(request.max_wall_seconds) or _NO_WALL_BUDGET_SECONDS),
                ),
                progress_callback=request.progress_callback,
                ledger=ledger,
            )
            budget_guard.wall_checkpoint = wall_checkpoint
            # Declared only for a run that HAS a wall budget — the stand-in
            # above exists to give the tool-start gate one unconditional shape,
            # and accounting a 115-year "limit" would be a bound nobody has.
            if _positive_float(request.max_wall_seconds) is not None:
                ledger.declare(
                    RunBudgetKind.WALL,
                    enforcement=RunBudgetEnforcement.LANDS_TURN,
                    unit=UNIT_SECONDS,
                    limit=wall_checkpoint.budget.total_seconds,
                    consumed_provider=wall_checkpoint.consumed_seconds,
                )
            # MCP admission. Inside persona_profile_context (so HERMES_HOME
            # already points at the persona's own profile) and before agent
            # construction (so the admitted tools exist in the registry by the
            # time the factory resolves tool definitions). Bounded and
            # non-raising: a capability probe must never be able to fail a turn,
            # so every degradation comes back as a typed row and the turn
            # continues on the fallback lane.
            admission_outcome = self._admit_mcp_servers(request, timing, ledger=ledger)
            admitted_servers = admission_outcome.admitted if admission_outcome else ()
            if admitted_servers:
                # Declared only for a run that actually got MCP tools: a run with
                # nothing admitted has no MCP calls to bound. The MCP meter is
                # its own authority for the count, so the ledger READS it rather
                # than keeping a second tally that could disagree with the one
                # the refusal itself used.
                call_budget = getattr(admission_outcome, "call_budget", None)
                ledger.declare(
                    RunBudgetKind.MCP_CALLS,
                    enforcement=RunBudgetEnforcement.REFUSES_CALL,
                    unit=UNIT_CALLS,
                    limit=(
                        getattr(call_budget, "limit", None)
                        if call_budget is not None
                        else _positive_int(
                            getattr(request.mcp_admission, "max_tool_calls_per_run", None)
                        )
                    ),
                    consumed=0 if call_budget is None else None,
                    consumed_provider=(
                        None
                        if call_budget is None
                        else lambda: (call_budget.snapshot() or {}).get("spent")
                    ),
                )
                mcp_scope.callback(
                    self._teardown_mcp_admission,
                    request,
                    admitted_servers,
                    timing,
                    budget=call_budget,
                )
            # Per-run reasoning override → agent reasoning_config. Only passed
            # when explicitly requested so an unset run keeps the current
            # behavior (transport reads the global agent.reasoning_effort). The
            # transport reads params["reasoning_config"] = {"enabled": .., "effort": ..}.
            reasoning_kwargs: dict[str, Any] = {}
            if request.reasoning_effort:
                from hermes_constants import parse_reasoning_effort

                reasoning_config = parse_reasoning_effort(request.reasoning_effort)
                if reasoning_config is not None:
                    reasoning_kwargs["reasoning_config"] = reasoning_config
            # T3 (2026-08-09): the turn-scoped state a RESIDENT actor needs
            # refreshed, resolved from the REQUEST rather than read back off a
            # throwaway agent. This is what makes the construction below lazy:
            # `_prepare_resident_persona_chat_agent` used to consume exactly
            # these seven values from a freshly built agent, which is why one had
            # to be constructed (~1.4-1.8 s, tool setup dominated) even on the
            # warm serve lane where it was immediately discarded on reuse.
            turn_state = {
                "status_callback": _profile_status_callback(request, timing),
                # Kept on ONE line each, exactly as in the construction call this
                # was lifted out of: ``test_s55_registered_events_have_emitters``
                # witnesses that these two event labels are supplied by the RUNNER
                # rather than written at the sink, and it witnesses that by
                # matching the call's SOURCE TEXT — so a purely cosmetic wrap here
                # reads to that gate as "the runner stopped naming the label".
                "tool_progress_callback": _progress_adapter(request.progress_callback, "run.progress", guard=budget_guard),
                "tool_start_callback": _progress_adapter(request.progress_callback, "run.tool.started", guard=budget_guard),
                "tool_complete_callback": _progress_adapter(request.progress_callback, "run.tool.finished", guard=budget_guard),
                "clarify_callback": request.clarify_callback,
                # Header-only codex cache-scope hint; the default factory applies
                # it to the constructed agent (never to session/transcript load).
                "cache_scope_id": request.cache_scope_id,
                "max_iterations": request.max_iterations,
            }

            def _construct_agent():
                """Build this run's agent and time it. Called at most once."""

                construct_started = time.perf_counter()
                built = self._agent_factory(
                    provider=runtime.get("provider") or request.provider,
                    model=runtime.get("model") or request.model or "",
                    api_mode=request.api_mode or runtime.get("api_mode"),
                    base_url=runtime.get("base_url"),
                    api_key=runtime.get("api_key"),
                    **construction_kwargs(runtime),
                    **reasoning_kwargs,
                    enabled_toolsets=_enabled_toolsets_for_run(request, admitted_servers),
                    disabled_toolsets=request.disabled_toolsets,
                    blocked_tool_names=_blocked_tool_names_for_run(request),
                    quiet_mode=request.quiet_mode,
                    skip_context_files=request.skip_context_files,
                    skip_memory=request.skip_memory,
                    platform=request.platform,
                    session_id=request.session_id,
                    credential_pool=self._credential_pool,
                    session_db=self._session_db,
                    **turn_state,
                )
                timing["agent_construct_ms"] = _emit_request_timing(
                    request, "agent_construct", construct_started
                )
                return built

            if request.persona_chat_runtime_registry is not None and request.root_chat_session_id:
                active_id = request.session_id or request.root_chat_session_id
                # The factory is now genuinely lazy: the registry calls it only
                # on a miss or a rebuild. On reuse nothing is constructed at all,
                # so `agent_construct_ms` is ABSENT rather than reporting the
                # cost of work that was thrown away — `resident_actor_reused`
                # says why, so the absence is typed, never silent.
                entry, reused, rebuild_reason, signature_diff = (
                    request.persona_chat_runtime_registry.acquire(
                        root_session_id=request.root_chat_session_id,
                        active_session_id=active_id,
                        signature=actor_signature(runtime, request.persona_chat_runtime_signature or "default"),
                        revision=request.persona_chat_native_revision or "unknown",
                        factory=_construct_agent,
                        signature_components=(
                            request.persona_chat_runtime_signature_components
                        ),
                    )
                )
                if reused:
                    _prepare_resident_persona_chat_agent(entry.agent, turn_state)
                agent = entry.agent
                timing["resident_actor_reused"] = 1 if reused else 0
                if rebuild_reason:
                    timing[f"resident_rebuild_{rebuild_reason}"] = 1
                # One flag per moved component, inside the `resident_rebuild_*`
                # vocabulary the turn record already admits
                # (`mission_chat_turns.safe_turn_profile_timing`: `*_ms`,
                # `resident_actor_reused`, `resident_rebuild_*`, every value an
                # int). A joined string would be free text and would be dropped
                # at that gate by construction — so the diff rides as flags,
                # which is also what makes it queryable across turns. NAMES
                # only: no digest and no value ever reaches the record.
                for component in signature_diff:
                    timing[f"resident_rebuild_component_{component}"] = 1
            else:
                agent = _construct_agent()
                # This run BUILT its agent — there was no resident registry to
                # ask (the default: `persona_chat.hot_sessions_enabled` is off
                # unless the root config turns it on), or no chat root to key
                # one on. That is a fact this branch KNOWS, not an unknown, and
                # writing it is what lets the turn record carry
                # `agent_init_cold=true` instead of dropping the qualifier
                # entirely. Absent-never-zero cuts both ways: a fact that was
                # established must not read as unestablished. Live proof
                # (2026-08-23): with hot sessions off, every turn record lacked
                # `agent_init_cold` while every one of those turns had paid full
                # cold construction.
                timing["resident_actor_reused"] = 0
            if request.prewarm_only:
                # Everything above this line is what a real turn does before it
                # has an agent; everything below is what it does WITH one. A
                # prewarm stops exactly here — no turn-scoped attributes, no
                # compression threshold, no MCP steer notice, no `agent_ready`
                # callback and no conversation. The `with` block still unwinds
                # normally on the way out, so this run's admitted MCP scope is
                # torn down while it still holds `_WORKDIR_LOCK`, exactly as a
                # real run's is.
                #
                # `_finish_resident_persona_chat_agent` detaches the (already
                # empty) prewarm-local handles, so a resident actor is handed to
                # its first real turn in the same state a completed turn leaves
                # it in — one state for a warm actor, not two.
                _finish_resident_persona_chat_agent(agent)
                return None, agent, timing
            if request.root_chat_session_id:
                agent._persona_chat_root_session_id = request.root_chat_session_id
                agent._persona_chat_client_message_id = request.client_message_id
                agent._persona_chat_turn_id = request.turn_id
                # Type the user row the runtime is about to persist (relay
                # sender attribution). Single write path, marker or not.
                stage_persona_chat_user_row_marker(agent, request)
                # Persona-chat continuity deliberately keeps a stable logical
                # root while native compression advances to a child SessionDB
                # tip.  Hermes' global default is in-place compaction, which
                # cannot express that lineage (and makes the Launcher observe
                # depth=0 forever), so this lane must always use rotation.
                agent.compression_in_place = False
                compressor = getattr(agent, "context_compressor", None)
                if compressor is not None:
                    # T5 (2026-08-09). ONE write path for "when does this chat
                    # root compact", whether the number came from a per-turn
                    # override or the lane default — see
                    # `_apply_chat_compaction_threshold` for why the two must
                    # not be separate assignments.
                    if request.compression_threshold_tokens_override is not None:
                        threshold_tokens = int(request.compression_threshold_tokens_override)
                        if threshold_tokens <= 0:
                            raise ValueError("compression threshold tokens must be positive")
                        timing["chat_compaction"] = _apply_chat_compaction_threshold(
                            compressor, threshold_tokens, source="turn_override"
                        )
                    else:
                        from ..config import mission_chat_compaction_threshold_tokens

                        timing["chat_compaction"] = _apply_chat_compaction_threshold(
                            compressor,
                            mission_chat_compaction_threshold_tokens(),
                            source="lane_default",
                        )
                    if request.compression_protect_first_n_override is not None:
                        compressor.protect_first_n = max(
                            0, int(request.compression_protect_first_n_override)
                        )
                    if request.compression_protect_last_n_override is not None:
                        compressor.protect_last_n = max(
                            0, int(request.compression_protect_last_n_override)
                        )
            _steer_mcp_admission_notice(agent, request, admission_outcome)
            # Entered on the run's own ExitStack so it unwinds on BOTH
            # conversation lanes below and on the raised path, before the
            # resident registry can hand this agent to another turn.
            mcp_scope.enter_context(_capture_provider_errors(agent, provider_errors))
            agent_ready_cleanup = _notify_agent_ready(request, agent)
            max_wall_seconds = _positive_float(request.max_wall_seconds)
            if max_wall_seconds is None:
                try:
                    conversation_started = time.perf_counter()
                    conversation_kwargs: dict[str, Any] = {
                        "user_message": request.user_message,
                        "system_message": request.system_message,
                        "task_id": request.task_id,
                    }
                    if request.conversation_history is not None:
                        conversation_kwargs["conversation_history"] = request.conversation_history
                    if request.reuse_current_user_message:
                        conversation_kwargs["reuse_current_user_message"] = True
                    if request.stream_callback is not None:
                        conversation_kwargs["stream_callback"] = request.stream_callback
                    raw_result = _run_conversation_with_usage_ledger(agent, conversation_kwargs)
                    _attach_model_input_observability(raw_result, agent=agent, request=request)
                    timing["conversation_call_ms"] = _emit_request_timing(request, "conversation_call", conversation_started)
                    timing["run_budget"] = ledger.accounting()
                    return raw_result, agent, timing
                finally:
                    _cleanup_agent_ready(agent_ready_cleanup, request)

            expired = Event()
            wall_checkpoint.bind(agent)

            def interrupt_for_budget() -> None:
                expired.set()
                # Recorded where the bound actually FIRED (the timer thread), so
                # the accounting is already true by the time the main thread
                # raises. An ESCALATION: if the graceful checkpoint had already
                # opened, this replaces the `lands_turn` row with the hard kill
                # that followed it — both happened, and the kill is the fact.
                ledger.trip(
                    RunBudgetKind.WALL,
                    RunBudgetTripReason.WALL_CLOCK_EXCEEDED,
                    consumed=wall_checkpoint.consumed_seconds(),
                    detail=f"wall_seconds={max_wall_seconds:g}",
                    enforcement=RunBudgetEnforcement.TRIPS_RUN,
                )
                if hasattr(agent, "interrupt"):
                    try:
                        agent.interrupt("live run budget exceeded")
                    except Exception:
                        pass
                if request.progress_callback is not None:
                    request.progress_callback(
                        {
                            "type": "run.progress",
                            "phase": "runaway_warning",
                            "severity": "critical",
                            "step": "wall_clock_budget_exceeded",
                            "status": "failed",
                            "summary": f"Live run exceeded wall-clock budget: wall_seconds={max_wall_seconds:g}",
                        }
                    )

            # The graceful checkpoint opens BEFORE the hard wall (by the
            # reserved window). The hard wall below stays armed at the real
            # deadline as the last resort — it is no longer the first thing that
            # happens when a turn runs long.
            checkpoint_timer: Timer | None = None
            if wall_checkpoint.budget.supports_checkpoint:
                checkpoint_timer = Timer(
                    wall_checkpoint.budget.seconds_until_checkpoint(),
                    lambda: wall_checkpoint.engage(
                        trigger=turn_budget.CHECKPOINT_TRIGGER_TIMER
                    ),
                )
                checkpoint_timer.daemon = True
                checkpoint_timer.start()
            timer = Timer(max_wall_seconds, interrupt_for_budget)
            timer.daemon = True
            timer.start()
            try:
                conversation_started = time.perf_counter()
                conversation_kwargs = {
                    "user_message": request.user_message,
                    "system_message": request.system_message,
                    "task_id": request.task_id,
                }
                if request.conversation_history is not None:
                    conversation_kwargs["conversation_history"] = request.conversation_history
                if request.reuse_current_user_message:
                    conversation_kwargs["reuse_current_user_message"] = True
                if request.stream_callback is not None:
                    conversation_kwargs["stream_callback"] = request.stream_callback
                raw_result = _run_conversation_with_usage_ledger(agent, conversation_kwargs)
                _attach_model_input_observability(raw_result, agent=agent, request=request)
                timing["conversation_call_ms"] = _emit_request_timing(request, "conversation_call", conversation_started)
            except BaseException:
                timing["conversation_call_ms"] = _emit_request_timing(request, "conversation_call", conversation_started, status="failed")
                if expired.is_set():
                    raise RunBudgetExceeded(
                        f"live run budget exceeded: wall_seconds={max_wall_seconds:g}",
                        session_id=getattr(agent, "session_id", None),
                        wall_budget=wall_checkpoint.summary(),
                        run_budget=ledger.accounting(),
                    )
                raise
            finally:
                if checkpoint_timer is not None:
                    checkpoint_timer.cancel()
                timer.cancel()
                _cleanup_agent_ready(agent_ready_cleanup, request)
            if expired.is_set():
                raise RunBudgetExceeded(
                    f"live run budget exceeded: wall_seconds={max_wall_seconds:g}",
                    session_id=getattr(agent, "session_id", None),
                    wall_budget=wall_checkpoint.summary(),
                    run_budget=ledger.accounting(),
                )
            # The checkpoint fired and the turn still landed a reply: hand the
            # caller the typed provenance so it settles the turn as a
            # budget-ended turn instead of a plain completion.
            if wall_checkpoint.engaged and isinstance(raw_result, dict):
                raw_result["wall_budget_checkpoint"] = wall_checkpoint.summary()
            timing["run_budget"] = ledger.accounting()
            return raw_result, agent, timing


def _normalize_result(result: Any, *, agent) -> AgentRunResult:
    if isinstance(result, dict):
        messages = result.get("messages") if isinstance(result.get("messages"), list) else []
        return AgentRunResult(
            final_response=str(result.get("final_response", "")),
            session_id=result.get("session_id") or getattr(agent, "session_id", None),
            provider=result.get("provider") or getattr(agent, "provider", None),
            model=result.get("model") or getattr(agent, "model", None),
            base_url=result.get("base_url") or getattr(agent, "base_url", None),
            messages=[msg for msg in messages if isinstance(msg, dict)],
            api_calls=result.get("api_calls"),
            input_tokens=result.get("input_tokens") or result.get("prompt_tokens"),
            output_tokens=result.get("output_tokens") or result.get("completion_tokens"),
            total_tokens=result.get("total_tokens"),
            cache_read_tokens=result.get("cache_read_tokens"),
            cache_write_tokens=result.get("cache_write_tokens"),
            reasoning_tokens=result.get("reasoning_tokens"),
            usage_ledger=[
                row for row in (result.get("usage_ledger") or []) if isinstance(row, dict)
            ]
            if isinstance(result.get("usage_ledger"), list)
            else [],
            raw=dict(result),
        )
    return AgentRunResult(
        final_response=str(result),
        session_id=getattr(agent, "session_id", None),
        provider=getattr(agent, "provider", None),
        model=getattr(agent, "model", None),
        base_url=getattr(agent, "base_url", None),
        messages=[],
        raw={"result_type": type(result).__name__},
    )


def _default_agent_factory(**kwargs):
    from run_agent import AIAgent

    # ``cache_scope_id`` is a fork-runtime, header-only codex cache-scope hint —
    # NOT part of the upstream AIAgent constructor. Pop it before construction so
    # the upstream signature is untouched, then apply it as an attribute the
    # codex build seam reads via ``getattr(agent, "cache_scope_id", None)``. It
    # never participates in session/transcript loading.
    cache_scope_id = kwargs.pop("cache_scope_id", None)
    agent = AIAgent(**kwargs)
    if cache_scope_id:
        agent.cache_scope_id = cache_scope_id
    return agent
