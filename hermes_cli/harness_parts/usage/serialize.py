"""Usage snapshots and envelopes as dicts: windows, lanes, the empty and the degraded envelope.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from .detect import USAGE_SCHEMA, _usage_provider_label

__layer__ = "policy"
__all__ = [
    "_USAGE_LANE_SUPPRESSING_STAGES",
    "_empty_usage_envelope",
    "_parse_usage_iso",
    "_serialize_usage_lane",
    "_serialize_usage_window",
    "_stamp_usage_degraded",
    "_unavailable_usage_lane",
    "_usage_iso",
    "_usage_lanes_suppressed",
]


def _usage_iso(dt) -> Optional[str]:
    """Serialize a datetime as ISO-8601 UTC, or None. Fail-open → None."""
    if dt is None:
        return None
    try:
        aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _serialize_usage_window(window) -> Optional[dict]:
    """Serialize one usage window into a lane-window dict, or return None to DROP
    the window.

    A non-finite ``used_percent`` (NaN / inf leaking out of an upstream fetcher)
    would serialize through ``emit_json`` — which is ``json.dumps`` with the
    default ``allow_nan=True`` — as the bare tokens ``NaN`` / ``Infinity``. That
    is invalid JSON, and the Launcher's strict parser drops the ENTIRE envelope
    into its failure state. So a non-finite percent drops just this window (never
    nulled, never clamped) rather than corrupting the whole payload. A genuinely
    unknown percent (``None``) is still a valid window and is kept.
    """
    used = window.used_percent
    if used is not None:
        try:
            used = float(used)
        except (TypeError, ValueError):
            # Non-numeric percent (shouldn't happen for a typed snapshot): treat
            # as unknown rather than crash the whole envelope.
            used = None
        else:
            if not math.isfinite(used):
                return None
    return {
        "label": window.label,
        # Raw float, not clamped — the console decides how to present overage.
        "used_percent": used,
        "reset_at": _usage_iso(window.reset_at),
        "detail": window.detail,
    }


def _unavailable_usage_lane(provider_id: str, reason: str, *, active: bool) -> dict:
    return {
        "provider": provider_id,
        "display_name": _usage_provider_label(provider_id),
        "active": active,
        "available": False,
        "plan": None,
        "source": None,
        "fetched_at": None,
        "windows": [],
        "details": [],
        "unavailable_reason": reason,
    }


def _serialize_usage_lane(provider_id: str, snapshot, *, active: bool) -> dict:
    """Serialize an AccountUsageSnapshot (or None) into a lane dict.

    A None snapshot on a detected login lane is emitted as ``no usage data``,
    which since the direct-dispatch change in [_fetch_usage_lane] means exactly
    ONE thing: the fetcher DECLINED — it returned without raising, e.g. no token
    resolved, or the provider exposes no usage surface. It no longer means
    "anything broke": a fetcher that raises now reaches
    [_fetch_usage_lanes]' handler and is reported by class or HTTP status.
    """
    if snapshot is None:
        return _unavailable_usage_lane(provider_id, "no usage data", active=active)
    return {
        "provider": provider_id,
        "display_name": _usage_provider_label(provider_id),
        "active": active,
        "available": bool(snapshot.available),
        "plan": snapshot.plan,
        "source": snapshot.source,
        "fetched_at": _usage_iso(snapshot.fetched_at),
        # A window whose percent is non-finite serializes to None and is dropped
        # here — an empty windows list on an otherwise-available lane is honest.
        "windows": [
            w
            for w in (_serialize_usage_window(win) for win in snapshot.windows)
            if w is not None
        ],
        "details": [str(d) for d in snapshot.details],
        "unavailable_reason": snapshot.unavailable_reason,
    }


#: The degrade stages that can have EATEN LANES — the discriminator
#: [_usage_lanes_suppressed] reads, and the ONE place that judgement is written.
#:
#: The full stage vocabulary is these four plus ``active_provider``, which is
#: deliberately absent here: a failed active-provider resolution suppresses no
#: lanes at all, so an envelope degraded only there may still carry an honest
#: empty lane list. Every stage name is a fixed literal chosen at the raising
#: seam, never derived from an exception, so it leaks nothing.
_USAGE_LANE_SUPPRESSING_STAGES: tuple[str, ...] = (
    "detect",
    "fetch",
    "build",
    "serialize",
)


def _stamp_usage_degraded(payload: dict, stage: str, exc: BaseException) -> dict:
    """Record ``degraded[stage] = <ExceptionClass>`` on a usage envelope.

    The same ``{unit: ExceptionClass}`` shape as ``block_errors`` on the
    provider-visibility payload (see [_record_visibility_block]) — one idiom for
    "this builder tried and failed", on both halves of the provider surface.

    Why it exists: ``lanes: []`` and ``active_provider: null`` were each carrying
    two meanings. Empty lanes meant "no signed-in providers" OR "a seam
    collapsed"; a null active provider meant "none selected" OR "the resolver
    threw". The renderer's positive claim ("no signed-in providers detected") was
    the visible lie — see [_render_account_usage_human], which now consults this
    field before making it.

    First cause wins (``setdefault``): a detector collapse routinely makes the
    seams after it collapse too, and the FIRST class is the one that explains the
    envelope. Class name only, never ``str(exc)``.
    """
    payload.setdefault("degraded", {}).setdefault(stage, type(exc).__name__)
    return payload


def _usage_lanes_suppressed(payload: dict) -> Optional[str]:
    """The exception class of a degrade that SUPPRESSED lanes, or None.

    Not every degrade suppresses: a failed ``active_provider`` resolution leaves
    lane collection untouched, so an envelope degraded only there may still
    carry a complete, honest, EMPTY lane list — and the "no signed-in providers"
    claim is legitimate. Only the stages in [_USAGE_LANE_SUPPRESSING_STAGES] can
    have eaten lanes.
    """
    degraded = payload.get("degraded")
    if not isinstance(degraded, dict):
        return None
    for stage in _USAGE_LANE_SUPPRESSING_STAGES:
        found = degraded.get(stage)
        if found:
            return str(found)
    return None


def _parse_usage_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _empty_usage_envelope(degraded: Optional[tuple[str, BaseException]] = None) -> dict:
    """Minimal, always-serializable ``hermes.account_usage/v1`` envelope with no
    lanes — the guaranteed fallback whenever a richer build or serialization step
    fails.

    ``degraded`` is the ``(stage, exception)`` that forced the fallback. It is
    optional only because a caller may genuinely have no cause to name; every
    caller that DOES have one passes it, because this envelope's empty ``lanes``
    is otherwise the same two-meaninged absence EG-6.1 removed everywhere else —
    and here it is emitted at the exact moment something is known to be broken.
    """
    payload: dict = {
        "schema": USAGE_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_provider": None,
        "lanes": [],
    }
    if degraded is not None:
        stage, exc = degraded
        _stamp_usage_degraded(payload, stage, exc)
    return payload
