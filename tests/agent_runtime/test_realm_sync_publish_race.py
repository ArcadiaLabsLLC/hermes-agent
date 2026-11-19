"""Two members publishing one realm at once (RT-REALM-PUBLISH-RACE-SAYS-UNREACHABLE).

The loser of the race must be told that someone else published first and to pull, and its pull
must then REACH the whole-document reconciliation the pull lane already has. Before the fix both
verbs answered ``sync_remote_unreachable``, so the loser was stuck: publish refused ``sync_behind``
"pull before publishing" and the pull aborted on ``--ff-only`` with the network's error code.

The race is interleaved deterministically in the one window that has it — between
``publish_realm_sync``'s fetch and ``_stage_commit_and_push``'s push — by letting the other member
publish inside the patched refresh. No server, no network: one bare remote on disk per the
``_Team`` harness.
"""
from __future__ import annotations

import subprocess

import pytest

from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync
from agent_runtime.realm_sync import git as realm_git
from agent_runtime.realm_sync import publish as realm_publish
from agent_runtime.store import WorkspaceStore
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team, _git, _shared_workspace


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _race(team: _Team, monkeypatch, realm_id: str, *, racer: str, publishes, then_publish: bool = True) -> None:
    """``racer`` publishes inside the next publish's fetch->push window, once.

    ``then_publish=False``: ``publishes`` itself puts the racer's commit on the remote, and no
    ``publish_realm_sync`` of the racer's follows (that one rewrites the realm document)."""

    real_refresh = realm_publish._refresh_remote_tracking
    state = {"raced": False}

    def refresh(repo, **kwargs):
        answer = real_refresh(repo, **kwargs)
        if not state["raced"]:
            state["raced"] = True
            team.be(racer)
            publishes()
            if then_publish:
                publish_realm_sync(realm_id)
            team.be("bob")
        return answer

    monkeypatch.setattr(realm_publish, "_refresh_remote_tracking", refresh)


def test_the_loser_of_a_publish_race_is_told_to_pull_and_its_pull_reconciles(team, monkeypatch):
    """Carol publishes in Bob's fetch->push window; Bob's push is rejected non-fast-forward.

    Mutation: in ``_push_upstream`` restore the blanket ``sync_remote_unreachable`` re-raise
    -> red at ``sync_push_rejected``. Mutation: in ``_pull_remote_into_repo`` drop the diverged
    branch (always ``--ff-only``) -> Bob's pull raises ``sync_remote_unreachable`` and he never sees
    Carol's workspace."""

    shared, workspace = _shared_workspace(team, members=("bob", "carol"))
    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob renamed")

    carols: dict[str, str] = {}

    def carol_publishes() -> None:
        carols["id"] = WorkspaceStore().create(name="Carol's own", realm_id=shared.id).id

    _race(team, monkeypatch, shared.id, racer="carol", publishes=carol_publishes)

    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(shared.id)
    assert refused.value.code == "sync_push_rejected"
    assert refused.value.retryable is True
    assert "published to this realm first" in str(refused.value)
    assert "unreachable" not in str(refused.value).lower()

    # The deadlock: the loser's own next publish refuses, and the pull must get it out.
    with pytest.raises(RealmSyncError) as behind:
        publish_realm_sync(shared.id)
    assert behind.value.code == "sync_behind"

    pulled = pull_realm_sync(shared.id)
    assert pulled["state"] == "pulled"
    assert WorkspaceStore().get(carols["id"]).realm_id == shared.id
    assert WorkspaceStore().get(workspace.id).name == "Bob renamed"
    published = publish_realm_sync(shared.id)
    assert published["state"] == "published"
    assert team.published_workspace_ids(shared) == {workspace.id, carols["id"]}


