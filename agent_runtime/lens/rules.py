"""Lens RULES: the closed rule schema and the deterministic evaluator.

Ported from Companion's ``monitor_feed.dart`` (``AnomalyRule``, ``checkRule``) and
``rule_evaluator.dart`` (``RuleEvaluator.evaluate``); the conformance corpus
``tests/agent_runtime/lens/conformance/observation_corpus.json`` is the oracle.

Same rule, same ordered observations and same evaluation time give the same
verdict on every host. The four forms:

* ``threshold`` — the latest observation breaches.
* ``for_duration`` — every observation across ``window_ms`` breaches, and the
  window is COMPLETE: it needs an anchor at or before its start and unbroken
  samples to the end. A four-minute breach never fires a five-minute rule.
* ``delta`` — last minus the exact window anchor breaches (never extrapolated).
* ``consecutive_samples`` — the last ``samples`` observations all breach.

Missing evidence is ``unknown``, never ``healthy``: a gap, a stale latest sample,
a sequence hole or a sample later than ``now`` all answer ``unknown``. Recovery
uses ``recovery_threshold`` (hysteresis) and also needs a complete window.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Sequence

from .feed import Observation
from .wire_value import (
    bounded_int,
    checked_object,
    enum_value,
    finite_number,
    opaque_id,
    require,
)

__layer__ = "models"

#: The longest rule window (24 h) and the reference's consecutive-sample ceiling.
MAXIMUM_RULE_WINDOW_MS = 24 * 60 * 60 * 1000
MAXIMUM_CONSECUTIVE_SAMPLES = 4096
MINIMUM_SAMPLING_INTERVAL_MS = 1000
#: A maximum window at the fastest cadence, both endpoints, plus one anchor.
MAXIMUM_OBSERVATIONS = (MAXIMUM_RULE_WINDOW_MS + MINIMUM_SAMPLING_INTERVAL_MS - 1) // MINIMUM_SAMPLING_INTERVAL_MS + 2


class RuleForm(str, Enum):
    THRESHOLD = "threshold"
    DELTA = "delta"
    FOR_DURATION = "for_duration"
    CONSECUTIVE_SAMPLES = "consecutive_samples"


class Direction(str, Enum):
    ABOVE = "above"
    BELOW = "below"


class Severity(str, Enum):
    ATTENTION = "attention"
    URGENT = "urgent"


class Verdict(str, Enum):
    FIRING = "firing"
    HEALTHY = "healthy"
    UNKNOWN = "unknown"


_TIMED_FORMS = frozenset({RuleForm.DELTA, RuleForm.FOR_DURATION})

RULE_KEYS = frozenset({
    "version", "id", "feed_id", "form", "severity", "direction",
    "threshold", "recovery_threshold", "window_ms", "samples",
})


def read_rule(value: Any) -> dict[str, Any]:
    """The canonical rule dict, or :class:`~agent_runtime.lens.wire_value.WireError`."""

    m = checked_object(value, RULE_KEYS)
    rule = {
        "version": bounded_int(m["version"], minimum=1, maximum=1),
        "id": opaque_id(m["id"]),
        "feed_id": opaque_id(m["feed_id"]),
        "form": enum_value(m["form"], RuleForm).value,
        "severity": enum_value(m["severity"], Severity).value,
        "direction": enum_value(m["direction"], Direction).value,
        "threshold": finite_number(m["threshold"]),
        "recovery_threshold": finite_number(m["recovery_threshold"]),
        "window_ms": bounded_int(m["window_ms"]),
        "samples": bounded_int(m["samples"], minimum=1, maximum=MAXIMUM_CONSECUTIVE_SAMPLES),
    }
    _check_rule(rule)
    return rule


def _check_rule(rule: dict[str, Any]) -> None:
    above = rule["direction"] == Direction.ABOVE.value
    hysteresis = rule["recovery_threshold"] < rule["threshold"] if above else rule["recovery_threshold"] > rule["threshold"]
    require(hysteresis, "recovery must have hysteresis")
    form = RuleForm(rule["form"])
    window = rule["window_ms"]
    require(0 < window <= MAXIMUM_RULE_WINDOW_MS if form in _TIMED_FORMS else window == 0, "rule window mismatch")
    require(form is RuleForm.CONSECUTIVE_SAMPLES or rule["samples"] == 1, "sample count only for consecutive rule")


def continuity_limit(interval: timedelta) -> timedelta:
    """Ordinary arrival jitter vs a missed tick: half an interval late, never a whole one."""

    if interval <= timedelta(0):
        raise ValueError("positive sampling interval required")
    return interval + interval / 2


def _ordered_samples(rule: dict[str, Any], observations: Sequence[Observation]) -> list[Observation]:
    samples = [obs for obs in observations if obs.feed_id == rule["feed_id"]]
    samples.sort(key=lambda obs: (obs.observed_at, obs.sequence))
    return samples


def _latest_is_current(last: Observation, now: datetime, limit: timedelta) -> bool:
    return (
        last.observed_at <= now
        and last.received_at <= now
        and now - last.observed_at <= limit
        and not last.gap
        and last.value is not None
    )


def _window(rule: dict[str, Any], samples: list[Observation], limit: timedelta) -> list[Observation] | None:
    """The complete window the form needs, or None when the evidence is incomplete."""

    form = RuleForm(rule["form"])
    if form is RuleForm.CONSECUTIVE_SAMPLES:
        window = samples[-rule["samples"]:]
        return window if len(window) >= rule["samples"] else None
    window_start = samples[-1].observed_at - timedelta(milliseconds=rule["window_ms"])
    anchor = max((i for i, obs in enumerate(samples) if obs.observed_at <= window_start), default=-1)
    if anchor < 0 or window_start - samples[anchor].observed_at > limit:
        return None
    window = samples[anchor:]
    return window if window and window[0].observed_at <= window_start else None


def _unbroken(window: list[Observation], now: datetime, limit: timedelta) -> bool:
    for i, obs in enumerate(window):
        if obs.gap or obs.value is None or obs.observed_at > now:
            return False
        if i:
            prev = window[i - 1]
            if (
                obs.observed_at - prev.observed_at > limit
                or obs.sequence != prev.sequence + 1
                or obs.observed_at <= prev.observed_at
            ):
                return False
    return True


def evaluate(
    rule: dict[str, Any],
    observations: Sequence[Observation],
    *,
    now: datetime,
    expected_interval: timedelta,
    was_firing: bool,
    has_gap: bool = False,
) -> Verdict:
    """The verdict of ``rule`` over ``observations`` at ``now``. Pure."""

    if expected_interval <= timedelta(0):
        raise ValueError("positive expected interval required")
    if len(observations) > MAXIMUM_OBSERVATIONS:
        raise ValueError(f"at most {MAXIMUM_OBSERVATIONS} observations")
    if has_gap or not observations:
        return Verdict.UNKNOWN
    samples = _ordered_samples(rule, observations)
    if not samples or len({obs.monitor_id for obs in samples}) != 1:
        return Verdict.UNKNOWN
    limit = continuity_limit(expected_interval)
    if not _latest_is_current(samples[-1], now, limit):
        return Verdict.UNKNOWN

    threshold = rule["recovery_threshold"] if was_firing else rule["threshold"]
    above = rule["direction"] == Direction.ABOVE.value

    def breach(value: float) -> bool:
        return value > threshold if above else value < threshold

    def result(firing: bool) -> Verdict:
        return Verdict.FIRING if firing else Verdict.HEALTHY

    form = RuleForm(rule["form"])
    if form is RuleForm.THRESHOLD:
        return result(breach(samples[-1].value))
    window = _window(rule, samples, limit)
    if window is None or not _unbroken(window, now, limit):
        return Verdict.UNKNOWN
    if form is RuleForm.DELTA:
        window_start = samples[-1].observed_at - timedelta(milliseconds=rule["window_ms"])
        if window[0].observed_at != window_start:
            return Verdict.UNKNOWN
        return result(breach(window[-1].value - window[0].value))
    # Recovery also needs a complete window; missing evidence never heals.
    if was_firing:
        return result(any(breach(obs.value) for obs in window))
    return result(all(breach(obs.value) for obs in window))
