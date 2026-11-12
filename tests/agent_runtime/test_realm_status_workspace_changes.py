"""`realm sync status` names what the next publish does to the realm's workspaces.

RT-REALM-STATUS-MISSES-A-WAITING-WORKSPACE-LEAVE: a workspace moved out of a synced realm, or deleted from it,
waited in the realm's delete ledger while status answered ``unpublished_changes: false`` — the member's next
publish then took it from the team with nothing having said so. Reproduced first through real ``hermes harness``
child processes (one runtime root, a bare remote: move, delete, status, publish, status) and pinned here through
the app's doors (``runtime.realm.sync.status``, ``runtime.workspace.move_realm``), every scenario with sync runs.

Killing mutations are named per test.
"""
from __future__ import annotations

import pytest

from agent_runtime import serve_rpc
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.store import RealmStore, WorkspaceStore
from tests.agent_runtime.test_workspace_move_leaves_every_realm import _own_realm
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team, _gone, _move, _shared_workspace


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _status(realm_id: str) -> dict:
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "st", "method": "runtime.realm.sync.status", "params": {"realm_id": realm_id}})
    assert "error" not in reply, reply
    return reply["result"]


def _changes(realm_id: str) -> tuple[bool, list[tuple]]:
    """``(unpublished_changes, [(workspace_id, change, to_realm_id)])`` as the app reads them."""
    status = _status(realm_id)
    return status["unpublished_changes"], [
        (row["workspace_id"], row["change"], row["to_realm_id"]) for row in status["workspace_changes"]]


def _rows(realm_id: str) -> list[tuple]:
    """The rows alone — for a team fixture whose two members share this process's skills folder, where the
    flag is also lit by skill drift that is not this file's subject (the own-realm test pins the flag)."""
    return _changes(realm_id)[1]


def test_a_move_out_of_a_shared_realm_is_named_until_the_mover_publishes(team):
    """Alice moves the team's workspace into a realm of her own. Until she publishes, Bob still has it — and
    her status says so, naming the workspace, the realm it leaves and the realm it went to.

    Mutation: in ``workspace_publish_changes`` drop the loop over the files the clone holds and the publish
    no longer ships -> no ``left`` row, red."""
    shared, workspace = _shared_workspace(team)
    assert _rows(shared.id) == []
    private = RealmStore().create(name="Private")
    _move(workspace_id=workspace.id, realm_id=private.id, confirm_leave_realm=shared.id)

    status = _status(shared.id)
    assert status["unpublished_changes"] is True
    assert status["workspace_changes"] == [{
        "workspace_id": workspace.id, "name": "Roadmap", "change": "left",
        "realm_id": shared.id, "realm_name": "Team Realm",
        "to_realm_id": private.id, "to_realm_name": "Private",
    }]
    # A sync run in between changes nothing: the leave is still only on Alice's machine.
    pull_realm_sync(shared.id)
    assert _rows(shared.id) == [(workspace.id, "left", private.id)]
    team.be("bob")
    pull_realm_sync(shared.id)
    assert WorkspaceStore().get(workspace.id).realm_id == shared.id
    assert _rows(shared.id) == []

    team.be("alice")
    publish_realm_sync(shared.id)
    assert _rows(shared.id) == []
    team.be("bob")
    pull_realm_sync(shared.id)
    _gone(workspace.id)
    assert _rows(shared.id) == []


def test_a_delete_a_move_and_an_arrival_between_your_own_realms_are_each_named(team):
    """One player, two of her own realms in one personal repo: Roadmap moves Home -> Studio, Notes is deleted.

    Mutations: in ``workspace_publish_changes`` answer ``left`` for every removed file -> the deleted Notes
    reads as a move, red; drop the ``added`` arm -> Studio says nothing waits while Roadmap is not in the
    team's copy of it, red."""
    home = _own_realm(team, "desk", "Home")
    studio = _own_realm(team, "desk", "Studio")
    roadmap = WorkspaceStore().create(name="Roadmap", realm_id=home.id)
    notes = WorkspaceStore().create(name="Notes", realm_id=home.id)
    publish_realm_sync(home.id)
    publish_realm_sync(studio.id)
    assert _changes(home.id) == (False, []) and _changes(studio.id) == (False, [])

    _move(workspace_id=roadmap.id, realm_id=studio.id)
    WorkspaceStore().delete(notes.id)
    pull_realm_sync(home.id)  # a sync run that is not the publish: the rows stay
    home_rows = {row["workspace_id"]: row for row in _status(home.id)["workspace_changes"]}
    assert {key: (row["change"], row["name"], row["to_realm_name"]) for key, row in home_rows.items()} == {
        roadmap.id: ("left", "Roadmap", "Studio"), notes.id: ("deleted", "Notes", None)}
    assert _changes(home.id)[0] is True
    assert _changes(studio.id) == (True, [(roadmap.id, "added", None)])

    publish_realm_sync(studio.id)
    publish_realm_sync(home.id)
    assert _changes(home.id) == (False, []) and _changes(studio.id) == (False, [])


