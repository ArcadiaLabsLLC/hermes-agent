"""A realm whose server you left, or were removed from, becomes a local realm
(``agent_runtime.realm_leave``, RT-LEFT-SERVER-REALM-STAYS-LISTED). The team's copy is a bare git
repository under ``tmp_path`` and another member is a second clone of it; the two-machine read is the
lane's real-path run. Killing mutations are named per test."""
import json
import subprocess
from pathlib import Path

import pytest

from agent_runtime import paths as runtime_paths
from agent_runtime import realm_leave, serve_rpc, turn_activity
from agent_runtime.board_store import BoardStore
from agent_runtime.realm_rekey import read_rekey_journal
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync, realm_sync_status
from agent_runtime.realm_sync.git import _sync_repo_path
from agent_runtime.realm_sync.revocation import (
    HOST_STATE_REASONS,
    MEMBER_ACCESS_REASONS,
    RealmRevokedReason,
    mark_realm_revoked,
    read_realm_revocation,
    read_realm_shared_from,
    realm_shared_from_path,
    write_realm_shared_from,
)
from agent_runtime.realm_sync.sidecar import realm_sync_sidecar_path
from agent_runtime.snapshot import realm_summary
from agent_runtime.store import RealmStore, WorkspaceStore

SECRET = "ghs_s3cr3tT0ken"


def _rpc(method, **params):
    """Every call here is made while a turn is live, so the re-key the leave owes WAITS: these tests read the
    leave itself, the realm still under the id it had. What the re-key and a re-join then do is
    ``test_realm_rejoin_fresh.py``."""
    with turn_activity.admitted_turn("a live turn"):
        return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "lv", "method": method, "params": params})


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _events(realm_id):
    return [event.payload.get("change") for event in RealmStore().event_log.tail(80)
            if event.type == "realm.updated" and event.payload.get("realm_id") == realm_id]


def _team_realm(tmp_path, *, realm_id="realm_team", server_id="srv_team"):
    """A server realm whose sync repository is a clone of the team's bare repository."""
    bare = tmp_path / "team.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    clone = tmp_path / "team-clone"
    subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "member@localhost")
    _git(clone, "config", "user.name", "Member")
    _git(clone, "commit", "--allow-empty", "-m", "init")
    _git(clone, "remote", "add", "origin", str(bare))
    _git(clone, "push", "-q", "-u", "origin", "HEAD")
    realm = RealmStore().create(name="Team", server_id=server_id, realm_id=realm_id)
    realm.sync_manifest_ref = str(clone)
    return RealmStore().save(realm), bare, clone


def _adopt(monkeypatch, *items):
    import agent_runtime.realm_membership as membership
    from agent_runtime.realm_verbs import realm_adopt

    monkeypatch.setattr(membership, "_request_json", lambda *a, **k: (200, {"items": list(items)}))
    credential = membership.RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": "realm_team", "api_base": "https://api.test.invalid/api",
        "api_token": "etk_t", "git_url": "https://git.test.invalid/r.git",
        "git_authorization": "Basic x", "expires_at": "2999-01-01T00:00:00Z",
    })
    return realm_adopt(credential)


