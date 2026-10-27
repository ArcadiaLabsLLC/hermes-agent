"""Lens L0 remainder — the watch-a-deal rules and typed values (plan §6a, §6b W2 W5 W7).

Gates:

* ``changed`` / ``moved_by`` fire on the two newest unbroken reads; a percent move
  off a zero read is unknown, never a 100 % alert.
* ``best_of`` fires when the best listing changes holder or beats the baseline;
  a group mixing currencies is refused at the manifest (W5).
* ``ends_within`` fires on the runtime clock with NO new read (W7).
* ``confirm_reads: 2`` keeps a one-read spike from opening an Episode (W2(b)).
* A read the feed's value type or plausible range refuses is a GAP with its
  reason, and no rule sees it (W2(a)(c)) — "price read as 0" never alerts.
* RT-LENS-W5-TOTAL-COST: a money feed's ``total_cost`` stores price + shipping +
  tax, converted by a dated rate feed (a stale rate is a gap ``fx_stale``), and
  ``best_of`` compares totals across listings in different currencies (W5); the
  median/deviation outlier guard refuses a spike but admits a level shift (W2(c));
  the cadence tightens as a deadline nears, and a clock-fired deadline gets a
  confirming read first (W7).
"""

from __future__ import annotations

import copy
import itertools
from datetime import datetime, timedelta, UTC

import httpx
import pytest

from agent_runtime.lens.feed import Observation, ReadingRefusal, read_feed, typed_reading
from agent_runtime.lens.manifest import read_manifest
from agent_runtime.lens.host_budget import HostBudget
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.rules import Verdict, evaluate, read_rule
from agent_runtime.lens.store import LensStore, MonitorState
from agent_runtime.lens.wire_value import WireError

T0 = datetime(2026, 10, 18, 12, tzinfo=UTC)
STEP = timedelta(minutes=1)
PUBLIC = ["93.184.216.34"]


def _rule(form: str, **over) -> dict:
    base = {"version": 1, "id": "r", "feed_id": "a", "form": form, "severity": "attention",
            "direction": "either", "threshold": 0, "recovery_threshold": 0, "window_ms": 0, "samples": 1}
    base.update(over)
    return read_rule(base)


def _obs(feed: str, values: list[float | None], *, start: datetime = T0, step: timedelta = STEP) -> list[Observation]:
    return [Observation(monitor_id="m", feed_id=feed, sequence=i + 1, observed_at=start + step * i,
                        received_at=start + step * i, value=v, gap=v is None) for i, v in enumerate(values)]


def _at(observations: list[Observation]) -> datetime:
    return max(obs.observed_at for obs in observations)


def _verdict(rule: dict, observations: list[Observation], *, now: datetime | None = None,
             was_firing: bool = False) -> Verdict:
    return evaluate(rule, observations, now=now or _at(observations), expected_interval=STEP, was_firing=was_firing)


# --- change rules ----------------------------------------------------------------


def test_changed_fires_on_a_change_and_heals_on_a_repeat():
    rule = _rule("changed")
    assert _verdict(rule, _obs("a", [399, 389])) is Verdict.FIRING
    assert _verdict(rule, _obs("a", [389, 389])) is Verdict.HEALTHY
    assert _verdict(rule, _obs("a", [389])) is Verdict.UNKNOWN  # one read is not a change
    assert _verdict(rule, _obs("a", [389, None, 380])) is Verdict.UNKNOWN  # a gap is never a change


@pytest.mark.parametrize(("direction", "values", "expected"), [
    ("below", [400, 350], Verdict.FIRING),     # down 12.5 %
    ("below", [400, 380], Verdict.HEALTHY),    # down 5 %
    ("below", [400, 460], Verdict.HEALTHY),    # up is not down
    ("above", [400, 460], Verdict.FIRING),
    ("either", [400, 350], Verdict.FIRING),
    ("either", [0, 10], Verdict.UNKNOWN),      # a percent off zero is no answer
])
def test_moved_by_percent(direction, values, expected):
    rule = _rule("moved_by", direction=direction, threshold=10, recovery_threshold=10, percent=True)
    assert _verdict(rule, _obs("a", values)) is expected


def test_moved_by_absolute():
    rule = _rule("moved_by", direction="above", threshold=5, recovery_threshold=5)
    assert _verdict(rule, _obs("a", [100, 106])) is Verdict.FIRING
    assert _verdict(rule, _obs("a", [100, 104])) is Verdict.HEALTHY


