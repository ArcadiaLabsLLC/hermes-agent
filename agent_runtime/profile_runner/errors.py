"""The runner's errors (``ProfileRunnerError``, ``RunBudgetExceeded``) and the
provider-error capture a run wraps its conversation in.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any

from agent_runtime.profile_runner.models import _positive_int

__layer__ = "models"

__all__ = [
    "ProfileRunnerError",
    "RunBudgetExceeded",
    "_NO_WALL_BUDGET_SECONDS",
    "_ProviderErrorCapture",
    "_capture_provider_errors",
]


class ProfileRunnerError(RuntimeError):
    """Raised before agent construction when a profile-bound run cannot start.

    ...and, at ``_run``'s tail, when the conversation itself came back failed.
    That second lane is why ``provider_error`` exists: the transport collapses a
    provider SDK exception into ``AIAgent._summarize_api_error`` TEXT several
    frames below and returns a result dict, so by the time this class is raised
    the status code, the error body and its ``reason``/``reset_at`` are gone and
    ``str(exc)`` is all that survives. ``mission_chat_outcome.provider_refusal``
    reads this attribute and nothing else; without it, telling a plan-quota 429
    from a dead socket would mean regexing the prose — a wire contract nobody
    wrote down and every provider is free to break.

    ``None`` means "no provider verdict is attached", never "the provider was
    fine": an unattached failure stays ambiguous downstream.
    """

    def __init__(self, message: str, *, provider_error: dict[str, Any] | None = None):
        super().__init__(message)
        self.provider_error = provider_error


class RunBudgetExceeded(ProfileRunnerError):
    """Raised when a live persona run exceeds its configured budget.

    ``wall_budget`` carries the typed budget projection when the WALL budget
    (not the api-call / token / read-search budgets) is what tripped, so the
    caller can settle the turn as ``budget_exhausted`` — a known, terminal
    outcome — instead of the ambiguous ``outcome_unknown``.

    ``run_budget`` carries the run's WHOLE budget accounting block (see
    ``run_budget.RunBudgetLedger.accounting``) — the same block the completed
    path writes into ``profile_timing``. Without it a tripped run is the one
    case where the accounting is unreadable after the fact, because the result
    that would have carried it is never returned.
    """

    def __init__(
        self,
        message: str,
        *,
        session_id: str | None = None,
        wall_budget: dict[str, Any] | None = None,
        run_budget: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.session_id = session_id
        self.wall_budget = wall_budget
        self.run_budget = run_budget


@dataclass(slots=True)
class _ProviderErrorCapture:
    """The last provider API error this RUN saw, with its typed context intact.

    Filled by wrapping the agent's own ``_extract_api_error_context`` — the one
    call the conversation loop already makes, on every API error, with the live
    SDK exception in hand. Wrapping rather than editing: that loop is upstream
    core and this runner is fork-owned, so the capture is installed around the
    conversation call and removed when it returns.

    ``summary`` is the capture's IDENTITY, not decoration. A run can survive an
    error (a 429 a retry or a credential rotation recovered) and then fail
    minutes later for an unrelated reason; attaching the recovered 429 to that
    failure would report a plan wall that is not there. So the block is handed
    over only when the terminal result's ``error`` string — produced by the same
    ``_summarize_api_error`` on the same object — equals what was captured.
    """

    status_code: int | None = None
    context: dict[str, Any] | None = None
    summary: str | None = None
    provider: str | None = None
    model: str | None = None

    def record(self, agent: Any, error: BaseException, context: Any) -> None:
        try:
            summary = agent._summarize_api_error(error)
        except Exception:
            summary = str(error)
        self.status_code = _positive_int(getattr(error, "status_code", None))
        self.context = dict(context) if isinstance(context, dict) else {}
        self.summary = summary
        self.provider = getattr(agent, "provider", None) or None
        self.model = getattr(agent, "model", None) or None

    def block_for(self, detail: str, raw: Any) -> dict[str, Any] | None:
        """The typed block for a terminal ``detail``, or ``None`` when that
        detail is not the error this capture saw."""

        if self.status_code is None or self.summary is None:
            return None
        if self.summary.strip() != str(detail).strip():
            return None
        context = self.context or {}
        block: dict[str, Any] = {"status_code": self.status_code}
        for key in ("reason", "message"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                block[key] = value.strip()
        if context.get("reset_at") not in (None, ""):
            block["reset_at"] = context["reset_at"]
        if self.provider:
            block["provider"] = self.provider
        if self.model:
            block["model"] = self.model
        # The harness's OWN classification of the same error, when the failing
        # lane recorded one. Read downstream only to keep an ambiguous 400
        # ambiguous — never to choose operator-facing copy.
        if isinstance(raw, dict):
            failure_reason = raw.get("failure_reason")
            if isinstance(failure_reason, str) and failure_reason.strip():
                block["failure_reason"] = failure_reason.strip()
        return block


@contextmanager
def _capture_provider_errors(agent: Any, capture: "_ProviderErrorCapture | None"):
    """Wrap ``agent._extract_api_error_context`` for the length of one run."""

    original = getattr(agent, "_extract_api_error_context", None)
    if capture is None or original is None:
        yield
        return
    had_own = "_extract_api_error_context" in getattr(agent, "__dict__", {})
    previous = agent.__dict__.get("_extract_api_error_context")

    def _recording(error, *args, **kwargs):
        context = original(error, *args, **kwargs)
        try:
            capture.record(agent, error, context)
        except Exception:
            # A diagnostic may never change a live turn's outcome.
            pass
        return context

    try:
        agent._extract_api_error_context = _recording
        yield
    finally:
        # Resident actors are REUSED across turns, so leaving the wrapper (and
        # its closure over this run's capture) installed would let one turn's
        # errors land in the next turn's block.
        if had_own:
            agent.__dict__["_extract_api_error_context"] = previous
        else:
            agent.__dict__.pop("_extract_api_error_context", None)


# Stand-in "budget" for runs that carry no wall budget at all. The checkpoint is
# still constructed (one unconditional shape for the tool-start gate) but with a
# deadline it can never reach, so it never engages and never arms a timer.
_NO_WALL_BUDGET_SECONDS = 3650.0 * 24 * 3600
