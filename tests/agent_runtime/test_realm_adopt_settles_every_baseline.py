"""Taking the team's copy leaves nothing to publish, for desks, office layouts and drawings alike.

RT-REALM-ADOPTING-THE-TEAMS-COPY-SETTLES-EVERY-BASELINE (review w1118a.40 D11): every adopt — a pull applier, a
take-remote resolve, a revert — records the hash the drift walk computes for the body as written and drops a
baseline entry outside the walk's scope (``agent_runtime.realm_sync.settle``). Two simulated computers
(``_Team``), one local bare remote, both gits. The persona-instance arm is 308a54da63's
(``test_persona_instance_dropped_edge_rounds.py``); the office-actor arm keeps its tests in
``test_realm_sync_publish_keeps_team_copies.py``. Killing mutations are named per test.
"""

from __future__ import annotations

import pytest

from agent_runtime.flow_graph_sync import flow_graph_baseline_key, read_flow_graph_baseline, write_flow_graph_baseline
from agent_runtime.office_store import OfficeStore
from agent_runtime.realm_revert import revert_realm_sync
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.realm_sync.status import realm_sync_status
from tests.agent_runtime.test_realm_member_desk_archived_by_a_pull import AGENT, _git, _shared_agent
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team, _shared_workspace

DRAWING = f"runtime_{AGENT}"


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _items(realm_id: str) -> list[tuple[str, str, str]]:
    return [(str(row["family"]), row["item_key"], row["kind"]) for row in realm_sync_status(realm_id)["store_drift"]["items"]]


def _desk(workspace_id: str, key: str, x: float) -> None:
    OfficeStore().upsert_actor(workspace_id, {"persona_id": key, "items": [
        {"item_id": key, "persona_id": key, "kind": "agent", "position": [x, -2.0], "folder": "Agents"}]})


def _move_the_agents_desk(workspace_id: str) -> None:
    from agent_runtime.serde import to_jsonable

    body = to_jsonable(OfficeStore().get_actor(workspace_id, AGENT))
    body["items"][0]["position"] = [7.0, 7.0]
    OfficeStore().upsert_actor(workspace_id, body)


def _remove_the_desk_file_by_hand(team: _Team, shared) -> None:
    """The live read's teammate: the agent's desk file leaves the realm, its drawing and agent stay."""
    team.be("alice")
    clone = team.clone("alice", shared.server_id)
    _git(clone, "fetch", "-q", "origin")
    _git(clone, "reset", "-q", "--hard", "origin/main")
    desks = [name for name in _git(clone, "ls-files").splitlines() if name.endswith(f"/actors/{AGENT}.json")]
    _git(clone, "rm", "-q", *desks)
    _git(clone, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "-m", "desk file removed")
    _git(clone, "push", "-q", "origin", "HEAD:main")


def test_a_pull_that_keeps_my_own_tombstone_leaves_no_office_layout_change(team):
    """Bob deletes a desk and publishes; Alice puts it back and publishes, so the team's ledger drops Bob's
    tombstone. Bob's pull keeps his own tombstone (the union) and holds the desk; the office layout it wrote is
    settled, so no "office layout changed". Bob's own new desk still reads as his.

    Mutation: ``_reconcile_surface`` stamps ``remote_hash`` again -> an ``office_surface`` ``changed`` row."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    OfficeStore().remove_actor(workspace.id, "dev")
    publish_realm_sync(shared.id)
    team.be("alice")
    pull_realm_sync(shared.id)
    OfficeStore().restore_actor(workspace.id, "dev")
    publish_realm_sync(shared.id)

    team.be("bob")
    _desk(workspace.id, "ops", 6.0)
    pull_realm_sync(shared.id)
    assert "dev" in OfficeStore().get_surface(workspace.id).archived_actor_keys
    assert _items(shared.id) == [("office_actor", "ops", "added")]


def test_a_pull_of_a_desk_removed_by_hand_leaves_its_drawing_unpublished_too(team):
    """The teammate removes only the agent's desk file; Bob's pull archives the desk. The drawing, still in the
    realm, left Bob's shipped desks with it, so it is not "no longer published".

    Mutation: skip ``_release_out_of_scope_baselines`` in ``apply_flow_graph_pull`` -> the ``flow_graph``
    ``removed`` row."""

    shared, workspace, _ = _shared_agent(team)
    _remove_the_desk_file_by_hand(team, shared)
    team.be("bob")
    assert pull_realm_sync(shared.id)["office_sync"]["archived"] == 1
    assert _items(shared.id) == []
    assert flow_graph_baseline_key(DRAWING) not in read_flow_graph_baseline(shared.id)


def test_taking_the_teams_delete_of_a_desk_leaves_its_drawing_unpublished_too(team):
    """Bob moves the agent's desk; the teammate removes the desk file; Bob's pull holds the desk and he takes the
    team's copy. Neither the desk nor its drawing is left to publish.

    Mutation: drop ``settle_flow_graph_scope_for_workspace`` in ``resolve_conflict``'s delete arm -> the
    ``flow_graph`` ``removed`` row."""

    shared, workspace, _ = _shared_agent(team)
    team.be("bob")
    _move_the_agents_desk(workspace.id)
    _remove_the_desk_file_by_hand(team, shared)

    team.be("bob")
    assert [row["actor_key"] for row in pull_realm_sync(shared.id)["office_sync"]["held"]] == [AGENT]
    OfficeStore().resolve_conflict(workspace.id, AGENT, take="remote")
    assert _items(shared.id) == []


def test_reverting_a_drawing_whose_desk_left_leaves_nothing_to_publish(team):
    """A machine an older engine left with the drawing's entry (the pull before this fix kept it): the walk reads
    the drawing ``removed``; Revert all takes the team's copy, and the row is gone after it.

    Mutation: drop ``settle_flow_graph_scope_for_realm`` in ``revert_realm_sync`` -> the row survives the revert."""

    shared, workspace, _ = _shared_agent(team)
    team.be("bob")
    entry = read_flow_graph_baseline(shared.id)[flow_graph_baseline_key(DRAWING)]
    _remove_the_desk_file_by_hand(team, shared)
    team.be("bob")
    pull_realm_sync(shared.id)
    baseline = read_flow_graph_baseline(shared.id)
    baseline[flow_graph_baseline_key(DRAWING)] = entry
    write_flow_graph_baseline(shared.id, baseline)
    assert _items(shared.id) == [("flow_graph", DRAWING, "removed")]

    revert_realm_sync(shared.id, revert_all=True)
    assert _items(shared.id) == []
