"""Lens Episode writers never write another writer's field back stale (row ``RT-LENS-EPISODE-WRITE-RACE``).

Three threads write one Episode row: the poller (state, ``last_seen``, ``count``), the operator's
decision (``store_decisions.decide_episode``) and the exit door's receipt transaction (``turn_id``).
Each test interleaves the other writer deterministically between a writer's read and its write
(``RacingStore`` runs it inside the first ``move_episode``).

Gates and their killing mutations (each red recorded in the row's commit):

* a decision / a ``turn_id`` written during a poller tick survives the tick, and the tick still
  lands — killed by writing the poller's step without the compare (``move_episode(..., checked=False)``);
* the door sets ``turn_id`` on the row as stored, never on its stale copy — killed by
  ``store_episode_rows.door_owned`` returning the copy it was handed;
* a poller tick during a decision survives the decision — killed by the same unchecked write.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import httpx
from test_lens_exit_door import T0, _monitor

from agent_runtime.lens.episode import Decision, EpisodeState
from agent_runtime.lens.poller import LensPoller
from agent_runtime.lens.store import LensStore, MonitorState, to_ms
from agent_runtime.lens.store_decisions import decide_episode

PUBLIC = ["93.184.216.34"]


class RacingStore(LensStore):
    """Runs ``interleave`` once, inside the first compare-and-set, after its writer read the row."""

    def __init__(self) -> None:
        super().__init__()
        self.interleave = None

    def move_episode(self, expected, episode, **kwargs):
        once, self.interleave = self.interleave, None
        if once is not None:
            once()
        return super().move_episode(expected, episode, **kwargs)


def _breaching() -> tuple[RacingStore, LensPoller, list]:
    store = RacingStore()
    store.create(_monitor(level="notify"))
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    at = [T0]
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"cpu": 95})),
                          follow_redirects=False)
    poller = LensPoller(store_factory=lambda: store, clock=lambda: at[0], client=client,
                        resolver=lambda host: PUBLIC)
    poller.tick()
    at[0] += timedelta(seconds=5)
    return store, poller, at


def _episode(store: LensStore):
    return store.latest_episode("status", "cpu_hot")


def _receipt(episode_id: str) -> dict:
    return {"episode_id": episode_id, "monitor_id": "status", "turn_id": f"lens-episode-{episode_id}",
            "started_ms": to_ms(T0), "outcome": "notified", "tool_admission": "none"}


def test_a_decision_written_during_a_poller_tick_survives_it():
    store, poller, at = _breaching()
    opened = _episode(store)
    store.interleave = lambda: decide_episode(store, opened.id, Decision.INVESTIGATE, at[0])

    poller.tick()

    after = _episode(store)
    assert (after.decision, after.decided_at) == (Decision.INVESTIGATE, at[0]), "the operator's word stands"
    assert (after.count, after.last_seen) == (2, at[0]), "positive control: the tick still landed"


def test_a_turn_id_written_during_a_poller_tick_survives_it():
    store, poller, at = _breaching()
    opened = _episode(store)
    turn = f"lens-episode-{opened.id}"
    store.interleave = lambda: store.save_receipt(_receipt(opened.id), episode=replace(opened, turn_id=turn))

    poller.tick()

    after = _episode(store)
    assert after.turn_id == turn
    assert (after.count, after.last_seen) == (2, at[0])


def test_the_door_sets_turn_id_on_the_row_as_stored_not_on_its_stale_copy():
    store, poller, at = _breaching()
    admitted = _episode(store)
    poller.tick()  # the poller moves the row after the door read it

    store.save_receipt(_receipt(admitted.id), episode=replace(admitted, turn_id=f"lens-episode-{admitted.id}"))

    after = _episode(store)
    assert after.turn_id == f"lens-episode-{admitted.id}"
    assert (after.count, after.last_seen, after.state) == (2, at[0], EpisodeState.ACTIVE)


def test_a_poller_tick_during_a_decision_survives_it():
    store, poller, at = _breaching()
    opened = _episode(store)
    store.interleave = poller.tick

    decide_episode(store, opened.id, Decision.SNOOZE_15M, at[0])

    after = _episode(store)
    assert (after.count, after.last_seen) == (2, at[0]), "the tick between the decision's read and write stands"
    assert after.decision is Decision.SNOOZE_15M and after.suppressed_until == at[0] + timedelta(minutes=15)