def test_a_race_on_the_very_same_document_ends_where_a_plain_pull_ends(team, monkeypatch):
    """Both rename the SAME workspace. The loser's pull goes through and the realm's own
    reconciliation decides the document — the state a pull of a merely-behind repo reaches,
    not a git conflict on the manifest every publish rewrites.

    Mutation: in ``_merge_remote`` drop ``-X theirs`` -> the merge conflicts on
    ``manifest.json`` and the pull raises ``sync_conflict``, red at ``pulled``."""

    shared, workspace = _shared_workspace(team, members=("bob", "carol"))
    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob renamed")

    def carol_publishes() -> None:
        WorkspaceStore().rename(workspace.id, "Carol renamed")

    _race(team, monkeypatch, shared.id, racer="carol", publishes=carol_publishes)

    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(shared.id)
    assert refused.value.code == "sync_push_rejected"

    pulled = pull_realm_sync(shared.id)
    assert pulled["state"] == "pulled"
    assert WorkspaceStore().get(workspace.id).name == "Carol renamed"
    assert publish_realm_sync(shared.id)["state"] == "published"


def test_the_publish_after_the_pull_carries_the_losers_own_commit_upstream(team, monkeypatch):
    """The other member's publish touches nothing Bob changed, so after the pull Bob's store
    already matches the merged subtree and his next publish has no NEW bytes to commit. It must
    still push his kept commit and the merge, or it answers "published" while the remote never
    got his work (seen live 2026-11-13, w1113-publishrace: the clone stayed ``ahead 2``).

    Mutation: in ``_stage_commit_and_push`` drop the nothing-to-commit push -> red at the
    unpushed count (Bob's kept commit and the merge, ``2``)."""

    shared, workspace = _shared_workspace(team, members=("bob", "carol"))
    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob renamed")

    def carol_publishes() -> None:
        clone = team.clone("carol", shared.server_id)
        _git(clone, "pull", "-q", "--ff-only")
        _git(clone, "-c", "user.email=c@localhost", "-c", "user.name=Carol",
             "commit", "-q", "--allow-empty", "-m", "Carol's publish")
        _git(clone, "push", "-q", "origin", "HEAD:main")

    _race(team, monkeypatch, shared.id, racer="carol", publishes=carol_publishes, then_publish=False)

    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(shared.id)
    assert refused.value.code == "sync_push_rejected"
    assert pull_realm_sync(shared.id)["state"] == "pulled"
    assert publish_realm_sync(shared.id)["state"] == "published"

    bob = team.clone("bob", shared.server_id)
    _git(bob, "fetch", "-q", "origin")
    assert _git(bob, "rev-list", "--count", "@{u}..HEAD").strip() == "0"
    assert _git(team.remote(shared.server_id), "grep", "-l", "Bob renamed", "main").strip()


def test_a_merge_git_cannot_resolve_is_a_conflict_not_an_unreachable_remote(tmp_path):
    """Two sides whose trees disagree on a path's shape: ``-X theirs`` cannot resolve it, and
    the operator is told which paths to clear.

    Mutation: in ``_merge_remote`` drop the ``conflicts`` branch -> ``sync_remote_unreachable``,
    red at ``sync_conflict``."""

    bare, repo = tmp_path / "remote.git", tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "T")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    _git(repo, "push", "-q", "-u", "origin", "main")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "doc").write_text("ours\n", encoding="utf-8")  # a FILE where theirs holds a directory
    _git(repo, "add", "doc")
    _git(repo, "commit", "-q", "-m", "ours")
    ours = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", base)
    (repo / "doc").mkdir()
    (repo / "doc" / "inner.txt").write_text("theirs\n", encoding="utf-8")
    _git(repo, "add", "doc/inner.txt")
    _git(repo, "commit", "-q", "-m", "theirs")
    _git(repo, "push", "-q", "origin", "HEAD:main")
    _git(repo, "checkout", "-q", "-B", "main", ours)
    _git(repo, "fetch", "-q", "origin")

    with pytest.raises(RealmSyncError) as conflicted:
        realm_git._merge_remote(repo)
    assert conflicted.value.code == "sync_conflict"
    assert conflicted.value.safe_details["conflicts"]


