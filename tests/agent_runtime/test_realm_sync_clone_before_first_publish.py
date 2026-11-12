"""A sync repo cloned before anything was published can still pull (RT-REALM-PULL-FAILS-ON-CLONE-MADE-BEFORE-FIRST-PUBLISH).

Two members, each with its own runtime root and its own clone of one bare remote, through
``realm_sync_status`` / ``publish_realm_sync`` / ``pull_realm_sync``. Hermes writes its ``.gitattributes`` pin
untracked into a clone whose remote held none; the first publish by anyone else then made git refuse that
clone's fast-forward for good. Killing mutations are named per test.
"""
from __future__ import annotations

import pytest

from agent_runtime import paths
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync, realm_sync_status
from agent_runtime.store import RealmStore, WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team, _git


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _both_clone_before_any_publish(team: _Team):
    """Alice founds the realm; Bob adopts it and reads its status — both clones exist, nothing is published."""
    shared = team.found("alice", "Team Realm", "srv_team")
    team.be("bob")
    record = RealmStore().create(name=shared.name, server_id=shared.server_id)
    paths.realm_path(record.id).unlink()
    record.id, record.workspace_ids = shared.id, []
    record.sync_manifest_ref = str(team.clone("bob", "srv_team"))
    RealmStore().save(record)
    realm_sync_status(shared.id)
    clone = team.clone("bob", "srv_team")
    assert _git(clone, "status", "--porcelain") == "?? .gitattributes"
    return shared, clone


def test_a_member_whose_clone_predates_the_first_publish_pulls_it_and_publishes_after(team):
    """Mutation: in ``realm_sync.git._pull_fast_forward`` drop the ``path.unlink()`` of the untracked pin ->
    Bob's pull raises ``sync_remote_unreachable`` ("untracked working tree files would be overwritten")."""
    shared, clone = _both_clone_before_any_publish(team)
    team.be("alice")
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    publish_realm_sync(shared.id)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert pulled["state"] == "pulled"
    assert WorkspaceStore().get(workspace.id).realm_id == shared.id
    assert _git(clone, "ls-files", ".gitattributes") == ".gitattributes"
    assert _git(clone, "status", "--porcelain", "--", ".gitattributes") == ""
    WorkspaceStore().rename(workspace.id, "Bob renamed")
    publish_realm_sync(shared.id)

    team.be("alice")
    pull_realm_sync(shared.id)
    assert WorkspaceStore().get(workspace.id).name == "Bob renamed"


def test_an_untracked_gitattributes_hermes_did_not_write_is_never_removed(team):
    """Mutation: in ``_pull_fast_forward`` drop the marker test (``ours = path.is_file()``) -> the member's
    own file is deleted and the pull goes through, red at the ``RealmSyncError`` expectation."""
    shared, clone = _both_clone_before_any_publish(team)
    (clone / ".gitattributes").write_text("*.bin binary\n", encoding="utf-8")
    team.be("alice")
    WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    publish_realm_sync(shared.id)

    team.be("bob")
    with pytest.raises(RealmSyncError) as refused:
        pull_realm_sync(shared.id)
    assert refused.value.code == "sync_remote_unreachable"
    assert (clone / ".gitattributes").read_text(encoding="utf-8") == "*.bin binary\n"


def test_a_pull_that_brings_no_pin_leaves_the_untracked_one_in_place(team):
    """A remote that tracks no ``.gitattributes`` (nothing published yet): the pin is back after the pull.
    Mutation: drop the ``finally: _ensure_repo_gitattributes(repo)`` -> the file is missing after the pull."""
    shared, clone = _both_clone_before_any_publish(team)
    pull_realm_sync(shared.id)
    assert _git(clone, "status", "--porcelain") == "?? .gitattributes"