# --- best_of -----------------------------------------------------------------------


def _best_rule(**over) -> dict:
    fields = {"direction": "below", "threshold": 0, "recovery_threshold": 0, "feed_ids": ["a", "b"], **over}
    return _rule("best_of", **fields)


def test_best_of_fires_when_the_cheapest_listing_changes_holder():
    rule = _best_rule()
    steady = _obs("a", [300, 300]) + _obs("b", [320, 320], start=T0 + timedelta(seconds=10))
    assert _verdict(rule, steady) is Verdict.HEALTHY
    undercut = _obs("a", [300, 300]) + _obs("b", [320, 290], start=T0 + timedelta(seconds=10))
    assert _verdict(rule, undercut) is Verdict.FIRING


def test_best_of_fires_when_the_best_beats_the_baseline():
    rule = _best_rule(threshold=310, recovery_threshold=310)
    observations = _obs("a", [300, 300]) + _obs("b", [320, 320], start=T0 + timedelta(seconds=10))
    assert _verdict(rule, observations) is Verdict.FIRING


def test_best_of_with_a_stale_listing_is_unknown():
    rule = _best_rule()
    observations = _obs("a", [300]) + _obs("b", [320, 320, 320, 320], start=T0 + timedelta(seconds=10))
    assert _verdict(rule, observations) is Verdict.UNKNOWN


def _deal_manifest(**feed_b) -> dict:
    def feed(feed_id: str, **extra) -> dict:
        return {"version": 1, "id": feed_id, "kind": "http_json", "interval_ms": 60000,
                "source": {"url": f"https://shop.example.invalid/{feed_id}", "selector": "$.price"},
                "value_type": {"kind": "money", "currency": "USD"}, **extra}

    rule = {"version": 1, "id": "best", "feed_id": "a", "form": "best_of", "severity": "attention",
            "direction": "below", "threshold": 400, "recovery_threshold": 400, "window_ms": 0, "samples": 1,
            "feed_ids": ["a", "b"]}
    return {"version": 1, "monitor_id": "deal", "feeds": [feed("a"), feed("b", **feed_b)], "rules": [rule],
            "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}, "persona_id": None}


def test_a_best_of_group_mixing_currencies_is_refused():
    read_manifest(_deal_manifest())
    with pytest.raises(WireError):
        read_manifest(_deal_manifest(value_type={"kind": "money", "currency": "EUR"}))


# --- ends_within ---------------------------------------------------------------------


def test_ends_within_reads_the_deadline_against_now():
    rule = _rule("ends_within", direction="below", window_ms=600000)
    deadline = (T0 + timedelta(minutes=30)).timestamp() * 1000
    observations = _obs("a", [deadline])
    assert _verdict(rule, observations, now=T0) is Verdict.HEALTHY
    assert _verdict(rule, observations, now=T0 + timedelta(seconds=80)) is Verdict.HEALTHY
    later = _obs("a", [deadline], start=T0 + timedelta(minutes=21))
    assert _verdict(rule, later, now=T0 + timedelta(minutes=21)) is Verdict.FIRING


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def _client(payload) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload())),
                        follow_redirects=False)


def _enabled(manifest: dict) -> LensStore:
    store = LensStore()
    store.create(manifest)
    store.seal(manifest["monitor_id"])
    store.set_state(manifest["monitor_id"], MonitorState.ENABLED)
    return store


def test_the_clock_fires_a_deadline_with_no_new_read():
    deadline = (T0 + timedelta(minutes=10, seconds=20)).timestamp() * 1000
    manifest = {
        "version": 1, "monitor_id": "auction",
        "feeds": [{"version": 1, "id": "ends", "kind": "http_json", "interval_ms": 300000,
                   "source": {"url": "https://shop.example.invalid/lot", "selector": "$.ends_ms"},
                   "value_type": {"kind": "instant"}}],
        "rules": [{"version": 1, "id": "ending", "feed_id": "ends", "form": "ends_within", "severity": "urgent",
                   "direction": "below", "threshold": 0, "recovery_threshold": 0, "window_ms": 600000,
                   "samples": 1}],
        "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 4}, "persona_id": None,
    }
    store = _enabled(manifest)
    clock = _Clock(T0)
    poller = LensPoller(clock=clock, client=_client(lambda: {"ends_ms": deadline}), resolver=lambda host: PUBLIC)
    assert poller.tick() == 1
    assert store.latest_episode("auction", "ending") is None
    clock.at = T0 + timedelta(seconds=30)  # inside the lead time; no feed is due — the clock decides
    assert poller.tick() == 1  # ... and the clock's verdict is given ONE confirming read first (W7)
    episode = store.latest_episode("auction", "ending")
    assert episode is not None and episode.state.value == "active"


