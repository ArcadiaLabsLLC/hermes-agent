"""A pull keeps a workspace or realm change made here since the last publish, instead of putting the team's copy back.

RT-A-TEAM-PULL-PUTS-BACK-A-WORKSPACE-OR-REALM-CHANGED-HERE (review w1118a.50 D7). Seen in Eternia 2026-11-19: a
workspace renamed here after its publish read the team's older name again after Sync's pull. The WORKSPACE and
REALM records now merge field-wise against the copy last published or adopted here
(``agent_runtime.realm_sync.record_merge``): changed only here is kept and published next, changed only by the
team is taken, changed on both sides is held — the team's value is published until the member resolves it.

Two members, one bare remote, the ``_Team`` harness. Killing mutations are named per test.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.realm_sync.record_merge import merge_record
from agent_runtime.realm_sync.status import realm_sync_status
from agent_runtime.realm_verbs import realm_sync_resolve
from agent_runtime.store import RealmStore, WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team, _git, _shared_workspace


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _team_record(team: _Team, shared, family: str, record_id: str) -> dict:
    remote = team.remote(shared.server_id)
    rel = f"realms/{paths.safe_path_token(shared.id)}/store/{family}/{paths.safe_path_token(record_id)}.json"
    return json.loads(_git(remote, "show", f"main:{rel}"))


def test_a_rename_made_here_after_the_last_publish_survives_a_pull(team):
    """Bob renames the workspace and does not publish; Alice publishes something else; Bob's pull keeps his name,
    and his next publish ships it.

    KILLING MUTATION (run 2026-11-20): ``record_merge.merge_record_pull`` answering ``team`` always (the old
    overwrite) -> Bob reads "Roadmap" after the pull, red."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob's roadmap")
    team.be("alice")
    realm = RealmStore().get(shared.id)
    realm.skill_publish_mode = "selected"
    RealmStore().save(realm)
    publish_realm_sync(shared.id)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert WorkspaceStore().get(workspace.id).name == "Bob's roadmap"
    assert RealmStore().get(shared.id).skill_publish_mode == "selected"
    assert pulled["records_held"] == []
    publish_realm_sync(shared.id)
    assert _team_record(team, shared, "workspaces", workspace.id)["name"] == "Bob's roadmap"


def test_a_teammates_rename_of_a_workspace_unchanged_here_is_taken(team):
    """KILLING MUTATION (run 2026-11-20): ``merge_record`` keeping the local value on ``WRITE_REMOTE`` -> Bob still
    reads "Roadmap", red."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    WorkspaceStore().rename(workspace.id, "Alice's roadmap")
    publish_realm_sync(shared.id)

    team.be("bob")
    pull_realm_sync(shared.id)
    assert WorkspaceStore().get(workspace.id).name == "Alice's roadmap"


def test_a_rename_on_both_sides_holds_and_publishes_neither(team):
    """Both rename. Bob's pull keeps his name and HOLDS the record (named in the pull and the status); his publish
    leaves Alice's name on the team copy; a second pull still holds; taking the team's copy ends it.

    KILLING MUTATIONS (run 2026-11-20): ``keep_team_fields`` returning ``artifacts`` unchanged -> the team copy
    reads Bob's name after his publish, red; ``record_baselines_after_publish`` not putting a held field's old
    baseline back -> the second pull no longer holds, red."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob's roadmap")
    team.be("alice")
    WorkspaceStore().rename(workspace.id, "Alice's roadmap")
    publish_realm_sync(shared.id)

    team.be("bob")
    key = f"record::workspace:{workspace.id}"
    assert pull_realm_sync(shared.id)["records_held"] == [key]
    assert WorkspaceStore().get(workspace.id).name == "Bob's roadmap"
    assert realm_sync_status(shared.id)["records_held"] == [key]

    publish_realm_sync(shared.id)
    assert _team_record(team, shared, "workspaces", workspace.id)["name"] == "Alice's roadmap"
    assert pull_realm_sync(shared.id)["records_held"] == [key]
    assert WorkspaceStore().get(workspace.id).name == "Bob's roadmap"

    realm_sync_resolve(shared.id, key=key, take="remote")
    assert WorkspaceStore().get(workspace.id).name == "Alice's roadmap"
    assert pull_realm_sync(shared.id)["records_held"] == []


def test_keeping_the_members_side_of_a_hold_publishes_it(team):
    """``--take local`` writes nothing here and records the team's value as seen: the next publish ships Bob's name.

    KILLING MUTATION (run 2026-11-20): ``resolve_record_hold`` leaving the baseline as it was -> the next pull
    holds again, red."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob's roadmap")
    team.be("alice")
    WorkspaceStore().rename(workspace.id, "Alice's roadmap")
    publish_realm_sync(shared.id)

    team.be("bob")
    pull_realm_sync(shared.id)
    realm_sync_resolve(shared.id, key=f"record::workspace:{workspace.id}", take="local")
    assert pull_realm_sync(shared.id)["records_held"] == []
    publish_realm_sync(shared.id)
    assert _team_record(team, shared, "workspaces", workspace.id)["name"] == "Bob's roadmap"


def test_a_realm_record_merges_its_workspace_list_and_keeps_the_newer_stamp():
    """Each side's added workspace is kept, a removed one leaves; the stamp is the newer and never holds.

    KILLING MUTATION (run 2026-11-20): the ``workspace_ids`` arm dropped (classified like any field) -> both
    sides changed the list, so it is held and Bob's list stays, red."""

    base = {"name": "R", "workspace_ids": ["w1", "w2"], "updated_at": "2026-11-19T00:00:00"}
    local = {"name": "R", "workspace_ids": ["w1", "w2", "bob"], "updated_at": "2026-11-20T01:00:00"}
    remote = {"name": "R", "workspace_ids": ["w1", "alice"], "updated_at": "2026-11-20T00:00:00"}

    result = merge_record("realm", local, remote, base)

    assert result.merged["workspace_ids"] == ["w1", "alice", "bob"]
    assert result.merged["updated_at"] == "2026-11-20T01:00:00"
    assert result.held == {}