def test_a_rename_waits_as_changed_and_a_realm_never_published_has_nothing_waiting(team):
    """Mutations: drop ``or workspace_changes`` from ``unpublished_changes`` in ``realm_sync_status`` -> the
    flag reads False over the waiting rename, red; in ``workspace_publish_changes`` drop the never-published guard (no realm record in the
    clone's subtree -> no rows) -> a device-only realm reads ``unpublished_changes: true`` for every workspace
    it holds, red; make ``workspace_file_published`` answer True -> the rename is not named and the
    per-workspace state reads ``published``, red."""
    team.be("alice")
    solo = RealmStore().create(name="Solo")
    WorkspaceStore().create(name="Scratch", realm_id=solo.id)
    assert _changes(solo.id) == (False, [])

    shared, workspace = _shared_workspace(team, members=())
    assert _status(shared.id)["workspace_statuses"] == [{"workspace_id": workspace.id, "state": "published"}]
    WorkspaceStore().rename(workspace.id, "Roadmap 2027")
    status = _status(shared.id)
    assert status["unpublished_changes"] is True
    assert [(row["workspace_id"], row["name"], row["change"]) for row in status["workspace_changes"]] == [
        (workspace.id, "Roadmap 2027", "changed")]
    assert status["workspace_statuses"] == [{"workspace_id": workspace.id, "state": "unpublished"}]
    publish_realm_sync(shared.id)
    status = _status(shared.id)
    assert (status["unpublished_changes"], status["workspace_changes"]) == (False, [])
    assert status["workspace_statuses"] == [{"workspace_id": workspace.id, "state": "published"}]


def test_a_skill_deleted_for_the_realm_waits_until_it_is_published(team):
    """The team's copy still carries a skill this member deleted for the whole realm: status lists it as
    waiting and says there is something to publish; a pull in between changes nothing; the publish clears it.

    Mutations: make ``_skill_deletes_waiting`` answer ``[]`` -> the waiting delete is not listed, red; drop
    ``or skill_deletes_waiting`` from ``unpublished_changes`` -> the flag reads False over it, red."""
    from pathlib import Path

    from agent_runtime.skill_promotion import iter_skill_packages
    from tests.agent_runtime.test_realm_leave import _git

    home = _own_realm(team, "desk", "Home")
    publish_realm_sync(home.id)
    clone, slug = Path(home.sync_manifest_ref), "doomed"
    published = clone / "realms" / home.id / "skills"
    (published / slug).mkdir(parents=True)
    (published / slug / "SKILL.md").write_bytes(b"---\nname: doomed\n---\n# v1\n")
    _git(clone, "add", "-A")
    _git(clone, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "-m", "a teammate's skill")
    _git(clone, "push", "-q", "origin", "HEAD:main")
    pull_realm_sync(home.id)  # adopts the skill here and records its baseline
    publish_realm_sync(home.id)  # and this home's own skills ship, so nothing else is left to publish
    before = _status(home.id)
    assert (before["unpublished_changes"], before["skill_deletes_waiting"]) == (False, [])

    RealmStore().tombstone_skill(home.id, slug)
    pull_realm_sync(home.id)
    waiting = _status(home.id)
    assert (waiting["unpublished_changes"], waiting["skill_deletes_waiting"]) == (True, [slug])

    publish_realm_sync(home.id)
    after = _status(home.id)
    assert (after["unpublished_changes"], after["skill_deletes_waiting"]) == (False, [])
    assert slug not in {name for name, _dir in iter_skill_packages(published)}