# --- confirm on a second read (W2(b)) --------------------------------------------------


def test_a_one_read_spike_needs_its_second_read():
    rule = _rule("threshold", direction="above", threshold=90, recovery_threshold=80, confirm_reads=2)
    assert _verdict(rule, _obs("a", [50, 95])) is Verdict.UNKNOWN
    assert _verdict(rule, _obs("a", [50, 95, 96])) is Verdict.FIRING
    # Already firing: recovery is not delayed by the confirmation.
    assert _verdict(rule, _obs("a", [95, 70]), was_firing=True) is Verdict.HEALTHY


# --- typed values (W2(a)(c)) --------------------------------------------------------------


def test_typed_reading_refuses_what_the_feed_says_cannot_be():
    price = read_feed({"version": 1, "id": "p", "kind": "http_json", "interval_ms": 60000,
                       "source": {"url": "https://shop.example.invalid/p", "selector": "$.price"},
                       "value_type": {"kind": "money", "currency": "USD"},
                       "plausible": {"minimum": 50, "maximum": 5000}})
    assert typed_reading(price, 389.99) == (389.99, None)
    assert typed_reading(price, 0) == (None, ReadingRefusal.IMPLAUSIBLE)
    count = read_feed({"version": 1, "id": "c", "kind": "http_json", "interval_ms": 60000,
                       "source": {"url": "https://shop.example.invalid/c", "selector": "$.bids"},
                       "value_type": {"kind": "count"}})
    assert typed_reading(count, 2.5) == (None, ReadingRefusal.TYPE_MISMATCH)
    assert typed_reading(count, 3) == (3, None)


def test_a_price_read_as_zero_is_a_gap_and_never_alerts():
    manifest = _deal_manifest()
    for feed in manifest["feeds"]:
        feed["plausible"] = {"minimum": 50, "maximum": 5000}
    store = _enabled(manifest)
    poller = LensPoller(clock=_Clock(T0), client=_client(lambda: {"price": 0}), resolver=lambda host: PUBLIC)
    assert poller.tick() == 2
    rows = store.observations("deal", "a", start=T0 - STEP, end=T0 + STEP)
    assert [(row["gap"], row["reason"]) for row in rows] == [(True, "implausible")]
    assert store.latest_episode("deal", "best") is None


# --- the closed schema still holds -------------------------------------------------------


@pytest.mark.parametrize("bad", [
    {"form": "threshold", "direction": "either", "threshold": 90, "recovery_threshold": 80},
    {"form": "changed", "percent": True},
    {"form": "threshold", "direction": "above", "threshold": 90, "recovery_threshold": 80, "feed_ids": ["a", "b"]},
    {"form": "best_of", "direction": "below"},  # no group
    {"form": "moved_by", "direction": "above", "threshold": 0},
    {"form": "ends_within", "direction": "below", "window_ms": 0},
    {"form": "changed", "confirm_reads": 3},
])
def test_ill_formed_journey_rules_are_refused(bad):
    base = {"version": 1, "id": "r", "feed_id": "a", "form": "changed", "severity": "attention",
            "direction": "either", "threshold": 0, "recovery_threshold": 0, "window_ms": 0, "samples": 1}
    base.update(bad)
    with pytest.raises(WireError):
        read_rule(base)


def test_defaults_have_one_canonical_form():
    rule = _rule("changed", confirm_reads=1)
    assert "confirm_reads" not in rule and read_rule(copy.deepcopy(rule)) == rule
    feed = read_feed({"version": 1, "id": "p", "kind": "http_json", "interval_ms": 60000,
                      "source": {"url": "https://shop.example.invalid/p", "selector": "$.price"},
                      "value_type": {"kind": "number"}})
    assert "value_type" not in feed


# --- RT-LENS-W5-TOTAL-COST: total cost (W5), the outlier guard (W2(c)), adaptive cadence (W7) ---


