"""Moving a workspace OUT of a server-bound realm (RT-WORKSPACE-MOVE-OUT-OF-SERVER-REALM).

Several members, each with its own runtime root and its own clone of one bare git remote, driven through the
real verbs (``runtime.workspace.move_realm``, ``publish_realm_sync``, ``pull_realm_sync``). The three hazards
the plan names (``docs/agent-runtime-harness/planned/workspace-move-out-of-server-realm-2026-11-12.md`` §2) are
one scenario each, with publish and pull in both orders. Killing mutations are named per test.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime import board_models, paths, serve_rpc
from agent_runtime.board_store import BoardStore
from agent_runtime.office_store import OfficeStore
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync
from agent_runtime.store import RealmStore, WorkspaceStore


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _move(**params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "m", "method": "runtime.workspace.move_realm",
                                     "params": params})


class _Team:
    """Members of shared realms: ``be(name)`` makes that member the current machine."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp, self.monkeypatch = tmp_path, monkeypatch

    def be(self, member: str) -> None:
        self.monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(self.tmp / member / "agent-runtime"))

    def remote(self, server_id: str) -> Path:
        bare = self.tmp / f"{server_id}.git"
        if not bare.exists():
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
            seed = self.tmp / f"{server_id}-seed"
            subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, capture_output=True)
            _git(seed, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "seed")
            _git(seed, "push", "-q", str(bare), "HEAD:main")
        return bare

    def clone(self, member: str, server_id: str) -> Path:
        clone = self.tmp / member / f"clone-{server_id}"
        if not clone.exists():
            clone.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "-q", str(self.remote(server_id)), str(clone)], check=True, capture_output=True)
        return clone

    def found(self, member: str, name: str, server_id: str):
        """``member`` creates the shared realm ``name`` (server-bound, its own clone of the remote)."""
        self.be(member)
        realm = RealmStore().create(name=name, server_id=server_id)
        realm.sync_manifest_ref = str(self.clone(member, server_id))
        return RealmStore().save(realm)

    def join(self, member: str, realm) -> None:
        """``member`` adopts the realm (what the backend adoption writes) and pulls it."""
        self.be(member)
        record = RealmStore().create(name=realm.name, server_id=realm.server_id)
        paths.realm_path(record.id).unlink()
        record.id, record.workspace_ids = realm.id, []
        record.sync_manifest_ref = str(self.clone(member, realm.server_id))
        RealmStore().save(record)
        pull_realm_sync(realm.id)

    def published_workspace_ids(self, realm) -> set[str]:
        """The workspace files the realm's remote holds on ``main``."""
        prefix = f"realms/{paths.safe_path_token(realm.id)}/store/workspaces/"
        names = _git(self.remote(realm.server_id), "ls-tree", "-r", "--name-only", "main").splitlines()
        return {Path(name).stem for name in names if name.startswith(prefix)}


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _shared_workspace(team: _Team, *, members: tuple[str, ...] = ("bob",)):
    """Alice's shared realm with one workspace (an office desk, a board card), published and pulled by ``members``."""
    shared = team.found("alice", "Team Realm", "srv_team")
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    OfficeStore().upsert_actor(workspace.id, {"persona_id": "dev", "items": [
        {"item_id": "dev", "persona_id": "dev", "kind": "agent", "position": [1.5, -2.0], "folder": "Agents"}]})
    BoardStore().add_card(workspace_id=workspace.id, title="Ship it", description="seeded", priority="p1")
    publish_realm_sync(shared.id)
    for member in members:
        team.join(member, shared)
        assert WorkspaceStore().get(workspace.id).realm_id == shared.id
    team.be("alice")
    return shared, workspace


def _whole(workspace_id: str, realm_id: str) -> None:
    """The workspace is here, owned by ``realm_id``, with its desk and its card."""
    stored = WorkspaceStore().get(workspace_id)
    assert (stored.realm_id, stored.archived, stored.name) == (realm_id, False, "Roadmap")
    assert [actor.actor_key for actor in OfficeStore().scan_actors(workspace_id).actors] == ["dev"]
    assert [card.title for card in BoardStore().list_cards(board_models.default_board_id(workspace_id))] == ["Ship it"]


def _gone(workspace_id: str) -> None:
    assert not paths.workspace_path(workspace_id).exists()


