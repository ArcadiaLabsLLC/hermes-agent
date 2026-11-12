"""A move out of ANY realm writes the leave, and a pull that re-homes a workspace leaves the realm that held it.

Three rows, each reproduced first through real ``hermes harness`` child processes (two isolated runtime roots,
one bare remote) and pinned here through the same verbs (``runtime.workspace.move_realm``,
``runtime.workspace.unarchive``, ``runtime.realm.revoked``, the realm adopt, ``publish_realm_sync``,
``pull_realm_sync``), every scenario with the sync runs that rewrite baselines and realm records:

* RT-WORKSPACE-MOVE-OUT-OF-PERSONAL-REPO-REALM — a player's two machines, two of her own realms in one repo;
* RT-WORKSPACE-RESTORED-IN-SOURCE-AFTER-A-MOVE-SITS-IN-TWO-REALMS — another member restores it in the source;
* RT-REJOIN-KEEPS-WORKSPACES-MOVED-WHILE-LOCAL — moved out while the realm was local, then a re-join.

Killing mutations are named per test.
"""
from __future__ import annotations

import shutil

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync
from agent_runtime.store import RealmStore, WorkspaceStore
from tests.agent_runtime.test_realm_leave import _adopt, _team_realm
from tests.agent_runtime.test_realm_leave import _git as _git_out
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team, _move, _shared_workspace


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "mv", "method": method, "params": params})


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _lists(realm_id: str) -> tuple[list[str], list[str]]:
    realm = RealmStore().get(realm_id)
    return list(realm.workspace_ids), list(realm.deleted_workspace_ids)


def _own_realm(team: _Team, machine: str, name: str, realm_id: str | None = None):
    """One of the player's own realms (no server) on ``machine``, synced through her personal repo."""
    team.be(machine)
    realm = RealmStore().create(name=name, realm_id=realm_id) if realm_id else RealmStore().create(name=name)
    realm.sync_manifest_ref = str(team.clone(machine, "personal"))
    return RealmStore().save(realm)


def _published_under(team: _Team, realm_id: str) -> set[str]:
    prefix = f"realms/{paths.safe_path_token(realm_id)}/store/workspaces/"
    names = _git_out(team.remote("personal"), "ls-tree", "-r", "--name-only", "main").splitlines()
    return {name[len(prefix):].removesuffix(".json") for name in names if name.startswith(prefix)}


@pytest.mark.parametrize("desk_pulls", [("home", "studio"), ("studio", "home")])
def test_a_move_between_your_own_realms_stays_moved_on_your_other_machine(team, desk_pulls):
    """The laptop hears of the source realm only, publishes it, and the desk pulls in either order.

    Mutation: in ``move_workspace_realm`` write the leave only ``if source.server_id`` (else the plain
    ``workspace_ids`` removal) -> the laptop keeps the workspace under Home and republishes it there
    (red at ``_published_under(home) == set()``), and the desk's pull of Home puts ``realm_id`` back."""
    home = _own_realm(team, "desk", "Home")
    studio = _own_realm(team, "desk", "Studio")
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=home.id)
    publish_realm_sync(home.id)
    publish_realm_sync(studio.id)
    for realm in (home, studio):
        _own_realm(team, "laptop", realm.name, realm.id)
        pull_realm_sync(realm.id)
    assert WorkspaceStore().get(workspace.id).realm_id == home.id

    team.be("desk")
    moved = _move(workspace_id=workspace.id, realm_id=studio.id)["result"]
    assert (moved["moved"], moved["from_realm_id"], moved["publish_owed"]) == (True, home.id, [])
    assert _lists(home.id) == ([], [workspace.id])
    publish_realm_sync(studio.id)
    publish_realm_sync(home.id)

    team.be("laptop")
    pull_realm_sync(home.id)
    WorkspaceStore().create(name="Notes", realm_id=home.id)
    publish_realm_sync(home.id)
    assert workspace.id not in _published_under(team, home.id)
    assert workspace.id in _published_under(team, studio.id)

    team.be("desk")
    by_name = {"home": home.id, "studio": studio.id}
    for name in desk_pulls:
        pull_realm_sync(by_name[name])
    assert WorkspaceStore().get(workspace.id).realm_id == studio.id
    assert workspace.id not in _lists(home.id)[0] and workspace.id in _lists(studio.id)[0]

    team.be("laptop")
    pull_realm_sync(studio.id)
    pull_realm_sync(home.id)
    assert WorkspaceStore().get(workspace.id).realm_id == studio.id
    assert workspace.id not in _lists(home.id)[0] and workspace.id in _lists(studio.id)[0]


def test_moving_it_back_into_a_local_realm_lifts_the_leave(team):
    """Mutation: drop ``lift_deleted_workspace(target, …)`` in ``move_workspace_realm`` -> Home keeps the id on
    its delete ledger after the workspace came back, red."""
    home = _own_realm(team, "desk", "Home")
    studio = _own_realm(team, "desk", "Studio")
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=home.id)
    _move(workspace_id=workspace.id, realm_id=studio.id)
    assert _lists(home.id) == ([], [workspace.id])
    _move(workspace_id=workspace.id, realm_id=home.id)
    assert _lists(home.id) == ([workspace.id], [])
    assert _lists(studio.id) == ([], [workspace.id])


