"""Every realm has its own sync clone (RT-REALM-SYNC-ONE-CLONE-PER-REALM).

The clone used to be keyed by ``realm.server_id or "local"``: every realm of a server shared one working
tree and every server-less realm shared ``local``, so two realms could name different repositories but
not have different clones. Real ``git`` and bare repositories on disk throughout; the server realms take
the allow stub explicitly (the backend's membership answer is not what is under test).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime import paths
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync
from agent_runtime.realm_sync.git import _sync_repo_path
from agent_runtime.realm_sync.models import RealmMembershipProvider
from agent_runtime.store import RealmStore, WorkspaceStore

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

ALLOW = RealmMembershipProvider()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _bare(tmp_path: Path, name: str) -> Path:
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    seed = tmp_path / f"{name}-seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, capture_output=True)
    _git(seed, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "seed")
    _git(seed, "push", "-q", str(bare), "HEAD:main")
    return bare


def _server_realm(name: str, bare: Path, server_id: str = "srv_team"):
    realm = RealmStore().create(name=name, server_id=server_id)
    realm.sync_manifest_ref = bare.as_uri()
    realm = RealmStore().save(realm)
    WorkspaceStore().create(name=f"{name} desk", realm_id=realm.id)
    return realm


def _on(bare: Path) -> set[str]:
    return {line.split("/")[1] for line in _git(bare, "ls-tree", "-r", "--name-only", "main").splitlines()
            if line.startswith("realms/")}


def test_two_realms_of_one_server_bound_to_two_repositories_each_publish_and_pull(isolate_agent_runtime_root, tmp_path):
    """KILLING MUTATION: key ``_sync_repo_path`` by ``realm.server_id or "local"`` again -> the second realm
    publishes into the first one's clone, so its subtree lands on the FIRST repository and its own stays
    empty, red."""
    first_bare, second_bare = _bare(tmp_path, "first"), _bare(tmp_path, "second")
    first, second = _server_realm("First", first_bare), _server_realm("Second", second_bare)

    assert publish_realm_sync(first.id, membership=ALLOW)["state"] == "published"
    assert publish_realm_sync(second.id, membership=ALLOW)["state"] == "published"

    assert _on(first_bare) == {paths.safe_path_token(first.id)}
    assert _on(second_bare) == {paths.safe_path_token(second.id)}
    first_clone, second_clone = (_sync_repo_path(RealmStore().get(item.id)) for item in (first, second))
    assert first_clone != second_clone
    assert _git(first_clone, "config", "--get", "remote.origin.url") == first_bare.as_uri()
    assert _git(second_clone, "config", "--get", "remote.origin.url") == second_bare.as_uri()
    # Another member moves the second repository on; each realm pulls its own.
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", "-q", str(second_bare), str(peer)], check=True, capture_output=True)
    _git(peer, "-c", "user.email=p@localhost", "-c", "user.name=P", "commit", "-q", "--allow-empty", "-m", "peer")
    _git(peer, "push", "-q", "origin", "HEAD:main")
    pull_realm_sync(first.id, membership=ALLOW)
    pull_realm_sync(second.id, membership=ALLOW)
    assert _git(second_clone, "rev-parse", "HEAD") == _git(second_bare, "rev-parse", "main")
    assert _git(first_clone, "rev-parse", "HEAD") == _git(first_bare, "rev-parse", "main")


def test_a_server_less_realm_no_longer_shares_a_tree_with_the_players_other_local_realms(isolate_agent_runtime_root):
    one, two = RealmStore().create(name="One"), RealmStore().create(name="Two")
    for realm in (one, two):
        WorkspaceStore().create(name=f"{realm.name} desk", realm_id=realm.id)
        assert publish_realm_sync(realm.id)["changed"] is True

    one_clone, two_clone = _sync_repo_path(one), _sync_repo_path(two)
    assert one_clone == paths.realm_sync_clone_dir(one.id) and two_clone == paths.realm_sync_clone_dir(two.id)
    assert not (one_clone / "realms" / paths.safe_path_token(two.id)).exists()
    assert not (two_clone / "realms" / paths.safe_path_token(one.id)).exists()
    # The clone never lands in the realm's baseline folder, which already holds files.
    assert paths.realm_sync_clone_dir(one.id) not in (paths.realm_sync_root() / paths.safe_path_token(one.id)).parents
    assert not (paths.realm_sync_root() / paths.safe_path_token(one.id) / ".git").exists()


def _legacy_clone(bare: Path, server_id: str) -> Path:
    legacy = paths.realm_sync_root() / server_id
    legacy.parent.mkdir(parents=True, exist_ok=True)
    # As ``_git_clone`` made it: from the realm's own ref, so ``origin`` is that ref exactly.
    subprocess.run(["git", "clone", "-q", bare.as_uri(), str(legacy)], check=True, capture_output=True)
    return legacy


def test_an_old_shared_clone_is_copied_to_each_realm_it_holds_with_its_unpublished_work(isolate_agent_runtime_root, tmp_path):
    """KILLING MUTATION: drop the ``_carry_shared_clone`` call in ``_sync_repo_path`` -> the realm clones its
    remote fresh, and the unpublished commit and the uncommitted file are not in its clone, red."""
    bare = _bare(tmp_path, "team")
    first, second = _server_realm("First", bare), _server_realm("Second", bare)
    legacy = _legacy_clone(bare, "srv_team")
    for realm in (first, second):
        subtree = legacy / "realms" / paths.safe_path_token(realm.id)
        subtree.mkdir(parents=True)
        (subtree / "notes.txt").write_text(f"{realm.id} unpublished\n", encoding="utf-8")
    _git(legacy, "add", "-A")
    _git(legacy, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "-m", "never pushed")
    (legacy / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
    unpublished = _git(legacy, "rev-parse", "HEAD")

    for realm in (first, second):
        clone = _sync_repo_path(RealmStore().get(realm.id))
        assert clone == paths.realm_sync_clone_dir(realm.id)
        assert _git(clone, "rev-parse", "HEAD") == unpublished
        assert (clone / "scratch.txt").read_text(encoding="utf-8") == "uncommitted\n"
    assert _git(legacy, "rev-parse", "HEAD") == unpublished and (legacy / "scratch.txt").exists()  # never deleted

    publish_realm_sync(first.id, membership=ALLOW)
    assert _git(bare, "merge-base", "--is-ancestor", unpublished, "main") == ""  # the old work reached the remote


def test_an_old_shared_clone_is_not_inherited_by_a_realm_it_does_not_hold_or_whose_repository_differs(
    isolate_agent_runtime_root, tmp_path
):
    team_bare, own_bare = _bare(tmp_path, "team"), _bare(tmp_path, "own")
    fresh = _server_realm("Fresh", team_bare)
    moved = _server_realm("Moved", own_bare)
    legacy = _legacy_clone(team_bare, "srv_team")
    (legacy / "realms" / paths.safe_path_token(moved.id)).mkdir(parents=True)
    (legacy / "realms" / paths.safe_path_token(moved.id) / "x.txt").write_text("x\n", encoding="utf-8")

    assert not _sync_repo_path(fresh).exists()  # nothing of Fresh's in the old clone: it clones on its own
    assert not _sync_repo_path(moved).exists()  # the old clone's origin is another repository
    publish_realm_sync(moved.id, membership=ALLOW)
    assert _git(_sync_repo_path(moved), "config", "--get", "remote.origin.url") == own_bare.as_uri()


def test_after_leaving_a_server_the_realms_publish_never_reaches_the_teams_repository(isolate_agent_runtime_root, tmp_path):
    """The realm's own clone carries the team's ``origin``: the leave drops it, so the now-local realm's next
    publish commits into a clone of its own. KILLING MUTATION: drop ``_drop_clone(paths.realm_sync_clone_dir(
    realm.id))`` in ``make_realm_local`` -> the publish pushes the member's local work to the team, red."""
    from agent_runtime.realm_leave import make_realm_local
    from agent_runtime.realm_sync.revocation import RealmRevokedReason

    bare = _bare(tmp_path, "team")
    realm = _server_realm("Team", bare)
    publish_realm_sync(realm.id, membership=ALLOW)
    team_head = _git(bare, "rev-parse", "main")

    make_realm_local(realm.id, RealmRevokedReason.MEMBERSHIP_LEFT)
    WorkspaceStore().create(name="Added after leaving", realm_id=realm.id)
    assert publish_realm_sync(realm.id)["changed"] is True

    assert _git(bare, "rev-parse", "main") == team_head
    assert _git(_sync_repo_path(RealmStore().get(realm.id)), "remote") == ""


