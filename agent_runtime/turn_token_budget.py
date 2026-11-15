"""A token and provider-call ceiling for ONE turn, checked between provider calls.

``profile_runner/budget.py``'s ``max_total_tokens`` / ``max_api_calls`` trip a run AFTER it
ends (``_enforce_result_budgets``): the money is already spent and the reply is lost. A turn
nobody attends — a Lens investigate (``lens/trigger.py``, design
``planned/lens-act-and-safe-investigate.md`` §3) — needs the bound DURING the turn, and a
landing instead of a trip. This module is that bound:

* the caller ARMS a :class:`TurnTokenBudget` for the turn's ``client_message_id``
  (:func:`armed_turn_budget`) before the turn runs;
* every provider call's usage reaches :func:`on_provider_call` (``usage_ledger.record_usage``
  calls it: the ``post_api_request`` hook and the Codex accrual site both go through there),
  which finds the running turn through the persona-turn binding — the agent carries the
  turn's ``client_message_id`` (``profile_runner.execute.bind_chat_root``) — so the budget is
  found whichever thread the turn runs on;
* at :data:`NUDGE_RATIO` of either limit the model is told, in-band, to write what it has
  (one steered ``runtime_notice``, code ``token_budget``);
* while the landing reply still fits under a limit (it would be the last call allowed, or one
  more working call plus the landing — each about the size of the last call — would pass the
  token limit) the turn LANDS: the same steer, then the agent's iteration budget is drained
  (``turn_budget.drain_iteration_budget``, the wall checkpoint's own mechanism), so no further
  tool round starts and upstream's finalizer takes one toolless call — the landing reply, which
  is the report.

**Not counted yet:** upstream's iteration-summary call (``agent/chat_completion_helpers.py::
handle_max_iterations``) fires no ``post_api_request``, so the landing reply's tokens reach no
fork reader — not this budget, not the turn record's ``provider_usage`` (seen live 2026-11-14:
4 requests, ``api_calls: 2``). The stop leaves room for it instead; counting it needs an upstream
seam (row ``RT-ITERATION-SUMMARY-CALL-UNCOUNTED``).

Unarmed turns pay one dict lookup per provider call. Nothing here raises into the turn.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

__layer__ = "policy"

__all__ = ["NUDGE_RATIO", "TurnTokenBudget", "armed_turn_budget", "on_provider_call", "usage_tokens"]

logger = logging.getLogger(__name__)

#: The share of a limit at which the turn is told to write what it has (design §3: 80 %).
NUDGE_RATIO = 0.8
#: Why a turn landed: its tokens or its provider calls.
STOPPED_BY_TOKENS = "tokens"
STOPPED_BY_CALLS = "calls"

NUDGE_TEXT = ("Token budget: {used} of {limit} used. Stop exploring; write what you have found so far as "
              "your report.")
LANDING_TEXT = ("Token budget spent ({used} of {limit}). No further tool calls will run: write your report now "
                "from what you have.")


def usage_tokens(usage: Any) -> int:
    """One call's total tokens: its ``total_tokens``, else prompt (input + cache) plus output."""

    def bucket(name: str) -> int:
        value = usage.get(name) if isinstance(usage, Mapping) else getattr(usage, name, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0

    total = bucket("total_tokens")
    if total:
        return total
    prompt = bucket("prompt_tokens") or (bucket("input_tokens") + bucket("cache_read_tokens")
                                         + bucket("cache_write_tokens"))
    return prompt + bucket("output_tokens")


@dataclass
class TurnTokenBudget:
    """One turn's ceiling. ``None`` for a limit means "no ceiling on that axis"."""

    token_limit: int | None = None
    call_limit: int | None = None
    tokens: int = 0
    calls: int = 0
    last_call_tokens: int = 0
    nudged: bool = False
    stopped_by: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def charge(self, tokens: int, *, calls: int = 1) -> None:
        """Count spend that did not come through a provider call of the turn (an auxiliary check)."""

        with self._lock:
            self.tokens += max(0, int(tokens))
            self.calls += max(0, int(calls))

    def observe(self, usage: Any, agent: Any) -> None:
        """One provider call finished: count it, then nudge or land the turn."""

        spent = usage_tokens(usage)
        with self._lock:
            self.tokens += spent
            self.calls += 1
            self.last_call_tokens = spent
            if self.stopped_by is not None:
                return  # the landing call itself: counted, nothing more to do
            stop = self._stop_reason()
            nudge = stop is None and not self.nudged and self._past_nudge()
            if stop is not None:
                self.stopped_by, self.nudged = stop, True
            elif nudge:
                self.nudged = True
            used, limit = self._headline()
        if stop is not None:
            _steer(agent, LANDING_TEXT.format(used=used, limit=limit), title="Token budget spent")
            from .turn_budget import drain_iteration_budget

            drain_iteration_budget(agent)
        elif nudge:
            _steer(agent, NUDGE_TEXT.format(used=used, limit=limit), title="Token budget checkpoint")

    def _stop_reason(self) -> str | None:
        # The landing reply is one more call. Stop while it still fits: by count, when it would be the
        # last call allowed; by tokens, when one more working call AND the landing (each about the size
        # of the last call) would pass the limit.
        if self.call_limit is not None and self.calls + 1 >= self.call_limit:
            return STOPPED_BY_CALLS
        if self.token_limit is not None and self.tokens + 2 * self.last_call_tokens >= self.token_limit:
            return STOPPED_BY_TOKENS
        return None

    def _past_nudge(self) -> bool:
        return ((self.token_limit is not None and self.tokens >= NUDGE_RATIO * self.token_limit)
                or (self.call_limit is not None and self.calls >= NUDGE_RATIO * self.call_limit))

    def _headline(self) -> tuple[str, str]:
        if self.token_limit is not None:
            return f"{self.tokens:,} tokens", f"{self.token_limit:,}"
        return f"{self.calls} calls", f"{self.call_limit}"

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {"tokens_used": self.tokens, "token_limit": self.token_limit, "calls_used": self.calls,
                    "call_limit": self.call_limit, "nudged": self.nudged, "stopped_by": self.stopped_by}


_ARMED: dict[str, TurnTokenBudget] = {}
_ARMED_LOCK = threading.Lock()


@contextmanager
def armed_turn_budget(client_message_id: str, budget: TurnTokenBudget) -> Iterator[TurnTokenBudget]:
    """Bind ``budget`` to the turn whose ``client_message_id`` this is, for the ``with`` block."""

    with _ARMED_LOCK:
        _ARMED[client_message_id] = budget
    try:
        yield budget
    finally:
        with _ARMED_LOCK:
            if _ARMED.get(client_message_id) is budget:
                del _ARMED[client_message_id]


def on_provider_call(usage: Any) -> None:
    """``usage_ledger.record_usage``'s tap: charge the running turn's armed budget, if any."""

    if not _ARMED or usage is None:
        return
    try:
        from .persona_turn_binding import current_persona_turn_agent

        agent = current_persona_turn_agent()
        key = str(getattr(agent, "_persona_chat_client_message_id", None) or "")
        with _ARMED_LOCK:
            budget = _ARMED.get(key) if key else None
        if budget is not None:
            budget.observe(usage, agent)
    except Exception:  # bookkeeping never fails a turn
        logger.debug("turn token budget tap failed", exc_info=True)


def _steer(agent: Any, text: str, *, title: str) -> None:
    steer = getattr(agent, "steer", None)
    if not callable(steer):
        return
    try:
        from .persona_chat_history.vocabulary import RUNTIME_NOTICE_TOKEN_BUDGET, runtime_notice

        steer(runtime_notice(text, title=title, code=RUNTIME_NOTICE_TOKEN_BUDGET))
    except Exception:
        logger.debug("turn token budget steer failed", exc_info=True)