def test_an_unreachable_remote_still_says_unreachable(team):
    """The two codes stay apart: a remote that is gone is not a lost race.

    Mutation: in ``_push_upstream`` answer every push failure with ``sync_push_rejected``
    -> red here."""

    shared, _workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    clone = team.clone("bob", shared.server_id)
    _git(clone, "remote", "set-url", "origin", str(team.tmp / "nowhere.git"))
    WorkspaceStore().rename(_workspace.id, "Bob renamed")

    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(shared.id)
    assert refused.value.code == "sync_remote_unreachable"


def test_the_push_rejection_classifier_reads_gits_own_words():
    """The non-fast-forward tell, not a guess at the whole stderr.

    Mutation: make ``_push_was_rejected`` return True unconditionally -> red at the second case."""

    assert realm_git._push_was_rejected(
        "! [rejected]        main -> main (fetch first)\nerror: failed to push some refs"
    )
    assert not realm_git._push_was_rejected("fatal: could not read from remote repository")



def test_githubs_cannot_lock_ref_is_a_lost_race_not_an_unreachable_remote():
    """GitHub refuses the loser of two pushes landing at once with ``cannot lock ref``
    (RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE, seen 2026-11-19); a hook's bare refusal is not a race.

    Mutation: drop ``cannot lock ref`` from ``_PUSH_REJECTED_TELLS`` -> red at the first case."""

    assert realm_git._push_was_rejected(
        " ! [remote rejected] HEAD -> main (cannot lock ref 'refs/heads/main': is at 8a2a4af but expected 6e81c31)"
    )
    assert not realm_git._push_was_rejected(" ! [remote rejected] HEAD -> main (pre-receive hook declined)")


def test_a_push_refused_with_cannot_lock_ref_tells_the_member_to_pull(team, monkeypatch, realm_sync_arm):
    """Both gits read the refusal through the ONE tells list (RT-REALM-PUSH-LOST-RACE-READS-REMOTE-UNREACHABLE).

    The git program meets a held ref lock on the bare remote, which it words as GitHub does; the phone's git
    gets GitHub's per-ref refusal from a stand-in transport (a local remote never words one). Mutation: in
    ``git_dulwich.DulwichSyncGit.push`` test the old hand-kept tuple instead of ``_push_was_rejected`` -> the
    dulwich arm reds at ``sync_push_rejected``."""

    shared, workspace = _shared_workspace(team, members=("bob",))
    team.be("bob")
    WorkspaceStore().rename(workspace.id, "Bob renamed")
    if realm_sync_arm == "dulwich":
        from dulwich.client import SendPackResult

        from agent_runtime.realm_sync import git_dulwich

        class _GitHub:
            def send_pack(self, path, update_refs, generate_pack_data):
                return SendPackResult({}, ref_status={
                    b"refs/heads/main": "cannot lock ref 'refs/heads/main': is at 8a2a4af but expected 6e81c31"})

        real_client = git_dulwich.DulwichSyncGit._client

        def client(self, url, auth, step):
            found = real_client(self, url, auth, step)
            return (_GitHub(), found[1]) if step[0] == "push" else found

        monkeypatch.setattr(git_dulwich.DulwichSyncGit, "_client", client)
    else:
        (team.remote(shared.server_id) / "refs" / "heads" / "main.lock").write_text("held\n", encoding="utf-8")

    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(shared.id)
    assert refused.value.code == "sync_push_rejected"


def _desk(workspace_id: str, x: float) -> None:
    from agent_runtime.office_store import OfficeStore

    OfficeStore().upsert_actor(workspace_id, {"persona_id": "dev", "items": [
        {"item_id": "dev", "persona_id": "dev", "kind": "agent", "position": [x, -2.0], "folder": "Agents"}]})


def _remote_desks(team: _Team, shared) -> list[str]:
    names = _git(team.remote(shared.server_id), "ls-tree", "-r", "--name-only", "main").splitlines()
    return [name.rsplit("/", 1)[-1] for name in names if "/store/office/" in name and "/actors/" in name]


