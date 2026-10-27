"""Lens W8 — a recorded deadline that passed while the watcher was off is a ``missed`` Episode
(plan ``planned/LENS_EXTENSIONS_2026-10-27.md`` §4, ``RT-LENS-MISSED-DEADLINES``).

No real network and no model: reads go through an ``httpx.MockTransport``, the exit door's turn is
an injected ``forge`` callable, the clock is fixed and the home is the test's isolated
``HERMES_HOME``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC

import httpx
import pytest

from agent_runtime.lens.episode import Episode, EpisodeState, needs_admission, observe
from agent_runtime.lens.missed_deadlines import record_missed_deadlines
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.rules import Verdict
from agent_runtime.lens.store import LensStore, MonitorState, to_ms
from agent_runtime.lens.wire_value import WireError

T0 = datetime(2026, 10, 27, 12, tzinfo=UTC)
LEAD = timedelta(minutes=10)
PUBLIC = ["93.184.216.34"]


def _manifest(*, level: str = "notify", persona_id: str | None = None) -> dict:
    return {
        "version": 1, "monitor_id": "auction", "persona_id": persona_id,
        "feeds": [{"version": 1, "id": "ends", "kind": "http_json", "interval_ms": 300000,
                   "source": {"url": "https://shop.example.invalid/lot", "selector": "$.ends_ms"},
                   "value_type": {"kind": "instant"}}],
        "rules": [{"version": 1, "id": "ending", "feed_id": "ends", "form": "ends_within", "severity": "urgent",
                   "direction": "below", "threshold": 0, "recovery_threshold": 0,
                   "window_ms": int(LEAD / timedelta(milliseconds=1)), "samples": 1}],
        "automation": {"level": level, "when": "always", "daily_turn_cap": 4},
    }


def _enabled(manifest: dict) -> LensStore:
    store = LensStore()
    store.create(manifest)
    store.seal(manifest["monitor_id"])
    store.set_state(manifest["monitor_id"], MonitorState.ENABLED)
    return store


def _poller(store: LensStore, at: datetime, deadline_ms: float | None = None) -> LensPoller:
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ends_ms": deadline_ms})), follow_redirects=False)
    return LensPoller(store_factory=lambda: store, clock=lambda: at, client=client, resolver=lambda host: PUBLIC)


def _rows(store: LensStore) -> list[dict]:
    return store.observations("auction", "ends", start=T0 - timedelta(days=1), end=T0 + timedelta(days=1))


def _episodes(store: LensStore) -> list[dict]:
    return store.episodes(monitor_id="auction")


def _outage(deadline: datetime, *, resume: datetime = T0 + timedelta(hours=1), **manifest) -> LensStore:
    """The deadline read at T0, then the serve is down until ``resume`` and catches up."""

    store = _enabled(_manifest(**manifest))
    store.record("auction", "ends", observed_at=T0, received_at=T0, value=float(to_ms(deadline)), reason="ok")
    _poller(store, resume).catch_up()
    return store


def test_a_deadline_that_passed_in_the_outage_is_one_missed_episode():
    deadline = T0 + timedelta(minutes=20)
    store = _outage(deadline)

    [row] = _episodes(store)
    assert (row["state"], row["version"], row["missed_deadline_ms"]) == ("missed", 2, to_ms(deadline))
    assert (row["first_seen"], row["last_seen"], row["count"]) == (
        "2026-10-27T12:10:00.000Z", "2026-10-27T12:20:00.000Z", 1)
    # No observation is invented for the unwatched interval: only the existing offline gap.
    assert [(r["reason"], r["gap"]) for r in _rows(store)] == [("ok", False), ("watcher_offline", True)]


def test_a_second_catch_up_and_a_repeated_call_still_leave_one():
    deadline = T0 + timedelta(minutes=20)
    store = _outage(deadline)
    _poller(store, T0 + timedelta(hours=1)).catch_up()
    manifest = store.get("auction")["sealed"]["manifest"]
    again = record_missed_deadlines(store, "auction", manifest, manifest["feeds"][0], offline_from=T0,
                                    now=T0 + timedelta(hours=1))

    assert again == 0
    assert [row["state"] for row in _episodes(store)] == ["missed"]


def test_a_deadline_still_ahead_at_resume_is_not_missed_and_the_tick_fires_it():
    """Positive control: the same outage with the deadline ahead opens the NORMAL Episode."""

    resume = T0 + timedelta(hours=1)
    deadline = resume + timedelta(minutes=5)
    store = _outage(deadline, resume=resume)
    assert _episodes(store) == []

    _poller(store, resume, float(to_ms(deadline))).tick()
    [row] = _episodes(store)
    assert (row["state"], row["version"]) == ("active", 1)


def test_a_rule_that_fired_before_the_outage_is_not_missed():
    deadline = T0 + timedelta(minutes=5)
    store = _enabled(_manifest())
    _poller(store, T0, float(to_ms(deadline))).tick()  # inside the lead: the rule fires while watched
    assert [row["state"] for row in _episodes(store)] == ["active"]

    _poller(store, T0 + timedelta(hours=1)).catch_up()
    assert [row["state"] for row in _episodes(store)] == ["active"]


def test_a_missed_episode_is_admitted_and_painted_and_never_open():
    from agent_runtime.lens.snapshot_fold import lens_fold
    from agent_runtime.lens.trigger import LensForge

    resume = T0 + timedelta(hours=1)
    store = _outage(T0 + timedelta(minutes=20), resume=resume)
    episode = store.latest_episode("auction", "ending")
    assert needs_admission(episode, resume)

    assert LensForge(store_factory=lambda: store, clock=lambda: resume).tick() == ["notified"]
    assert [row["state"] for row in lens_fold(store)["open_episodes"]] == ["missed"]
    # Not open: a later real breach is the next ordinal, the missed row is kept.
    nxt = observe(monitor_id="auction", rule_id="ending", next_ordinal=2, verdict=Verdict.FIRING,
                  at=resume, previous=store.latest_episode("auction", "ending"))
    assert (nxt.ordinal, nxt.state) == (2, EpisodeState.ACTIVE)


def test_the_opening_block_says_what_is_known_and_what_is_not():
    from agent_runtime.lens.trigger import LensForge

    resume = T0 + timedelta(hours=1)
    store = _outage(T0 + timedelta(minutes=20), resume=resume, level="investigate", persona_id="qa")
    messages = []

    def forge(*, manifest, episode, message):
        messages.append(message)
        return True, {"ok": True}

    assert LensForge(store_factory=lambda: store, clock=lambda: resume, forge=forge).tick() == ["forged"]
    [message] = messages
    assert "MISSED its deadline" in message and "2026-10-27T12:20:00Z" in message
    assert "offline from 2026-10-27T12:00:00Z to 2026-10-27T13:00:00Z" in message
    assert "no read was made in that interval" in message and "unknown until the next read" in message
    typed = json.loads(message.split("\n")[4])
    assert typed["offline"] == {"from_ms": to_ms(T0), "until_ms": to_ms(resume)}


def test_episode_rows_keep_version_one_and_version_two_round_trips():
    active = Episode(monitor_id="m", rule_id="r", ordinal=1, first_seen=T0, last_seen=T0, count=1,
                     state=EpisodeState.ACTIVE)
    assert active.to_json()["version"] == 1 and "missed_deadline_ms" not in active.to_json()
    missed = Episode(monitor_id="m", rule_id="r", ordinal=2, first_seen=T0, last_seen=T0, count=1,
                     state=EpisodeState.MISSED, missed_deadline_ms=to_ms(T0))
    assert Episode.from_json(json.loads(json.dumps(missed.to_json()))) == missed
    with pytest.raises(WireError):
        Episode.from_json({**active.to_json(), "missed_deadline_ms": 1})
    with pytest.raises(WireError):
        Episode.from_json({**missed.to_json(), "version": 1})
