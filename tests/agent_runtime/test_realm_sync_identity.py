"""A realm's git history never carries the publishing member's own name or address
(RT-REALM-SYNC-COMMIT-LEAKS-MEMBER-EMAIL).

The robot identity used to be written only when ``git config user.email`` answered nothing, and that
lookup reads the GLOBAL config: on a machine whose user had a git identity -- nearly every developer
machine -- the publish carried that person's name and email into a repository other members read.
These cases give the "member" a global identity AND exported ``GIT_AUTHOR_*``/``GIT_COMMITTER_*``
variables (which outrank any config) and drive the real publish verb.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_runtime.realm_sync import publish_realm_sync
from agent_runtime.store import RealmStore, WorkspaceStore

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

_MEMBER = "Member Person"
_MEMBER_EMAIL = "member.person@example.invalid"
_ROBOT = "Hermes Realm Sync <realm-sync@localhost>"


@pytest.fixture
def member_identity(tmp_path, monkeypatch):
    home = tmp_path / "member-home"
    home.mkdir()
    (home / ".gitconfig").write_text(f"[user]\n\tname = {_MEMBER}\n\temail = {_MEMBER_EMAIL}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", _MEMBER)
        monkeypatch.setenv(f"GIT_{role}_EMAIL", _MEMBER_EMAIL)


def _git(repo: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": str(repo), "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def _identities(repo: Path, rev: str = "HEAD") -> set[str]:
    return set(_git(repo, "log", "--format=%an <%ae>%n%cn <%ce>", rev).split("\n")) - {""}


def test_a_publish_from_a_machine_with_a_git_identity_is_authored_by_the_robot(
    isolate_agent_runtime_root, tmp_path, member_identity
):
    """KILLING MUTATION: drop ``*SYNC_IDENTITY`` from ``_REPO_CONFIG`` -> the commit names the
    member, red; keep it but let ``run_sync_git`` pass the env through -> red the same way."""
    realm = RealmStore().create(name="Identity Realm")
    repo = tmp_path / "realm-sync-repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    realm.sync_manifest_ref = str(repo)
    RealmStore().save(realm)
    WorkspaceStore().create(name="Launcher", realm_id=realm.id)

    assert publish_realm_sync(realm.id)["changed"] is True

    assert _identities(repo) == {_ROBOT}
    assert _MEMBER_EMAIL not in _git(repo, "log", "--format=%B%n%an%ae%cn%ce")
    assert "user.email" not in _git(repo, "config", "--local", "--list")


def test_the_commit_a_remote_receives_names_the_robot(isolate_agent_runtime_root, tmp_path, member_identity):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True, text=True)
    realm = RealmStore().create(name="Remote Identity Realm")
    repo = tmp_path / "realm-sync-repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _git(repo, "-c", "user.name=Seed", "-c", "user.email=seed@localhost", "commit", "--allow-empty", "-m", "init")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "HEAD")
    realm.sync_manifest_ref = str(repo)
    RealmStore().save(realm)
    WorkspaceStore().create(name="Launcher", realm_id=realm.id)

    assert publish_realm_sync(realm.id)["changed"] is True

    assert _identities(bare, "-1") == {_ROBOT}
