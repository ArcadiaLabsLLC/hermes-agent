"""The pieces of one agent run's execution around the conversation: which tools
and toolsets the run may use (the blocked-tool set with the registry-hygiene
names, the admitted toolsets), the per-request runtime resolution and its
short-lived memo (one memo, one writer), agent-ready notification and cleanup,
and the usage-ledger wrapper.
"""

from __future__ import annotations

import contextvars
import functools
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from threading import Event, RLock, Timer
import time
from typing import Any, Callable

from hermes_cli.runtime_provider import resolve_runtime_provider

from agent_runtime import idle_turn_keeper, live_turns, turn_budget
from agent_runtime.persona_chat_identity import resolved_runtime_revision
from agent_runtime.personas import _blocked_tool_names_with_registry_hygiene
from agent_runtime.profile_context import PersonaProfileBinding, persona_profile_context
from agent_runtime.run_budget import (
    UNIT_CALLS,
    UNIT_SECONDS,
    RunBudgetEnforcement,
    RunBudgetKind,
    RunBudgetLedger,
    RunBudgetTripReason,
)

from agent_runtime.first_turn_warmup import warm_first_turn_paths
from agent_runtime.prewarmed_system_prompt import (
    RAN_ON_RUN_END,
    run_deferred_turn_persist,
    stash_prewarmed_system_prompt,
)
from agent_runtime.serde import positive_float, positive_int
from agent_runtime.tool_blocks import bound_tool_block
from agent_runtime.profile_runner.errors import (
    PrewarmYielded,
    RunBudgetExceeded,
    _NO_WALL_BUDGET_SECONDS,
)
from agent_runtime.profile_runner.models import (
    AgentRunRequest,
)
from agent_runtime.profile_runner.budget import (
    WallBudgetCheckpoint,
    _ToolBudgetGuard,
)
from agent_runtime.profile_runner.resident_actor import (
    log_turn_effort,
    turn_reasoning_config,
    _finish_resident_persona_chat_agent,
    _prepare_resident_persona_chat_agent,
    stage_persona_chat_user_row_marker,
)
from agent_runtime.profile_runner.mcp_lane import (
    _steer_mcp_admission_notice,
)
from agent_runtime.profile_runner.workdir import (
    _WORKDIR_LOCK,
    _agent_workdir,
)
from agent_runtime.profile_runner.status import (
    _emit_request_timing,
    _profile_status_callback,
)
from agent_runtime.profile_runner.progress import ToolFinishJoin, _progress_adapter
from agent_runtime.profile_runner.model_input_observability import (
    _apply_chat_compaction_threshold,
    _attach_model_input_observability,
)

__layer__ = "lanes"


def _warm_skill_catalog(agent) -> None:
    """Fill the process-wide skill-catalog memo the turn's observability row reads (h-send-window)."""

    from agent_runtime.prompt_observability.skills_resolver import _installed_skill_catalog

    _installed_skill_catalog()


#: Warm-up steps that read a store; ``first_turn_warmup`` is policy and may not import one.
_FIRST_TURN_STORE_STEPS = (("skill_catalog", _warm_skill_catalog),)

__all__ = [
    "AgentRunExecution",
    "RUNTIME_RESOLVE_CACHE_TTL_SECONDS",
    "_RUNTIME_RESOLVE_CACHE",
    "_RUNTIME_RESOLVE_CACHE_LOCK",
    "_RUNTIME_RESOLVE_STAMPED_FILES",
    "_blocked_tool_names_for_run",
    "_cleanup_agent_ready",
    "_emit_agent_ready_callback_warning",
    "_enabled_toolsets_for_run",
    "_notify_agent_ready",
    "_resolve_request_runtime",
    "_run_conversation_with_usage_ledger",
    "_runtime_resolve_cache_key",
]


# ── which tools and toolsets a run may use ──────────────────────────────────

def _blocked_tool_names_for_run(request: "AgentRunRequest") -> list[str]:
    """Registry hygiene plus this run's admission-scoped MCP tool block."""

    names = _blocked_tool_names_with_registry_hygiene(request.blocked_tool_names)
    admission = request.mcp_admission
    if admission is None:
        return names
    seen = set(names)
    for name in admission.blocked_tool_names:
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _enabled_toolsets_for_run(
    request: "AgentRunRequest", admitted_servers: tuple[str, ...] = ()
) -> list[str] | None:
    """Scope this run's toolsets to the MCP servers it was ADMITTED.

    The second fork-owned chokepoint at agent construction, and the one that
    makes the cross-persona isolation property hold on every lane rather than
    only on the chat lane: MCP registration is process-global, so in a warm
    multi-persona harness process any run whose toolsets were resolved from the
    live registry (``unbounded`` resolves ``all_registered_toolsets()``) would
    otherwise inherit another persona's admitted ``mcp-*`` toolsets. Applied
    here, no call site can opt out.

    With no admission on the request — every lane today except an admitted
    mission-chat turn — this strips any MCP toolset the run did not earn, which
    is a no-op while the harness lane registers nothing at all.
    ``enabled_toolsets=None`` (the "everything" sentinel) is passed through
    untouched: narrowing it would change what a default run resolves.
    """

    from ..mcp_admission.resolve import scope_toolsets_to_admission

    if request.enabled_toolsets is None:
        return None
    return scope_toolsets_to_admission(
        request.enabled_toolsets, admitted_servers=admitted_servers
    )


