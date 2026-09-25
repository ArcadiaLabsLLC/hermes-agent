"""``hermes harness usage``: the account-usage envelope, its human render, and the verb.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from agent_runtime.cli_format import emit_json
from agent_runtime.clock import parse_iso
from agent_runtime.root_observability import attach_root_observability

from .detect import (
    DEFAULT_USAGE_TIMEOUT,
    USAGE_SCHEMA,
    _detect_usage_candidates,
    _resolve_active_provider_id,
    _usage_lane_scope,
)
from .lanes import _fetch_usage_lanes
from .serialize import (
    _empty_usage_envelope,
    _stamp_usage_degraded,
    _unavailable_usage_lane,
    _usage_lanes_suppressed,
)

__layer__ = "lanes"
__all__ = [
    "_cmd_usage",
    "_emit_usage_json",
    "_render_account_usage_human",
    "build_account_usage",
]


def build_account_usage(
    *,
    only_provider: Optional[str] = None,
    timeout: float = DEFAULT_USAGE_TIMEOUT,
) -> dict:
    """Build the ``hermes.account_usage/v1`` envelope: one lane per detected
    provider login (codex / anthropic / openrouter / nous), fetched concurrently
    under an overall wall-clock bound. Fail-open at every seam — worst case the
    envelope carries empty lanes AND a ``degraded`` map naming which seam gave
    way (EG-6.1: fail-open, but never fail-silent)."""
    payload: dict = {
        "schema": USAGE_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_provider": None,
        "lanes": [],
    }
    try:
        payload["active_provider"] = _resolve_active_provider_id()
    except Exception as exc:  # noqa: BLE001 — named, not swallowed
        _stamp_usage_degraded(payload, "active_provider", exc)
    active_provider = payload["active_provider"]
    try:
        candidates, detect_failures = _detect_usage_candidates(only_provider)
    except Exception as exc:  # noqa: BLE001 — named, not swallowed
        return _stamp_usage_degraded(payload, "detect", exc)
    if not candidates and not detect_failures:
        return payload
    fetched: list[dict] = []
    if candidates:
        try:
            fetched = _fetch_usage_lanes(
                candidates, active_provider=active_provider, timeout=timeout
            )
        except Exception as exc:  # noqa: BLE001 — named, not swallowed
            fetched = []
            _stamp_usage_degraded(payload, "fetch", exc)
    # Merge the fetched lanes with the detector-failed ones, back into the stable
    # `_USAGE_LANE_PROVIDERS` emission order: a lane whose DETECTOR raised holds
    # its natural slot in the Limits panel rather than being appended after the
    # healthy ones (or, as before EG-6.1, disappearing).
    lanes_by_provider = {lane["provider"]: lane for lane in fetched}
    for provider, reason in detect_failures.items():
        lanes_by_provider[provider] = _unavailable_usage_lane(
            provider, reason, active=provider == active_provider
        )
    payload["lanes"] = [
        lanes_by_provider[p]
        for p in _usage_lane_scope(only_provider)
        if p in lanes_by_provider
    ]
    return payload


def _render_account_usage_human(payload: dict) -> None:
    """Render the envelope as human lines, reusing the shared
    ``render_account_usage_lines`` per available lane."""
    from agent.account_usage import (
        AccountUsageSnapshot,
        AccountUsageWindow,
        render_account_usage_lines,
    )

    raw_degraded = payload.get("degraded")
    degraded = raw_degraded if isinstance(raw_degraded, dict) else {}
    active_label = payload.get("active_provider") or "(none)"
    if degraded.get("active_provider"):
        # "(none)" would be a claim about the operator's configuration; the
        # resolver never got far enough to make it.
        active_label = f"(unknown — resolution failed ({degraded['active_provider']}))"
    print(f"Active provider: {active_label}")
    lanes = payload.get("lanes") or []
    if not lanes:
        # THE claim this stage exists to fence. "no signed-in providers detected"
        # is a positive assertion about the operator's auth state, and it may be
        # printed ONLY when detection actually ran and found none. When a seam
        # that collects lanes gave way, the truth is that we do not know — so
        # state the degrade instead, naming the class.
        suppressed = _usage_lanes_suppressed(payload)
        if suppressed:
            print(f"No account-usage lanes: usage lanes unavailable ({suppressed}).")
            return
        print("No account-usage lanes (no signed-in providers detected).")
        return
    for lane in lanes:
        marker = " *" if lane.get("active") else ""
        print("")
        print(f"{lane.get('display_name') or lane.get('provider')}{marker}")
        if not lane.get("available"):
            print(f"  Unavailable: {lane.get('unavailable_reason') or 'no usage data'}")
            continue
        windows = tuple(
            AccountUsageWindow(
                label=w.get("label"),
                used_percent=w.get("used_percent"),
                reset_at=parse_iso(w.get("reset_at")),
                detail=w.get("detail"),
            )
            for w in lane.get("windows") or []
        )
        snapshot = AccountUsageSnapshot(
            provider=lane.get("provider") or "",
            source=lane.get("source") or "",
            fetched_at=datetime.now(timezone.utc),
            plan=lane.get("plan"),
            windows=windows,
            details=tuple(lane.get("details") or []),
        )
        for line in render_account_usage_lines(snapshot):
            print(f"  {line}")


def _emit_usage_json(payload: dict) -> None:
    """Print the envelope as JSON, guaranteeing the ``--json`` branch NEVER
    raises. The verb's contract is total failure isolation, but ``emit_json`` (or
    the stdout write itself) can still fail; if it does, fall back to a minimal
    always-valid empty envelope serialized with the stdlib ``json.dumps`` so the
    fallback does not depend on the possibly-broken ``emit_json``. If even that
    write fails there is nothing more we can do, so it is swallowed and the verb
    still exits 0.

    The fallback envelope carries ``degraded: {"serialize": <Class>}``: it is
    reporting zero lanes at the exact moment it knows the real payload could not
    be written, and a client cannot be asked to tell that apart from a genuinely
    idle account."""
    try:
        print(emit_json(payload))
        return
    except Exception as exc:  # noqa: BLE001 — named on the fallback envelope
        serialize_error: BaseException = exc
    try:
        print(json.dumps(_empty_usage_envelope(("serialize", serialize_error))))
    except Exception:
        pass


def _cmd_usage(args) -> int:
    """`hermes harness usage` — typed per-provider account-usage envelope. Total
    failure isolation: nothing here may raise; worst case is a valid envelope
    with empty lanes."""
    only_provider = getattr(args, "provider", None)
    timeout = float(getattr(args, "timeout", DEFAULT_USAGE_TIMEOUT) or DEFAULT_USAGE_TIMEOUT)
    try:
        payload = build_account_usage(only_provider=only_provider, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — named on the fallback envelope
        payload = _empty_usage_envelope(("build", exc))
    # Stamped on the JSON exits only, and the human render is left alone: the
    # keys it prints are its own. An account whose credentials live under a
    # different HERMES_HOME answers "zero lanes" in a perfectly well-formed
    # envelope — the incident shape this stamp exists for — and until now this
    # verb reached the gate through ``_emit_usage_json``, where a direct-call
    # scan could not see it. ``attach_root_observability`` never raises, so the
    # verb's total-isolation contract is unchanged.
    if getattr(args, "json", False):
        _emit_usage_json(attach_root_observability(payload))
        return 0
    try:
        _render_account_usage_human(payload)
    except Exception:
        # Human rendering must not crash the verb either.
        _emit_usage_json(attach_root_observability(payload))
    return 0
