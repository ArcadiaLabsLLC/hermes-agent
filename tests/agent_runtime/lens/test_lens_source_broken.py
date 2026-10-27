"""Lens W1 slice 2 — the reserved ``source_broken:<feed_id>`` Episode (plan
``planned/LENS_EXTENSIONS_2026-10-27.md`` §1 decisions 5–6, row ``RT-LENS-SOURCE-BROKEN-EPISODE``).

No real network: reads go through an ``httpx.MockTransport`` and a fixed resolver; the exit door
runs through the fake handlers of ``test_lens_exit_door.py``.

Gates and their killing mutations (each red recorded in the row's commit):

* a manifest rule id ``source_broken:x`` is refused, ``broken_source`` is not (positive control) —
  killed by removing the prefix check in ``rules._authored_id``;
* an urgent-only monitor's broken feed is ``notified`` while an attention rule on it stays
  ``skipped_severity`` (positive control) — killed by letting the urgency filter answer
  ``skipped_severity`` for the reserved rule too;
* a drifted feed opens the Episode on its first bad read and a good read recovers it — killed by
  dropping the ``_source_drift`` call from ``LensPoller._record``.
"""

from __future__ import annotations

import re
from datetime import timedelta

import httpx
import pytest
from test_lens_exit_door import T0, _monitor, door  # noqa: F401  (door is a fixture)

from agent_runtime.lens.episode import Episode, EpisodeState
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.rules import read_rule
from agent_runtime.lens.shapes import json_skeleton
from agent_runtime.lens.store import LensStore, MonitorState
from agent_runtime.lens.store_shapes import record_shape
from agent_runtime.lens.trigger import LensForge
from agent_runtime.lens.wire_value import WireError

PUBLIC = ["93.184.216.34"]


def _rule(rule_id: str) -> dict:
    return {"version": 1, "id": rule_id, "feed_id": "api", "form": "threshold", "severity": "urgent",
            "direction": "above", "threshold": 90, "recovery_threshold": 80, "window_ms": 0, "samples": 1}


def test_a_manifest_cannot_author_the_reserved_rule_id():
    assert read_rule(_rule("broken_source"))["id"] == "broken_source"
    with pytest.raises(WireError):
        read_rule(_rule("source_broken:api"))


def _enabled(manifest: dict) -> LensStore:
    store = LensStore()
    store.create(manifest)
    store.seal(manifest["monitor_id"])
    store.set_state(manifest["monitor_id"], MonitorState.ENABLED)
    return store


def _drift_episode(store: LensStore):
    return store.latest_episode("status", "source_broken:api")


def _reading(store: LensStore, bodies: list) -> tuple[LensPoller, list]:
    at = [T0]
    answers = iter(bodies)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=next(answers))),
                          follow_redirects=False)
    return LensPoller(store_factory=lambda: store, clock=lambda: at[0], client=client,
                      resolver=lambda host: PUBLIC), at


def test_a_drifted_feed_opens_its_source_broken_episode_and_a_good_read_recovers_it():
    store = _enabled(_monitor(level="notify"))
    poller, at = _reading(store, [{"cpu": 10}, {"cpu_pct": 20}, {"cpu": 30}])

    poller.tick()
    assert _drift_episode(store) is None, "a good read opens nothing"
    at[0] += timedelta(seconds=5)
    poller.tick()
    opened = _drift_episode(store)
    assert (opened.state, opened.ordinal, opened.first_seen) == (EpisodeState.ACTIVE, 1, at[0])
    at[0] += timedelta(seconds=5)
    poller.tick()
    assert _drift_episode(store).state is EpisodeState.RECOVERED


def test_a_recovery_read_by_a_later_sealed_revision_closes_the_episode():
    store = _enabled(_monitor(level="notify"))
    poller, at = _reading(store, [{"cpu": 10}, {"cpu_pct": 20}, {"cpu": 30}])
    for _ in range(2):
        poller.tick()
        at[0] += timedelta(seconds=5)
    store.create(_monitor(level="notify"))
    store.seal("status")

    poller.tick()

    assert _drift_episode(store).state is EpisodeState.CLOSED_RECOVERED


def _owed_drift(store: LensStore) -> None:
    record_shape(store, "status", "api", shape=json_skeleton({"cpu": 1}), answered=True, reason="ok", at=T0)
    record_shape(store, "status", "api", shape=json_skeleton({"cpu_pct": 1}), answered=False,
                 reason="selector_missing", at=T0)
    store.save_episode(Episode(monitor_id="status", rule_id="source_broken:api", ordinal=1, first_seen=T0,
                               last_seen=T0, count=1, state=EpisodeState.ACTIVE))


def test_an_urgent_only_monitor_is_notified_of_a_broken_source_and_still_skips_an_attention_rule(door):
    store = _enabled(_monitor(when="urgent", severity="attention"))
    _owed_drift(store)
    store.save_episode(Episode(monitor_id="status", rule_id="cpu_hot", ordinal=1, first_seen=T0, last_seen=T0,
                               count=1, state=EpisodeState.ACTIVE))

    outcomes = LensForge(clock=lambda: T0).tick()

    assert sorted(outcomes) == ["notified", "skipped_severity"]
    receipts = {row["episode_id"]: row["outcome"] for row in store.receipts()}
    assert receipts[_drift_episode(store).id] == "notified"
    assert door.calls == []


def test_an_investigate_monitor_forges_a_repair_turn_carrying_both_skeletons_inside_the_fence(door):
    from agent_runtime.lens.tool import UNTRUSTED_EVIDENCE_CLOSE, UNTRUSTED_EVIDENCE_OPEN

    store = _enabled(_monitor())
    _owed_drift(store)

    assert LensForge(clock=lambda: T0).tick() == ["forged"]

    [args] = door.calls
    assert "[LENS EPISODE — status · source_broken:api · #1]" in args.message
    assert "stopped answering in the shape it was sealed against" in args.message
    fence = re.compile(re.escape(UNTRUSTED_EVIDENCE_OPEN + "\n") + "(.*?)" + re.escape("\n" + UNTRUSTED_EVIDENCE_CLOSE),
                       re.S)
    bodies = fence.findall(args.message)
    assert len(bodies) == 2, "the sources and the shapes are each fenced"
    assert '"known_good"' in bodies[1] and "$.cpu" in bodies[1] and "$.cpu_pct" in bodies[1]
    assert "$.cpu_pct" not in fence.sub("", args.message)
