"""Lens W3 — one read budget per HOST, shared across monitors (plan
``LENS_EXTENSIONS_2026-10-27.md`` §2, rows ``RT-LENS-HOST-READ-BUDGET`` and
``RT-LENS-CONDITIONAL-READS``).

No real network: every read goes through an ``httpx.MockTransport`` and a fixed
resolver; the poller is driven by ``tick`` on a fake clock.

Gates and their killing mutations (each red recorded in the row's commit):

* two monitors on one host read it no more than its budget, while a feed on another
  host keeps its cadence (positive control) — killed by keying the bucket by FEED
  (``host_key`` answering the feed's own id): the shared host doubles its reads;
* a defer past the continuity limit records exactly one ``host_budget_deferred`` gap —
  killed by deleting the ``store.record`` in ``LensPoller._admitted``;
* every read says ``User-Agent: EterniaLens/<version>`` — killed by dropping the header
  from ``fetch_json``.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, UTC

import httpx

from agent_runtime.lens import host_budget
from agent_runtime.lens.host_budget import HostBudget, host_key
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.store import LensStore, MonitorState

T0 = datetime(2026, 10, 27, 12, tzinfo=UTC)
PUBLIC = ["93.184.216.34"]


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def _feed(url: str, interval_ms: int = 1000) -> dict:
    return {"version": 1, "id": "api", "kind": "http_json", "interval_ms": interval_ms,
            "source": {"url": url, "selector": "$.cpu"}}


def _enable(monitor_id: str, feed: dict) -> LensStore:
    manifest = {"version": 1, "monitor_id": monitor_id, "feeds": [feed], "rules": [],
                "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}, "persona_id": None}
    store = LensStore()
    store.create(manifest)
    store.seal(monitor_id)
    store.set_state(monitor_id, MonitorState.ENABLED)
    return store


def _poller(clock: _Clock, handler, budget: HostBudget) -> LensPoller:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return LensPoller(clock=clock, client=client, resolver=lambda host: PUBLIC, host_budget=budget)


def _rows(store: LensStore, monitor_id: str) -> list[dict]:
    return store.observations(monitor_id, "api", start=T0 - timedelta(days=1), end=T0 + timedelta(days=1))


def test_two_monitors_on_one_host_share_its_budget_and_another_host_keeps_its_cadence():
    _enable("first", _feed("https://shared.example.invalid/a"))
    _enable("second", _feed("https://shared.example.invalid/b"))
    store = _enable("elsewhere", _feed("https://other.example.invalid/c", interval_ms=5000))
    reads: Counter = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        reads[request.url.host] += 1
        return httpx.Response(200, json={"cpu": 1})

    clock = _Clock(T0)
    poller = _poller(clock, handler, HostBudget(public_per_minute=12, private_per_minute=120))
    for _ in range(60):
        poller.tick()
        clock.at += timedelta(seconds=1)

    # One minute: the burst (5) plus one minute's refill (12), for BOTH monitors together.
    assert reads["shared.example.invalid"] <= host_budget.PUBLIC_BURST + 12
    # Positive control: the other host's one feed is read on its own 5 s cadence, unslowed.
    assert reads["other.example.invalid"] == 12
    assert all(not row["gap"] for row in _rows(store, "elsewhere"))


def test_a_defer_past_the_continuity_limit_records_one_host_budget_gap(monkeypatch):
    monkeypatch.setattr(host_budget, "PUBLIC_BURST", 1)
    store = _enable("status", _feed("https://status.example.invalid/h"))
    clock = _Clock(T0)
    poller = _poller(clock, lambda request: httpx.Response(200, json={"cpu": 7}),
                     HostBudget(public_per_minute=1, private_per_minute=1))
    for _ in range(4):  # 0 s reads; 1 s defers; 3 s is past the 1.5 s continuity limit
        poller.tick()
        clock.at += timedelta(seconds=1)

    assert [(row["gap"], row["reason"]) for row in _rows(store, "status")] == [
        (False, "ok"), (True, "host_budget_deferred")]


def test_every_read_names_eterna_lens_and_a_hostless_feed_spends_no_budget():
    from agent_runtime import __version__

    _enable("status", _feed("https://status.example.invalid/h"))
    agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers.get("user-agent"))
        return httpx.Response(200, json={"cpu": 1})

    _poller(_Clock(T0), handler, HostBudget(public_per_minute=30, private_per_minute=120)).tick()

    assert agents == [f"EterniaLens/{__version__}"]
    assert host_key({"kind": "command_allowlisted", "source": {}}) is None
    assert host_key(_feed("https://Status.Example.invalid/h")) == "status.example.invalid:443"
    assert host_key(_feed("http://10.0.0.5:9090/x")) == "10.0.0.5:9090"


# --- RT-LENS-CONDITIONAL-READS ------------------------------------------------------


def _conditional(sent: list) -> callable:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json={"cpu": 95}, headers={"ETag": '"v1"'})

    return handler


def test_a_304_records_the_last_value_as_not_modified_and_its_rule_stays_evaluable():
    rule = {"version": 1, "id": "hot", "feed_id": "api", "form": "consecutive_samples",
            "severity": "urgent", "direction": "above", "threshold": 90, "recovery_threshold": 80, "window_ms": 0,
            "samples": 2}
    manifest = {"version": 1, "monitor_id": "status", "feeds": [_feed("https://status.example.invalid/h", 5000)],
                "rules": [rule], "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0},
                "persona_id": None}
    store = LensStore()
    store.create(manifest)
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    sent: list = []
    clock = _Clock(T0)
    poller = _poller(clock, _conditional(sent), HostBudget(public_per_minute=30, private_per_minute=120))
    poller.tick()
    clock.at += timedelta(seconds=5)
    poller.tick()

    assert sent == [None, '"v1"']
    assert [(row["value"], row["gap"], row["reason"], row["http_status"]) for row in _rows(store, "status")] == [
        (95.0, False, "ok", 200), (95.0, False, "not_modified", 304)]
    # Two non-gap samples above 90: the 304 counts as evidence, so the rule fires.
    assert [e["state"] for e in store.episodes(monitor_id="status")] == ["active"]


def test_a_restarted_poller_holds_no_validators_and_sends_a_full_get():
    _enable("status", _feed("https://status.example.invalid/h", 5000))
    sent: list = []
    budget = HostBudget(public_per_minute=30, private_per_minute=120)
    _poller(_Clock(T0), _conditional(sent), budget).tick()
    _poller(_Clock(T0 + timedelta(seconds=5)), _conditional(sent), budget).tick()

    assert sent == [None, None]