# ── the per-request runtime resolution and its memo ─────────────────────────

#: T6 (2026-08-09): how long a resolved runtime may be reused for an unchanged
#: (profile, provider, model, config) tuple. 0.28-0.44 s of every send was spent
#: re-resolving an identical answer.
#:
#: THE TTL IS A SAFETY BOUND, NOT A TUNING KNOB, and it is why it is 30 s rather
#: than something generous. ``resolve_runtime_provider`` returns live OAuth
#: credentials and refreshes any token within
#: ``hermes_cli.auth.ACCESS_TOKEN_REFRESH_SKEW_SECONDS`` (120 s) of expiry. A
#: memo handed out T seconds after resolution therefore carries a token with at
#: least ``skew - T`` seconds of validity left: at 30 s that floor is 90 s,
#: comfortably longer than the turn that is about to use it. Raising this past
#: the skew would hand out expired credentials, so it must stay well under it —
#: the invariant is pinned by
#: ``tests/agent_runtime/test_send_path_runner_reuse.py`` (`:425-426`, which
#: asserts this constant is positive AND below half the refresh skew). This
#: line named ``test_runtime_resolve_cache.py``, a file that never existed;
#: repointed MCF-78 2026-08-20.
RUNTIME_RESOLVE_CACHE_TTL_SECONDS = 30.0


#: Files whose content can change what ``resolve_runtime_provider`` returns for
#: an otherwise identical request (default provider/model, base_url, a provider
#: flipped to ``enabled: false``, a rotated key). Their (mtime_ns, size) join the
#: cache key, so an operator edit invalidates the memo immediately instead of
#: waiting out the TTL.
_RUNTIME_RESOLVE_STAMPED_FILES = ("config.yaml", ".env")


_RUNTIME_RESOLVE_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}


_RUNTIME_RESOLVE_CACHE_LOCK = RLock()


def _runtime_resolve_cache_key(request: AgentRunRequest) -> tuple:
    """Everything that can change the answer, and nothing that cannot.

    ``HERMES_HOME`` is in the key because this resolves INSIDE
    ``persona_profile_context`` — two personas bound to different profiles must
    never share a memo (the same reason profile-context memos key on it).
    """

    from hermes_constants import get_hermes_home
    from hermes_cli.auth import authentication_owner_stamps

    home = Path(get_hermes_home())
    stamps = []
    for name in _RUNTIME_RESOLVE_STAMPED_FILES:
        try:
            stat = (home / name).stat()
            stamps.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            # An absent file is a stable fact about the config too; it becomes a
            # different key the moment one is created.
            stamps.append((name, None, None))
    return (
        str(home),
        str(request.provider or ""),
        str(request.model or ""),
        tuple(stamps),
        authentication_owner_stamps(),
    )


def _resolve_request_runtime(
    request: AgentRunRequest, timing: dict[str, Any] | None = None
) -> dict[str, Any]:
    from ..local_llama_adapter import is_local_llama_provider
    if is_local_llama_provider(request.provider):
        from ..local_llama_adapter.provider import resolve
        return resolve(request.model, root=request.runtime_root)
    if not request.provider:
        return {}
    key = _runtime_resolve_cache_key(request)
    now = time.monotonic()
    with _RUNTIME_RESOLVE_CACHE_LOCK:
        cached = _RUNTIME_RESOLVE_CACHE.get(key)
        if cached is not None and now - cached[0] <= RUNTIME_RESOLVE_CACHE_TTL_SECONDS:
            if timing is not None:
                timing["runtime_resolve_cached"] = 1
            return dict(cached[1])
    resolved = _resolved_fields(resolve_runtime_provider(requested=request.provider, target_model=request.model))
    # h-idle-turn: between turns the idle keeper re-resolves this entry before it lapses, in this
    # turn's context (the profile binding), so the next turn after a pause reads it warm.
    idle_turn_keeper.register_refresh(
        f"runtime_resolve:{key[0]}|{key[1]}|{key[2]}",
        functools.partial(contextvars.copy_context().run, _idle_refresh_runtime_resolve,
                          str(request.provider or ""), str(request.model or "")),
    )
    _store_resolved(key, now, resolved)
    if timing is not None:
        timing["runtime_resolve_cached"] = 0
    return resolved