def test_leaving_makes_the_realm_local_keeps_its_workspaces_and_a_repeat_writes_nothing():
    """Mutations: drop ``realm.server_id = None`` -> the stored realm keeps ``srv_team``, red; drop the
    ``write_realm_shared_from`` call -> ``shared_from`` is None, red; drop the ``became_local`` event -> the
    event list, red; drop the ``if not realm.server_id`` early return -> the repeat answers ``became_local``
    true, red; show ``shared_from`` on a bound realm -> the before-row, red; drop ``server_name`` at the method
    door -> the record's name is None, red."""
    realms = RealmStore()
    realm = realms.create(name="Team", server_id="srv_team", realm_id="realm_team")
    realm.sync_manifest_ref = "https://git.test.invalid/team.git"
    realm = realms.save(realm)
    workspace = WorkspaceStore().create(name="Shared", realm_id=realm.id)
    card = BoardStore().add_card(workspace_id=workspace.id, title="Team card")
    # A record beside a still-bound realm (a crash between the two writes) is never shown.
    write_realm_shared_from(realm.id, server_id="srv_stale", server_name=None, reason=RealmRevokedReason.GRANT_REMOVED)
    assert realm_summary(realm, workspaces=[])["shared_from"] is None

    result = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left", server_name="The Guild")["result"]

    assert (result["kind"], result["became_local"], result["host_state"]) == ("realm_revocation", True, False)
    shared = result["shared_from"]
    assert (shared["server_id"], shared["server_name"], shared["reason"]) == ("srv_team", "The Guild", "membership_left")
    assert shared["left_at"] == result["revoked_at"] and shared["left_at"]
    stored = realms.get(realm.id)
    assert (stored.server_id, stored.sync_manifest_ref, stored.archived) == (None, None, False)
    assert [item.id for item in realms.list_all()] == [realm.id]
    assert WorkspaceStore().get(workspace.id).realm_id == realm.id
    assert BoardStore().get_card(card.card_id).title == "Team card"
    assert read_realm_revocation(realm.id) is None  # the record is the history; no "revoked" on a local realm
    row = _rpc("runtime.realm.archive", realm_id=realm.id)["error"]["data"]
    assert row["reason"] != "realm_server_bound"
    summary = realm_summary(stored, workspaces=WorkspaceStore().list_all())
    assert (summary["server_id"], summary["shared_from"]) == (None, shared)
    assert _events(realm.id)[-1] == "became_local"
    before = len(_events(realm.id))

    again = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_kicked")["result"]
    assert (again["became_local"], again["shared_from"], again["reason"]) == (False, shared, "membership_left")
    assert len(_events(realm.id)) == before


def test_every_reason_is_either_the_members_access_or_the_git_hosts_state():
    assert MEMBER_ACCESS_REASONS | HOST_STATE_REASONS == frozenset(RealmRevokedReason)
    assert not MEMBER_ACCESS_REASONS & HOST_STATE_REASONS


# Spelled out, not read from ``MEMBER_ACCESS_REASONS``: a narrowed set must fail rows, not drop them.
@pytest.mark.parametrize("reason", [
    "membership_left", "membership_kicked", "membership_banned", "timeout_started", "role_revoked",
    "grant_removed", "realm_deleted", "server_deleted", "ownership_transferred",
])
def test_being_removed_by_someone_else_gives_the_same_local_realm(reason):
    """Mutation: narrow ``MEMBER_ACCESS_REASONS`` to ``membership_left`` -> every other row keeps
    ``srv_team`` and a mark, red."""
    realm = RealmStore().create(name="Team", server_id="srv_team", realm_id="realm_team")
    result = _rpc("runtime.realm.revoked", realm_id=realm.id, reason=reason)["result"]
    assert (result["became_local"], result["shared_from"]["reason"], result["shared_from"]["server_name"]) == (
        True, reason, None)
    assert RealmStore().get(realm.id).server_id is None
    assert read_realm_revocation(realm.id) is None


@pytest.mark.parametrize("reason", sorted(item.value for item in HOST_STATE_REASONS))
def test_a_git_host_loss_keeps_the_realm_bound_and_marked(reason):
    """Mutation: make every reason a member-access reason -> ``server_id`` is None, red."""
    realm = RealmStore().create(name="Team", server_id="srv_team", realm_id="realm_team")
    result = _rpc("runtime.realm.revoked", realm_id=realm.id, reason=reason)["result"]
    assert (result["became_local"], result["shared_from"], result["host_state"]) == (False, None, True)
    assert RealmStore().get(realm.id).server_id == "srv_team"
    assert read_realm_revocation(realm.id)["reason"] == reason
    assert read_realm_shared_from(realm.id) is None
    with pytest.raises(ValueError):
        realm_leave.make_realm_local(realm.id, RealmRevokedReason(reason))


def test_a_realm_that_never_had_a_server_is_left_alone():
    """Mutation: drop the ``if not realm.server_id`` early return -> ``became_local`` is true and an event is
    appended, red."""
    realm = RealmStore().create(name="Mine")
    result = _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left")["result"]
    assert (result["became_local"], result["shared_from"]) == (False, None)
    assert not realm_shared_from_path(realm.id).exists()
    assert _events(realm.id) == []


