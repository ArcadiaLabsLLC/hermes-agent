"""The operator chat's turn policy, run by the serve's one turn engine (``tui_gateway``).

Row ``RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT`` (owner 2026-11-21: "Yes, fold and
delete"); plan ``docs/agent-runtime-harness/planned/operator-chat-on-the-gateway-engine-2026-11-21.md``.
A Mission Control chat turn is the engine's turn: ``prompt.submit`` on the chat's in-process gateway
session (``agent_runtime.operator_gateway_turn``). What the operator lane decides about that turn is this
module's :class:`OperatorTurn`, called from the engine's two fork seams:

* agent build — the gateway's ``agent_factory._make_agent`` asks ``worker_app_functions.operator_agent``,
  which builds through :meth:`OperatorTurn.construct_agent` and :func:`build_agent` (the one builder of an
  operator chat's agent);
* the turn — the gateway's turn thread calls the session agent's ``run_conversation``, whose door runs
  :meth:`OperatorTurn.converse` around the real call (the persona's profile scope must be the innermost
  one, inside the gateway's own profile binding, which ``worker_app_functions.bind`` runs before).

One object per turn. :meth:`acquire` opens or reuses the chat's gateway session before the submit;
:meth:`converse` runs on the engine's turn thread; :meth:`prewarm` opens the session before a chat's first
message. The per-turn phases are the old ``AgentRunExecution``'s, in the same order with the same comments:
``scopes`` (the whole-run scope stack, the root lock first) -> ``resolve_runtime`` ->
``arm_wall_checkpoint`` -> ``admit_mcp`` -> ``build_turn_state`` -> the session's agent ->
``bind_chat_root`` -> the conversation, unbounded or under the wall.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import logging
from threading import Event, Timer
import time
from typing import Any

from agent_runtime import idle_turn_keeper, live_turns, turn_budget
from agent_runtime._upstream_doors import sanitize_surrogates
from agent_runtime.first_turn_warmup import warm_first_turn_paths
from agent_runtime import operator_turn_runtime
from agent_runtime.operator_turn_runtime import (
    _FIRST_TURN_STORE_STEPS,
    _blocked_tool_names_for_run,
    _cleanup_agent_ready,
    _enabled_toolsets_for_run,
    _local_engine_construction_kwargs,
    _local_engine_prewarm_scope,
    _notify_agent_ready,
    _qa_silence,
    _run_conversation_with_usage_ledger,
    _run_transport,
)
from agent_runtime.prewarmed_system_prompt import stash_prewarmed_system_prompt
from agent_runtime.turn_lock_wait import log_root_lock_wait
from agent_runtime.profile_context import PersonaProfileBinding, persona_profile_context
from agent_runtime.provider_credential_source import refuse_an_unusable_chosen_credential
from agent_runtime.run_budget import (
    UNIT_CALLS,
    UNIT_SECONDS,
    RunBudgetEnforcement,
    RunBudgetKind,
    RunBudgetLedger,
    RunBudgetTripReason,
)
from agent_runtime.serde import positive_float, positive_int
from agent_runtime.tool_blocks import bound_tool_block
from agent_runtime.profile_runner.budget import WallBudgetCheckpoint, _ToolBudgetGuard
from agent_runtime.profile_runner.errors import PrewarmYielded, RunBudgetExceeded, _NO_WALL_BUDGET_SECONDS
from agent_runtime.profile_runner.mcp_lane import _steer_mcp_admission_notice
from agent_runtime.profile_runner.model_input_observability import (
    _apply_chat_compaction_threshold,
    _attach_model_input_observability,
)
from agent_runtime.profile_runner.models import AgentRunRequest
from agent_runtime.profile_runner.progress import ToolFinishJoin, _progress_adapter
from agent_runtime.profile_runner.status import _emit_request_timing, _profile_status_callback
from agent_runtime.profile_runner.workdir import (
    _agent_workdir,
    _posix_process_home,
    _workspace_turnstile,
    root_run_lock,
)

__layer__ = "lanes"

__all__ = [
    "OperatorTurn",
    "_finish_resident_persona_chat_agent",
    "_prepare_resident_persona_chat_agent",
    "_sanitized_user_message_text",
    "build_agent",
    "log_turn_effort",
    "stage_persona_chat_user_row_marker",
    "turn_reasoning_config",
]

_logger = logging.getLogger(__name__)


# ── the resident actor's turn-local state ───────────────────────────────────

def _prepare_resident_persona_chat_agent(agent: Any, turn_state: dict[str, Any]) -> None:
    """Refresh turn-scoped state without erasing native compressor memory.

    ``turn_state`` is the per-turn values resolved from the REQUEST (see
    ``_execute_agent_run``), not read back off a freshly constructed agent. That
    distinction is the whole of T3: the seven values below are the only thing a
    resident actor ever wanted from the candidate, and building a ~1.5 s agent to
    carry them across — then discarding it — was the cost of the warm lane.
    """

    for name, value in turn_state.items():
        if hasattr(agent, name):
            setattr(agent, name, value)
    for name in (
        "session_prompt_tokens", "session_completion_tokens", "session_total_tokens",
        "session_api_calls", "session_input_tokens", "session_output_tokens",
        "session_cache_read_tokens", "session_cache_write_tokens",
        "session_reasoning_tokens", "session_estimated_cost_usd", "_api_call_count",
    ):
        if hasattr(agent, name):
            setattr(agent, name, 0.0 if name.endswith("cost_usd") else 0)
    for name, value in (
        ("_stream_callback", None), ("_interrupt_requested", False),
        ("_interrupt_reason", None), ("_current_api_request_id", ""),
        ("_current_turn_id", None), ("_current_task_id", None),
    ):
        if hasattr(agent, name):
            setattr(agent, name, value)


def _finish_resident_persona_chat_agent(agent: Any) -> None:
    """Detach every turn-local handle while preserving conversation state."""

    for name in (
        "status_callback",
        "tool_progress_callback",
        "tool_start_callback",
        "tool_complete_callback",
        "clarify_callback",
        "_stream_callback",
    ):
        if hasattr(agent, name):
            setattr(agent, name, None)
    for name, value in (
        ("_interrupt_requested", False),
        ("_interrupt_reason", None),
        ("_current_api_request_id", ""),
        ("_current_turn_id", None),
        ("_current_task_id", None),
        ("_persona_chat_client_message_id", None),
        ("_persona_chat_turn_id", None),
        ("_pending_cli_user_message", None),
    ):
        if hasattr(agent, name):
            setattr(agent, name, value)


def _sanitized_user_message_text(text: str) -> str:
    """The prologue's own view of this turn's clean user text.

    ``build_turn_context`` sanitizes surrogates BEFORE comparing the staged
    message below, so an unsanitized copy of a surrogate-bearing message would
    silently fail the match and drop the marker. Falls back to the raw text if
    the upstream helper ever moves — a no-op for every non-surrogate message.
    """

    try:
        return sanitize_surrogates(text)
    except Exception:  # pragma: no cover - upstream helper relocated, or defensive
        return text


def stage_persona_chat_user_row_marker(
    agent: Any, request: AgentRunRequest
) -> dict[str, Any] | None:
    """Stage this turn's user-message dict so its NATIVE row carries a marker.

    Since native session continuity landed, the mission-chat lane no longer
    appends the incoming operator row itself — the runtime persists it as part
    of the turn. ``build_turn_context`` adopts an already-staged
    ``_pending_cli_user_message`` whose clean text matches this turn's message,
    appends THAT dict as the turn's user message, and preserves every extra key
    on it; the session flush then writes ``finish_reason=msg.get(
    "finish_reason")`` onto the persisted row. Staging here is therefore the one
    seam where a fork-owned lane can TYPE the row the runtime writes — no second
    write, no duplicate row, and the model's prompt is untouched.

    Always writes the attribute: a stale dict left on a RESIDENT chat agent
    would otherwise be adopted by a later turn. No marker (every operator/CLI
    send) clears it, and the turn behaves exactly as it did before attribution
    existed. Returns the staged dict, or ``None`` when nothing was staged.
    """

    marker = getattr(request, "persona_chat_user_finish_reason", None)
    if (
        not marker
        # The retry lane reuses a row that is already durable (and already
        # carries the marker from the attempt that wrote it); re-staging would
        # be a no-op the prologue never reads.
        or request.reuse_current_user_message
        or not isinstance(request.user_message, str)
    ):
        agent._pending_cli_user_message = None
        return None
    staged = {
        "role": "user",
        "content": _sanitized_user_message_text(request.user_message),
        "finish_reason": str(marker),
    }
    agent._pending_cli_user_message = staged
    return staged


def turn_reasoning_config(request: AgentRunRequest, model: str | None) -> dict | None:
    """The instance's effort when the request carries one, else the ACTIVE profile's
    ``agent.reasoning_effort`` (per-model override first) — the chokepoint every
    upstream surface uses. Before this, a run without an instance effort passed
    nothing and the codex transport sent its own ``medium`` whatever the profile said.
    Runs inside the persona's profile scope, so ``load_config`` is that profile's.
    The resolution itself is :func:`agent_runtime.persona_chat_session.reasoning_config_for`
    (the stores layer, which the effective-model payload reads too)."""

    from agent_runtime.persona_chat_session import reasoning_config_for

    return reasoning_config_for(request.reasoning_effort, model)


def log_turn_effort(request: AgentRunRequest, agent: Any, *, reused: bool) -> None:
    """Receipt the reasoning effort this run's agent will send, and where it came from."""

    from agent_runtime.persona_chat_session import TURN_EFFORT_RECEIPT, reasoning_effort_label

    model = getattr(agent, "model", None) or request.model
    effort = reasoning_effort_label(getattr(agent, "reasoning_config", None))
    source = "instance" if request.reasoning_effort else ("profile" if effort else "default")
    actor = "prewarm" if request.prewarm_only else ("reused" if reused else "built")
    _logger.info(TURN_EFFORT_RECEIPT, request.root_chat_session_id or request.session_id or "-",
                 request.turn_id or "-", model or "-", request.reasoning_effort or "-",
                 effort or "-", source, actor)