def test_a_move_out_leaves_the_shared_realm_for_everyone_and_stays_with_the_mover(team):
    """Mover publishes first. Hazard 1 (no tombstone -> it comes back) and hazard 2 (a tombstone deletes the
    moved workspace by id).

    Mutations: in ``move_workspace_realm`` replace ``record_deleted_workspace`` by the plain ``workspace_ids``
    removal -> Bob keeps his copy and his publish puts the workspace back in the shared realm's remote, red at
    ``_gone`` for Bob; in ``_apply_workspace_tombstones`` drop the other-realm skip -> Alice's pull of the
    shared realm deletes the workspace she moved, red at ``_whole`` (NotFound)."""
    shared, workspace = _shared_workspace(team)
    private = RealmStore().create(name="Private")
    result = _move(workspace_id=workspace.id, realm_id=private.id, confirm_leave_realm="team realm")["result"]
    assert (result["realm_id"], result["moved"], result["from_realm_id"], result["publish_owed"]) == (
        private.id, True, shared.id, [shared.id])
    left = RealmStore().get(shared.id)
    assert left.deleted_workspace_ids == [workspace.id]
    publish_realm_sync(shared.id)
    assert team.published_workspace_ids(shared) == set()
    pull_realm_sync(shared.id)
    _whole(workspace.id, private.id)

    team.be("bob")
    pulled = pull_realm_sync(shared.id)
    assert pulled["workspace_tombstones"]["deleted"] == [workspace.id]
    _gone(workspace.id)
    publish_realm_sync(shared.id)
    assert team.published_workspace_ids(shared) == set()

    team.be("alice")
    pull_realm_sync(shared.id)
    _whole(workspace.id, private.id)
    assert workspace.id in RealmStore().get(private.id).workspace_ids


def test_a_members_older_copy_published_before_the_movers_cannot_bring_the_workspace_back(team):
    """Member publishes first. Hazard 3 (a pull of the source overwrites the local workspace file with the
    remote's older record), then hazard 1 again in this order.

    Mutation: in ``_overwrite_generic_families`` drop the ``moved_out`` skip -> Alice's pull writes Bob's copy
    (``realm_id`` the shared realm, his name for it) over her moved workspace and the tombstone applier then
    deletes it, red at ``_whole`` (NotFound)."""
    shared, workspace = _shared_workspace(team)
    private = RealmStore().create(name="Private")
    assert _move(workspace_id=workspace.id, realm_id=private.id, confirm_leave_realm=shared.id)["result"]["moved"]

    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob's older copy")
    publish_realm_sync(shared.id)
    assert team.published_workspace_ids(shared) == {workspace.id}

    team.be("alice")
    with pytest.raises(RealmSyncError) as behind:
        publish_realm_sync(shared.id)
    assert behind.value.code == "sync_behind"
    pull_realm_sync(shared.id)
    _whole(workspace.id, private.id)
    assert RealmStore().get(shared.id).deleted_workspace_ids == [workspace.id]
    publish_realm_sync(shared.id)
    assert team.published_workspace_ids(shared) == set()

    team.be("bob")
    pull_realm_sync(shared.id)
    _gone(workspace.id)
    team.be("alice")
    pull_realm_sync(shared.id)
    _whole(workspace.id, private.id)


@pytest.mark.parametrize("first", ["target", "source"])
def test_a_member_of_both_realms_ends_with_the_workspace_in_the_target_whichever_they_pull_first(team, first):
    """A move between two shared realms; Carol is in both. Target first: she keeps it throughout. Source first:
    it is gone until the pull of the target brings it back (the plan's stated order across machines).

    Mutations: drop the other-realm skip in ``_apply_workspace_tombstones`` -> pulling the source after the
    target deletes it, red (target-first, NotFound); make ``publish_owed`` list the source first -> red on the
    order assertion."""
    shared, workspace = _shared_workspace(team, members=("carol",))
    other = team.found("alice", "Other Team", "srv_other")
    publish_realm_sync(other.id)
    team.join("carol", other)
    team.be("alice")
    result = _move(workspace_id=workspace.id, realm_id=other.id, confirm_leave_realm="Team Realm")["result"]
    assert result["publish_owed"] == [other.id, shared.id]
    for realm_id in result["publish_owed"]:
        publish_realm_sync(realm_id)
    assert team.published_workspace_ids(other) == {workspace.id} and team.published_workspace_ids(shared) == set()

    team.be("carol")
    if first == "target":
        pull_realm_sync(other.id)
        _whole(workspace.id, other.id)
        pull_realm_sync(shared.id)
    else:
        pull_realm_sync(shared.id)
        _gone(workspace.id)
        pull_realm_sync(other.id)
    _whole(workspace.id, other.id)
    pull_realm_sync(shared.id)
    _whole(workspace.id, other.id)


def test_moving_it_back_returns_it_to_the_team(team):
    """Mutation: drop ``lift_deleted_workspace`` on the move's target -> the id stays on the shared realm's
    delete ledger, the publish leaves it out and Bob never gets it back, red at ``_whole`` for Bob."""
    shared, workspace = _shared_workspace(team)
    private = RealmStore().create(name="Private")
    _move(workspace_id=workspace.id, realm_id=private.id, confirm_leave_realm=shared.id)
    publish_realm_sync(shared.id)
    team.be("bob")
    pull_realm_sync(shared.id)
    _gone(workspace.id)

    team.be("alice")
    back = _move(workspace_id=workspace.id, realm_id=shared.id)["result"]
    assert (back["realm_id"], back["publish_owed"]) == (shared.id, [shared.id])
    publish_realm_sync(shared.id)
    team.be("bob")
    pull_realm_sync(shared.id)
    _whole(workspace.id, shared.id)