def _legacy_with_unpublished_work(bare: Path, realms) -> tuple[Path, str]:
    legacy = _legacy_clone(bare, "srv_team")
    for realm in realms:
        subtree = legacy / "realms" / paths.safe_path_token(realm.id)
        subtree.mkdir(parents=True)
        (subtree / "notes.txt").write_text(f"{realm.id} unpublished\n", encoding="utf-8")
    _git(legacy, "add", "-A")
    _git(legacy, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "-m", "never pushed")
    return legacy, _git(legacy, "rev-parse", "HEAD")


def test_an_old_shared_clone_is_removed_once_every_realm_it_holds_has_its_own_copy(isolate_agent_runtime_root, tmp_path):
    """RT-REALM-SYNC-OLD-SHARED-CLONES-STAY-ON-DISK. Kept while one realm has still to take its copy, removed
    after the last one does -- and the unpublished commit lives on in each realm's own clone.

    KILLING MUTATION: drop the ``_retire_shared_clone`` call in ``_sync_repo_path`` -> the old clone stays, red.
    KILLING MUTATION: drop the "has not taken its copy yet" return -> removed after the FIRST realm's lookup,
    and the second realm's unpublished commit is gone, red."""
    bare = _bare(tmp_path, "team")
    first, second = _server_realm("First", bare), _server_realm("Second", bare)
    legacy, unpublished = _legacy_with_unpublished_work(bare, (first, second))

    _sync_repo_path(RealmStore().get(first.id))
    assert legacy.exists()  # Second has not taken its copy yet
    second_clone = _sync_repo_path(RealmStore().get(second.id))
    assert not legacy.exists()
    assert _git(second_clone, "rev-parse", "HEAD") == unpublished
    assert _git(_sync_repo_path(first), "rev-parse", "HEAD") == unpublished


