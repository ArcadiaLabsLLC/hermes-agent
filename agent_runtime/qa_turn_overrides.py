"""QA-only per-turn limit overrides (RT-QA-TURN-LIMIT-OVERRIDES).

A QA lane cannot reach a turn's wall-budget checkpoint or its tool-iteration limit without a
long, costly real turn (Eternia w1108a-live-a, 2026-11-08: Sol answered in ~10 s, no limit was
reached), so the Agent Console rows that draw those moments stay unread. Three overrides
bring each moment within a cheap turn:

- ``checkpoint_after_seconds`` — the wall-budget checkpoint opens this many seconds into the
  turn instead of at ``total - max(60s, 15%)``; the hard wall keeps the turn's real budget.
- ``max_iterations`` — the tool-calling loop's iteration limit (default 90), so a 1-step limit
  makes the next tool-using turn end on the iteration-limit nudge.
- ``silence_seconds`` — the runner waits this long before the first provider call, a model
  silence the turn's ``turn.progress`` heartbeat beats through (the liveness fallback's case).

They are honoured ONLY in a Launcher QA namespace (``HERMES_NAMESPACE=stagec-*``) that runs
under a QA provider pool (``HERMES_QA_PROVIDER_POOL``, RT-QA-SHARED-PROVIDER-POOL): anywhere
else a turn that carries one is refused before it starts (``qa_turn_overrides_refused``), so an
owner's agent can never be throttled by a stray flag. Pure: the env is passed in.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__layer__ = "policy"

__all__ = [
    "QA_POOL_ENV",
    "QaTurnOverrides",
    "QaTurnOverridesRefused",
    "qa_turn_overrides",
    "qa_turn_overrides_admitted",
]

#: The QA provider pool env (``hermes_cli._namespace_bootstrap.QA_POOL_ENV``), spelled here so this
#: policy stays import-free; a test pins the two equal.
QA_POOL_ENV = "HERMES_QA_PROVIDER_POOL"
#: The Launcher's QA namespace prefix (``hermes_cli._namespace_bootstrap.QA_PREFIX``); pinned equal too.
QA_PREFIX = "stagec-"

#: Bounds: an override is a test seam, so it stays inside a short turn.
MAX_CHECKPOINT_AFTER_SECONDS = 600.0
MAX_ITERATIONS = 90
MAX_SILENCE_SECONDS = 300.0

REFUSED = "qa_turn_overrides_refused"
INVALID = "qa_turn_overrides_invalid"


class QaTurnOverridesRefused(ValueError):
    """A turn carried an override it may not: ``error_kind`` is :data:`REFUSED` or :data:`INVALID`."""

    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind


@dataclass(frozen=True)
class QaTurnOverrides:
    checkpoint_after_seconds: float | None = None
    max_iterations: int | None = None
    silence_seconds: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in (
            ("checkpoint_after_seconds", self.checkpoint_after_seconds),
            ("max_iterations", self.max_iterations),
            ("silence_seconds", self.silence_seconds),
        ) if value is not None}


def qa_turn_overrides_admitted(env: Mapping[str, str] | None = None) -> bool:
    """True in a QA namespace that runs under a QA provider pool — the only place overrides apply."""

    source = os.environ if env is None else env
    namespace = str(source.get("HERMES_NAMESPACE") or "").strip()
    return namespace.startswith(QA_PREFIX) and bool(str(source.get(QA_POOL_ENV) or "").strip())


def _seconds(name: str, value: Any, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QaTurnOverridesRefused(INVALID, f"{name} must be a number")
    if not (low <= float(value) <= high):
        raise QaTurnOverridesRefused(INVALID, f"{name} must be between {low:g} and {high:g} seconds")
    return float(value)


def qa_turn_overrides(
    *,
    checkpoint_after_seconds: Any = None,
    max_iterations: Any = None,
    silence_seconds: Any = None,
    env: Mapping[str, str] | None = None,
) -> QaTurnOverrides | None:
    """The turn's overrides, ``None`` when it carries none, or :class:`QaTurnOverridesRefused`."""

    if checkpoint_after_seconds is None and max_iterations is None and silence_seconds is None:
        return None
    # MUTATION: drop this check and test_qa_turn_overrides' "outside a QA pool is refused" reddens.
    if not qa_turn_overrides_admitted(env):
        raise QaTurnOverridesRefused(
            REFUSED,
            f"QA turn overrides apply only in a QA namespace ({QA_PREFIX}*) under a QA provider pool ({QA_POOL_ENV})",
        )
    checkpoint = None if checkpoint_after_seconds is None else _seconds(
        "checkpoint_after_seconds", checkpoint_after_seconds, low=1.0, high=MAX_CHECKPOINT_AFTER_SECONDS)
    silence = None if silence_seconds is None else _seconds(
        "silence_seconds", silence_seconds, low=0.0, high=MAX_SILENCE_SECONDS)
    iterations = None
    if max_iterations is not None:
        if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
            raise QaTurnOverridesRefused(INVALID, "max_iterations must be a whole number")
        if not (1 <= max_iterations <= MAX_ITERATIONS):
            raise QaTurnOverridesRefused(INVALID, f"max_iterations must be between 1 and {MAX_ITERATIONS}")
        iterations = max_iterations
    return QaTurnOverrides(checkpoint, iterations, silence)