def test_nothing_reaches_the_team_after_leaving_and_the_teams_copy_is_untouched(tmp_path):
    """Mutations: drop ``realm.sync_manifest_ref = None`` -> the publish after leaving pushes to the team
    (the bare head moves) and the pull fetches the team's new commit, red; drop the sidecar unlink -> the
    stale ``sync`` state stays on the snapshot row, red."""
    realm, bare, clone = _team_realm(tmp_path)
    workspace = WorkspaceStore().create(name="Shared", realm_id=realm.id)
    BoardStore().add_card(workspace_id=workspace.id, title="Published while a member")
    assert publish_realm_sync(realm.id)["changed"] is True
    team_head, team_tree = _git(bare, "rev-parse", "main"), _git(bare, "ls-tree", "-r", "main")
    assert realm_sync_sidecar_path(realm.id).exists()

    assert _rpc("runtime.realm.revoked", realm_id=realm.id, reason="membership_left")["result"]["became_local"]

    # Leaving sent nothing, and the member's realm no longer points at the team's repository.
    assert (_git(bare, "rev-parse", "main"), _git(bare, "ls-tree", "-r", "main")) == (team_head, team_tree)
    local = RealmStore().get(realm.id)
    assert _sync_repo_path(local) == runtime_paths.realm_sync_root() / "local"
    assert realm_summary(local, workspaces=[])["sync"] is None
    # A local edit, then a publish: it is a local realm's publish and never reaches the team.
    BoardStore().add_card(workspace_id=workspace.id, title="Added after leaving")
    assert publish_realm_sync(realm.id)["changed"] is True  # into the local realm's own history, nowhere else
    assert _git(bare, "rev-parse", "main") == team_head
    assert _git(clone, "rev-parse", "HEAD") == team_head
    # The team moves on; a pull here does not fetch it.
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", "-q", str(bare), str(peer)], check=True, capture_output=True)
    _git(peer, "config", "user.email", "peer@localhost")
    _git(peer, "config", "user.name", "Peer")
    _git(peer, "commit", "--allow-empty", "-m", "the team moves on")
    _git(peer, "push", "-q")
    moved = _git(bare, "rev-parse", "main")
    assert moved != team_head
    pull_realm_sync(realm.id)
    assert _git(clone, "rev-parse", "HEAD") == team_head
    assert moved not in _git(runtime_paths.realm_sync_root() / "local", "rev-list", "--all")
    # Another member still reads exactly what was published before the leave.
    assert _git(peer, "ls-tree", "-r", "HEAD") == team_tree


def test_archive_follows_the_local_rules_once_the_realm_is_local():
    """Mutation: keep ``server_id`` on the realm -> the last archive answers ``realm_server_bound``, red."""
    realms, workspaces = RealmStore(), WorkspaceStore()
    home = realms.create(name="Home")
    realms.set_active(home.id)
    realms.set_default_pointer(home.id)
    team = realms.create(name="Team", server_id="srv_team", realm_id="realm_team")
    workspace = workspaces.create(name="Shared", realm_id=team.id)
    assert _rpc("runtime.realm.archive", realm_id=team.id)["error"]["data"] == {
        "reason": "realm_server_bound", "server_id": "srv_team"}
    _rpc("runtime.realm.revoked", realm_id=team.id, reason="membership_banned")
    assert _rpc("runtime.realm.archive", realm_id=team.id)["error"]["data"] == {
        "reason": "realm_not_empty", "workspace_ids": [workspace.id]}
    realms.set_active(team.id)
    workspaces.archive(workspace.id)
    assert _rpc("runtime.realm.archive", realm_id=team.id)["error"]["data"] == {"reason": "realm_is_active"}
    realms.set_active(home.id)
    archived = _rpc("runtime.realm.archive", realm_id=team.id)["result"]
    assert (archived["archived"], archived["changed"], archived["shared_from"]["server_id"]) == (True, True, "srv_team")