def test_a_move_out_is_refused_until_the_caller_names_the_realm_it_leaves(team):
    """Mutation: make ``_names_realm`` answer True -> the unconfirmed move goes through (KeyError 'error'), red;
    accept any non-empty confirm -> the wrong-name call moves it, red."""
    shared, workspace = _shared_workspace(team, members=())
    private = RealmStore().create(name="Private")
    needed = {"reason": "workspace_move_confirm_required", "owner_realm_id": shared.id, "owner_realm_name": "Team Realm"}
    for confirm in ({}, {"confirm_leave_realm": ""}, {"confirm_leave_realm": "Private"},
                    {"confirm_leave_realm": private.id}, {"confirm_leave_realm": True}):
        error = _move(workspace_id=workspace.id, realm_id=private.id, **confirm)["error"]
        assert (error["data"], error["code"]) == (needed, 4090), confirm
    assert _move(workspace_id=workspace.id, realm_id=private.id, yes=True)["error"]["data"] == {"reason": "invalid_request"}
    stored = RealmStore().get(shared.id)
    assert WorkspaceStore().get(workspace.id).realm_id == shared.id
    assert not stored.deleted_workspace_ids
    assert _move(workspace_id=workspace.id, realm_id=private.id, confirm_leave_realm="  TEAM realm ")["result"]["moved"]


def _credential(realm_id: str) -> dict:
    return {"schema_version": 1, "realm_id": realm_id, "api_base": "https://api.test.invalid/api",
            "api_token": "etk_test_api_token_000000", "git_url": "https://git.test.invalid/realm-sync/test.git",
            "git_authorization": "Bearer forgejo_sekret_value_1234567890", "expires_at": "2999-01-01T00:00:00Z"}


def test_a_member_who_may_not_publish_to_the_shared_realm_is_refused_and_nothing_is_written(monkeypatch):
    """The source realm's own publish gate, asked before the confirm when a credential is given.

    Mutations: drop the ``authorize()`` calls in ``_admit_leaving_shared_realms`` -> the reader's confirmed
    move goes through (KeyError 'error'), red; ask for ``pull`` instead of ``publish`` -> the action assertion
    in the backend stub, red."""
    import agent_runtime.realm_membership as realm_membership

    realms, workspaces = RealmStore(), WorkspaceStore()
    shared = realms.create(name="Team Realm", server_id="srv_team")
    shared.sync_manifest_ref = "https://git.test.invalid/realm-sync/test.git"
    realms.save(shared)
    workspace = workspaces.create(name="Roadmap", realm_id=shared.id)
    private = realms.create(name="Private")
    answer = {"allowed": False, "code": "role_insufficient", "message": "reader role"}

    def backend(method, url, **kwargs):
        assert f"/realms/{shared.id}/sync/permission?action=publish" in url
        return 200, answer

    monkeypatch.setattr(realm_membership, "_request_json", backend)
    move = {"workspace_id": workspace.id, "realm_id": private.id}
    for extra, reason in (
            ({"credential": _credential(shared.id), "confirm_leave_realm": shared.id}, "role_insufficient"),
            ({"credential": _credential(shared.id)}, "role_insufficient"),
            ({"confirm_leave_realm": shared.id}, "sync_auth_failed"),
            ({"credential": _credential("realm_elsewhere"), "confirm_leave_realm": shared.id}, "sync_auth_failed")):
        error = _move(**move, **extra)["error"]
        assert (error["data"], error["code"]) == ({"reason": reason, "retryable": False}, 4090), extra
    stored = realms.get(shared.id)
    assert workspaces.get(workspace.id).realm_id == shared.id
    assert not stored.deleted_workspace_ids

    answer.update(allowed=True, code="")
    assert _move(**move, credential=_credential(shared.id))["error"]["data"]["reason"] == "workspace_move_confirm_required"
    moved = _move(**move, credential=_credential(shared.id), confirm_leave_realm="Team Realm")["result"]
    assert (moved["realm_id"], moved["publish_owed"]) == (private.id, [shared.id])


def test_the_argv_verb_takes_the_confirm_and_says_which_realm_to_name(team):
    """Mutation: stop passing ``--confirm-leave-realm`` through the argv door -> the confirmed call is refused
    again (exit code), red."""
    from tests.agent_runtime._harness_cli import run_harness_in_process

    shared, workspace = _shared_workspace(team, members=())
    private = RealmStore().create(name="Private")
    refused = run_harness_in_process("workspace", "move-realm", workspace.id, private.id, "--output", "json")
    assert refused.returncode != 0
    assert "workspace_move_confirm_required" in refused.stdout and "Team Realm" in refused.stdout and shared.id in refused.stdout
    moved = run_harness_in_process("workspace", "move-realm", workspace.id, private.id,
                                   "--confirm-leave-realm", "Team Realm", "--output", "json")
    assert moved.returncode == 0, moved.stdout + moved.stderr
    assert WorkspaceStore().get(workspace.id).realm_id == private.id
