"""The MCP admission lane's in-run notices: the steer notice and the
budget-exhausted callback and receipt.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.run_budget import RunBudgetKind, RunBudgetLedger, RunBudgetTripReason

from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "lanes"

__all__ = [
    "_emit_mcp_budget_exhausted",
    "_on_mcp_budget_exhausted",
    "_steer_mcp_admission_notice",
]


def _steer_mcp_admission_notice(agent: Any, request: AgentRunRequest, outcome: Any) -> bool:
    """In-band backstop for admission failures the turn's ENVELOPE could not carry.

    Design §D3 says the agent's own turn context must state a denial, and the
    guaranteed lane for that is the runtime-context envelope's volatile tail —
    rendered before the turn by the mission-chat command, which is why it can
    only carry RESOLUTION-time denials (``mcp_admission_disabled``,
    ``mcp_server_not_configured``, the machine-roots codes).

    EXECUTION-time degradations (``mcp_admission_timeout``,
    ``mcp_admission_lane_busy``, and "admitted but did not register") are only
    known here, after that envelope was sealed. They ride ``agent.steer`` — the
    same in-band lane ``turn_budget``'s checkpoint nudge uses, appended to the
    next tool result — so an agent that starts reaching for tools it does not
    have is told why on its next iteration instead of improvising. An agent that
    calls no tool never needed them.
    """

    if outcome is None or not getattr(outcome, "degraded", False):
        return False
    steer = getattr(agent, "steer", None)
    if not callable(steer):
        return False
    from ..mcp_admission import render_mcp_admission_line

    # ``admission=None`` on purpose: only the EXECUTION half belongs here. The
    # policy half is already on this turn's envelope, and repeating it in a
    # second voice teaches the model to discount both.
    line = render_mcp_admission_line(None, outcome=outcome)
    if not line:
        return False
    try:
        steer(f"[harness] {line.removeprefix('- ')}")
    except Exception:  # pragma: no cover - a notice must never fail a turn
        return False
    return True


def _on_mcp_budget_exhausted(
    request: AgentRunRequest,
    denial: Any,
    snapshot: dict[str, Any],
    *,
    ledger: RunBudgetLedger | None = None,
) -> None:
    """First refusal of an admitted MCP call: record it, then tell the operator.

    Fires once per run (``_metered_handler`` gates on ``refused == 1``) from the
    dispatching thread. The ledger record is what makes a refusal readable from
    the run record afterwards — the refusal itself only ever reached the agent's
    tool result and one progress warning, both of which are gone by the time
    anyone asks "why did that turn stop driving the launcher?".
    """

    if ledger is not None:
        try:
            ledger.trip(
                RunBudgetKind.MCP_CALLS,
                RunBudgetTripReason.MCP_CALLS_EXHAUSTED,
                consumed=(snapshot or {}).get("spent"),
                detail=getattr(denial, "code", None) or None,
            )
        except Exception:  # pragma: no cover - accounting must never fail a tool call
            pass
    _emit_mcp_budget_exhausted(request, denial, snapshot)


def _emit_mcp_budget_exhausted(request: AgentRunRequest, denial: Any, snapshot: dict[str, Any]) -> None:
    """Operator-facing half of ``mcp_admission_budget_exhausted``. Never raises.

    Fires ONCE per run, on the first refused call, from whichever thread
    dispatched the tool. It is deliberately a ``run.progress`` WARNING and not an
    interrupt: the agent keeps its non-MCP tools and can still land a reply, and
    a turn that lands honestly beats a turn that dies at the bound.
    """

    callback = request.progress_callback
    if callback is None:
        return
    try:
        callback(
            {
                "type": "run.progress",
                "phase": "mcp_admission",
                "severity": "warning",
                "step": "mcp_admission_budget_exhausted",
                "status": "warning",
                "summary": (
                    "MCP call budget exhausted "
                    f"({snapshot.get('spent')}/{snapshot.get('limit')} admitted call(s)); "
                    "further MCP calls are refused for this turn."
                ),
                "mcp_call_budget": dict(snapshot),
                "mcp_admission": {"denied": [denial.row()]},
            }
        )
    except Exception:  # pragma: no cover - accounting must never fail a tool call
        return