def _auction(deadline_ms: list[float], *, interval_ms: int = 300000, lead_ms: int = 600000) -> dict:
    return {
        "version": 1, "monitor_id": "auction",
        "feeds": [{"version": 1, "id": "ends", "kind": "http_json", "interval_ms": interval_ms,
                   "source": {"url": "https://shop.example.invalid/lot", "selector": "$.ends_ms"},
                   "value_type": {"kind": "instant"}}],
        "rules": [{"version": 1, "id": "ending", "feed_id": "ends", "form": "ends_within", "severity": "urgent",
                   "direction": "below", "threshold": 0, "recovery_threshold": 0, "window_ms": lead_ms,
                   "samples": 1}],
        "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 4}, "persona_id": None,
    }


def test_a_clock_fired_deadline_that_was_extended_opens_no_episode():
    first = (T0 + timedelta(minutes=10, seconds=20)).timestamp() * 1000
    extended = (T0 + timedelta(hours=1)).timestamp() * 1000  # the anti-snipe extension
    answers = iter([first, extended])
    store = _enabled(_auction([first]))
    clock = _Clock(T0)
    poller = LensPoller(clock=clock, client=_client(lambda: {"ends_ms": next(answers)}), resolver=lambda host: PUBLIC)
    poller.tick()
    clock.at = T0 + timedelta(seconds=30)
    assert poller.tick() == 1  # the confirming read
    assert store.latest_episode("auction", "ending") is None or store.latest_episode(
        "auction", "ending").state.value != "active"


def test_cadence_tightens_as_the_deadline_nears():
    deadline = (T0 + timedelta(minutes=12)).timestamp() * 1000
    reads = []
    store = _enabled(_auction([deadline], lead_ms=5000))
    clock = _Clock(T0)
    poller = LensPoller(clock=clock, client=_client(lambda: reads.append(clock.at) or {"ends_ms": deadline}),
                        resolver=lambda host: PUBLIC)
    for second in range(0, 12 * 60, 5):
        clock.at = T0 + timedelta(seconds=second)
        poller.tick()
    gaps = [(b - a).total_seconds() for a, b in itertools.pairwise(reads)]
    # 12 min out: 180 s (remaining / 4, under the 300 s interval); then ever tighter, floored at 5 s.
    assert gaps[0] == 180 and gaps == sorted(gaps, reverse=True) and min(gaps) == 5
    assert store.latest_episode("auction", "ending") is not None


def test_a_far_deadline_keeps_the_feed_interval():
    deadline = (T0 + timedelta(hours=5)).timestamp() * 1000
    reads = []
    _enabled(_auction([deadline]))
    clock = _Clock(T0)
    poller = LensPoller(clock=clock, client=_client(lambda: reads.append(clock.at) or {"ends_ms": deadline}),
                        resolver=lambda host: PUBLIC)
    for second in range(0, 601, 5):
        clock.at = T0 + timedelta(seconds=second)
        poller.tick()
    assert [(r - T0).total_seconds() for r in reads] == [0, 300, 600]