# ── the one builder of an operator chat's agent ─────────────────────────────

def build_agent(factory: Any = None, **kwargs: Any) -> Any:
    """An operator chat's agent: upstream's ``AIAgent`` with the operator lane's construction policy.

    The engine's agent build for an operator session reaches here (``operator_gateway_turn.construct`` ->
    :meth:`OperatorTurn.construct_agent`). ``factory`` is an injected stand-in (a test's fake), which
    receives the lane's keyword arguments as they are; None is upstream's ``AIAgent``.
    """

    if factory is not None:
        return factory(**kwargs)
    from run_agent import AIAgent
    from agent_runtime.checkpoint_config import checkpoint_constructor_kwargs

    # ``cache_scope_id`` is a fork-runtime, header-only codex cache-scope hint —
    # NOT part of the upstream AIAgent constructor. Pop it before construction so
    # the upstream signature is untouched, then apply it as an attribute the
    # codex build seam reads via ``getattr(agent, "cache_scope_id", None)``. It
    # never participates in session/transcript loading.
    cache_scope_id = kwargs.pop("cache_scope_id", None)
    # The run's blocked tools are not an upstream constructor parameter either: the
    # agent is pruned once here, and the wire and the call are guarded by the
    # eternia-harness plugin against the block the run binds (agent_runtime.tool_blocks).
    blocked_tool_names = kwargs.pop("blocked_tool_names", None)
    # The chat lane's per-persona defer (agent_runtime.chat_lane_defer) is not one either:
    # the eager list is re-assembled with the persona's names deferred, BEFORE the block is
    # pruned, since the re-assembly starts from the lane's unpruned definitions.
    chat_lane_defer_tools = kwargs.pop("chat_lane_defer_tools", None)
    agent = AIAgent(**{**checkpoint_constructor_kwargs(), **kwargs})
    if cache_scope_id:
        agent.cache_scope_id = cache_scope_id
    # The tool form has one owner (agent_runtime.chat_lane_tool_form, settled in the
    # eternia-harness pre_llm_call hook): upstream's between-turns MCP refresh is switched off
    # through its own per-agent door; the owner lands this run's admitted MCP scope instead.
    agent._skip_mcp_refresh = True
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer

    apply_chat_lane_defer(agent, chat_lane_defer_tools, blocked=blocked_tool_names)
    return agent


