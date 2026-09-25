"""Fetching usage lanes: one lane through its provider, every detected lane failure-isolated.
"""

from __future__ import annotations

import time
from typing import Optional

from .detect import UnknownUsageLaneError, _usage_failure_reason
from .providers import USAGE_LANES
from .serialize import _serialize_usage_lane, _unavailable_usage_lane

__layer__ = "lanes"
__all__ = [
    "_fetch_usage_lane",
    "_fetch_usage_lanes",
]


def _fetch_usage_lane(provider_id: str):
    """Fetch the account-usage snapshot for one provider (may return None or
    raise; callers isolate failures) through its ``providers.USAGE_LANES`` row.
    Nous flows through the portal-account + credits-snapshot path; the rest
    dispatch DIRECTLY to their per-provider fetcher. An id outside
    ``_USAGE_LANE_PROVIDERS`` raises ``UnknownUsageLaneError``.

    The direct dispatch is the point. ``agent.account_usage.fetch_account_usage``
    wraps all three shared fetchers in a blanket ``except Exception: return
    None`` (upstream-owned, `:884-902` — this module must not modify it), which
    erases the failure CLASS before ``_fetch_usage_lanes``' honest per-lane
    handler can report it. The None then serializes as the unfalsifiable
    ``no usage data``: a swallowed 401 rendered exactly like a provider that
    genuinely has nothing to say. Routing around the wrapper (the fork-boundary
    rule: route around upstream, don't patch it) lets the exception reach the
    handler that was built to name it.

    EG-0.3 REAPED THE FALL-THROUGH. This function used to end with
    ``return fetch_account_usage(provider_id)`` — dead code (EG-0.2 §3.2 proved
    the chain closed: the tuple is filter-only, and an unknown ``--provider``
    yields an empty candidate list that returns before dispatch) that was ALSO
    the one surviving route back into the swallow the paragraph above routed
    around. A typed raise is the replacement: the removal contract is a CODE row
    on ``fetch_account_usage`` scoped to ``hermes_cli`` in
    ``tests/agent_runtime/test_tombstone_registry.py``, so re-adding the call is
    loud by enumeration rather than by review.
    """
    lane = USAGE_LANES.get(provider_id)
    if lane is None:
        raise UnknownUsageLaneError(provider_id)
    return lane.fetch()


def _fetch_usage_lanes(
    candidates: list[str],
    *,
    active_provider: Optional[str],
    timeout: float,
) -> list[dict]:
    """Fetch every candidate lane CONCURRENTLY, bounded by an overall wall-clock
    deadline. Per-lane timeout/failure degrades to an unavailable lane carrying a
    CLASS-NAME-ONLY reason (never an exception message, which could leak a token
    or URL). Never blocks process exit on a hung fetch."""
    import concurrent.futures

    lanes_by_provider: dict[str, dict] = {}
    deadline = time.monotonic() + max(0.0, float(timeout))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(candidates)))
    try:
        future_map = {pool.submit(_fetch_usage_lane, p): p for p in candidates}
        for future, provider_id in future_map.items():
            active = provider_id == active_provider
            # Deadline-derived remaining bound: forwarding a shared deadline as
            # each future's result timeout keeps the OVERALL wall clock ≈timeout
            # even though the futures run concurrently.
            remaining = max(0.0, deadline - time.monotonic())
            try:
                snapshot = future.result(timeout=remaining)
            except concurrent.futures.TimeoutError:
                lanes_by_provider[provider_id] = _unavailable_usage_lane(
                    provider_id, "usage fetch failed (TimeoutError)", active=active
                )
            except Exception as exc:  # noqa: BLE001 — class/status only, fail-open
                lanes_by_provider[provider_id] = _unavailable_usage_lane(
                    provider_id,
                    _usage_failure_reason(exc),
                    active=active,
                )
            else:
                lanes_by_provider[provider_id] = _serialize_usage_lane(
                    provider_id, snapshot, active=active
                )
    finally:
        # Don't let the context-manager shutdown(wait=True) block on a hung
        # provider fetch — each underlying fetch already carries its own HTTP
        # timeout, and cancel_futures drops anything not yet started.
        pool.shutdown(wait=False, cancel_futures=True)
    return [lanes_by_provider[p] for p in candidates if p in lanes_by_provider]