def _guarded(values: list[float]) -> list[tuple[float | None, str]]:
    feed = {"version": 1, "id": "cpu", "kind": "http_json", "interval_ms": 1000,
            "source": {"url": "https://status.example.invalid/m", "selector": "$.v"},
            "outlier_guard": {"window": 5, "deviations": 3}}
    manifest = {"version": 1, "monitor_id": "fast", "feeds": [feed], "rules": [],
                "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}, "persona_id": None}
    store = _enabled(manifest)
    answers = iter(values)
    clock = _Clock(T0)
    # A 1 s feed outruns one public host's default read budget (W3); this test is about the guard.
    budget = HostBudget(public_per_minute=6000, private_per_minute=6000)
    poller = LensPoller(clock=clock, client=_client(lambda: {"v": next(answers)}), resolver=lambda host: PUBLIC,
                        host_budget=budget)
    for i in range(len(values)):
        clock.at = T0 + timedelta(seconds=i)
        poller.tick()
    rows = store.observations("fast", "cpu", start=T0, end=T0 + timedelta(minutes=5))
    return [(row["value"], row["reason"]) for row in rows]


def test_the_outlier_guard_refuses_a_spike_and_admits_a_level_shift():
    rows = _guarded([100, 101, 99, 100, 102, 500, 101, 500, 500, 500])
    assert rows[5] == (None, "outlier") and rows[6] == (101, "ok")
    # The window holds refused reads too: once the new level is the median it is admitted.
    assert rows[-1] == (500, "ok")
    assert [reason for _, reason in rows[:5]] == ["ok"] * 5  # abstains until the window is full


def test_the_outlier_guard_abstains_over_a_flat_window():
    assert _guarded([389, 389, 389, 389, 389, 349])[-1] == (349, "ok")  # a price step is a change


def _listing(feed_id: str, value_type: dict) -> dict:
    return {"version": 1, "id": feed_id, "kind": "http_json", "interval_ms": 60000,
            "source": {"url": f"https://shop.example.invalid/{feed_id}", "selector": "$.price"},
            "value_type": value_type}


def _total_cost_manifest(fx_max_age_ms: int = 3600000) -> dict:
    rate = {"version": 1, "id": "gbpusd", "kind": "http_json", "interval_ms": 60000,
            "source": {"url": "https://fx.example.invalid/gbpusd", "selector": "$.rate"}}
    us = _listing("us", {"kind": "money", "currency": "USD", "total_cost": {"shipping": 20, "tax_rate": 0.1}})
    uk = _listing("uk", {"kind": "money", "currency": "USD", "total_cost": {
        "fx": {"feed_id": "gbpusd", "from": "GBP", "max_age_ms": fx_max_age_ms}}})
    rule = {"version": 1, "id": "best", "feed_id": "us", "form": "best_of", "severity": "attention",
            "direction": "below", "threshold": 0, "recovery_threshold": 0, "window_ms": 0, "samples": 1,
            "feed_ids": ["us", "uk"]}
    return {"version": 1, "monitor_id": "deal", "feeds": [us, uk, rate], "rules": [rule],
            "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}, "persona_id": None}


def _shop(rate: float | None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/gbpusd":
            return httpx.Response(503) if rate is None else httpx.Response(200, json={"rate": rate})
        return httpx.Response(200, json={"price": {"/us": 380, "/uk": 300}[path]})
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_total_cost_stores_price_shipping_tax_and_converts_by_the_dated_rate():
    store = _enabled(_total_cost_manifest())
    LensPoller(clock=_Clock(T0), client=_shop(1.25), resolver=lambda host: PUBLIC).tick()
    latest = {feed: store.latest("deal", feed)["value"] for feed in ("us", "uk", "gbpusd")}
    assert latest == {"us": 440.0, "uk": 375.0, "gbpusd": 1.25}  # (380 + 20) x 1.1; 300 GBP x 1.25


def test_a_conversion_with_no_current_rate_is_a_gap_fx_stale():
    store = _enabled(_total_cost_manifest(fx_max_age_ms=60000))
    store.record("deal", "gbpusd", observed_at=T0 - timedelta(hours=2), received_at=T0 - timedelta(hours=2),
                 value=1.3, reason="ok")  # a rate, but older than max_age
    LensPoller(clock=_Clock(T0), client=_shop(None), resolver=lambda host: PUBLIC).tick()
    row = store.latest("deal", "uk")
    assert (row["value"], row["reason"]) == (None, "fx_stale")


def test_preview_shows_the_total_with_its_own_rate_read():
    from agent_runtime.lens.sources import preview_reads

    reads = preview_reads(read_manifest(_total_cost_manifest()), client=_shop(1.25), resolver=lambda host: PUBLIC)
    assert {feed: result.value for feed, result in reads.items()} == {"us": 440.0, "uk": 375.0, "gbpusd": 1.25}


def test_a_group_of_totals_in_one_currency_is_comparable_and_a_bad_fx_feed_is_refused():
    read_manifest(_total_cost_manifest())  # different shipping / source currency, one stored currency
    for bad in ({"feed_id": "nope", "from": "GBP", "max_age_ms": 60000},   # not a feed of this monitor
                {"feed_id": "us", "from": "GBP", "max_age_ms": 60000},     # not a plain-number rate
                {"feed_id": "gbpusd", "from": "USD", "max_age_ms": 60000}):  # no conversion at all
        manifest = _total_cost_manifest()
        manifest["feeds"][1]["value_type"]["total_cost"]["fx"] = bad
        with pytest.raises(WireError):
            read_manifest(manifest)
    mixed = _total_cost_manifest()
    mixed["feeds"][1]["value_type"]["currency"] = "EUR"  # stored totals in two currencies
    mixed["feeds"][1]["value_type"]["total_cost"]["fx"]["from"] = "GBP"
    with pytest.raises(WireError):
        read_manifest(mixed)