def test_a_committed_edit_meeting_a_teammates_delete_takes_the_team_copy(team, monkeypatch):
    """Bob's publish moves the desk and loses the race to Carol's delete of it. His pull takes the team's
    copy instead of stopping in ``sync_conflict``, names the edit it dropped, and the desk stays deleted for
    the team (TASK-REALM-DELETE-MEETS-AN-EDIT, review w1118a.36 D1; both gits).

    Mutations: ``merge_theirs.FavouringMerger._settle_modify_delete`` / ``git_binary.BinarySyncGit.
    _settle_modify_delete`` a no-op -> that arm reds at ``sync_conflict``; answer ``[]`` for
    ``DROPPED_LOCAL_CHANGES_KEY`` in ``pull._pull_realm_sync`` -> red at the dropped list."""

    from agent_runtime.office_store import OfficeStore
    from agent_runtime.realm_sync.pull import DROPPED_LOCAL_CHANGES_KEY

    shared, workspace = _shared_workspace(team, members=("bob", "carol"))
    team.be("bob")
    _desk(workspace.id, 9.5)

    def carol_deletes_the_desk() -> None:
        OfficeStore().remove_actor(workspace.id, "dev")

    _race(team, monkeypatch, shared.id, racer="carol", publishes=carol_deletes_the_desk)
    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(shared.id)
    assert refused.value.code == "sync_push_rejected"

    pulled = pull_realm_sync(shared.id)
    assert pulled["state"] == "pulled"
    assert pulled["conflicts"] == []
    assert [path.rsplit("/", 1)[-1] for path in pulled[DROPPED_LOCAL_CHANGES_KEY]] == ["dev.json"]
    assert all(path.startswith("store/office/") for path in pulled[DROPPED_LOCAL_CHANGES_KEY])
    # The store's copy is the member's to choose: held, never silently dropped or re-published.
    assert [row["actor_key"] for row in pulled["office_sync"]["held"]] == ["dev"]
    assert publish_realm_sync(shared.id)["state"] == "published"
    assert _remote_desks(team, shared) == []


def test_revert_all_frees_a_clone_stuck_in_a_conflict(team, monkeypatch):
    """A clone an older engine left mid-merge (``sync_conflict`` on every verb) is freed by Revert all: the
    unpublished commit and the merge state go, the clone sits on the team's copy, and the next pull and
    publish go through (TASK-REALM-DELETE-MEETS-AN-EDIT, review w1118a.36 D1; both gits).

    Mutation: skip the reset in ``git._reset_clone_to_team_copy`` -> red at the pull after the revert."""

    from agent_runtime.office_store import OfficeStore
    from agent_runtime.realm_revert import revert_realm_sync

    shared, workspace = _shared_workspace(team, members=("bob", "carol"))
    team.be("bob")
    _desk(workspace.id, 9.5)

    def carol_deletes_the_desk() -> None:
        OfficeStore().remove_actor(workspace.id, "dev")

    _race(team, monkeypatch, shared.id, racer="carol", publishes=carol_deletes_the_desk)
    with pytest.raises(RealmSyncError):
        publish_realm_sync(shared.id)
    clone = team.clone("bob", shared.server_id)
    # The state an older engine left: git's own merge, which leaves a modify/delete in the index.
    stuck = subprocess.run(["git", "-C", str(clone), "-c", "user.email=b@localhost", "-c", "user.name=B",
                            "pull", "-q", "--no-rebase", "--no-edit", "-X", "theirs"], capture_output=True, text=True)
    assert stuck.returncode != 0
    with pytest.raises(RealmSyncError) as conflicted:
        pull_realm_sync(shared.id)
    assert conflicted.value.code == "sync_conflict"

    reverted = revert_realm_sync(shared.id, revert_all=True)
    assert reverted["clone_reset"]["conflicts"]
    assert reverted["clone_reset"]["unpublished_commits"] == 1
    assert realm_git._git_state(clone) == {"ahead": 0, "behind": 0, "conflicts": [], "dirty": False}
    assert pull_realm_sync(shared.id)["state"] == "pulled"
    assert publish_realm_sync(shared.id)["state"] == "published"
    assert _remote_desks(team, shared) == []
