"""A chat turn sitting out a provider retry says so, typed: the ``provider.retry_wait`` frame.

``agent.turn_recovery.compute_error_backoff`` names the wait ("rate limited — resets in …,
retrying in 600s (attempt 1/3)") only on the agent's ``thinking_callback``, which the profile
runner never wires, so a Mission Control turn waiting out an HTTP 429 reached the Agent Console as
"Thinking · 1m elapsed" for the whole wait (runtime row ``RT-CHAT-PROVIDER-RETRY-WAIT-FRAME``,
launcher ``MC-CONSOLE-PROVIDER-429-BACKOFF-SHOWS-THINKING``, live 2026-11-01).

The path, the compaction frame's one door over (``docs/agent-runtime-harness/05-chat-turn-lane.md``
§5c): ``agent.turn_api_error.handle_api_error`` → :func:`emit_provider_retry_wait` → the agent's
``ReceiptSink.receipt`` (``agent_runtime/receipt_sink.py``; any other ``status_callback`` never sees
it) → the run's progress callback → ``ChatProgressSink`` (live stream only, no EventLog row) →
``_ChatProtocolV2Emitter`` writes ``provider.retry_wait``. Every hop re-reads the payload through
:func:`safe_provider_retry_wait`, so only its closed set of keys ever crosses.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agent_runtime.receipt_sink import agent_receipt_callback

__layer__ = "policy"

__all__ = [
    "PROVIDER_RETRY_WAIT_FRAME",
    "PROVIDER_RETRY_WAIT_PHASE",
    "emit_provider_retry_wait",
    "provider_retry_wait_payload",
    "provider_reset_seconds",
    "reset_outlasts_retries",
    "safe_provider_retry_wait",
]

#: The ``run.progress`` phase a retry-wait receipt carries between the agent and the stream.
PROVIDER_RETRY_WAIT_PHASE = "provider_retry_wait"
#: The protocol-v2 frame type the Launcher reads.
PROVIDER_RETRY_WAIT_FRAME = "provider.retry_wait"

_COUNT_FIELDS = ("retry_in_seconds", "attempt", "max_attempts")

_logger = logging.getLogger(__name__)


def _whole(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


def provider_retry_wait_payload(
    classified: Any,
    error_context: Optional[dict[str, Any]],
    *,
    wait_seconds: Any,
    attempt: Any,
    max_attempts: Any,
    now: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """The ``run.progress`` receipt for one retry wait, or ``None`` when the numbers are unreadable.

    ``provider_refusal`` is the same block a settled refusal carries
    (``ProviderRefusal.as_dict``, ``resets_in_seconds`` included) and is present only when the
    waited-on error IS a refusal (429, 401–404): a 5xx or a dropped stream waits with no
    refusal and the frame says only when the retry runs.
    """

    counts = {
        "retry_in_seconds": _whole(wait_seconds),
        "attempt": _whole(attempt),
        "max_attempts": _whole(max_attempts),
    }
    if any(value is None for value in counts.values()):
        return None
    payload: dict[str, Any] = {"type": "run.progress", "phase": PROVIDER_RETRY_WAIT_PHASE, **counts}
    if classified is not None:
        # Lazy: ``agent.turn_api_error`` imports this module at load, and the refusal
        # vocabulary is only needed once a wait actually runs.
        from agent.provider_failure import provider_failure_block
        from agent_runtime.mission_chat_outcome import provider_refusal_from_block

        refusal = provider_refusal_from_block(provider_failure_block(classified, error_context))
        if refusal is not None:
            payload["provider_refusal"] = refusal.as_dict(now=now)
    return payload


def emit_provider_retry_wait(
    agent: Any,
    classified: Any,
    error_context: Optional[dict[str, Any]],
    *,
    wait_seconds: Any,
    attempt: Any,
    max_attempts: Any,
) -> None:
    """Send the retry wait to the run's receipt door. Best-effort: an instrument never fails a turn."""

    try:
        callback = agent_receipt_callback(agent)
        if callback is None:
            return
        payload = provider_retry_wait_payload(
            classified, error_context, wait_seconds=wait_seconds, attempt=attempt, max_attempts=max_attempts,
        )
        if payload is not None:
            callback(payload)
    except Exception:
        return


def safe_provider_retry_wait(payload: Any) -> Optional[dict[str, Any]]:
    """The closed-set copy of a retry-wait receipt, or ``None`` when *payload* is not one.

    The refusal block passes ``safe_provider_refusal`` — the turn record's own whitelist —
    because its text originates in a provider's error body."""

    if not isinstance(payload, dict) or payload.get("phase") != PROVIDER_RETRY_WAIT_PHASE:
        return None
    from agent_runtime.mission_chat_turns.records import safe_provider_refusal

    safe: dict[str, Any] = {"type": "run.progress", "phase": PROVIDER_RETRY_WAIT_PHASE}
    for key in _COUNT_FIELDS:
        value = _whole(payload.get(key))
        if value is None:
            return None
        safe[key] = value
    refusal = safe_provider_refusal(payload.get("provider_refusal"))
    if refusal is not None:
        safe["provider_refusal"] = refusal
    return safe


def provider_reset_seconds(api_error: Any, error_context: Optional[dict[str, Any]]) -> Optional[float]:
    """Seconds until the provider says it accepts again: the LATER of its uncapped ``Retry-After``
    and its ``reset_at`` (read as the settled refusal reads it), or ``None`` when it named neither."""

    from agent.retry_utils import provider_retry_after_seconds
    from agent_runtime.mission_chat_outcome import ProviderRefusal

    candidates = [provider_retry_after_seconds(api_error)]
    reset_at = (error_context or {}).get("reset_at")
    if reset_at not in (None, ""):
        candidates.append(ProviderRefusal(status_code=0, reset_at=reset_at).resets_in_seconds())
    known = [float(value) for value in candidates if value is not None and value > 0]
    return max(known) if known else None


def reset_outlasts_retries(
    api_error: Any, error_context: Optional[dict[str, Any]], *, retry_count: int, max_retries: int,
) -> bool:
    """True when no retry left in this cycle can reach the provider's reset, so the caller ends
    the attempt cycle now — fallback first, else the terminal result whose ``provider_error``
    settles as a typed refusal carrying the reset (runtime row RT-RETRY-AFTER-CAP-RETRIES-WEEK-LIMIT).

    Each wait is capped at ``RETRY_AFTER_CAP_S`` (600 s) and ``max_retries - retry_count`` waits
    remain, so a reset beyond their sum is a wall every retry walks into: the Anthropic Account's
    used week limit ("resets in 3d 6h") slept 600 s three times into the same 429 (live
    2026-11-01). A reset the remaining waits DO reach is still waited out — a paid bucket reopens
    on time, and ``fallback.min_switch_reset_seconds`` relies on that wait. The attended free
    tier's shorter rule is ``agent.turn_recovery.free_tier_cooldown_ends_turn``."""

    from agent.retry_utils import RETRY_AFTER_CAP_S

    reset = provider_reset_seconds(api_error, error_context)
    remaining_waits = max(int(max_retries) - int(retry_count), 0)
    if reset is None or reset <= RETRY_AFTER_CAP_S * remaining_waits:
        return False
    _logger.info(
        "Provider reset in %.0fs outlasts the %d remaining capped retry wait(s) — ending retries after attempt %s",
        reset, remaining_waits, retry_count,
    )
    return True