def _store_resolved(key: tuple, at: float, resolved: dict[str, Any], *, replace_only: bool = False) -> None:
    """The memo's one write path (a turn's resolve; the idle keeper's, ``replace_only``)."""

    with _RUNTIME_RESOLVE_CACHE_LOCK:
        if replace_only and key not in _RUNTIME_RESOLVE_CACHE:
            return
        # Bounded: one entry per live (profile, provider, model, config) tuple,
        # and the set of those is small. Evict the oldest wholesale rather than
        # keep an LRU — a cold re-resolve costs one turn 0.3 s, a leak costs the
        # process.
        if len(_RUNTIME_RESOLVE_CACHE) >= 64:
            _RUNTIME_RESOLVE_CACHE.clear()
        _RUNTIME_RESOLVE_CACHE[key] = (at, dict(resolved))


def _resolved_fields(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        key_name: value
        for key_name, value in runtime.items()
        if key_name in {"provider", "model", "api_mode", "base_url", "api_key"} and value
    }


def _idle_refresh_runtime_resolve(provider: str, model: str) -> bool:
    """h-idle-turn: re-resolve one warm memo entry that would lapse before the keeper's next tick."""

    request = SimpleNamespace(provider=provider, model=model)
    key = _runtime_resolve_cache_key(request)  # type: ignore[arg-type]
    with _RUNTIME_RESOLVE_CACHE_LOCK:
        cached = _RUNTIME_RESOLVE_CACHE.get(key)
    lapse_after = max(0.0, RUNTIME_RESOLVE_CACHE_TTL_SECONDS - idle_turn_keeper.KEEPER_INTERVAL_SECONDS)
    if cached is None or time.monotonic() - cached[0] < lapse_after:
        return False  # gone (a config edit moved the key) or still fresh
    started = time.monotonic()
    _store_resolved(key, started, _resolved_fields(resolve_runtime_provider(requested=provider, target_model=model)),
                    replace_only=True)
    return True


def _notify_agent_ready(request: AgentRunRequest, agent: Any) -> Callable[[], None] | None:
    callback = request.agent_ready_callback
    if callback is None:
        return None
    try:
        return callback(agent)
    except Exception as exc:
        _emit_agent_ready_callback_warning(request, exc, phase="start")
        return None


def _run_conversation_with_usage_ledger(agent: Any, conversation_kwargs: dict[str, Any]) -> Any:
    """Run the turn with a per-call usage ledger, the persona agent bound for plugin
    middleware (dispatch timing, cache routing) and the provider stream observers armed;
    a dict result carries the ledger as ``usage_ledger`` and the turn's reasoning
    (``stream_gap_receipt.TurnReasoning``) as ``reasoning_window``."""
    from agent_runtime.chat_lane_defer import turn_defer_tools
    from agent_runtime.codex_observability import stream_observers_armed
    from agent_runtime.persona_turn_binding import bind_persona_turn_agent
    from agent_runtime.stream_gap_receipt import bind_turn_reasoning
    from agent_runtime.usage_ledger import bind_usage_ledger
    from tools.tool_search_downstream import scoped_turn_defer

    # The persona's defer reaches the bridge's reads (search catalog, tool_call resolve) here.
    with bind_usage_ledger() as usage_ledger, bind_persona_turn_agent(agent), stream_observers_armed(),             scoped_turn_defer(turn_defer_tools(agent)), bind_turn_reasoning(agent) as reasoning:
        try:
            raw_result = agent.run_conversation(**conversation_kwargs)
        finally:
            # h-turn1-conn: a held first-turn persist whose request never went out runs now.
            run_deferred_turn_persist(agent, RAN_ON_RUN_END)
    if isinstance(raw_result, dict):
        raw_result["usage_ledger"] = list(usage_ledger)
        window = reasoning.fields()
        reported = sum(row.get("reasoning_tokens", 0) for row in usage_ledger)
        if reported > 0:
            raw_result["reasoning_tokens"] = reported
            if not window:
                window = {"reasoning_tokens": reported}
        raw_result["reasoning_window"] = window
    return raw_result


def _cleanup_agent_ready(cleanup: Callable[[], None] | None, request: AgentRunRequest) -> None:
    if cleanup is None:
        return
    try:
        cleanup()
    except Exception as exc:
        _emit_agent_ready_callback_warning(request, exc, phase="cleanup")