def test_an_old_shared_clone_with_work_only_it_holds_is_kept(isolate_agent_runtime_root, tmp_path):
    """Never removed while it has a file it never committed, or a commit some realm's own clone lacks.

    KILLING MUTATION: drop the porcelain check -> removed with the uncommitted file, red.
    KILLING MUTATION: drop the ``merge-base --is-ancestor`` check -> removed although First's clone was reset
    behind the shared clone's last commit, red."""
    bare = _bare(tmp_path, "team")
    first = _server_realm("First", bare)
    legacy, unpublished = _legacy_with_unpublished_work(bare, (first,))
    (legacy / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")

    clone = _sync_repo_path(RealmStore().get(first.id))
    assert legacy.exists() and (legacy / "scratch.txt").exists()  # a file only it has (the copy took one too)

    (legacy / "scratch.txt").unlink()
    _git(clone, "reset", "-q", "--hard", "HEAD~1")  # First's clone no longer holds the shared clone's commit
    _sync_repo_path(RealmStore().get(first.id))
    assert legacy.exists() and _git(legacy, "rev-parse", "HEAD") == unpublished

    _git(clone, "reset", "-q", "--hard", unpublished)
    _sync_repo_path(RealmStore().get(first.id))
    assert not legacy.exists()


def _empty_bare(tmp_path: Path, name: str) -> Path:
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    return bare


def _credential_for(realm, git_url: str):
    from datetime import UTC, datetime, timedelta

    from agent_runtime.realm_membership import RealmSyncCredential

    return RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": realm.id, "api_base": "https://api.test/api", "api_token": "t",
        "git_url": git_url, "git_authorization": "Basic dA==",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    })


def test_a_server_realm_whose_repository_moved_publishes_to_the_new_one_with_its_unpublished_work(
    isolate_agent_runtime_root, tmp_path
):
    """Backend REALM-OWN-REPO-CHANGE-NOT-ANNOUNCED, hermes half: the server connects another repository; the
    next credential names it. The existing clone used to keep the OLD origin and publish there for good.

    KILLING MUTATION: make ``_follow_server_repository`` return at once -> the publish lands on the old
    repository and the new one stays empty, red.
    KILLING MUTATION: drop ``_take_server_credential_url`` -> the realm's ref never moves, red."""
    old_bare, new_bare = _bare(tmp_path, "old"), _empty_bare(tmp_path, "new")
    realm = _server_realm("Team", old_bare)
    publish_realm_sync(realm.id, membership=ALLOW)
    clone = _sync_repo_path(RealmStore().get(realm.id))
    _git(clone, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "never pushed")
    unpublished = _git(clone, "rev-parse", "HEAD")
    old_tip = _git(old_bare, "rev-parse", "main")

    WorkspaceStore().create(name="A second desk", realm_id=realm.id)
    publish_realm_sync(realm.id, membership=ALLOW, credential=_credential_for(realm, new_bare.as_uri()))

    assert RealmStore().get(realm.id).sync_manifest_ref == new_bare.as_uri()
    assert _git(clone, "config", "--get", "remote.origin.url") == new_bare.as_uri()
    assert _git(old_bare, "rev-parse", "main") == old_tip  # nothing more went to the old repository
    assert _git(new_bare, "merge-base", "--is-ancestor", unpublished, "main") == ""
    assert _on(new_bare) == {paths.safe_path_token(realm.id)}
    assert pull_realm_sync(realm.id, membership=ALLOW)["state"] == "pulled"


def test_a_moved_repository_that_collides_with_the_clone_is_refused_with_nothing_lost(isolate_agent_runtime_root, tmp_path):
    """The new repository holds another history touching the same realm subtree: refused, the old origin is
    put back (the next verb tries again), the clone's commits are where they were.

    KILLING MUTATION: drop the put-back in the refusal arm -> the clone is left with no origin, red."""
    old_bare = _bare(tmp_path, "old")
    realm = _server_realm("Team", old_bare)
    publish_realm_sync(realm.id, membership=ALLOW)
    clone = _sync_repo_path(RealmStore().get(realm.id))
    head = _git(clone, "rev-parse", "HEAD")
    other = _empty_bare(tmp_path, "other")
    seed = tmp_path / "other-seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, capture_output=True)
    (seed / "realms" / paths.safe_path_token(realm.id)).mkdir(parents=True)
    (seed / "realms" / paths.safe_path_token(realm.id) / "manifest.json").write_text("{}\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "-m", "someone else's")
    _git(seed, "push", "-q", str(other), "HEAD:main")

    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(realm.id, membership=ALLOW, credential=_credential_for(realm, other.as_uri()))

    assert refused.value.code == "sync_remote_diverged"
    assert _git(clone, "config", "--get", "remote.origin.url") == old_bare.as_uri()
    assert _git(clone, "rev-parse", "HEAD") == head
