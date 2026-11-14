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


def _race(team: _Team, monkeypatch, realm_id: str, *, racer: str, publishes) -> None:
    """``racer`` publishes inside the next publish's fetch->push window, once."""

    real_refresh = realm_publish._refresh_remote_tracking
    state = {"raced": False}

    def refresh(repo, **kwargs):
        answer = real_refresh(repo, **kwargs)
        if not state["raced"]:
            state["raced"] = True
            team.be(racer)
            publishes()
            publish_realm_sync(realm_id)
            team.be("bob")
        return answer

    monkeypatch.setattr(realm_publish, "_refresh_remote_tracking", refresh)


def test_the_loser_of_a_publish_race_is_told_to_pull_and_its_pull_reconciles(team, monkeypatch):
    """Carol publishes in Bob's fetch->push window; Bob's push is rejected non-fast-forward.

    Mutation: in ``_stage_commit_and_push`` restore the blanket ``sync_remote_unreachable`` re-raise
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

    Mutation: in ``_stage_commit_and_push`` answer every push failure with ``sync_push_rejected``
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

