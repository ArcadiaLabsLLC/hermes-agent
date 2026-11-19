"""A realm clone that moved ahead of this machine's store reads "pull", never "publish".

RT-REALM-STATUS-READS-AN-UNADOPTED-PULL-AS-UNPUBLISHED: on a second computer the realm sheet said
"Changes to push" for a teammate's slot change (owner, macOS, 2026-11-18, relayed). A pull merges the
team's commit into this machine's sync clone and only then runs the appliers that adopt it into the
store; when the appliers do not finish, git reads ``behind: 0`` while the store still holds the old
documents, the status's store-vs-clone compare names them as this machine's changes, and a publish
(refused only when git is behind) writes the old store over the teammate's newer commit.

Pinned through the app's doors (``runtime.workspace.slots.declare``, ``runtime.realm.sync.status``)
and the sync verbs. Killing mutations are named per test.
"""
from __future__ import annotations

import json

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync
from agent_runtime.realm_sync import pull as pull_module
from agent_runtime.realm_sync.pull import PullApplier
from agent_runtime.workspace_slots import live_slots, load_document
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _git, _shared_workspace, _Team

CLONE_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _call(method: str, params: dict) -> dict:
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})
    assert "error" not in reply, reply
    return reply["result"]


def _declare(workspace_id: str, branch: str, issued_at: str) -> None:
    slot = {"name": "rsdocs", "repo": {"clone_url": CLONE_URL, "default_branch": branch}, "context": {"role": "docs"}}
    _call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": [slot], "issued_at": issued_at})


def _team_branch(team: _Team, realm, workspace_id: str) -> str:
    """The slot's branch in the team's copy on the remote."""
    rel = f"realms/{paths.safe_path_token(realm.id)}/store/workspace_slots/{paths.safe_path_token(workspace_id)}.json"
    document = json.loads(_git(team.remote(realm.server_id), "show", f"main:{rel}"))
    return document["slots"]["rsdocs"]["repo"]["default_branch"]


def _here_branch(workspace_id: str) -> str:
    return live_slots(load_document(workspace_id))["rsdocs"]["repo"]["default_branch"]


def _interrupted_slot_applier(monkeypatch) -> None:
    def boom(run):
        raise RuntimeError("the slot applier did not finish")

    monkeypatch.setattr(pull_module, "PULL_APPLIERS", tuple(
        PullApplier(a.name, boom) if a.name == "workspace_slots_sync" else a for a in pull_module.PULL_APPLIERS))


def test_a_pull_merged_but_not_adopted_reads_pull_and_publish_refuses_until_the_pull_finishes(team, monkeypatch):
    """Alice changes the slot's branch and publishes; Bob's pull merges her commit but its slot applier does
    not finish. Bob's status must not call Alice's change his own, and his publish must not undo it.

    Mutations: in ``realm_sync_status`` answer ``adopted = True`` -> Bob reads ``in_sync`` and the slot
    document as his change to publish, red; in ``_publish_realm_sync`` drop the
    ``sync_not_adopted`` refusal -> Bob's publish writes ``main`` back over Alice's ``dev``, red; in
    ``_pull_realm_sync`` record the adopted head before the appliers -> the interrupted pull reads adopted,
    red."""
    shared, workspace = _shared_workspace(team)
    _declare(workspace.id, "main", "2026-11-18T10:00:00+00:00")
    publish_realm_sync(shared.id)
    team.be("bob")
    pull_realm_sync(shared.id)
    assert _call("runtime.realm.sync.status", {"realm_id": shared.id})["store_adopted"] is True

    team.be("alice")
    _declare(workspace.id, "dev", "2026-11-18T11:00:00+00:00")
    publish_realm_sync(shared.id)
    assert _team_branch(team, shared, workspace.id) == "dev"

    team.be("bob")
    with monkeypatch.context() as patch:
        _interrupted_slot_applier(patch)
        with pytest.raises(RuntimeError):
            pull_realm_sync(shared.id)
    assert _here_branch(workspace.id) == "main"

    status = _call("runtime.realm.sync.status", {"realm_id": shared.id})
    assert (status["behind"], status["store_adopted"], status["state"]) == (0, False, "behind")
    assert status["unpublished_changes"] is False
    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(shared.id)
    assert refused.value.code == "sync_not_adopted"
    assert _team_branch(team, shared, workspace.id) == "dev"

    pull_realm_sync(shared.id)
    assert _here_branch(workspace.id) == "dev"
    status = _call("runtime.realm.sync.status", {"realm_id": shared.id})
    assert (status["store_adopted"], status["state"]) == (True, "in_sync")
    assert [p for p in status["publish_changes"] if p.startswith("store/workspace_slots/")] == []
    publish_realm_sync(shared.id)
    assert _team_branch(team, shared, workspace.id) == "dev"


def test_a_member_s_own_publish_stays_adopted_and_his_next_edit_reads_unpublished(team):
    """Bob pulled (the marker names Alice's commit), then publishes his own slot change: his own commit is
    adopted by construction, so his status is in sync, and his next edit reads as his to publish.

    Mutation: in ``_stage_commit_and_push`` stop recording the adopted head after the commit -> Bob's own
    commit reads not adopted ("behind") and his next publish is refused, red."""
    shared, workspace = _shared_workspace(team)
    _declare(workspace.id, "main", "2026-11-18T10:00:00+00:00")
    publish_realm_sync(shared.id)
    team.be("bob")
    pull_realm_sync(shared.id)
    _declare(workspace.id, "dev", "2026-11-18T11:00:00+00:00")
    publish_realm_sync(shared.id)
    status = _call("runtime.realm.sync.status", {"realm_id": shared.id})
    assert (status["store_adopted"], status["state"]) == (True, "in_sync")
    _declare(workspace.id, "qa", "2026-11-18T12:00:00+00:00")
    status = _call("runtime.realm.sync.status", {"realm_id": shared.id})
    assert status["store_adopted"] is True
    assert [p for p in status["publish_changes"] if p.startswith("store/workspace_slots/")] == [
        f"store/workspace_slots/{paths.safe_path_token(workspace.id)}.json"]
    publish_realm_sync(shared.id)
    assert _team_branch(team, shared, workspace.id) == "qa"
