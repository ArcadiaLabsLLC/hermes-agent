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


# --- taking the team's copy of a held desk leaves nothing to publish ---------------------------------------
# RT-REALM-TAKING-THE-TEAMS-COPY-OF-A-HELD-DESK-LEAVES-UNPUBLISHED-CHANGES (review w1118a.38 D5): both take-remote
# arms of ``office resolve-conflict`` settle that ONE desk's baseline (``office_sync.settle_office_actor_baseline``),
# and the delete arm archives as the pull does (no tombstone of Bob's). Bob's other unpublished desk stays his.


def _office_drift(realm_id: str) -> dict[str, int]:
    return realm_sync_status(realm_id)["store_drift"]["office"]


def _bobs_own_desk(workspace_id: str) -> None:
    OfficeStore().upsert_actor(workspace_id, {"persona_id": "ops", "items": [
        {"item_id": "ops", "persona_id": "ops", "kind": "agent", "position": [6.0, 3.0], "folder": "Agents"}]})


@pytest.mark.parametrize("tombstone", [True, False], ids=["delete-from-eternia", "file-removed-without-tombstone"])
def test_taking_the_teams_delete_of_a_held_desk_leaves_nothing_to_publish(team, tombstone):
    """Bob moves the desk and adds one of his own, unpublished; Alice deletes the desk and publishes. Bob's
    pull holds it; he takes the team's copy. Nothing is left to publish but his own desk. The second case is the
    live read's teammate, whose delete reached the realm with no tombstone on the surface.

    Mutations, each red: drop the settle in the delete arm -> ``actors_removed`` 1 (both cases); record the
    tombstone again (``record_tombstone=False`` dropped) -> ``offices_changed`` 1 (second case); the helper also
    records every other desk of the workspace -> ``actors_added`` 0 (Bob's own desk blessed)."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    _desk(workspace.id, 9.5)
    _bobs_own_desk(workspace.id)
    team.be("alice")
    OfficeStore().remove_actor(workspace.id, "dev", record_tombstone=tombstone)
    publish_realm_sync(shared.id)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert pulled["office_sync"]["held"] == [{"workspace_id": workspace.id, "actor_key": "dev", "kind": "edit_vs_remove"}]

    OfficeStore().resolve_conflict(workspace.id, "dev", take="remote")
    assert [actor.actor_key for actor in OfficeStore().scan_actors(workspace.id).actors] == ["ops"]
    drift = _office_drift(shared.id)
    assert (drift["offices_changed"], drift["actors_changed"], drift["actors_removed"]) == (0, 0, 0)
    assert drift["actors_added"] == 1

    assert publish_realm_sync(shared.id)["state"] == "published"
    assert [name.rsplit("/", 1)[-1] for name in _remote_files(team, shared, "/actors/")] == ["ops.json"]


def test_taking_the_teams_edit_of_a_held_desk_leaves_nothing_to_publish(team):
    """Bob and Alice both move the desk; Alice publishes first. Bob's pull holds it; he takes the team's copy,
    and only his own new desk is left to publish.

    Mutation: drop the settle in the adopt arm -> ``actors_changed`` 1."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    _desk(workspace.id, 9.5)
    _bobs_own_desk(workspace.id)
    team.be("alice")
    _desk(workspace.id, -4.0)
    publish_realm_sync(shared.id)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert [row["actor_key"] for row in pulled["office_sync"]["held"]] == ["dev"]

    taken = OfficeStore().resolve_conflict(workspace.id, "dev", take="remote")
    assert taken.items[0].position[0] == -4.0
    drift = _office_drift(shared.id)
    assert (drift["offices_changed"], drift["actors_changed"], drift["actors_removed"]) == (0, 0, 0)
    assert drift["actors_added"] == 1


def test_keeping_my_copy_of_a_held_desk_still_reads_as_mine_to_publish(team):
    """Take-local is unchanged: Bob keeps his move over Alice's delete, and it reads as his change to publish.

    Mutation: settle the baseline in the take-local arm too -> ``actors_changed`` 0."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    _desk(workspace.id, 9.5)
    team.be("alice")
    OfficeStore().remove_actor(workspace.id, "dev")
    publish_realm_sync(shared.id)

    team.be("bob")
    pull_realm_sync(shared.id)
    OfficeStore().resolve_conflict(workspace.id, "dev", take="local")
    assert _office_drift(shared.id)["actors_changed"] == 1
