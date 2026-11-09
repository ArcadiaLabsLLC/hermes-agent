"""Lens workspace scope and ORPHANED Episodes (row ``RT-LENS-WORKSPACE-SCOPE-AND-ORPHANS``,
``agent_runtime/lens/store_scope.py``).

Gates and their killing mutations (each red recorded in the row's commit):

* a ``workspace_id`` read answers only that workspace's monitors and Episodes, an absent one
  every workspace, and every served Episode row names its workspace — killed by dropping the
  ``workspace_id`` clause from ``LensStore.episodes``;
* a create without ``workspace_id`` belongs to the active workspace — killed by dropping
  ``or active_workspace_id()`` from ``runtime.lens.create``;
* a store written before the column gains it and its monitors read NULL — killed by not
  calling ``_add_workspace_column`` when the store opens;
* an open Episode whose monitor is gone or paused is served ``orphan`` and
  ``episodes.close_orphans`` resolves it, an enabled monitor's stays open — killed by
  ``orphan_reason`` answering None for a monitor it does not know;
* retiring a monitor resolves its open Episodes — killed by dropping the ``close_orphans``
  call from ``LensStore.set_state``;
* a Dismiss of an orphan resolves it while a Dismiss on an observed Episode keeps it active —
  killed by dropping the orphan branch from ``decide_episode``;
* ``episode.close`` resolves the ONE orphan it names and leaves its sibling orphan open —
  killed by closing every orphan instead of the named row (RT-LENS-EPISODE-CLOSE-ONE);
* ``episode.close`` refuses an Episode its monitor still observes ``episode_not_orphaned`` and
  leaves it active — killed by dropping the ``orphan_reason`` guard from ``close_orphan``;
* a second Close is ``episode_settled``, an unknown id or one outside the given workspace
  ``episode_not_found`` — killed by dropping the ``workspace_id`` check from ``close_orphan``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from agent_runtime.lens.episode import Episode, EpisodeState
from agent_runtime.lens.store import LensStore, MonitorState

T0 = datetime(2026, 11, 8, 9, tzinfo=UTC)


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert "error" not in reply, reply
    return reply["result"]


def _manifest(monitor_id: str) -> dict:
    feed = {"version": 1, "id": "latency", "kind": "http_json", "interval_ms": 60_000,
            "source": {"url": "https://status.example.invalid/api", "selector": "$.latency"}}
    return {"version": 1, "monitor_id": monitor_id, "feeds": [feed], "rules": [],
            "automation": {"level": "notify", "when": "always", "daily_turn_cap": 4}, "persona_id": None}


def _monitor(monitor_id: str, workspace_id: str | None, state: MonitorState = MonitorState.ENABLED) -> None:
    params = {"manifest": _manifest(monitor_id)}
    if workspace_id is not None:
        params["workspace_id"] = workspace_id
    _rpc("runtime.lens.create", params)
    store = LensStore()
    store.seal(monitor_id)
    store.set_state(monitor_id, state)


def _episode(monitor_id: str, state: EpisodeState = EpisodeState.ACTIVE) -> Episode:
    episode = Episode(monitor_id=monitor_id, rule_id="slow", ordinal=1, first_seen=T0, last_seen=T0, count=1,
                      state=state)
    LensStore().save_episode(episode)
    return episode


def _episodes(**params) -> dict[str, dict]:
    return {row["monitor_id"]: row for row in _rpc("runtime.lens.episodes", params)["episodes"]}


def test_a_workspace_read_answers_only_that_workspace_and_an_absent_one_every_workspace():
    _monitor("alpha", "ws_a")
    _monitor("beta", "ws_b")
    _episode("alpha")
    _episode("beta")

    scoped = _episodes(workspace_id="ws_a")
    assert set(scoped) == {"alpha"}
    assert scoped["alpha"]["workspace_id"] == "ws_a" and scoped["alpha"]["orphan"] is None
    every = _episodes()
    assert {name: row["workspace_id"] for name, row in every.items()} == {"alpha": "ws_a", "beta": "ws_b"}

    listed = _rpc("runtime.lens.list", {"workspace_id": "ws_b"})["monitors"]
    assert [(row["monitor_id"], row["workspace_id"]) for row in listed] == [("beta", "ws_b")]
    assert {row["monitor_id"] for row in _rpc("runtime.lens.list", {})["monitors"]} == {"alpha", "beta"}
    fold = _rpc("runtime.lens.fold", {"workspace_id": "ws_a"})
    assert fold["monitors_enabled"] == 1
    assert [row["monitor_id"] for row in fold["open_episodes"]] == ["alpha"]


def test_a_create_without_a_workspace_belongs_to_the_active_one(monkeypatch):
    from agent_runtime.lens import store_scope

    monkeypatch.setattr(store_scope, "active_workspace_id", lambda: "ws_active")
    _monitor("gamma", None)

    assert LensStore().get("gamma")["workspace_id"] == "ws_active"
    assert [row["monitor_id"] for row in _rpc("runtime.lens.list", {"workspace_id": "ws_active"})["monitors"]] \
        == ["gamma"]


def test_a_store_written_before_the_column_gains_it_and_reads_null():
    _monitor("legacy", "ws_a")
    store = LensStore()
    with store.connection() as conn:
        db = conn.execute("PRAGMA database_list").fetchone()[2]
    raw = sqlite3.connect(db)
    raw.execute("ALTER TABLE monitors DROP COLUMN workspace_id")
    raw.commit()
    raw.close()

    assert LensStore().get("legacy")["workspace_id"] is None
    assert _rpc("runtime.lens.list", {"workspace_id": "ws_a"})["monitors"] == []
    assert [row["monitor_id"] for row in _rpc("runtime.lens.list", {})["monitors"]] == ["legacy"]


def test_an_orphan_is_served_as_one_and_close_orphans_resolves_only_orphans():
    _monitor("watched", "ws_a")
    _monitor("paused", "ws_a", MonitorState.PAUSED)
    _episode("watched")
    _episode("paused")
    _episode("gone", EpisodeState.RECOVERED)  # its monitor was never stored (or is gone)

    served = _episodes()
    assert {name: row["orphan"] for name, row in served.items()} == {
        "watched": None, "paused": "monitor_paused", "gone": "monitor_gone"}

    closed = _rpc("runtime.lens.episodes.close_orphans", {})["closed"]
    assert sorted((row["monitor_id"], row["state"], row["decision"]) for row in closed) == [
        ("gone", "resolved", "dismiss"), ("paused", "resolved", "dismiss")]
    assert {name: row["state"] for name, row in _episodes().items()} == {
        "watched": "active", "paused": "resolved", "gone": "resolved"}
    assert _rpc("runtime.lens.episodes.close_orphans", {})["closed"] == [], "a second call finds none"


def test_close_orphans_keeps_to_the_workspace_it_is_given():
    _monitor("here", "ws_a", MonitorState.PAUSED)
    _monitor("there", "ws_b", MonitorState.PAUSED)
    _episode("here")
    _episode("there")

    closed = _rpc("runtime.lens.episodes.close_orphans", {"workspace_id": "ws_a"})["closed"]
    assert [row["monitor_id"] for row in closed] == ["here"]
    assert _episodes()["there"]["state"] == "active"


def test_retiring_a_monitor_resolves_its_open_episodes():
    _monitor("retiring", "ws_a")
    _monitor("staying", "ws_a")
    _episode("retiring")
    _episode("staying")

    LensStore().set_state("retiring", MonitorState.RETIRED)

    assert {name: row["state"] for name, row in _episodes().items()} == {"retiring": "resolved", "staying": "active"}


def test_a_dismissed_orphan_is_resolved_and_a_dismissed_observed_episode_stays_open():
    _monitor("watched", "ws_a")
    orphan = _episode("gone")
    observed = _episode("watched")

    dismissed = _rpc("runtime.lens.episode.decide", {"episode_id": orphan.id, "decision": "dismiss"})
    kept = _rpc("runtime.lens.episode.decide", {"episode_id": observed.id, "decision": "dismiss"})

    assert (dismissed["state"], dismissed["decision"]) == ("resolved", "dismiss")
    assert (kept["state"], kept["decision"]) == ("active", "dismiss")


def _refusal(method: str, params: dict) -> tuple[int, str]:
    from agent_runtime import serve_rpc

    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert "error" in reply, reply
    return reply["error"]["code"], reply["error"]["data"]["reason"]


def test_episode_close_resolves_only_the_one_orphan_it_names():
    _monitor("paused", "ws_a", MonitorState.PAUSED)
    named = _episode("paused")
    sibling = _episode("gone")

    closed = _rpc("runtime.lens.episode.close", {"episode_id": named.id})["closed"]

    assert [(row["id"], row["state"], row["decision"]) for row in closed] == [(named.id, "resolved", "dismiss")]
    assert {name: (row["state"], row["orphan"]) for name, row in _episodes().items()} == {
        "paused": ("resolved", None), "gone": ("active", "monitor_gone")}, sibling.id


def test_episode_close_refuses_an_observed_episode_and_leaves_it_active():
    from agent_runtime.serve_rpc.protocol import ERR_CONFLICT

    _monitor("watched", "ws_a")
    observed = _episode("watched")

    assert _refusal("runtime.lens.episode.close", {"episode_id": observed.id}) == (ERR_CONFLICT, "episode_not_orphaned")
    assert _episodes()["watched"]["state"] == "active"


def test_episode_close_refuses_a_second_close_an_unknown_id_and_another_workspace():
    from agent_runtime.lens.episode import episode_id
    from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_NOT_FOUND

    _monitor("here", "ws_a", MonitorState.PAUSED)
    _monitor("there", "ws_b", MonitorState.PAUSED)
    here = _episode("here")
    there = _episode("there")

    assert _refusal("runtime.lens.episode.close", {"episode_id": there.id, "workspace_id": "ws_a"}) == (
        ERR_NOT_FOUND, "episode_not_found")
    assert _episodes()["there"]["state"] == "active"
    unknown = episode_id("nobody", "slow", 1)
    assert _refusal("runtime.lens.episode.close", {"episode_id": unknown}) == (ERR_NOT_FOUND, "episode_not_found")

    assert _rpc("runtime.lens.episode.close", {"episode_id": here.id, "workspace_id": "ws_a"})["closed"][0]["id"] \
        == here.id
    assert _refusal("runtime.lens.episode.close", {"episode_id": here.id}) == (ERR_CONFLICT, "episode_settled")