def test_no_address_or_token_stays_behind_and_the_servers_clone_goes_with_its_last_realm(tmp_path, monkeypatch):
    """Mutations: drop ``realm.sync_manifest_ref = None`` -> the realm record still holds the token, red; drop
    the ``_drop_server_clone`` call -> ``.git/config`` still holds it, red; drop the still-bound check in
    ``_drop_server_clone`` -> the clone goes while ``second`` still needs it, red; drop the remote-removal
    fallback -> the token stays when the tree cannot be removed, red."""
    url = f"https://x-access-token:{SECRET}@git.test.invalid/team.git"
    realms = RealmStore()

    def _bound(realm_id, server_id):
        realm = realms.create(name=realm_id, server_id=server_id, realm_id=realm_id)
        realm.sync_manifest_ref = url
        return realms.save(realm)

    def _clone_for(server_id):
        clone = runtime_paths.realm_sync_root() / server_id
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True, capture_output=True)
        _git(clone, "remote", "add", "origin", url)
        return clone

    def _leaks():
        root = runtime_paths.store_root()
        return sorted(str(path.relative_to(root)) for path in root.rglob("*")
                      if path.is_file() and SECRET.encode() in path.read_bytes())

    first, second = _bound("realm_first", "srv_team"), _bound("realm_second", "srv_team")
    clone = _clone_for("srv_team")
    baseline = runtime_paths.board_baseline_path(first.id)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("{}", encoding="utf-8")
    assert _leaks()

    _rpc("runtime.realm.revoked", realm_id=first.id, reason="membership_kicked")
    assert (clone / ".git").exists()  # ``second`` is still bound to the server and still syncs through it
    assert SECRET not in runtime_paths.realm_path(first.id).read_text(encoding="utf-8")
    _rpc("runtime.realm.revoked", realm_id=second.id, reason="membership_kicked")
    assert not clone.exists()
    assert _leaks() == []
    assert baseline.exists()  # the drift baselines are the realm's, not the clone's
    assert SECRET not in json.dumps(realm_summary(realms.get(first.id), workspaces=[]), default=str)

    # A clone that cannot be removed whole still loses its remotes.
    third = _bound("realm_third", "srv_other")
    stuck = _clone_for("srv_other")

    def _refuse(_path):
        raise OSError("in use")

    monkeypatch.setattr(realm_leave, "_remove_tree", _refuse)
    _rpc("runtime.realm.revoked", realm_id=third.id, reason="server_deleted")
    assert stuck.exists() and _git(stuck, "remote") == ""
    assert SECRET not in (stuck / ".git" / "config").read_text(encoding="utf-8")


def test_an_adopt_converts_a_realm_still_bound_under_an_old_member_mark(monkeypatch):
    """Mutation: drop the ``make_marked_realms_local`` call in ``realm_adopt`` -> ``old`` keeps ``srv_old``,
    red; drop its ``host_state`` skip -> the host-marked realm is refused by ``make_realm_local`` (ValueError),
    red; drop ``clear_realm_revocation`` in ``make_realm_local`` -> ``old`` keeps its mark, red."""
    realms = RealmStore()
    old = realms.create(name="Old", server_id="srv_old", realm_id="realm_old")
    host = realms.create(name="Host", server_id="srv_host", realm_id="realm_host")
    held = realms.create(name="Held", server_id="srv_team", realm_id="realm_team")
    mark_realm_revoked(old, RealmRevokedReason.ROLE_REVOKED)
    mark_realm_revoked(host, RealmRevokedReason.GIT_HOST_UNBOUND)
    mark_realm_revoked(held, RealmRevokedReason.TIMEOUT_STARTED)

    with turn_activity.admitted_turn("a live turn"):  # the re-key the conversion owes waits (read here: the leave)
        _adopt(monkeypatch, {"id": held.id, "server_id": "srv_team", "name": "Held", "slug": "held", "git_url": ""})

    assert realms.get(old.id).server_id is None
    assert read_rekey_journal(old.id)["state"] == "owed" and read_rekey_journal(held.id) is None
    assert read_realm_shared_from(old.id)["reason"] == "role_revoked"
    assert read_realm_revocation(old.id) is None
    assert realms.get(host.id).server_id == "srv_host"
    assert read_realm_revocation(host.id)["reason"] == "git_host_unbound"
    assert realms.get(held.id).server_id == "srv_team"  # re-granted: its mark was lifted, it stays bound
    assert read_realm_shared_from(held.id) is None
