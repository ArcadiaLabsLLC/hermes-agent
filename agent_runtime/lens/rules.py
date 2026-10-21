"""Lens RULES: the closed rule schema and the deterministic evaluator.

Ported from Companion's ``monitor_feed.dart`` (``AnomalyRule``, ``checkRule``) and
``rule_evaluator.dart`` (``RuleEvaluator.evaluate``); the conformance corpus
``tests/agent_runtime/lens/conformance/observation_corpus.json`` is the oracle for
the four Companion forms.

Same rule, same ordered observations and same evaluation time give the same
verdict on every host. The Companion forms:

* ``threshold`` — the latest observation breaches.
* ``for_duration`` — every observation across ``window_ms`` breaches, and the
  window is COMPLETE: it needs an anchor at or before its start and unbroken
  samples to the end. A four-minute breach never fires a five-minute rule.
* ``delta`` — last minus the exact window anchor breaches (never extrapolated).
* ``consecutive_samples`` — the last ``samples`` observations all breach.

The watch-a-deal forms (plan ``eternia-lens-in-hermes.md`` §6a), each over the
two newest unbroken reads unless stated:

* ``changed`` — the newest read differs from the one before it (direction ``either``).
* ``moved_by`` — newest minus previous moved by more than ``threshold``, absolute
  or (``percent``) relative to the previous read; ``above`` = up, ``below`` = down,
  ``either`` = both. A percent move off a zero read is ``unknown``.
* ``best_of`` — across the rule's equivalence group ``feed_ids`` (sealed by the
  operator; the manifest refuses a group whose value types differ — W5): the best
  (``below`` = minimum, ``above`` = maximum) changed holder since the previous read,
  or beats the baseline ``threshold``.
* ``ends_within`` — an INSTANT feed's deadline is at most ``window_ms`` after
  ``now``. Evaluated on the runtime clock (W7): the poller asks it every tick,
  not only when the feed is read.

``confirm_reads: 2`` (W2(b)) makes a rule that is not already firing fire only
when it also fires at the previous read — one bad parse never opens an Episode.

Missing evidence is ``unknown``, never ``healthy``: a gap, a stale latest sample,
a sequence hole or a sample later than ``now`` all answer ``unknown``. Recovery
uses ``recovery_threshold`` (hysteresis) and also needs a complete window.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Sequence

from .feed import Observation
from .wire_value import (
    boolean_value,
    bounded_int,
    bounded_list,
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
#: The longest ``ends_within`` lead time (7 d).
MAXIMUM_DEADLINE_LEAD_MS = 7 * 24 * 60 * 60 * 1000
MAXIMUM_GROUP_FEEDS = 4
MAXIMUM_CONFIRM_READS = 2


class RuleForm(str, Enum):
    THRESHOLD = "threshold"
    DELTA = "delta"
    FOR_DURATION = "for_duration"
    CONSECUTIVE_SAMPLES = "consecutive_samples"
    CHANGED = "changed"
    MOVED_BY = "moved_by"
    BEST_OF = "best_of"
    ENDS_WITHIN = "ends_within"


class Direction(str, Enum):
    ABOVE = "above"
    BELOW = "below"
    EITHER = "either"


class Severity(str, Enum):
    ATTENTION = "attention"
    URGENT = "urgent"


class Verdict(str, Enum):
    FIRING = "firing"
    HEALTHY = "healthy"
    UNKNOWN = "unknown"


_COMPANION_FORMS = frozenset({RuleForm.THRESHOLD, RuleForm.DELTA, RuleForm.FOR_DURATION,
                              RuleForm.CONSECUTIVE_SAMPLES})
_TIMED_FORMS = frozenset({RuleForm.DELTA, RuleForm.FOR_DURATION})
#: Forms the runtime clock moves without a new read (the poller asks them every tick).
CLOCK_FORMS = frozenset({RuleForm.ENDS_WITHIN})

RULE_KEYS = frozenset({
    "version", "id", "feed_id", "form", "severity", "direction",
    "threshold", "recovery_threshold", "window_ms", "samples",
})
#: ``percent`` (moved_by), ``feed_ids`` (best_of's group), ``confirm_reads`` (W2(b)).
RULE_KEYS_OPTIONAL = frozenset({"percent", "feed_ids", "confirm_reads"})


def read_rule(value: Any) -> dict[str, Any]:
    """The canonical rule dict, or :class:`~agent_runtime.lens.wire_value.WireError`."""

    m = checked_object(value, RULE_KEYS, RULE_KEYS_OPTIONAL)
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
    # Absence and the default are one canonical form (no key).
    if m.get("percent") is not None and boolean_value(m["percent"]):
        rule["percent"] = True
    if m.get("feed_ids") is not None:
        rule["feed_ids"] = bounded_list(m["feed_ids"], opaque_id, minimum=2, maximum=MAXIMUM_GROUP_FEEDS)
    if m.get("confirm_reads") is not None:
        confirm = bounded_int(m["confirm_reads"], minimum=1, maximum=MAXIMUM_CONFIRM_READS)
        if confirm > 1:
            rule["confirm_reads"] = confirm
    _check_rule(rule)
    return rule


def rule_feed_ids(rule: dict[str, Any]) -> tuple[str, ...]:
    """Every feed the rule reads: its equivalence group, or its one feed."""

    return tuple(rule.get("feed_ids") or (rule["feed_id"],))


def _check_rule(rule: dict[str, Any]) -> None:
    form = RuleForm(rule["form"])
    direction = Direction(rule["direction"])
    window = rule["window_ms"]
    require(form is RuleForm.CONSECUTIVE_SAMPLES or rule["samples"] == 1, "sample count only for consecutive rule")
    require(form is RuleForm.MOVED_BY or "percent" not in rule, "percent only for moved_by")
    require((form is RuleForm.BEST_OF) == ("feed_ids" in rule), "feed_ids exactly for best_of")
    if form in _COMPANION_FORMS:
        require(direction is not Direction.EITHER, "either only for change rules")
        above = direction is Direction.ABOVE
        hysteresis = (rule["recovery_threshold"] < rule["threshold"] if above
                      else rule["recovery_threshold"] > rule["threshold"])
        require(hysteresis, "recovery must have hysteresis")
        require(0 < window <= MAXIMUM_RULE_WINDOW_MS if form in _TIMED_FORMS else window == 0, "rule window mismatch")
        return
    # A change, comparison or deadline is an edge: recovery is "not this read", no second level.
    require(rule["recovery_threshold"] == rule["threshold"], "recovery equals threshold for this form")
    if form is RuleForm.ENDS_WITHIN:
        require(direction is Direction.BELOW and rule["threshold"] == 0, "ends_within is below 0")
        require(0 < window <= MAXIMUM_DEADLINE_LEAD_MS, "ends_within lead time")
        return
    require(window == 0, "rule window mismatch")
    if form is RuleForm.CHANGED:
        require(direction is Direction.EITHER and rule["threshold"] == 0, "changed is either over 0")
    elif form is RuleForm.MOVED_BY:
        require(rule["threshold"] > 0, "moved_by needs a positive move")
    else:  # BEST_OF
        group = rule["feed_ids"]
        require(direction is not Direction.EITHER, "best_of picks a minimum or a maximum")
        require(len(set(group)) == len(group) and rule["feed_id"] in group, "best_of group")


def continuity_limit(interval: timedelta) -> timedelta:
    """Ordinary arrival jitter vs a missed tick: half an interval late, never a whole one."""

    if interval <= timedelta(0):
        raise ValueError("positive sampling interval required")
    return interval + interval / 2


def _ordered_samples(feed_id: str, observations: Sequence[Observation]) -> list[Observation]:
    samples = [obs for obs in observations if obs.feed_id == feed_id]
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


def _pair(samples: list[Observation], now: datetime, limit: timedelta) -> tuple[float, float] | None:
    """(previous, newest) values of the two newest reads, or None when they are not unbroken."""

    pair = samples[-2:]
    if len(pair) < 2 or not _unbroken(pair, now, limit):
        return None
    return pair[0].value, pair[1].value


def _result(firing: bool) -> Verdict:
    return Verdict.FIRING if firing else Verdict.HEALTHY


# --- one evaluator per form (the table, not a ladder) ---------------------------

_Ctx = dict[str, Any]


def _companion(ctx: _Ctx) -> Verdict:
    rule, samples, now, limit = ctx["rule"], ctx["samples"], ctx["now"], ctx["limit"]
    threshold = rule["recovery_threshold"] if ctx["was_firing"] else rule["threshold"]
    above = rule["direction"] == Direction.ABOVE.value

    def breach(value: float) -> bool:
        return value > threshold if above else value < threshold

    form = RuleForm(rule["form"])
    if form is RuleForm.THRESHOLD:
        return _result(breach(samples[-1].value))
    window = _window(rule, samples, limit)
    if window is None or not _unbroken(window, now, limit):
        return Verdict.UNKNOWN
    if form is RuleForm.DELTA:
        window_start = samples[-1].observed_at - timedelta(milliseconds=rule["window_ms"])
        if window[0].observed_at != window_start:
            return Verdict.UNKNOWN
        return _result(breach(window[-1].value - window[0].value))
    # Recovery also needs a complete window; missing evidence never heals.
    if ctx["was_firing"]:
        return _result(any(breach(obs.value) for obs in window))
    return _result(all(breach(obs.value) for obs in window))


def _moved(ctx: _Ctx) -> Verdict:
    rule = ctx["rule"]
    pair = _pair(ctx["samples"], ctx["now"], ctx["limit"])
    if pair is None:
        return Verdict.UNKNOWN
    previous, newest = pair
    move = newest - previous
    if rule.get("percent"):
        if previous == 0:
            return Verdict.UNKNOWN
        move = move / abs(previous) * 100.0
    direction, by = Direction(rule["direction"]), rule["threshold"]
    if RuleForm(rule["form"]) is RuleForm.CHANGED:
        return _result(move != 0)
    if direction is Direction.ABOVE:
        return _result(move > by)
    if direction is Direction.BELOW:
        return _result(move < -by)
    return _result(abs(move) > by)


def _best(values: dict[str, float], group: Sequence[str], minimum: bool) -> str:
    """The holder of the best value; a tie goes to the earlier feed in the sealed group."""

    ordered = sorted(group, key=lambda feed: (values[feed] if minimum else -values[feed], group.index(feed)))
    return ordered[0]


def _best_of(ctx: _Ctx) -> Verdict:
    rule, now, limit = ctx["rule"], ctx["now"], ctx["limit"]
    group = rule["feed_ids"]
    per_feed = {feed: _ordered_samples(feed, ctx["observations"]) for feed in group}
    if any(not samples or not _latest_is_current(samples[-1], now, limit) for samples in per_feed.values()):
        return Verdict.UNKNOWN
    minimum = rule["direction"] == Direction.BELOW.value
    values = {feed: samples[-1].value for feed, samples in per_feed.items()}
    holder = _best(values, group, minimum)
    best = values[holder]
    beats = best < rule["threshold"] if minimum else best > rule["threshold"]
    # The holder before the newest read: that read's feed takes its previous value back.
    newest = max(group, key=lambda feed: (per_feed[feed][-1].observed_at, -group.index(feed)))
    pair = _pair(per_feed[newest], now, limit)
    changed = False
    if pair is not None:
        before = dict(values)
        before[newest] = pair[0]
        changed = _best(before, group, minimum) != holder
    return _result(changed or beats)


def _ends_within(ctx: _Ctx) -> Verdict:
    deadline_ms = ctx["samples"][-1].value
    now_ms = ctx["now"].timestamp() * 1000.0
    return _result(deadline_ms - now_ms <= ctx["rule"]["window_ms"])


_EVALUATORS: dict[RuleForm, Callable[[_Ctx], Verdict]] = {
    RuleForm.THRESHOLD: _companion,
    RuleForm.DELTA: _companion,
    RuleForm.FOR_DURATION: _companion,
    RuleForm.CONSECUTIVE_SAMPLES: _companion,
    RuleForm.CHANGED: _moved,
    RuleForm.MOVED_BY: _moved,
    RuleForm.BEST_OF: _best_of,
    RuleForm.ENDS_WITHIN: _ends_within,
}


def _evaluate_once(rule: dict[str, Any], observations: Sequence[Observation], *, now: datetime,
                   limit: timedelta, was_firing: bool) -> Verdict:
    feeds = rule_feed_ids(rule)
    relevant = [obs for obs in observations if obs.feed_id in feeds]
    if not relevant or len({obs.monitor_id for obs in relevant}) != 1:
        return Verdict.UNKNOWN
    samples = _ordered_samples(rule["feed_id"], relevant)
    if not samples or not _latest_is_current(samples[-1], now, limit):
        return Verdict.UNKNOWN
    ctx = {"rule": rule, "observations": relevant, "samples": samples, "now": now, "limit": limit,
           "was_firing": was_firing}
    return _EVALUATORS[RuleForm(rule["form"])](ctx)


def _previous_read(rule: dict[str, Any], observations: Sequence[Observation]) -> tuple[list[Observation], datetime] | None:
    """The evidence as it stood at the read before the newest one, and that read's time."""

    feeds = rule_feed_ids(rule)
    relevant = sorted((obs for obs in observations if obs.feed_id in feeds), key=lambda obs: (obs.observed_at,
                                                                                               obs.sequence))
    if len(relevant) < 2:
        return None
    earlier = relevant[:-1]
    return earlier, earlier[-1].received_at


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
    limit = continuity_limit(expected_interval)
    verdict = _evaluate_once(rule, observations, now=now, limit=limit, was_firing=was_firing)
    if verdict is not Verdict.FIRING or was_firing or rule.get("confirm_reads", 1) < 2:
        return verdict
    # W2(b): a new breach must also stand at the previous read, or it is not yet trusted.
    previous = _previous_read(rule, observations)
    if previous is None:
        return Verdict.UNKNOWN
    earlier, at = previous
    confirmed = _evaluate_once(rule, earlier, now=at, limit=limit, was_firing=False)
    return Verdict.FIRING if confirmed is Verdict.FIRING else Verdict.UNKNOWN