def _emit_agent_ready_callback_warning(request: AgentRunRequest, exc: Exception, *, phase: str) -> None:
    if request.progress_callback is None:
        return
    try:
        request.progress_callback(
            {
                "type": "run.progress",
                "phase": "agent_ready_callback",
                "severity": "warning",
                "step": phase,
                "status": "failed",
                "summary": f"Agent ready callback {phase} failed: {type(exc).__name__}",
            }
        )
    except Exception:
        return


# ── one agent run, phase by phase (was ProfileAgentRunner._execute_agent_run) ──


class AgentRunExecution:
    """ONE agent run, executed in named phases (program rule 17).

    ``ProfileAgentRunner._execute_agent_run`` was one 424-line body at depth 5
    whose two closures (``_construct_agent``, ``interrupt_for_budget``) read six of
    its locals. Those locals are the fields here, and each phase is a method:

    ``scopes`` (the whole-run scope stack, ``_WORKDIR_LOCK`` first) ->
    ``resolve_runtime`` -> ``arm_wall_checkpoint`` -> ``admit_mcp`` ->
    ``build_turn_state`` -> ``acquire_agent`` -> ``bind_chat_root`` ->
    ``converse`` (unbounded) or ``converse_under_wall``.

    The order and every comment are the old body's; nothing here is a new rule.
    """

    def __init__(
        self,
        runner: Any,
        binding: PersonaProfileBinding,
        request: AgentRunRequest,
        *,
        ledger: RunBudgetLedger | None = None,
    ) -> None:
        self.runner = runner
        self.binding = binding
        self.request = request
        self.ledger = ledger if ledger is not None else RunBudgetLedger()
        self.timing: dict[str, Any] = {}
        self.runtime: dict[str, Any] = {}
        self.budget_guard: _ToolBudgetGuard | None = None
        self.wall_checkpoint: WallBudgetCheckpoint | None = None
        self.admission_outcome: Any = None
        self.admitted_servers: tuple = ()
        self.reasoning_kwargs: dict[str, Any] = {}
        self.turn_state: dict[str, Any] = {}
        self.agent: Any = None
        self.mcp_scope: ExitStack | None = None

    # ── the run ─────────────────────────────────────────────────────────────

    def run(self) -> tuple[Any, Any, dict[str, Any]]:
        with self.scopes() as mcp_scope:
            self.mcp_scope = mcp_scope
            self.yield_point("lock_acquired")
            self.resolve_runtime()
            self.arm_wall_checkpoint()
            self.yield_point("runtime_resolved")
            self.admit_mcp()
            self.yield_point("mcp_admitted")
            self.build_turn_state()
            self.acquire_agent()
            log_turn_effort(self.request, self.agent, reused=bool(self.timing.get("resident_actor_reused")))
            if self.request.prewarm_only:
                return self.finish_prewarm()
            self.bind_chat_root()
            mcp_scope.enter_context(bound_tool_block(
                _blocked_tool_names_for_run(self.request),
                session_ids=(getattr(self.agent, "session_id", None), self.request.session_id),
            ))
            _steer_mcp_admission_notice(self.agent, self.request, self.admission_outcome)
            # RW1-RW3: what this turn is doing, readable by this process's
            # running-work projection and chat heartbeat while it runs.
            mcp_scope.enter_context(live_turns.live_turn(
                turn_id=self.request.turn_id or "",
                session_id=self.request.root_chat_session_id or self.request.session_id or "",
                persona_instance_id=self.request.persona_instance_id or "",
                agent=self.agent,
            ))
            idle_turn_keeper.note_active_agent(self.agent)  # h-idle-turn: the chat whose socket stays warm
            agent_ready_cleanup = _notify_agent_ready(self.request, self.agent)
            max_wall_seconds = positive_float(self.request.max_wall_seconds)
            if max_wall_seconds is None:
                return self.converse(agent_ready_cleanup)
            return self.converse_under_wall(max_wall_seconds, agent_ready_cleanup)

    def finish_prewarm(self) -> tuple[Any, Any, dict[str, Any]]:
        """A ``prewarm_only`` run's tail, with the agent acquired; still under the scopes.

        Everything before this is what a real turn does before it has an agent;
        everything after ``run``'s prewarm return is what it does WITH one. A prewarm
        stops here -- no turn-scoped attributes, no compression threshold, no MCP
        steer notice, no ``agent_ready`` callback and no conversation. The ``with``
        block still unwinds normally on the way out, so this run's admitted MCP scope
        is torn down while it still holds ``_WORKDIR_LOCK``, exactly as a real run's is.

        ``_finish_resident_persona_chat_agent`` detaches the (already empty)
        prewarm-local handles, so a resident actor is handed to its first real turn in
        the same state a completed turn leaves it in -- one state for a warm actor, not
        two. It runs on the yield path too: the actor is registered by then.

        h-turn1 A3: the first turn's system prompt is built HERE, under the same
        scopes, and adopted by that turn's ``_restore_or_build_system_prompt``.
        h-conn-pool: then the first turn's one-time process costs (spinner catalog,
        lazy imports, SDK headers), each step a yield point (h-turn-wait).
        """

        try:
            self.yield_point("agent_acquired")
            stash_prewarmed_system_prompt(self.agent, self.request.system_message, self.timing)
            self.yield_point("system_prompt_stashed")
            warm_first_turn_paths(self.agent, self.timing, _FIRST_TURN_STORE_STEPS,
                                  should_stop=self._prewarm_should_yield)
        finally:
            _finish_resident_persona_chat_agent(self.agent)
        return None, self.agent, self.timing

    def _prewarm_should_yield(self) -> Any:
        """The request's ``prewarm_yield`` answer on a prewarm, else ``None``. Never raises."""

        request = self.request
        if not request.prewarm_only or request.prewarm_yield is None:
            return None
        try:
            return request.prewarm_yield()
        except Exception:  # pragma: no cover - a gauge read never fails a prewarm
            return None

    def yield_point(self, phase: str) -> None:
        """h-turn-wait: a prewarm holding ``_WORKDIR_LOCK`` stands down for a turn.

        Raises :class:`PrewarmYielded`; the scope stack unwinds (MCP teardown first)
        and the lock passes to the waiting turn. A no-op on a real run.
        """

        reason = self._prewarm_should_yield()
        if reason:
            raise PrewarmYielded(phase, reason)

    @contextmanager
    def scopes(self):
        """The whole-run scope stack; yields the run's MCP ``ExitStack``."""

        request = self.request
        from ..persona_chat_continuity import (
            chat_root_session_key_scope,
            tool_execution_scope,
        )
        from ..terminal_envelope.records import terminal_envelope_scope
        from agent_runtime.skill_resolution import skill_runtime_scope
        from ..local_llama_adapter.provider import prewarm_scope

        with (
            _WORKDIR_LOCK,
            persona_profile_context(self.binding, runtime_root=request.runtime_root),
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
            yield mcp_scope

    # ── phases before the agent exists ──────────────────────────────────────

    def resolve_runtime(self) -> None:
        request, timing = self.request, self.timing
        try:
            runtime_started = time.perf_counter()
            self.runtime = _resolve_request_runtime(request, timing)
            timing["runtime_resolve_ms"] = _emit_request_timing(request, "runtime_resolve", runtime_started)
        except Exception:
            if self.runner._uses_default_agent_factory:
                raise
            self.runtime = {}
            timing["runtime_resolve_ms"] = _emit_request_timing(request, "runtime_resolve", runtime_started, status="failed")

    def arm_wall_checkpoint(self) -> None:
        request, ledger = self.request, self.ledger
        self.budget_guard = _ToolBudgetGuard(ledger=ledger)
        # Wall-clock checkpoint. Built even when the run carries no wall
        # budget (deadline in the far future ⇒ it never engages) so the
        # tool-start gate below has one unconditional shape. The clock
        # starts HERE — agent construction and the resident-registry probe
        # are on the turn's wall, so the countdown the agent sees must
        # include them.
        self.wall_checkpoint = WallBudgetCheckpoint(
            turn_budget.TurnWallBudget(
                total_seconds=positive_float(request.max_wall_seconds) or _NO_WALL_BUDGET_SECONDS,
                deadline_epoch=time.time()
                + (positive_float(request.max_wall_seconds) or _NO_WALL_BUDGET_SECONDS),
            ),
            progress_callback=request.progress_callback,
            ledger=ledger,
        )
        self.budget_guard.wall_checkpoint = self.wall_checkpoint
        # Declared only for a run that HAS a wall budget — the stand-in
        # above exists to give the tool-start gate one unconditional shape,
        # and accounting a 115-year "limit" would be a bound nobody has.
        if positive_float(request.max_wall_seconds) is not None:
            ledger.declare(
                RunBudgetKind.WALL,
                enforcement=RunBudgetEnforcement.LANDS_TURN,
                unit=UNIT_SECONDS,
                limit=self.wall_checkpoint.budget.total_seconds,
                consumed_provider=self.wall_checkpoint.consumed_seconds,
            )

    def admit_mcp(self) -> None:
        # MCP admission. Inside persona_profile_context (so HERMES_HOME
        # already points at the persona's own profile) and before agent
        # construction (so the admitted tools exist in the registry by the
        # time the factory resolves tool definitions). Bounded and
        # non-raising: a capability probe must never be able to fail a turn,
        # so every degradation comes back as a typed row and the turn
        # continues on the fallback lane.
        request = self.request
        self.admission_outcome = self.runner._admit_mcp_servers(request, self.timing, ledger=self.ledger)
        self.admitted_servers = self.admission_outcome.admitted if self.admission_outcome else ()
        if not self.admitted_servers:
            return
        # Declared only for a run that actually got MCP tools: a run with
        # nothing admitted has no MCP calls to bound. The MCP meter is
        # its own authority for the count, so the ledger READS it rather
        # than keeping a second tally that could disagree with the one
        # the refusal itself used.
        call_budget = getattr(self.admission_outcome, "call_budget", None)
        self.ledger.declare(
            RunBudgetKind.MCP_CALLS,
            enforcement=RunBudgetEnforcement.REFUSES_CALL,
            unit=UNIT_CALLS,
            limit=(
                getattr(call_budget, "limit", None)
                if call_budget is not None
                else positive_int(
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
        self.mcp_scope.callback(
            self.runner._teardown_mcp_admission,
            request,
            self.admitted_servers,
            self.timing,
            budget=call_budget,
        )

    def build_turn_state(self) -> None:
        request, budget_guard = self.request, self.budget_guard
        # The run's reasoning_config: the instance's effort, else the profile's
        # (``turn_reasoning_config``). The transport reads params["reasoning_config"].
        reasoning_config = turn_reasoning_config(request, self.runtime.get("model") or request.model)
        if reasoning_config is not None:
            self.reasoning_kwargs["reasoning_config"] = reasoning_config
        # T3 (2026-08-09): the turn-scoped state a RESIDENT actor needs
        # refreshed, resolved from the REQUEST rather than read back off a
        # throwaway agent. This is what makes the construction below lazy:
        # `_prepare_resident_persona_chat_agent` used to consume exactly
        # these seven values from a freshly built agent, which is why one had
        # to be constructed (~1.4-1.8 s, tool setup dominated) even on the
        # warm serve lane where it was immediately discarded on reuse.
        # One finished tool call, one published event: upstream's
        # ``tool.completed`` progress half is held here and folded into the
        # ``run.tool.finished`` event that claims it (``ToolFinishJoin``).
        tool_finish_join = ToolFinishJoin()
        self.turn_state = {
            "status_callback": _profile_status_callback(request, self.timing),
            # Kept on ONE line each, exactly as in the construction call this
            # was lifted out of: ``test_s55_registered_events_have_emitters``
            # witnesses that these two event labels are supplied by the RUNNER
            # rather than written at the sink, and it witnesses that by
            # matching the call's SOURCE TEXT — so a purely cosmetic wrap here
            # reads to that gate as "the runner stopped naming the label".
            "tool_progress_callback": _progress_adapter(request.progress_callback, "run.progress", guard=budget_guard, join=tool_finish_join),
            "tool_start_callback": _progress_adapter(request.progress_callback, "run.tool.started", guard=budget_guard, observe=self.observe_tool_started),
            "tool_complete_callback": _progress_adapter(request.progress_callback, "run.tool.finished", guard=budget_guard, observe=self.observe_tool_finished, join=tool_finish_join),
            "clarify_callback": request.clarify_callback,
            # Header-only codex cache-scope hint; the default factory applies
            # it to the constructed agent (never to session/transcript load).
            "cache_scope_id": request.cache_scope_id,
            "max_iterations": request.max_iterations,
        }

    def observe_tool_started(self, args: tuple[Any, ...], payload: dict[str, Any]) -> None:
        """Feed a ``run.tool.started`` call into the live-turn registry (worker thread)."""

        live_turns.tool_started(
            self.request.turn_id,
            payload.get("tool_call_id"),
            payload.get("tool_name"),
            preview=str(payload.get("command_full") or payload.get("summary") or ""),
            command=str(payload.get("command_full") or ""),
            timeout_seconds=payload.get("timeout_seconds"),
        )

    def observe_tool_finished(self, args: tuple[Any, ...], payload: dict[str, Any]) -> None:
        live_turns.tool_finished(self.request.turn_id, payload.get("tool_call_id"))

    def construct_agent(self) -> Any:
        """Build this run's agent and time it. Called at most once."""

        from ..local_llama_adapter.provider import construction_kwargs

        request, runtime, runner = self.request, self.runtime, self.runner
        construct_started = time.perf_counter()
        built = runner._agent_factory(
            provider=runtime.get("provider") or request.provider,
            model=runtime.get("model") or request.model or "",
            api_mode=request.api_mode or runtime.get("api_mode"),
            base_url=runtime.get("base_url"),
            api_key=runtime.get("api_key"),
            **construction_kwargs(runtime),
            **self.reasoning_kwargs,
            enabled_toolsets=_enabled_toolsets_for_run(request, self.admitted_servers),
            disabled_toolsets=request.disabled_toolsets,
            blocked_tool_names=_blocked_tool_names_for_run(request),
            # Only when set, so an injected factory that predates the knob keeps its signature.
            **({"chat_lane_defer_tools": list(request.chat_lane_defer_tools)}
               if request.chat_lane_defer_tools else {}),
            quiet_mode=request.quiet_mode,
            skip_context_files=request.skip_context_files,
            skip_memory=request.skip_memory,
            platform=request.platform,
            session_id=request.session_id,
            credential_pool=runner._credential_pool,
            session_db=runner._session_db,
            **self.turn_state,
        )
        from agent_runtime.chat_lane_skill_index import apply_chat_lane_skill_scope

        apply_chat_lane_skill_scope(built, request.chat_lane_index_skills)
        self.timing["agent_construct_ms"] = _emit_request_timing(
            request, "agent_construct", construct_started
        )
        return built

    def acquire_agent(self) -> None:
        request, timing = self.request, self.timing
        if request.persona_chat_runtime_registry is None or not request.root_chat_session_id:
            self.agent = self.construct_agent()
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
            return
        active_id = request.session_id or request.root_chat_session_id
        runtime_revision = resolved_runtime_revision(self.runtime)
        # The factory is now genuinely lazy: the registry calls it only
        # on a miss or a rebuild. On reuse nothing is constructed at all,
        # so `agent_construct_ms` is ABSENT rather than reporting the
        # cost of work that was thrown away — `resident_actor_reused`
        # says why, so the absence is typed, never silent.
        from ..chat_session_writer import current_chat_session_writer_owner
        from ..persona_chat_continuity.runtime_registry import OwnedResidentActor

        writer = getattr(self.runner, "_session_db", None)
        owner = current_chat_session_writer_owner()
        def owned_factory():
            if writer is None:
                return self.construct_agent()
            if owner is None:
                raise RuntimeError("resident constructor writer has no request owner")
            pin = owner.resident_pin(writer)
            try:
                return OwnedResidentActor(self.construct_agent(), pin)
            except BaseException:
                pin.close()
                raise

        entry, reused, rebuild_reason, signature_diff = (
            request.persona_chat_runtime_registry.acquire(
                root_session_id=request.root_chat_session_id,
                active_session_id=active_id,
                signature=f"{request.persona_chat_runtime_signature or 'default'}:{runtime_revision}",
                revision=request.persona_chat_native_revision or "unknown",
                factory=owned_factory,
                writer_generation=writer,
                signature_components={
                    **(request.persona_chat_runtime_signature_components or {}),
                    "resolved_runtime": runtime_revision,
                },
                prewarm=bool(request.prewarm_only),
                # The tool contract's enabled list, so a ``tool_contract``
                # rebuild names the toolsets that entered or left it.
                toolsets=request.enabled_toolsets,
            )
        )
        if reused:
            _prepare_resident_persona_chat_agent(entry.agent, self.turn_state)
            # The effort is per RUN, not per actor: a reused actor sends this run's.
            entry.agent.reasoning_config = self.reasoning_kwargs.get("reasoning_config")
        self.agent = entry.agent
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
        # h-chatperf: this rebuild threw away an actor the chat-open prewarm
        # built and no turn had used -- the prewarm's cost bought nothing. Inside
        # the admitted ``resident_rebuild_*`` vocabulary, so it reaches the record.
        take_discard = getattr(request.persona_chat_runtime_registry, "take_prewarm_discard", None)
        if callable(take_discard) and take_discard(request.root_chat_session_id) is not None:
            timing["resident_rebuild_prewarm_discarded"] = 1

    # ── phases with the agent ───────────────────────────────────────────────

    def bind_chat_root(self) -> None:
        request, agent = self.request, self.agent
        from ..turn_checkpoints import TurnCheckpointRecorder
        manager = getattr(agent, "_checkpoint_mgr", None)
        if manager is not None:
            manager.history_observer = (
                TurnCheckpointRecorder(request.root_chat_session_id, request.client_message_id, manager)
                if request.root_chat_session_id and request.client_message_id else None)
        if not request.root_chat_session_id:
            return
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
            self.apply_compaction(compressor)

    def apply_compaction(self, compressor: Any) -> None:
        request, timing = self.request, self.timing
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

    def conversation_kwargs(self) -> dict[str, Any]:
        request = self.request
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
        return conversation_kwargs

    def converse(self, agent_ready_cleanup: Any) -> tuple[Any, Any, dict[str, Any]]:
        request, agent, timing = self.request, self.agent, self.timing
        try:
            conversation_started = time.perf_counter()
            raw_result = _run_conversation_with_usage_ledger(agent, self.conversation_kwargs())
            _attach_model_input_observability(raw_result, agent=agent, request=request)
            timing["conversation_call_ms"] = _emit_request_timing(request, "conversation_call", conversation_started)
            timing["run_budget"] = self.ledger.accounting()
            return raw_result, agent, timing
        finally:
            _cleanup_agent_ready(agent_ready_cleanup, request)

    def converse_under_wall(
        self, max_wall_seconds: float, agent_ready_cleanup: Any
    ) -> tuple[Any, Any, dict[str, Any]]:
        request, agent, timing = self.request, self.agent, self.timing
        wall_checkpoint = self.wall_checkpoint
        expired = Event()
        wall_checkpoint.bind(agent)
        timers = self.start_wall_timers(max_wall_seconds, expired)
        try:
            conversation_started = time.perf_counter()
            raw_result = _run_conversation_with_usage_ledger(agent, self.conversation_kwargs())
            _attach_model_input_observability(raw_result, agent=agent, request=request)
            timing["conversation_call_ms"] = _emit_request_timing(request, "conversation_call", conversation_started)
        except BaseException:
            timing["conversation_call_ms"] = _emit_request_timing(request, "conversation_call", conversation_started, status="failed")
            if expired.is_set():
                raise self.wall_exceeded(max_wall_seconds)
            raise
        finally:
            for timer in timers:
                timer.cancel()
            _cleanup_agent_ready(agent_ready_cleanup, request)
        if expired.is_set():
            raise self.wall_exceeded(max_wall_seconds)
        # The checkpoint fired and the turn still landed a reply: hand the
        # caller the typed provenance so it settles the turn as a
        # budget-ended turn instead of a plain completion.
        if wall_checkpoint.engaged and isinstance(raw_result, dict):
            raw_result["wall_budget_checkpoint"] = wall_checkpoint.summary()
        timing["run_budget"] = self.ledger.accounting()
        return raw_result, agent, timing

    def start_wall_timers(self, max_wall_seconds: float, expired: Event) -> list[Timer]:
        """Arm the graceful checkpoint (when the budget supports one) and the hard wall."""

        wall_checkpoint = self.wall_checkpoint
        timers: list[Timer] = []
        # The graceful checkpoint opens BEFORE the hard wall (by the
        # reserved window). The hard wall below stays armed at the real
        # deadline as the last resort — it is no longer the first thing that
        # happens when a turn runs long.
        if wall_checkpoint.budget.supports_checkpoint:
            checkpoint_timer = Timer(
                wall_checkpoint.budget.seconds_until_checkpoint(),
                lambda: wall_checkpoint.engage(
                    trigger=turn_budget.CHECKPOINT_TRIGGER_TIMER
                ),
            )
            checkpoint_timer.daemon = True
            checkpoint_timer.start()
            timers.append(checkpoint_timer)
        timer = Timer(max_wall_seconds, lambda: self.interrupt_for_budget(max_wall_seconds, expired))
        timer.daemon = True
        timer.start()
        timers.append(timer)
        return timers

    def interrupt_for_budget(self, max_wall_seconds: float, expired: Event) -> None:
        expired.set()
        # Recorded where the bound actually FIRED (the timer thread), so
        # the accounting is already true by the time the main thread
        # raises. An ESCALATION: if the graceful checkpoint had already
        # opened, this replaces the `lands_turn` row with the hard kill
        # that followed it — both happened, and the kill is the fact.
        self.ledger.trip(
            RunBudgetKind.WALL,
            RunBudgetTripReason.WALL_CLOCK_EXCEEDED,
            consumed=self.wall_checkpoint.consumed_seconds(),
            detail=f"wall_seconds={max_wall_seconds:g}",
            enforcement=RunBudgetEnforcement.TRIPS_RUN,
        )
        agent = self.agent
        if hasattr(agent, "interrupt"):
            try:
                agent.interrupt("live run budget exceeded")
            except Exception:
                pass
        if self.request.progress_callback is not None:
            self.request.progress_callback(
                {
                    "type": "run.progress",
                    "phase": "runaway_warning",
                    "severity": "critical",
                    "step": "wall_clock_budget_exceeded",
                    "status": "failed",
                    "summary": f"Live run exceeded wall-clock budget: wall_seconds={max_wall_seconds:g}",
                }
            )

    def wall_exceeded(self, max_wall_seconds: float) -> RunBudgetExceeded:
        return RunBudgetExceeded(
            f"live run budget exceeded: wall_seconds={max_wall_seconds:g}",
            session_id=getattr(self.agent, "session_id", None),
            wall_budget=self.wall_checkpoint.summary(),
            run_budget=self.ledger.accounting(),
        )
