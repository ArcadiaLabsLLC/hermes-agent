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


def _credential_for(realm_id: str, member_public_id: object):
    from agent_runtime.realm_membership import RealmSyncCredential

    return RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": f"local:{realm_id}", "api_base": "https://api.test.invalid/api",
        "api_token": "etk_test_api_token_000000", "git_url": "https://git.test.invalid/realm-sync/test.git",
        "git_authorization": "Bearer test_value_1234567890", "expires_at": "2999-01-01T00:00:00Z",
        "member_public_id": member_public_id,
    })


def test_a_publish_names_the_member_by_eternia_public_id_in_a_trailer_only(
    isolate_agent_runtime_root, tmp_path, member_identity, monkeypatch
):
    """RT-REALM-SYNC-COMMITS-NAME-NOBODY (owner RULED 2026-11-14): the robot authors the commit and an
    ``Eternia-Member: <public id>`` trailer says who published -- never an email or a real name.
    KILLING MUTATION: drop ``*trailer`` from the publish commit -> no trailer, red."""
    from agent_runtime.realm_sync import publish as realm_publish

    realm = RealmStore().create(name="Trailer Realm")
    repo = tmp_path / "realm-sync-repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    realm.sync_manifest_ref = str(repo)
    RealmStore().save(realm)
    WorkspaceStore().create(name="Launcher", realm_id=realm.id)
    member = "6f1c2a3b-4d5e-4f60-8a7b-9c0d1e2f3a4b"
    # The commit is what is under test; the credential's remote adoption is not.
    commit = realm_publish._stage_commit_and_push
    credential = _credential_for(realm.id, member)

    def stage(*args, **kwargs):
        return commit(*args, **{**kwargs, "credential": credential})

    monkeypatch.setattr(realm_publish, "_stage_commit_and_push", stage)
    assert publish_realm_sync(realm.id)["changed"] is True

    trailers = _git(repo, "log", "-1", "--format=%(trailers:key=Eternia-Member,valueonly)").strip()
    assert trailers == member
    assert _identities(repo, "-1") == {_ROBOT}
    assert _MEMBER_EMAIL not in _git(repo, "log", "-1", "--format=%B") and _MEMBER not in _git(repo, "log", "-1", "--format=%B")


@pytest.mark.parametrize("raw", ["", None, "member.person@example.invalid", "Member Person", "x\nEternia-Member: y"])
def test_anything_but_a_uuid_never_becomes_a_trailer(raw):
    assert _credential_for("realm_x", raw).member_public_id == ""
