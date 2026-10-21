"""Lens receipt retention (RT-LENS-RECEIPT-RETENTION, plan ``lens-receipt-retention-2026-10-21.md``).

Receipts older than ``RECEIPT_RETENTION`` fold into ``receipt_rollups`` (a count per monitor,
UTC day and outcome), their settled Episodes and artifact folders go with them, and a second
pass at the same instant moves nothing. The home is the test's isolated ``HERMES_HOME``.

Killing mutations (each red recorded in its stage's commit):

* L1: fold AFTER the delete -> the rollup counts are empty; drop the ``state != 'active'``
  filter -> the old active Episode is deleted.
* L2: raise ``RECEIPTS_FULL`` at the fence as before -> the Episode is never settled (owed forever).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, UTC

from agent_runtime.lens.artifacts import episode_folder
from agent_runtime.lens.episode import Episode, EpisodeState
from agent_runtime.lens.retention import RECEIPT_RETENTION, ReceiptFoldReceipt, fold_receipts
from agent_runtime.lens.store import LensStore, ReceiptOutcome, to_ms

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
OUTCOMES = (ReceiptOutcome.FORGED.value, ReceiptOutcome.NOTIFIED.value, ReceiptOutcome.CAPPED.value)


def _episode(monitor_id: str, ordinal: int, at: datetime, state: EpisodeState) -> Episode:
    return Episode(monitor_id=monitor_id, rule_id="cpu_hot", ordinal=ordinal, first_seen=at, last_seen=at,
                   count=1, state=state)


def _seeded() -> tuple[LensStore, list[tuple[Episode, dict]]]:
    """40 receipts over 45 days, two monitors, mixed outcomes; ordinal 1 of ``m1`` is old and active."""

    store, rows = LensStore(), []
    for index in range(40):
        monitor_id = ("m1", "m2")[index % 2]
        ordinal = index // 2 + 1
        at = NOW - timedelta(days=45 - index * 45 / 40, hours=1)
        state = EpisodeState.ACTIVE if (monitor_id, ordinal) == ("m1", 1) else EpisodeState.RESOLVED
        episode = _episode(monitor_id, ordinal, at, state)
        receipt = {"episode_id": episode.id, "monitor_id": monitor_id, "turn_id": f"lens-episode-{episode.id}",
                   "started_ms": to_ms(at), "outcome": OUTCOMES[index % 3], "tool_admission": "full"}
        assert store.save_receipt(receipt, episode=episode)
        folder = episode_folder(episode.id)
        folder.mkdir(parents=True)
        (folder / "report.md").write_text("done", encoding="utf-8")
        rows.append((episode, receipt))
    return store, rows


def _rollups(store: LensStore) -> Counter:
    with store.connection() as conn:
        return Counter({(m, d, o): c for m, d, o, c in conn.execute(
            "SELECT monitor_id, day_ms, outcome, count FROM receipt_rollups")})


def test_one_pass_folds_old_receipts_and_keeps_the_month():
    store, rows = _seeded()
    cutoff = to_ms(NOW - RECEIPT_RETENTION)
    old = [(e, r) for e, r in rows if r["started_ms"] < cutoff]
    young = [(e, r) for e, r in rows if r["started_ms"] >= cutoff]
    assert old and young

    receipt = fold_receipts(store, NOW)

    assert receipt.receipts_folded == len(old)
    assert {r["episode_id"] for r in store.receipts(limit=100)} == {r["episode_id"] for _, r in young}
    expected = Counter((r["monitor_id"], r["started_ms"] // 86_400_000 * 86_400_000, r["outcome"]) for _, r in old)
    assert _rollups(store) == expected
    kept = {row["id"] for row in store.episodes(limit=1000)}
    old_active = next(e for e, _ in old if e.state is EpisodeState.ACTIVE)
    assert old_active.id in kept  # an active Episode is never retention's to delete
    assert all(e.id not in kept for e, _ in old if e.state is not EpisodeState.ACTIVE)
    assert all(e.id in kept for e, _ in young)
    assert receipt.episodes_deleted == len(old) - 1
    assert all(not episode_folder(e.id).exists() for e, _ in old)
    assert all((episode_folder(e.id) / "report.md").is_file() for e, _ in young)
    assert receipt.folders_removed == len(old)


def test_a_second_pass_at_the_same_instant_moves_nothing():
    store, _ = _seeded()
    fold_receipts(store, NOW)
    before = _rollups(store)

    assert fold_receipts(store, NOW) == ReceiptFoldReceipt(0, 0, 0)
    assert _rollups(store) == before


def test_the_newest_episode_of_a_rule_is_kept_so_no_ordinal_is_reused():
    store = LensStore()
    at = NOW - timedelta(days=40)
    for ordinal in (1, 2):
        episode = _episode("m1", ordinal, at, EpisodeState.RESOLVED)
        store.save_receipt({"episode_id": episode.id, "monitor_id": "m1", "turn_id": "notified",
                            "started_ms": to_ms(at), "outcome": "notified", "tool_admission": "full"},
                           episode=episode)

    assert fold_receipts(store, NOW).episodes_deleted == 1
    assert [row["ordinal"] for row in store.episodes()] == [2]
    assert store.latest_episode("m1", "cpu_hot").ordinal == 2


# --- L2 the fence -------------------------------------------------------------------


def _young_or_old(store: LensStore, count: int, at: datetime) -> None:
    for ordinal in range(1, count + 1):
        episode = _episode("m1", ordinal, at, EpisodeState.RESOLVED)
        assert store.save_receipt({"episode_id": episode.id, "monitor_id": "m1", "turn_id": "notified",
                                   "started_ms": to_ms(at), "outcome": "notified", "tool_admission": "full"},
                                  episode=episode)


def _owed(ordinal: int = 99) -> tuple[Episode, dict]:
    episode = _episode("m2", ordinal, NOW, EpisodeState.ACTIVE)
    turn_id = f"lens-episode-{episode.id}"
    return episode, {"episode_id": episode.id, "monitor_id": "m2", "turn_id": turn_id, "started_ms": to_ms(NOW),
                     "outcome": ReceiptOutcome.FORGING.value, "tool_admission": "full"}


def test_at_the_fence_expired_receipts_make_room(monkeypatch):
    from dataclasses import replace

    from agent_runtime.lens import store as store_module

    monkeypatch.setattr(store_module, "MAXIMUM_RECEIPTS", 3)
    store = LensStore()
    _young_or_old(store, 3, NOW - timedelta(days=31))
    episode, receipt = _owed()

    assert store.save_receipt(receipt, episode=replace(episode, turn_id=receipt["turn_id"])) is True
    assert [r["episode_id"] for r in store.receipts()] == [episode.id]


def test_still_full_settles_the_episode_with_no_receipt(monkeypatch, caplog):
    from dataclasses import replace

    from agent_runtime.lens import store as store_module
    from agent_runtime.lens.episode import needs_admission

    monkeypatch.setattr(store_module, "MAXIMUM_RECEIPTS", 3)
    store = LensStore()
    _young_or_old(store, 3, NOW - timedelta(days=2))
    episode, receipt = _owed()
    store.save_episode(episode)
    assert needs_admission(episode, NOW)

    with caplog.at_level(logging.WARNING, logger="agent_runtime.lens.store"):
        assert store.save_receipt(receipt, episode=replace(episode, turn_id=receipt["turn_id"])) is False

    assert not store.has_receipt(episode.id)
    [row] = [r for r in store.episodes() if r["id"] == episode.id]
    assert row["turn_id"] == "receipts_full"
    assert not needs_admission(Episode.from_json(row), NOW)  # settled: the next tick forges nothing
    assert f"[LensReceiptsFull] monitor=m2 episode={episode.id}" in caplog.text
