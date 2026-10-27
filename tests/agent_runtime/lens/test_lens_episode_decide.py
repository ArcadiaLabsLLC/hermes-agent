"""``runtime.lens.episode.decide`` — the one writer of an Episode's ``decision`` (row
``RT-LENS-EPISODE-DECIDE-VERB``), and the fold that a settled Episode leaves.

Gates and their killing mutations (each red recorded in the row's commit):

* a dismissed ``recovered`` Episode and a snoozed ``missed`` one leave the fold while an
  undecided ``recovered`` one stays (positive control) — killed by folding
  ``store.episodes(states=...)`` again (every open state, decided or not);
* a decision on a ``closed_recovered`` Episode is refused ``episode_settled`` — killed by
  dropping the settled-state check from ``decide_episode``;
* a decision that moves no state still appends ``lens.episode.changed`` — killed by
  ``announce=False`` in ``decide_episode``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_runtime.events import EventLog
from agent_runtime.lens.episode import Episode, EpisodeState, needs_admission
from agent_runtime.lens.snapshot_fold import lens_fold
from agent_runtime.lens.store import LensStore

T0 = datetime(2026, 10, 27, 9, tzinfo=UTC)


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _episode(rule_id: str, state: EpisodeState, **over) -> Episode:
    return Episode(monitor_id="status", rule_id=rule_id, ordinal=1, first_seen=T0, last_seen=T0, count=1,
                   state=state, **over)


def _decide(episode: Episode, decision: str) -> dict:
    return _rpc("runtime.lens.episode.decide", {"episode_id": episode.id, "decision": decision})


def _folded() -> set[str]:
    return {row["rule_id"] for row in lens_fold(LensStore())["open_episodes"]}


def test_a_settled_episode_leaves_the_fold_and_an_undecided_one_stays():
    store = LensStore()
    recovered = _episode("cpu_hot", EpisodeState.RECOVERED)
    missed = _episode("ends", EpisodeState.MISSED, missed_deadline_ms=1_000)
    kept = _episode("disk", EpisodeState.RECOVERED)
    for episode in (recovered, missed, kept):
        store.save_episode(episode)
    assert _folded() == {"cpu_hot", "ends", "disk"}

    dismissed = _decide(recovered, "dismiss")["result"]
    snoozed = _decide(missed, "snooze15m")["result"]

    assert (dismissed["state"], dismissed["decision"]) == ("closed_recovered", "dismiss")
    assert (snoozed["state"], snoozed["decision"]) == ("missed", "snooze15m")
    assert snoozed["suppressed_until"] is not None and snoozed["decided_at"] is not None
    assert _folded() == {"disk"}


def test_a_decided_episode_is_no_longer_owed_its_turn():
    store = LensStore()
    active = _episode("cpu_hot", EpisodeState.ACTIVE)
    store.save_episode(active)
    assert needs_admission(active, T0)

    assert _decide(active, "investigate")["result"]["state"] == "active"

    stored = store.latest_episode("status", "cpu_hot")
    assert stored.decision.value == "investigate" and not needs_admission(stored, T0 + timedelta(hours=1))
    assert _folded() == {"cpu_hot"}, "an active Episode stays on the fold whatever was decided"


def test_a_closed_episode_is_refused_and_an_unknown_one_is_not_found():
    from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND

    closed = _episode("cpu_hot", EpisodeState.CLOSED_RECOVERED)
    LensStore().save_episode(closed)

    refused = _decide(closed, "dismiss")["error"]
    assert (refused["code"], refused["data"]["reason"]) == (ERR_CONFLICT, "episode_settled")
    missing = _rpc("runtime.lens.episode.decide", {"episode_id": "f" * 64, "decision": "dismiss"})["error"]
    assert (missing["code"], missing["data"]["reason"]) == (ERR_NOT_FOUND, "episode_not_found")
    bad = _rpc("runtime.lens.episode.decide", {"episode_id": closed.id, "decision": "ignore"})["error"]
    assert bad["code"] == ERR_INVALID_PARAMS


def test_a_decision_that_moves_no_state_still_moves_the_push_lane(isolate_agent_runtime_root):
    from agent_runtime import serve_rpc
    from agent_runtime.call_authorization import TIER_CONSOLE

    missed = _episode("ends", EpisodeState.MISSED, missed_deadline_ms=1_000)
    LensStore().save_episode(missed)

    _decide(missed, "snooze15m")

    events = [evt.payload for _, evt in EventLog().iter_from_offset(0) if evt.type == "lens.episode.changed"]
    assert [body["state"] for body in events] == ["missed", "missed"]
    assert serve_rpc.method_tier("runtime.lens.episode.decide") == TIER_CONSOLE
