"""A workspace that only passed through a shared realm leaves nothing for the team to publish.

MC-REALM-A-WORKSPACE-THAT-ONLY-PASSED-THROUGH-ASKS-TO-BE-PUBLISHED, seen live 2026-11-20 (w1118a-rsync7,
account B, QA Realm): a new workspace moved into the shared realm, moved out again before any publish and
deleted. Check now then read ``unpublished_changes: true`` for ever: the move out had put the workspace on
the realm's ``deleted_workspace_ids`` and ``workspace_lifts``, which the team's copy never held, so the next
publish would have carried a tombstone for a workspace the team never saw.

The rule (``realm_sync.ledgers.forget_leaves_the_team_never_held``) runs at both ends of the realm record:
the pull (``pull._pulled_artifact_bytes``) and the publish (``artifacts._published_realm_record``). Driven
through the app's doors (``runtime.workspace.move_realm``, ``runtime.realm.sync.status``) and the real
publish and pull. Killing mutations are named per test.
"""
from __future__ import annotations

import json

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.store import RealmStore, WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _shared_workspace, _Team


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _call(method: str, params: dict) -> dict:
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})
    assert "error" not in reply, reply
    return reply["result"]


def _pass_through(shared_id: str) -> str:
    """A new workspace moved into the shared realm, out again (no publish between) and deleted."""
    private = RealmStore().create(name="Private")
    probe = WorkspaceStore().create(name="door probe", realm_id=private.id)
    _call("runtime.workspace.move_realm", {"workspace_id": probe.id, "realm_id": shared_id})
    _call("runtime.workspace.move_realm",
          {"workspace_id": probe.id, "realm_id": private.id, "confirm_leave_realm": shared_id})
    WorkspaceStore().delete(probe.id)
    return probe.id


def _ledgers(record: dict) -> set[str]:
    return {*(record.get("deleted_workspace_ids") or []),
            *(row.get("workspace_id") for row in record.get("workspace_lifts") or [])}


def _published_record(team: _Team, realm_id: str) -> dict:
    record = f"store/realms/{paths.safe_path_token(realm_id)}.json"
    return json.loads((team.clone("alice", "srv_team") / "realms" / paths.safe_path_token(realm_id) / record)
                      .read_text(encoding="utf-8"))


def test_a_workspace_that_only_passed_through_leaves_the_realm_in_sync(team):
    """The live repro: the leave is on the realm's ledgers here (as rsync7 read on disk), yet the status
    reads nothing waiting, and the next pull writes the record without it.

    Mutations, each red here: in ``ledgers.forget_leaves_the_team_never_held`` answer the empty set for
    ``never`` -> the status names the realm record as waiting; in ``pull._pulled_artifact_bytes`` drop the
    ``forget_leaves_the_team_never_held`` call -> the same (the pull side unions the leave back in)."""
    shared, _workspace = _shared_workspace(team)
    probe = _pass_through(shared.id)
    assert probe in _ledgers(json.loads(paths.realm_path(shared.id).read_text(encoding="utf-8")))

    status = _call("runtime.realm.sync.status", {"realm_id": shared.id})
    assert (status["unpublished_changes"], status["publish_changes"]) == (False, [])

    pull_realm_sync(shared.id)
    assert probe not in _ledgers(json.loads(paths.realm_path(shared.id).read_text(encoding="utf-8")))
    status = _call("runtime.realm.sync.status", {"realm_id": shared.id})
    assert (status["unpublished_changes"], status["publish_changes"]) == (False, [])


def test_a_workspace_that_only_passed_through_is_never_published(team):
    """A publish made for another change ships no trace of it, while a workspace the team DID hold keeps
    its tombstone on the published record.

    Mutations, each red here: in ``artifacts._published_realm_record`` drop the
    ``forget_leaves_the_team_never_held`` call -> the published ledgers name the probe; in
    ``ledgers._team_workspace_ids`` drop the ``workspace_ids`` line -> Roadmap's tombstone is forgotten and
    the published ledger lacks it."""
    shared, workspace = _shared_workspace(team)
    probe = _pass_through(shared.id)
    WorkspaceStore().delete(workspace.id)
    assert _call("runtime.realm.sync.status", {"realm_id": shared.id})["unpublished_changes"] is True

    publish_realm_sync(shared.id)
    published = _published_record(team, shared.id)
    assert probe not in _ledgers(published)
    assert workspace.id in published["deleted_workspace_ids"]
    status = _call("runtime.realm.sync.status", {"realm_id": shared.id})
    assert (status["unpublished_changes"], status["publish_changes"]) == (False, [])


def test_the_team_held_every_workspace_its_record_names_or_its_files_publish():
    """The team "held" a workspace its copy publishes a file for, or its record lists as a member, a delete
    or a lift; only a leave none of those names is forgotten, its lift with it.

    Mutations, each red here: in ``ledgers.team_workspace_ids`` drop the ``workspace_ids``, the
    ``deleted_workspace_ids`` or the ``workspace_lifts`` term -> that workspace's leave is forgotten."""
    from agent_runtime.realm_sync.ledgers import forget_leaves_the_team_never_held, team_workspace_ids

    team = {"workspace_ids": ["ws_member"], "deleted_workspace_ids": ["ws_deleted"],
            "workspace_lifts": [{"workspace_id": "ws_lifted", "restored_at": "2026-11-20T00:00:00Z"}]}
    held = team_workspace_ids(team, ["ws_file"])
    left = ["ws_member", "ws_deleted", "ws_lifted", "ws_file", "ws_passed"]
    record = {"deleted_workspace_ids": list(left),
              "workspace_lifts": [{"workspace_id": item, "deleted_at": "2026-11-20T01:00:00Z"} for item in left]}
    assert forget_leaves_the_team_never_held(record, held) is True
    assert record["deleted_workspace_ids"] == left[:-1]
    assert [row["workspace_id"] for row in record["workspace_lifts"]] == left[:-1]
    assert forget_leaves_the_team_never_held(record, held) is False
    assert forget_leaves_the_team_never_held({"deleted_workspace_ids": ["ws_passed"]}, None) is False
