"""The parity envelope: slimming, eviction markers, size, age and the
root/profile identity stamps.
"""

from __future__ import annotations

import json
import time
import hashlib
from datetime import datetime

from hermes_time import now
from agent_runtime import paths
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.parity import PARITY_ENVELOPE_VERSION, events_watermark
from agent_runtime.resolution import (
    resolution_payload,
    resolve_runtime,
    suspect_default_root,
)
from agent_runtime.serde import to_jsonable

from agent_runtime.snapshot.context import SNAPSHOT_CONTRACT_VERSION
from agent_runtime.snapshot.warnings import (
    _event_summary_warnings,
    _parity_warnings,
    _redaction_observed,
)
from agent_runtime.snapshot.summaries import _safe_model_label, _safe_repo_scope_label

__layer__ = "stores"

__all__ = [
    "parity_envelope",
    "_projection_age_ms",
    "_runtime_profile_identity",
    "_runtime_root_identity",
    "_snapshot_payload_size",
]


def parity_envelope(data, *, build_started, last_event, completeness, drop_samples, recent_events=None, sections_ms=None, build_start_position=None):
    """The S0 observability envelope: provenance + completeness + parity warnings.

    Additive and self-describing — turns the snapshot's silent drops into reported
    data and dates the snapshot against the event log so a reader knows how far
    behind it is. See the snapshot-architecture brain note.
    """

    last_ts = getattr(last_event, "ts", None) if last_event is not None else None
    watermark = events_watermark(last_event_ts=last_ts, position=build_start_position)
    resolution = resolve_runtime()
    cfg = load_agent_runtime_config()
    warnings = _parity_warnings(data)
    warnings.extend(_event_summary_warnings(recent_events or []))
    if watermark.get("event_offset") is None:
        # The frame cannot date itself against the log. Riders must resync
        # rather than read the absent position as byte 0 (= "caught up").
        warnings.append(
            {
                "code": "event_offset_unknown",
                "detail": (
                    "the event log's end offset could not be read, so this frame carries no "
                    "source position; watermark-gated consumers must resync instead of resuming "
                    f"({watermark.get('event_offset_error') or 'unreadable'})"
                ),
            }
        )
    if suspect_default_root(resolution):
        warnings.append(
            {
                "code": "suspect_default_root",
                "detail": "runtime root resolved through the default layer, but no store marker directories (persona_instances/, sessions/, agents/) exist; check runtime-root pins",
            }
        )
    return {
        "envelope_version": PARITY_ENVELOPE_VERSION,
        # The contract-version LEDGER (every bump and every KEPT ruling, 44 → 54,
        # with the two-part rule that decides them) is in
        # docs/agent-runtime-harness/02-runtime-data-and-shapes.md § "The contract
        # version ledger" — relocated there by lane R3 (rule 7); the number is
        # SNAPSHOT_CONTRACT_VERSION in snapshot/context.py.
        "contract_version": SNAPSHOT_CONTRACT_VERSION,
        "generated_at": data.get("generated_at"),
        "redaction_mode": getattr(cfg, "redaction_mode", "strict"),
        "redaction_observed": _redaction_observed(data),
        "build_ms": int(max(0.0, (time.perf_counter() - build_started)) * 1000),
        # Additive per-section wall-time breakdown (ms) alongside build_ms — a
        # small, stable, lowercase-keyed dict so a reader can see where a slow
        # build spent its time. Held BY REFERENCE so the caller can record the
        # parity section's own duration after this envelope is assembled.
        "sections_ms": sections_ms if sections_ms is not None else {},
        "snapshot_bytes": _snapshot_payload_size(data),
        "event_log_bytes": int(watermark.get("event_offset") or 0),
        "projection_age_ms": _projection_age_ms(last_ts),
        "watermark": watermark,
        "runtime_root": _runtime_root_identity(),
        "resolution": resolution_payload(resolution),
        "profile": _runtime_profile_identity(),
        "capabilities": [
            "operator_capabilities",
            "server_minted_chat_sessions",
        ],
        "freshness": {
            "state": "fresh",
            "stale_after_seconds": 30,
            "generated_at": data.get("generated_at"),
        },
        "completeness": completeness,
        "drops": drop_samples,
        "warnings": warnings,
    }


def _snapshot_payload_size(data) -> int:
    try:
        return len(json.dumps(to_jsonable(data), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0


def _projection_age_ms(last_event_ts) -> int | None:
    if last_event_ts is None:
        return None
    try:
        if isinstance(last_event_ts, datetime):
            ts = last_event_ts
        else:
            text = str(last_event_ts)
            ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
        current = now()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=current.tzinfo)
        return max(0, int((current - ts.astimezone(current.tzinfo)).total_seconds() * 1000))
    except Exception:
        return None


def _runtime_root_identity() -> dict:
    text = str(paths.store_root()).replace("\\", "/")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return {
        "fingerprint": digest,
        "label": _safe_repo_scope_label(text),
    }


def _runtime_profile_identity() -> dict:
    try:
        from ..profile_context import active_profile_name

        name = active_profile_name()
    except Exception:
        name = None
    safe = _safe_model_label(str(name)) if name else None
    return {"name": safe or "default"}
