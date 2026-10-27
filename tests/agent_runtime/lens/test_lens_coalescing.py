"""Lens W6 — cooldowns, digests and the global turn budget (plan
``LENS_EXTENSIONS_2026-10-27.md`` §3; rows ``RT-LENS-TRIGGER-COALESCING``,
``RT-LENS-GLOBAL-TURN-BUDGET``, ``RT-LENS-DIGEST-WINDOW``).

The exit door's own harness (``test_lens_exit_door.py``): a fake mission-chat handler
bound on the real door, a fixed clock, the test's isolated ``HERMES_HOME``.

Gates and their killing mutations (each red recorded in the row's commit):

* a manifest without the new keys keeps its seal digest byte-for-byte (the golden was
  sealed on the code before the keys existed) — killed by emitting ``cooldown_ms: 0``
  by default;
* a re-breach inside ``cooldown_ms`` is ``cooled`` with no forge call, and outside it
  forges (positive control) — killed by deleting the cooldown check from ``admit``;
* past ``daily_turn_budget`` the turn is ``notified_over_budget``, a receipt — killed by
  returning None instead, and by deleting the budget check;
* three Episodes in one digest window are one forge call, three receipts, one ``turn_id``,
  and a second door arriving during the turn forges nothing — killed by writing the
  member receipts AFTER the turn, and by skipping the digest gate.
"""

from __future__ import annotations

import copy
from datetime import timedelta

from test_lens_exit_door import T0, _armed, _episode, _monitor, door  # noqa: F401  (door is a fixture)

from agent_runtime.lens.seal import seal_manifest
from agent_runtime.lens.store import to_ms
from agent_runtime.lens.trigger import LensForge

#: ``_monitor()`` sealed at revision 1 on 5027e700fb, before W6's optional keys existed.
GOLDEN_DIGEST = "0ba68ac90953b51e70f1dcadeb23c658d2c3268cdfc110a3ff16f94ea8863301"


def _with(manifest: dict, **automation) -> dict:
    out = copy.deepcopy(manifest)
    out["automation"].update(automation)
    return out


def _at(delta: timedelta) -> LensForge:
    return LensForge(clock=lambda: T0 + delta)


def test_a_manifest_without_the_new_keys_keeps_its_seal_digest():
    assert seal_manifest(_monitor(), revision=1).digest == GOLDEN_DIGEST
    assert "cooldown_ms" not in seal_manifest(_monitor(), revision=1).manifest()["automation"]
    assert seal_manifest(_with(_monitor(), cooldown_ms=60_000), revision=1).manifest()["automation"][
        "cooldown_ms"] == 60_000


def test_a_re_breach_inside_the_cooldown_is_cooled_and_outside_it_forges(door):
    store = _armed(_with(_monitor(), cooldown_ms=10 * 60_000))
    assert _at(timedelta(0)).tick() == ["forged"]

    store.save_episode(_episode(2))
    assert _at(timedelta(minutes=5)).tick() == ["cooled"]
    assert len(door.calls) == 1
    assert store.receipt(_episode(2).id)["tool_admission"] == "none"
    assert store.receipts_today("status", T0) == 1  # a cooled Episode spends no cap

    # Positive control: past the cooldown (measured from the forged receipt, not the cooled one).
    store.save_episode(_episode(3))
    assert _at(timedelta(minutes=11)).tick() == ["forged"]
    assert len(door.calls) == 2


# --- RT-LENS-GLOBAL-TURN-BUDGET -----------------------------------------------------


def _set_budget(turns: int) -> None:
    from agent_runtime.config.loader import harness_root_config_path

    path = harness_root_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"agent_runtime:\n  lens:\n    daily_turn_budget: {turns}\n", encoding="utf-8")


def _armed_other() -> None:
    """A second enabled monitor, ``other``, owing one Episode (``_armed`` arms ``status`` only)."""
    from agent_runtime.lens.episode import Episode, EpisodeState
    from agent_runtime.lens.store import LensStore, MonitorState

    manifest = _monitor()
    manifest["monitor_id"] = "other"
    store = LensStore()
    store.create(manifest)
    store.seal("other")
    store.set_state("other", MonitorState.ENABLED)
    store.save_episode(Episode(monitor_id="other", rule_id="cpu_hot", ordinal=1, first_seen=T0, last_seen=T0,
                               count=1, state=EpisodeState.ACTIVE))


def test_past_the_global_budget_a_turn_is_downgraded_to_a_visible_notify(door):
    _set_budget(2)
    store = _armed(_monitor(), 1, 2)
    _armed_other()

    outcomes = _at(timedelta(0)).tick()

    assert sorted(outcomes) == ["forged", "forged", "notified_over_budget"]
    assert len(door.calls) == 2
    [downgraded] = [r for r in store.receipts(limit=8) if r["outcome"] == "notified_over_budget"]
    assert downgraded["tool_admission"] == "none" and downgraded["turn_id"] == "notified_over_budget"


def test_the_budget_defaults_to_96_and_a_malformed_value_reads_as_it():
    from agent_runtime.lens.settings import lens_setting

    assert lens_setting("daily_turn_budget") == 96
    _set_budget(-3)
    assert lens_setting("daily_turn_budget") == 96
    _set_budget(5)
    assert lens_setting("daily_turn_budget") == 5


# --- RT-LENS-DIGEST-WINDOW ----------------------------------------------------------


def test_episodes_owed_inside_one_window_share_one_turn_and_a_restart_forges_nothing_twice(door):
    from agent_runtime.lens.provenance import lens_client_message_id
    from agent_runtime.lens.store_admission import turns_today
    from agent_runtime.lens.store_digests import digest_id

    store = _armed(_with(_monitor(), digest_window_ms=60_000), 1, 2, 3)
    assert _at(timedelta(0)).tick() == []  # the window opens; every member waits
    assert _at(timedelta(seconds=30)).tick() == [] and door.calls == []  # a restart mid-window

    # A second door (a restart) arrives while the digest's turn runs.
    door.during = lambda args: _at(timedelta(seconds=61)).tick()
    assert _at(timedelta(seconds=60)).tick() == ["forged"]

    [args] = door.calls
    digest = digest_id("status", to_ms(T0))
    assert args.client_message_id == lens_client_message_id(digest)
    assert door.opener.calls[0].idempotency_key == f"{lens_client_message_id(digest)}:chat"
    assert args.message.startswith("[LENS DIGEST — status · 3 episodes]")
    receipts = sorted(store.receipts(limit=8), key=lambda r: r["episode_id"] != _episode(1).id)
    assert [(r["outcome"], r["turn_id"], r["digest_id"]) for r in receipts] == [
        ("forged", lens_client_message_id(digest), digest)] + [
        ("digested", lens_client_message_id(digest), digest)] * 2
    assert store.receipts_today("status", T0) == 1 and turns_today(store, T0) == 1
    assert _at(timedelta(minutes=5)).tick() == [] and len(door.calls) == 1


def test_a_notify_digest_writes_one_notified_leader_and_its_members():
    store = _armed(_with(_monitor(level="notify"), digest_window_ms=60_000), 1, 2)
    _at(timedelta(0)).tick()

    assert _at(timedelta(minutes=1)).tick() == ["notified"]
    assert sorted(r["outcome"] for r in store.receipts()) == ["digested", "notified"]
    # Positive control: an Episode owed after the settle opens the NEXT window, it is not swept in.
    store.save_episode(_episode(3))
    assert _at(timedelta(minutes=1, seconds=1)).tick() == []
