"""The exit door re-checks admission on the STORED Episode (row ``RT-LENS-DOOR-ADMITS-STALE-EPISODE``).

``LensForge.admit`` decides on an Episode it read before its receipt transaction. Each test runs
the operator's decision deterministically between that read and ``save_receipts`` (``RacingStore``
runs it once, on the door's first receipt write).

Gates and their killing mutation (red recorded in the row's commit):

* a ``dismiss`` / ``snooze15m`` written between the door's read and its receipt forges no turn and
  settles the receipt ``skipped_decided`` — killed by ``store_episode_rows.stale_pairs`` returning
  ``[]`` (the tick answers ``["forged"]`` / ``["notified"]``);
* positive control: the same Episode with no interleaved decision forges its turn.
"""

from __future__ import annotations

import pytest
from test_lens_exit_door import T0, _episode, _monitor, door  # noqa: F401 — ``door`` is a fixture

from agent_runtime.lens.episode import Decision
from agent_runtime.lens.store import LensStore, MonitorState, ReceiptOutcome
from agent_runtime.lens.store_decisions import decide_episode
from agent_runtime.lens.trigger import LensForge


class RacingStore(LensStore):
    """Runs ``interleave`` once, inside the door's first receipt write, before its transaction."""

    def __init__(self) -> None:
        super().__init__()
        self.interleave = None

    def save_receipts(self, pairs, **kwargs):
        once, self.interleave = self.interleave, None
        if once is not None:
            once()
        return super().save_receipts(pairs, **kwargs)


def _armed(**monitor) -> RacingStore:
    store = RacingStore()
    store.create(_monitor(**monitor))
    store.seal("status")
    store.set_state("status", MonitorState.ENABLED)
    store.save_episode(_episode(1))
    return store


def _forge(store: LensStore) -> LensForge:
    return LensForge(store_factory=lambda: store, clock=lambda: T0)


@pytest.mark.parametrize("decision", [Decision.DISMISS, Decision.SNOOZE_15M])
def test_a_decision_between_the_doors_read_and_its_receipt_forges_no_turn(door, decision):  # noqa: F811
    store = _armed()
    episode_id = _episode(1).id
    store.interleave = lambda: decide_episode(store, episode_id, decision, T0)

    assert _forge(store).tick() == []

    assert door.calls == [], "the turn ran on an Episode the operator had already decided"
    receipt = store.receipt(episode_id)
    assert (receipt["outcome"], receipt["turn_id"], receipt["tool_admission"]) == (
        ReceiptOutcome.SKIPPED_DECIDED.value, ReceiptOutcome.SKIPPED_DECIDED.value, "none")
    stored = store.latest_episode("status", "cpu_hot")
    assert stored.decision is decision, "the operator's word stands"
    assert stored.turn_id == ReceiptOutcome.SKIPPED_DECIDED.value
    assert _forge(store).tick() == [] and door.calls == []


def test_a_notification_is_skipped_too(door):  # noqa: F811
    store = _armed(level="notify")
    episode_id = _episode(1).id
    store.interleave = lambda: decide_episode(store, episode_id, Decision.DISMISS, T0)

    assert _forge(store).tick() == []
    assert store.receipt(episode_id)["outcome"] == ReceiptOutcome.SKIPPED_DECIDED.value
    assert store.receipts_today("status", T0) == 0, "a skip spends no cap"


def test_positive_control_no_decision_forges_the_turn(door):  # noqa: F811
    store = _armed()

    assert _forge(store).tick() == ["forged"]
    assert len(door.calls) == 1
