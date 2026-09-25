"""``ProfileAgentRunner`` — admit MCP servers, execute one agent run, tear down;
moved whole in the MOVE (ruling Q8), its ``_execute_agent_run`` becomes
``execute.AgentRunExecution`` in the CHANGE (the class delegates each run to it).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from agent_runtime.run_budget import (
    RunBudgetLedger,
)

from agent_runtime.profile_runner.errors import (
    ProfileRunnerError,
    _ProviderErrorCapture,
)
from agent_runtime.profile_runner.models import (
    AgentRunRequest,
    AgentRunResult,
)
from agent_runtime.profile_runner.budget import (
    _emit_budget_pressure_warning,
    _enforce_result_budgets,
)
from agent_runtime.profile_runner.resident_actor import (
    _finish_resident_persona_chat_agent,
)
from agent_runtime.profile_runner.execute import AgentRunExecution
from agent_runtime.profile_runner.mcp_lane import (
    _on_mcp_budget_exhausted,
)
from agent_runtime.profile_runner.workdir import (
    _counted_agent_run,
    _validate_workdir,
)
from agent_runtime.profile_runner.status import (
    _binding_for_profile,
    _elapsed_ms,
    _emit_request_timing,
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
        _, _, profile_timing = AgentRunExecution(self, binding, request).run()
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
            raw_result, agent, profile_timing = AgentRunExecution(
                self,
                binding, request, ledger=ledger, provider_errors=provider_errors
            ).run()
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
