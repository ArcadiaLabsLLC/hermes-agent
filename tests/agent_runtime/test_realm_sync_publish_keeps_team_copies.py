"""A publish writes the board and office documents the member changed, and the team's copy of the rest.

Two rules, one module (``agent_runtime.realm_sync.publish_keep``), both gits (``REALM_SYNC_BOTH_ARMS``), one
bare remote on disk per the ``_Team`` harness:

* a document the status's content compare does not name as changed keeps the team's bytes, so a publish after
  a pull no longer rewrites ``updated_by`` on what a teammate edited (RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES);
* a desk a pull HELD (edited here, deleted by the team) is not published until the member chooses
  (RT-REALM-LOCAL-EDIT-OUTLIVES-A-TEAMMATES-DELETE). Killing mutations are named per test.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import board_models, paths
from agent_runtime.board_store import BoardStore
from agent_runtime.office_store import OfficeStore
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.realm_sync.status import realm_sync_status
from agent_runtime.store import WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team, _git, _shared_workspace


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _remote_files(team: _Team, shared, fragment: str) -> dict[str, bytes]:
    remote = team.remote(shared.server_id)
    names = [name for name in _git(remote, "ls-tree", "-r", "--name-only", "main").splitlines() if fragment in name]
    return {name: _git(remote, "show", f"main:{name}").encode("utf-8") for name in names}


def _card(workspace_id: str):
    board_id = board_models.default_board_id(workspace_id)
    return board_id, BoardStore().list_cards(board_id)[0]


def _desk(workspace_id: str, x: float) -> None:
    OfficeStore().upsert_actor(workspace_id, {"persona_id": "dev", "items": [
        {"item_id": "dev", "persona_id": "dev", "kind": "agent", "position": [x, -2.0], "folder": "Agents"}]})


def test_a_publish_after_a_pull_leaves_the_teammates_documents_as_they_were(team):
    """Alice edits the card and the desk; Bob pulls them (the adopters stamp ``updated_by: realm_sync``) and
    publishes a change of his own. The team's card and desk keep Alice's bytes.

    Mutation: drop the content-compare branch in ``publish_keep.keep_team_copies`` -> red: both files carry
    ``realm_sync``."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    board_id, card = _card(workspace.id)
    BoardStore().edit_card(card.card_id, board_id=board_id, title="Ship it today")
    _desk(workspace.id, 4.0)
    publish_realm_sync(shared.id)
    before = {**_remote_files(team, shared, "/cards/"), **_remote_files(team, shared, "/actors/")}
    assert len(before) == 2

    team.be("bob")
    pull_realm_sync(shared.id)
    assert _card(workspace.id)[1].title == "Ship it today"
    WorkspaceStore().rename(workspace.id, "Bob renamed")
    assert publish_realm_sync(shared.id)["state"] == "published"

    after = {**_remote_files(team, shared, "/cards/"), **_remote_files(team, shared, "/actors/")}
    assert after == before
    assert all(b"realm_sync" not in body for body in after.values())
    assert _git(team.remote(shared.server_id), "grep", "-l", "Bob renamed", "main").strip()


def test_a_publish_carries_the_members_own_edit(team):
    """The content compare names Bob's own card edit, so that one document IS written from his store.

    Mutation: always keep the team's bytes in ``publish_keep.keep_team_copies`` (drop its ``not in drifted``
    test) -> red: the remote card keeps the old title."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    board_id, card = _card(workspace.id)
    BoardStore().edit_card(card.card_id, board_id=board_id, title="Bob's title")
    assert publish_realm_sync(shared.id)["state"] == "published"

    (body,) = _remote_files(team, shared, "/cards/").values()
    assert json.loads(body)["title"] == "Bob's title"


def test_a_held_desk_is_not_published_until_the_member_chooses(team):
    """Bob moves the desk without publishing; Alice deletes it and publishes. Bob's pull HOLDS the desk and
    names it; the status offers no Publish for it; Bob's next publish leaves Alice's delete standing; a second
    pull still holds it (the baseline kept its entry); Bob then takes the team's copy.

    Mutations: append the held artifact in ``publish_keep.keep_team_copies`` -> red at the team's desks;
    ``publish_keep.held_baseline_entries`` returns ``new`` unchanged -> red at the second pull (the desk is
    archived without Bob choosing); drop the held test in ``drift._office_store_drift_items`` -> red at the
    status's actor rows."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    _desk(workspace.id, 9.5)
    team.be("alice")
    OfficeStore().remove_actor(workspace.id, "dev")
    publish_realm_sync(shared.id)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert pulled["office_sync"]["held"] == [{"workspace_id": workspace.id, "actor_key": "dev", "kind": "edit_vs_remove"}]
    assert paths.office_conflict_path(workspace.id, "dev").exists()
    status = realm_sync_status(shared.id)
    assert status["store_drift"]["office"]["actors_changed"] == 0

    WorkspaceStore().rename(workspace.id, "Bob renamed")
    assert publish_realm_sync(shared.id)["state"] == "published"
    assert not _remote_files(team, shared, "/actors/")

    again = pull_realm_sync(shared.id)
    assert [row["actor_key"] for row in again["office_sync"]["held"]] == ["dev"]
    assert [actor.actor_key for actor in OfficeStore().scan_actors(workspace.id).actors] == ["dev"]

    OfficeStore().resolve_conflict(workspace.id, "dev", take="remote")
    assert OfficeStore().scan_actors(workspace.id).actors == []
    publish_realm_sync(shared.id)
    assert not _remote_files(team, shared, "/actors/")
