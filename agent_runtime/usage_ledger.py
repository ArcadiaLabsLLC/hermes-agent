"""Per-call usage ledger for one persona turn — Mission Control's context budget.

The budget needs the FIRST call's ``prompt_tokens`` (the assembled context,
tool schemas included), which the cumulative ``session_*`` counters cannot
answer. The persona runner binds a list around ``run_conversation``
(:func:`bind_usage_ledger`); the eternia-harness plugin's ``post_api_request``
hook appends one row per API call (:func:`on_post_api_request`), reading the
token buckets upstream already puts on that hook. Nothing is recorded when no
ledger is bound, so the hook costs nothing outside a persona turn.

The Codex app-server path never fires ``post_api_request``; its accrual site in
``agent/codex_runtime.py`` calls :func:`record_usage` directly.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# ``max_iterations`` bounds an agent turn at 90 calls; the cap only guards a
# ledger bound around something longer-lived.
USAGE_LEDGER_MAX_ROWS = 256

_FIELDS = (
    "prompt_tokens", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
)

_LEDGER: ContextVar[list[dict[str, Any]] | None] = ContextVar("agent_runtime_usage_ledger", default=None)


@contextmanager
def bind_usage_ledger() -> Iterator[list[dict[str, Any]]]:
    """Collect this context's per-call usage rows into the yielded list."""
    rows: list[dict[str, Any]] = []
    token = _LEDGER.set(rows)
    try:
        yield rows
    finally:
        _LEDGER.reset(token)


def _bucket(usage: Any, field: str) -> int:
    value = usage.get(field) if isinstance(usage, Mapping) else getattr(usage, field, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def record_usage(usage: Any) -> None:
    """Append one row (a token-bucket mapping or a ``CanonicalUsage``) to the bound ledger."""
    rows = _LEDGER.get()
    if rows is None or usage is None or len(rows) >= USAGE_LEDGER_MAX_ROWS:
        return
    rows.append({"call_index": len(rows) + 1, **{field: _bucket(usage, field) for field in _FIELDS}})


def on_post_api_request(usage: Any = None, **_context: Any) -> None:
    """``post_api_request`` hook: the call's normalized token buckets become a ledger row."""
    record_usage(usage)