# ── one turn, phase by phase ───────────────────────────────────────────────

class OperatorTurn:
    """One Mission Control chat turn's policy on the engine, in named phases (program rule 17).

    Was ``profile_runner.execute.AgentRunExecution`` (the operator chat's own turn host, which ran the
    conversation itself or, since F1, inside the engine's turn through a second execution). Now one object
    per turn, and the engine runs the turn: :meth:`acquire` gets the chat's gateway session before the
    submit, the engine's agent build calls :meth:`construct_agent`, and the engine's turn thread calls
    :meth:`converse` through the session agent's door (``operator_gateway_turn``).
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
        #: Set once the runtime is resolved: the turn's converse reuses the acquisition's answer
        #: (one resolve per turn).
        self._resolved = False
        #: Set when the conversation's wall timers are torn down (``converse_under_wall``).
        self._wall_closed = False

    # ── the turn ────────────────────────────────────────────────────────────

    def acquire(self) -> Any:
        """The chat's actor (its gateway session's agent), opened or reused under the turn's scopes,
        without conversing: the caller then submits the turn to that session. The acquisition's
        bounds are its own (a scratch ledger); the turn declares its bounds once, in :meth:`converse`."""

        with self.scopes("acquire") as mcp_scope:
            self.mcp_scope = mcp_scope
            refuse_an_unusable_chosen_credential(self.request)
            self.prepare(RunBudgetLedger())
            self.acquire_session()
            _finish_resident_persona_chat_agent(self.agent)
            return self.agent

    def prewarm(self) -> tuple[Any, Any, dict[str, Any]]:
        """Open the chat's gateway session before its first message (no turn runs)."""

        with self.scopes("prewarm") as mcp_scope:
            self.mcp_scope = mcp_scope
            self.yield_point("lock_acquired")
            refuse_an_unusable_chosen_credential(self.request)  # review w1118a.69 D1, before any token
            self.prepare(self.ledger, yield_points=True)
            self.acquire_session()
            log_turn_effort(self.request, self.agent, reused=bool(self.timing.get("resident_actor_reused")))
            return self.finish_prewarm()

    def converse(self, agent: Any) -> tuple[Any, Any, dict[str, Any]]:
        """The turn on the chat's actor ``agent``: on the engine's turn thread, inside the door
        (``operator_gateway_turn``), or inline on a turn the engine already runs for this chat."""

        with self.scopes("converse") as mcp_scope:
            self.mcp_scope = mcp_scope
            refuse_an_unusable_chosen_credential(self.request)  # review w1118a.69 D1, before any token
            self.prepare(self.ledger)
            self.adopt_actor(agent)
            log_turn_effort(self.request, self.agent, reused=bool(self.timing.get("resident_actor_reused")))
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
                request=self.request,  # the card's folder and asker (RT-RUNNING-WORK-ROWS-SAY-WHO-ASKED-…)
            ))
            idle_turn_keeper.note_active_agent(self.agent)  # h-idle-turn: the chat whose socket stays warm
            agent_ready_cleanup = _notify_agent_ready(self.request, self.agent)
            max_wall_seconds = positive_float(self.request.max_wall_seconds)
            if max_wall_seconds is None:
                return self.converse_unbounded(agent_ready_cleanup)
            return self.converse_under_wall(max_wall_seconds, agent_ready_cleanup)

    def prepare(self, ledger: RunBudgetLedger, *, yield_points: bool = False) -> None:
        """The phases before the agent: runtime, wall, MCP admission, the turn's callbacks."""

        self.resolve_runtime()
        self.arm_wall_checkpoint(ledger)
        if yield_points:
            self.yield_point("runtime_resolved")
        self.admit_mcp(ledger)
        if yield_points:
            self.yield_point("mcp_admitted")
        self.build_turn_state()

    def finish_prewarm(self) -> tuple[Any, Any, dict[str, Any]]:
        """A prewarm's tail, with the session's agent built; still under the scopes.

        No turn-scoped attributes, no compression threshold, no MCP steer notice, no ``agent_ready``
        callback and no conversation; the scopes unwind normally on the way out, so the admitted MCP
        scope is torn down while the root lock is still held, exactly as a turn's is.

        ``_finish_resident_persona_chat_agent`` detaches the (already empty) prewarm-local handles, so a
        resident actor is handed to its first real turn in the same state a completed turn leaves it in.
        It runs on the yield path too: the actor is registered by then.

        h-turn1 A3: the first turn's system prompt is built HERE, under the same scopes, and adopted by
        that turn's ``_restore_or_build_system_prompt``. h-conn-pool: then the first turn's one-time
        process costs (spinner catalog, lazy imports, SDK headers), each step a yield point (h-turn-wait).
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
        """h-turn-wait: a prewarm holding its root lock stands down for a turn.

        Raises :class:`PrewarmYielded`; the scope stack unwinds (MCP teardown first)
        and the lock passes to the waiting turn. A no-op on a real run.
        """

        reason = self._prewarm_should_yield()
        if reason:
            raise PrewarmYielded(phase, reason, self.timing)

    @contextmanager
    def scopes(self, stage: str = "run"):
        """The whole-run scope stack; yields the run's MCP ``ExitStack``. ``stage`` names the step for
        the ``turn_root_lock_wait`` receipt."""

        request = self.request
        from agent_runtime.persona_chat_continuity import (
            chat_root_session_key_scope,
            tool_execution_scope,
        )
        from agent_runtime.terminal_envelope.records import terminal_envelope_scope
        from agent_runtime.skill_resolution import skill_runtime_scope
        from agent_runtime.session_controls import session_approval_scope

        with (
            # Run-serialization S5: a run starts only between workspace writers, then
            # holds ITS ROOT's lock — another chat root runs alongside it, including
            # while this one waits on an operator approval. Everything below binds
            # context-locally (the profile binding; the cwd in a terminal scope); the one
            # process write left is POSIX ``HOME``, serialized by its own lock.
            _workspace_turnstile(),
            root_run_lock(request.root_chat_session_id or request.tool_execution_scope_id,
                          holder="prewarm" if request.prewarm_only else "turn"),
            _posix_process_home(self.binding),
            persona_profile_context(self.binding, runtime_root=request.runtime_root),
            _local_engine_prewarm_scope(request),
            _agent_workdir(request.workdir),
            tool_execution_scope(request.tool_execution_scope_id),
            # Same identity, second consumer: the container scope above keys
            # sandbox reuse by the chat root; this one hands the SAME root to
            # tools.approval's session-key surface, so background spawns and
            # delegations from this run carry a session_key the completion
            # drain can resolve to a chat root (see chat_root_session_key_scope).
            chat_root_session_key_scope(request.tool_execution_scope_id),
            session_approval_scope(None if request.prewarm_only else request.root_chat_session_id,
                                   requested_by_session=request.requested_by_session,
                                   turn_key=request.client_message_id),
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
            # holds its root lock and is still inside persona_profile_context,
            # on the raised path as well as the returned one. Using a stack
            # rather than a try/finally keeps the (large) run body unindented.
            ExitStack() as mcp_scope,
        ):
            log_root_lock_wait(request, stage=stage)
            yield mcp_scope

    # ── phases before the agent exists ──────────────────────────────────────

    def resolve_runtime(self) -> None:
        request, timing = self.request, self.timing
        if self._resolved:
            # One resolve per turn: the turn converses on the runtime its actor was acquired for.
            return
        self._resolved = True
        try:
            runtime_started = time.perf_counter()
            # Read through the module: the memo's one owner, and the seam a test patches.
            self.runtime = operator_turn_runtime._resolve_request_runtime(request, timing)
            timing["runtime_resolve_ms"] = _emit_request_timing(request, "runtime_resolve", runtime_started)
        except Exception:
            if self.runner._uses_default_agent_factory:
                raise
            self.runtime = {}
            timing["runtime_resolve_ms"] = _emit_request_timing(request, "runtime_resolve", runtime_started, status="failed")

    def arm_wall_checkpoint(self, ledger: RunBudgetLedger) -> None:
        request = self.request
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
                checkpoint_after_seconds=request.qa_checkpoint_after_seconds,
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

    def admit_mcp(self, ledger: RunBudgetLedger) -> None:
        # MCP admission. Inside persona_profile_context (so HERMES_HOME
        # already points at the persona's own profile) and before agent
        # construction (so the admitted tools exist in the registry by the
        # time the factory resolves tool definitions). Bounded and
        # non-raising: a capability probe must never be able to fail a turn,
        # so every degradation comes back as a typed row and the turn
        # continues on the fallback lane.
        request = self.request
        # A turn admits twice when its session is built (the build, then the turn on the engine): the
        # second finds the scope the first registered, and the turn's record keeps that it paid for one.
        registered_before = self.timing.get("mcp_admission_reused") == 0
        self.admission_outcome = self.runner._admit_mcp_servers(request, self.timing, ledger=ledger)
        if registered_before:
            self.timing["mcp_admission_reused"] = 0
        self.admitted_servers = self.admission_outcome.admitted if self.admission_outcome else ()
        if not self.admitted_servers:
            return
        # Declared only for a run that actually got MCP tools: a run with
        # nothing admitted has no MCP calls to bound. The MCP meter is
        # its own authority for the count, so the ledger READS it rather
        # than keeping a second tally that could disagree with the one
        # the refusal itself used.
        call_budget = getattr(self.admission_outcome, "call_budget", None)
        ledger.declare(
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
        if call_budget is not None:
            # Names this run to the metered handlers its tool threads call (S5): a
            # concurrent run of the same MCP scope charges its own binding, not this one.
            from agent_runtime.mcp_admission.resident import run_call_budget_scope

            self.mcp_scope.enter_context(run_call_budget_scope(call_budget))
        self.mcp_scope.callback(
            self.runner._release_mcp_admission,
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
        """Build the chat's agent for the engine's agent build (``operator_gateway_turn.construct``)
        and time it: the session's one construction."""

        construction_kwargs = _local_engine_construction_kwargs()

        request, runtime, runner = self.request, self.runtime, self.runner
        construct_started = time.perf_counter()
        built = build_agent(
            runner._agent_factory,
            provider=runtime.get("provider") or request.provider,
            model=runtime.get("model") or request.model or "",
            **_run_transport(request, runtime),
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
        self.apply_chat_speed(built)
        self.timing["agent_construct_ms"] = _emit_request_timing(
            request, "agent_construct", construct_started
        )
        return built

    def apply_chat_speed(self, agent) -> None:
        if not self.request.root_chat_session_id:
            return
        from agent_runtime.session_controls import apply_session_speed, resolved_session_controls

        controls = resolved_session_controls(self.request.root_chat_session_id,
            provider=self.runtime.get("provider") or self.request.provider,
            model=self.runtime.get("model") or self.request.model,
            **_run_transport(self.request, self.runtime))
        apply_session_speed(agent, controls)

    # ── phases with the agent ───────────────────────────────────────────────

    def bind_chat_root(self) -> None:
        request, agent = self.request, self.agent
        from agent_runtime.turn_checkpoints import TurnCheckpointRecorder
        manager = getattr(agent, "_checkpoint_mgr", None)
        if manager is not None:
            manager.lock_wait_budget = self.wall_checkpoint.budget.seconds_until_checkpoint
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
            from agent_runtime.config import mission_chat_compaction_threshold_tokens

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
        if request.user_image_paths and isinstance(request.user_message, str):
            from agent_runtime.operator_images import native_user_message

            conversation_kwargs["user_message"], conversation_kwargs["persist_user_message"] = native_user_message(
                request.user_message, request.user_image_paths)
        if request.stream_callback is not None:
            conversation_kwargs["stream_callback"] = request.stream_callback
        return conversation_kwargs

    def converse_unbounded(self, agent_ready_cleanup: Any) -> tuple[Any, Any, dict[str, Any]]:
        request, agent, timing = self.request, self.agent, self.timing
        try:
            _qa_silence(request, None)
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
            _qa_silence(request, expired)
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
            self._wall_closed = True  # a re-armed wall (``wall_timer_fired``) arms nothing after this
            for timer in list(timers):
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
        timer = Timer(max_wall_seconds, lambda: self.wall_timer_fired(max_wall_seconds, expired, timers, 0.0))
        timer.daemon = True
        timer.start()
        timers.append(timer)
        return timers

    def wall_timer_fired(self, max_wall_seconds: float, expired: Event, timers: list[Timer], credited: float) -> None:
        """The hard wall, less a dispatched turn's person-wait: a helper waiting on its lead's person
        (an approval card with no expiry) is not over budget for it (row
        ``RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS``). The timer re-arms for the
        wait not yet credited; any other turn's wait reads 0 and the wall fires as before."""

        from agent_runtime.session_controls import dispatched_person_wait_seconds

        if self._wall_closed:
            return
        waited = dispatched_person_wait_seconds(self.request.client_message_id)
        # MUTATION: fire the wall here regardless of ``waited`` and
        # test_the_turns_hard_wall_waits_out_a_person_wait reddens.
        if waited > credited + 0.05 and not expired.is_set():
            timer = Timer(waited - credited,
                          lambda: self.wall_timer_fired(max_wall_seconds, expired, timers, waited))
            timer.daemon = True
            timers.append(timer)
            timer.start()
            return
        self.interrupt_for_budget(max_wall_seconds, expired)

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

    # ── the chat's actor: its gateway session ───────────────────────────────

    def open_session(self) -> Any:
        """A new actor: the chat's gateway session, whose agent the engine builds through
        :meth:`construct_agent` (``operator_gateway_turn.open_actor``)."""

        from agent_runtime.operator_gateway_turn import open_actor

        return open_actor(self)

    def adopt_actor(self, agent: Any) -> None:
        """The engine's turn runs on ``agent``, the chat's actor: refresh it for this turn. The effort and
        the speed are per TURN, not per actor."""

        self.agent = agent
        _prepare_resident_persona_chat_agent(agent, self.turn_state)
        agent.reasoning_config = self.reasoning_kwargs.get("reasoning_config")
        self.apply_chat_speed(agent)
        # A turn the engine started for this chat (an inline delivery) acquired nothing: it found the actor.
        self.timing.setdefault("resident_actor_reused", 1)

    def acquire_session(self) -> None:
        """The chat's actor, built (a new gateway session) or reused from the resident registry."""

        from agent_runtime.persona_chat_identity import resolved_runtime_revision

        request, timing = self.request, self.timing
        if request.persona_chat_runtime_registry is None:
            self.agent = self.open_session()
            # This run BUILT its agent — there was no resident registry to
            # ask (the default: `persona_chat.hot_sessions_enabled` is off
            # unless the root config turns it on). That is a fact this branch
            # KNOWS, not an unknown, and writing it is what lets the turn record
            # carry `agent_init_cold=true` instead of dropping the qualifier
            # entirely. Absent-never-zero cuts both ways: a fact that was
            # established must not read as unestablished. Live proof
            # (2026-08-23): with hot sessions off, every turn record lacked
            # `agent_init_cold` while every one of those turns had paid full
            # cold construction.
            timing["resident_actor_reused"] = 0
            # Why nothing was reused: there was nothing to reuse from (RT-TURN-AGENT-INIT-COLD-ALWAYS-TRUE).
            timing["resident_registry_absent"] = 1
            return
        active_id = request.session_id or request.root_chat_session_id
        runtime_revision = resolved_runtime_revision(self.runtime)
        # The factory is now genuinely lazy: the registry calls it only
        # on a miss or a rebuild. On reuse nothing is constructed at all,
        # so `agent_construct_ms` is ABSENT rather than reporting the
        # cost of work that was thrown away — `resident_actor_reused`
        # says why, so the absence is typed, never silent.
        from agent_runtime.chat_session_writer import current_chat_session_writer_owner
        from agent_runtime.persona_chat_continuity.runtime_registry import OwnedResidentActor

        writer = getattr(self.runner, "_session_db", None)
        owner = current_chat_session_writer_owner()
        def owned_factory():
            if writer is None:
                return self.open_session()
            if owner is None:
                raise RuntimeError("resident constructor writer has no request owner")
            pin = owner.resident_pin(writer)
            try:
                return OwnedResidentActor(self.open_session(), pin)
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
