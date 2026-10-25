"""A Lens store transition moves the push lane: it appends a ``lens.*.changed`` EventLog event.

``RT-LENS-SNAPSHOT-SECTION-NO-PUSH-ON-STORE-WRITE``. The stream is gated on the EventLog watermark
and ``lens.sqlite3`` is in no watchdog fingerprint family, so before these events a monitor enabled
or an Episode opened reached a connected Launcher only when something else rebuilt the core. Feed
reads and an active Episode's ``last_seen`` ticks land every poll and must append nothing.

Killing mutations: drop the ``_changed`` call from ``set_state`` (the monitor test reds); make
``_episode_state_moves`` answer True (the tick test reds — one event per poll, the 2026-08-21
reconcile storm's shape).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from agent_runtime.events import EventLog
from agent_runtime.lens.episode import Episode, EpisodeState
from agent_runtime.lens.store import LensStore, MonitorState, ReceiptOutcome, to_ms

T0 = datetime(2026, 10, 25, 9, tzinfo=UTC)


def _lens_events() -> list[tuple[str, dict]]:
    return [(evt.type, evt.payload) for _, evt in EventLog().iter_from_offset(0) if evt.type.startswith("lens.")]


def _manifest() -> dict:
    return {"version": 1, "monitor_id": "status",
            "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                       "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}],
            "rules": [], "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0},
            "persona_id": None}


def _episode(**over) -> Episode:
    fields = {"monitor_id": "status", "rule_id": "cpu_hot", "ordinal": 1, "first_seen": T0, "last_seen": T0,
              "count": 1, "state": EpisodeState.ACTIVE, **over}
    return Episode(**fields)


def test_a_monitor_lifecycle_write_appends_its_event(isolate_agent_runtime_root):
    store = LensStore()
    store.create(_manifest())
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)

    assert [(kind, body.get("change"), body.get("state"), body.get("revision")) for kind, body in _lens_events()] == [
        ("lens.monitor.changed", "draft", None, None),
        ("lens.monitor.changed", "sealed", None, 1),
        ("lens.monitor.changed", "state", "enabled", None),
    ]


def test_an_episode_appends_on_open_and_state_change_never_on_a_tick(isolate_agent_runtime_root):
    store = LensStore()
    opened = _episode()
    store.save_episode(opened)
    for second in range(1, 4):  # three polls of the same active Episode: last_seen and count move
        store.save_episode(replace(opened, last_seen=T0 + timedelta(seconds=second), count=1 + second))
    assert [body["state"] for kind, body in _lens_events() if kind == "lens.episode.changed"] == ["active"]

    # Positive control: the same Episode, its STATE moved — that one is a transition.
    store.save_episode(replace(opened, state=EpisodeState.CLOSED_RECOVERED, last_seen=T0 + timedelta(seconds=9)))
    episode_events = [body for kind, body in _lens_events() if kind == "lens.episode.changed"]
    assert [body["state"] for body in episode_events] == ["active", "closed_recovered"]
    assert {body["episode_id"] for body in episode_events} == {opened.id}


def test_a_receipt_appends_when_written_and_when_settled(isolate_agent_runtime_root):
    store = LensStore()
    episode = _episode()
    receipt = {"episode_id": episode.id, "monitor_id": "status", "turn_id": f"lens-episode-{episode.id}",
               "started_ms": to_ms(T0), "outcome": ReceiptOutcome.FORGING.value, "tool_admission": "read_only"}
    assert store.save_receipt(receipt, episode=replace(episode, turn_id=receipt["turn_id"]))
    assert not store.save_receipt(receipt)  # the second write is refused, and appends nothing
    store.finish_receipt(episode.id, outcome=ReceiptOutcome.FORGED.value, finished_ms=to_ms(T0) + 1)

    assert [(kind, body.get("outcome") or body.get("state")) for kind, body in _lens_events()] == [
        ("lens.receipt.changed", "forging"),
        ("lens.episode.changed", "active"),
        ("lens.receipt.changed", "forged"),
    ]