def test_a_workspace_another_member_restored_after_a_move_ends_in_one_realm(team):
    """Bob's delete is blocked (an undecodable board), so the tombstone keeps his copy archived; he restores
    it and publishes; Alice — who moved it out — pulls.

    Mutation: in ``_overwrite_generic_families`` drop the ``_leave_realms_a_pull_rehomed_from`` call -> her
    private realm still lists the workspace the shared realm now owns, red at ``_lists(private.id)``."""
    shared, workspace = _shared_workspace(team)
    private = RealmStore().create(name="Private")
    _move(workspace_id=workspace.id, realm_id=private.id, confirm_leave_realm=shared.id)
    publish_realm_sync(shared.id)

    team.be("bob")
    broken = paths.boards_root() / "board_broken"
    broken.mkdir(parents=True)
    (broken / "board.json").write_text("{not json", encoding="utf-8")
    assert pull_realm_sync(shared.id)["workspace_tombstones"]["archived"] == [workspace.id]
    shutil.rmtree(broken)
    assert _rpc("runtime.workspace.unarchive", workspace_id=workspace.id)["result"]["restored"] is True
    publish_realm_sync(shared.id)
    assert team.published_workspace_ids(shared) == {workspace.id}

    team.be("alice")
    pull_realm_sync(shared.id)
    assert WorkspaceStore().get(workspace.id).realm_id == shared.id
    assert _lists(shared.id) == ([workspace.id], [])
    assert _lists(private.id) == ([], [workspace.id])
    # Her next publish of the shared realm keeps it there, and a second pull changes nothing.
    publish_realm_sync(shared.id)
    pull_realm_sync(shared.id)
    assert team.published_workspace_ids(shared) == {workspace.id}
    assert WorkspaceStore().get(workspace.id).realm_id == shared.id


def test_a_workspace_moved_out_while_the_realm_was_local_stays_out_after_a_re_join(tmp_path, monkeypatch):
    """Leave the server, move a workspace into your own realm, run a sync while local, join again, pull.

    Mutations: in ``move_workspace_realm`` write the leave only ``if source.server_id`` -> the pull after the
    re-join writes the team's copy back, ``realm_id`` is the team realm again, red;
    in ``_pulled_artifact_bytes`` drop the ``workspace_ids`` filter by the merged ledger -> the team realm
    lists the workspace its own ledger says left, red at ``_lists(realm.id)``."""
    realm, bare, clone = _team_realm(tmp_path)
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=realm.id)
    realm.workspace_ids.append(workspace.id)  # what the create verb writes: the team's record lists it
    RealmStore().save(realm)
    publish_realm_sync(realm.id)
    team_head = _git_out(bare, "rev-parse", "main")
    _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left", server_name="The Guild")
    home = RealmStore().create(name="Home")
    moved = _move(workspace_id=workspace.id, realm_id=home.id)["result"]  # a local realm: no confirm asked
    assert (moved["moved"], moved["publish_owed"]) == (True, [])
    with pytest.raises(RealmSyncError):
        publish_realm_sync(realm.id)  # commits to the local repo, has nowhere to push
    pull_realm_sync(realm.id)

    _adopt(monkeypatch, {"id": realm.id, "server_id": "srv_team", "name": "Team", "slug": "team", "git_url": str(clone)})
    pull_realm_sync(realm.id)

    assert WorkspaceStore().get(workspace.id).realm_id == home.id
    assert _lists(realm.id) == ([], [workspace.id])
    assert _lists(home.id) == ([workspace.id], [])
    # Nothing reached the team by the re-join or the pull: the leave is this member's to publish.
    assert _git_out(bare, "rev-parse", "main") == team_head
    assert f"realms/{realm.id}/store/workspaces/{workspace.id}.json" in _git_out(bare, "ls-tree", "-r", "--name-only", "main")
    publish_realm_sync(realm.id)
    assert f"store/workspaces/{workspace.id}.json" not in _git_out(bare, "ls-tree", "-r", "--name-only", "main")


def test_a_realms_default_workspace_cannot_be_moved_out_while_the_realm_is_local(tmp_path):
    """The row's second half, refuted: the adopt could only refuse ``sync_conflict`` if the default workspace
    had left its realm, and the move refuses that for a local realm as for a bound one."""
    realm, _bare, _clone = _team_realm(tmp_path)
    default = WorkspaceStore().create(name="Default", realm_id=realm.id)
    bound = RealmStore().get(realm.id)
    bound.default_workspace_id = default.id
    RealmStore().save(bound)
    _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left")
    home = RealmStore().create(name="Home")
    refused = _move(workspace_id=default.id, realm_id=home.id)["error"]["data"]
    assert (refused["reason"], refused["realm_id"]) == ("realm_default_workspace", realm.id)
    assert WorkspaceStore().get(default.id).realm_id == realm.id
