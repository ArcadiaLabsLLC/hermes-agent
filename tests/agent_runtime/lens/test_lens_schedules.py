"""Lens scheduled runs — the ``schedule:`` field, the ``schedule:run`` Episode, its clock, catch-up and
admission (plan ``planned/lens-deadline-schedule-equivalence-report-2026-10-27.md`` §2,
``RT-LENS-SCHEDULED-INSIGHTS``).

No real network and no model: reads go through an ``httpx.MockTransport``, the exit door's turn is an
injected ``forge`` callable, the clock is fixed and the home is the test's isolated ``HERMES_HOME``.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, UTC

import httpx
import pytest

from agent_runtime.lens.episode import Episode, EpisodeState
from agent_runtime.lens.manifest import read_manifest
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.rules import SCHEDULE_RULE_ID
from agent_runtime.lens.store import LensStore, MonitorState, ReceiptOutcome, to_ms
from agent_runtime.lens.wire_value import WireError

T0 = datetime(2026, 10, 27, 9, 30, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
PUBLIC = ["93.184.216.34"]
#: The seal digest of the unscheduled fixture, as ``origin/main`` computed it before the field existed.
UNSCHEDULED_DIGEST = "01afcd07d397852eaefa5ee4affc9034d49d882c62554b8c97d5787365bb9c75"
DAILY_AT_8 = {"every_ms": 86_400_000, "offset_ms": 28_800_000, "brief": "Look for new listings of <cpu> under 400"}


def _monitor(*, schedule: dict | None = None, level: str = "investigate", when: str = "always", cap: int = 24,
             digest_window_ms: int | None = None) -> dict:
    automation = {"level": level, "when": when, "daily_turn_cap": cap}
    if digest_window_ms is not None:
        automation["digest_window_ms"] = digest_window_ms
    manifest = {"version": 1, "monitor_id": "status",
                "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                           "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}],
                "rules": [{"version": 1, "id": "cpu_hot", "feed_id": "api", "form": "threshold",
                           "severity": "attention", "direction": "above", "threshold": 90,
                           "recovery_threshold": 80, "window_ms": 0, "samples": 1}],
                "automation": automation, "persona_id": "qa"}
    if schedule is not None:
        manifest["schedule"] = dict(schedule)
    return manifest


def _enabled(manifest: dict, *, state: MonitorState = MonitorState.ENABLED) -> LensStore:
    store = LensStore()
    store.create(manifest)
    store.seal(manifest["monitor_id"])
    store.set_state(manifest["monitor_id"], state)
    return store


def _reseal(store: LensStore, manifest: dict) -> None:
    store.create(manifest)
    store.seal(manifest["monitor_id"])


def _tick(store: LensStore, at: datetime) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"cpu": 10})),
                          follow_redirects=False)
    LensPoller(store_factory=lambda: store, clock=lambda: at, client=client, resolver=lambda host: PUBLIC).tick()


def _runs(store: LensStore) -> list[tuple[int, str, str]]:
    return [(row["ordinal"], row["state"], row["first_seen"]) for row in store.episodes(monitor_id="status")
            if row["rule_id"] == SCHEDULE_RULE_ID]


def _refusal(manifest: dict) -> str:
    with pytest.raises(WireError) as raised:
        read_manifest(manifest)
    return raised.value.code.value


# --- the field --------------------------------------------------------------------------------


def test_a_manifest_without_a_schedule_keeps_its_bytes_and_seal_digest():
    from agent_runtime.lens.seal import seal_manifest

    assert "schedule" not in read_manifest(_monitor())
    assert seal_manifest(_monitor(), revision=1).digest == UNSCHEDULED_DIGEST
    assert read_manifest(_monitor(schedule=DAILY_AT_8))["schedule"] == DAILY_AT_8


def test_a_schedule_is_refused_on_notify_and_when_the_cap_would_clip_it():
    hourly = {**DAILY_AT_8, "every_ms": 3_600_000, "offset_ms": 0}

    assert _refusal(_monitor(schedule=DAILY_AT_8, level="notify")) == "schedule_needs_investigate"
    assert _refusal(_monitor(schedule=hourly, cap=5)) == "schedule_over_cap"
    read_manifest(_monitor(schedule=hourly, cap=24))  # positive control: the cap holds one a slot


@pytest.mark.parametrize("bad", [
    {**DAILY_AT_8, "every_ms": 899_999},                 # under the quarter-hour floor
    {**DAILY_AT_8, "every_ms": 7 * 86_400_000 + 1},      # over a week
    {**DAILY_AT_8, "offset_ms": 86_400_000},             # the phase is inside the period
    {**DAILY_AT_8, "brief": "x" * 1025},
    {"every_ms": 86_400_000, "offset_ms": 0},            # closed schema: brief is required
])
def test_ill_formed_schedules_are_refused(bad):
    with pytest.raises(WireError):
        read_manifest(_monitor(schedule=bad))


def test_the_schedule_prefix_is_reserved():
    manifest = _monitor()
    manifest["rules"][0]["id"] = "schedule:run"
    with pytest.raises(WireError):
        read_manifest(manifest)


# --- the clock --------------------------------------------------------------------------------


def test_one_run_per_slot_and_the_next_slot_opens_the_next_ordinal():
    store = _enabled(_monitor(schedule=DAILY_AT_8))

    _tick(store, T0)
    _tick(store, T0 + HOUR)  # same slot (08:00 today)
    assert _runs(store) == [(1, "scheduled", "2026-10-27T08:00:00.000Z")]

    _tick(store, T0 + DAY)
    assert _runs(store) == [(2, "scheduled", "2026-10-28T08:00:00.000Z"), (1, "scheduled", "2026-10-27T08:00:00.000Z")]
    [second] = [row for row in store.episodes(monitor_id="status") if row["ordinal"] == 2]
    assert second["last_seen"] == "2026-10-28T09:30:00.000Z"  # lateness is last_seen - first_seen


def test_catch_up_is_one_late_run_that_names_the_previous_one():
    from agent_runtime.lens.trigger import LensForge

    store = _enabled(_monitor(schedule=DAILY_AT_8))
    _tick(store, T0)
    messages = []

    def forge(*, manifest, episode, message, **turn):
        messages.append(message)
        return True, {"ok": True, "reply": "found two listings"}

    LensForge(store_factory=lambda: store, clock=lambda: T0, forge=forge).tick()
    later = T0 + 3 * DAY  # three slots skipped
    _tick(store, later)

    assert [ordinal for ordinal, _, _ in _runs(store)] == [2, 1]
    assert LensForge(store_factory=lambda: store, clock=lambda: later, forge=forge).tick() == ["forged"]
    assert "the previous run was 2026-10-27T08:00:00Z" in messages[-1]
    assert "the previous run was none recorded" in messages[0]


def test_a_reseal_to_hourly_is_due_at_the_next_hourly_slot():
    store = _enabled(_monitor(schedule=DAILY_AT_8))
    _tick(store, T0)

    _reseal(store, _monitor(schedule={**DAILY_AT_8, "every_ms": 3_600_000, "offset_ms": 0}))
    _tick(store, T0 + HOUR)

    assert _runs(store)[0] == (2, "scheduled", "2026-10-27T10:00:00.000Z")


def test_a_paused_monitor_accrues_no_runs():
    store = _enabled(_monitor(schedule=DAILY_AT_8), state=MonitorState.PAUSED)
    _tick(store, T0)
    assert _runs(store) == []

    store.set_state("status", MonitorState.ENABLED)  # positive control
    _tick(store, T0)
    assert len(_runs(store)) == 1


# --- the door ---------------------------------------------------------------------------------


class _Forge:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, *, manifest, episode, message, **turn):
        self.calls.append((episode.rule_id, message, turn))
        return True, {"ok": True, "reply": "done"}


def _breach(ordinal: int = 1, at: datetime = T0) -> Episode:
    return Episode(monitor_id="status", rule_id="cpu_hot", ordinal=ordinal, first_seen=at, last_seen=at, count=1,
                   state=EpisodeState.ACTIVE)


def _door(store: LensStore, at: datetime, forge: _Forge):
    from agent_runtime.lens.trigger import LensForge

    return LensForge(store_factory=lambda: store, clock=lambda: at, forge=forge).tick()


def test_an_urgent_only_monitor_still_forges_its_scheduled_run():
    forge = _Forge()
    store = _enabled(_monitor(schedule=DAILY_AT_8, when="urgent"))
    store.save_episode(_breach())  # an attention breach on the same monitor: the control
    _tick(store, T0)

    outcomes = _door(store, T0, forge)

    assert sorted(outcomes) == ["forged", "skipped_severity"]
    [(rule_id, message, _)] = forge.calls
    assert rule_id == SCHEDULE_RULE_ID
    assert message.startswith("[LENS SCHEDULED RUN — status · #1]")
    assert 'standing ask (manifest text, JSON-encoded): "Look for new listings of \\u003ccpu> under 400"' in message
    assert "lens_propose" in message


def test_a_receipt_names_its_episodes_rule_so_a_scheduled_run_is_told_from_a_breach():
    # RT-LENS-RECEIPT-RULE-ID: the launcher labels a ``schedule:run`` receipt "scheduled run" by this key.
    forge = _Forge()
    store = _enabled(_monitor(schedule=DAILY_AT_8, when="urgent"))
    store.save_episode(_breach())
    _tick(store, T0)
    _door(store, T0, forge)

    receipts = store.receipts(monitor_id="status")
    assert {row["rule_id"]: row["outcome"] for row in receipts} == {
        SCHEDULE_RULE_ID: "forged", "cpu_hot": "skipped_severity"}
    assert all(store.receipt(row["episode_id"])["rule_id"] == row["rule_id"] for row in receipts)
    # A receipt whose Episode row is gone still reads, with no rule to name.
    store.save_receipt({"episode_id": "b" * 64, "monitor_id": "status", "turn_id": "x", "started_ms": to_ms(T0),
                        "outcome": ReceiptOutcome.FORGED.value, "tool_admission": "read_only"})
    assert store.receipt("b" * 64)["rule_id"] is None


def test_a_scheduled_run_spends_the_cap():
    forge = _Forge()
    store = _enabled(_monitor(schedule=DAILY_AT_8, cap=1))
    store.save_receipt({"episode_id": "a" * 64, "monitor_id": "status", "turn_id": "x", "started_ms": to_ms(T0),
                        "outcome": ReceiptOutcome.FORGED.value, "tool_admission": "read_only"})
    _tick(store, T0)

    assert _door(store, T0, forge) == ["capped"]
    assert forge.calls == []


def test_a_scheduled_run_never_joins_a_digest():
    forge = _Forge()
    window = timedelta(minutes=10)
    store = _enabled(_monitor(schedule={**DAILY_AT_8, "offset_ms": 34_500_000},  # 09:35 UTC
                              digest_window_ms=int(window / timedelta(milliseconds=1))))
    store.save_episode(_breach())
    assert _door(store, T0, forge) == []  # the breach opens the monitor's digest window and waits

    from agent_runtime.lens.schedules import record_due_schedule

    run_at = T0 + timedelta(minutes=5)
    # The 09:35 slot's run, owed inside the open window (no read: the breach must stay active).
    assert record_due_schedule(store, "status", store.get("status")["sealed"]["manifest"], run_at)
    assert _door(store, run_at, forge) == ["forged"]  # its own turn, not a digest member
    assert _door(store, T0 + window, forge) == ["forged"]  # the window closes on the breach alone

    assert [(rule_id, turn) for rule_id, _, turn in forge.calls] == [
        (SCHEDULE_RULE_ID, {}), ("cpu_hot", {"turn_key": forge.calls[1][2]["turn_key"]})]


def test_a_run_still_owed_when_the_window_closes_is_not_a_member():
    from agent_runtime.lens.schedules import record_due_schedule

    forge = _Forge()
    window = timedelta(minutes=10)
    store = _enabled(_monitor(schedule={**DAILY_AT_8, "offset_ms": 34_500_000},
                              digest_window_ms=int(window / timedelta(milliseconds=1))))
    store.save_episode(_breach())
    assert _door(store, T0, forge) == []
    assert record_due_schedule(store, "status", store.get("status")["sealed"]["manifest"], T0 + timedelta(minutes=5))

    assert _door(store, T0 + window, forge) == ["forged", "forged"]  # the breach's digest, then the run alone
    assert [rule_id for rule_id, _, _ in forge.calls] == ["cpu_hot", SCHEDULE_RULE_ID]
    assert ReceiptOutcome.DIGESTED.value not in {row["outcome"] for row in store.receipts(monitor_id="status")}


def test_a_scheduled_run_is_never_painted_as_an_open_episode():
    from agent_runtime.lens.snapshot_fold import lens_fold

    store = _enabled(_monitor(schedule=DAILY_AT_8))
    store.save_episode(_breach())
    _tick(store, T0)

    assert [row["rule_id"] for row in lens_fold(store)["open_episodes"]] == ["cpu_hot"]


def test_a_scheduled_episode_row_is_version_one_and_round_trips():
    run = Episode(monitor_id="status", rule_id=SCHEDULE_RULE_ID, ordinal=1, first_seen=T0, last_seen=T0 + HOUR,
                  count=1, state=EpisodeState.SCHEDULED)
    body = json.loads(json.dumps(run.to_json()))
    assert body["version"] == 1 and "missed_deadline_ms" not in body
    assert Episode.from_json(copy.deepcopy(body)) == run
