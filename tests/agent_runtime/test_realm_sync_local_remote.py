"""A local realm adopts the personal repo its ``local:`` credential names (p10-work §2.6, stage B1,
``REALM-LOCAL-REMOTE-FROM-CREDENTIAL``).

Real ``git`` throughout: a bare repo under ``tmp_path`` plays the player's personal GitHub repo,
reached through a one-process ``url.<dir>.insteadOf`` (``GIT_CONFIG_*`` env) so the credential's
``git_url`` is a real https-shaped remote (``_looks_like_remote``) and nothing touches the network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime import paths as runtime_paths
from agent_runtime.realm_membership import RealmSyncCredential
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync, realm_sync_status
from agent_runtime.store import RealmStore, WorkspaceStore

HOST = "https://github.example/player/"
PERSONAL = HOST + "eternia-realms.git"
SECRET = "Bearer gh_personal_sekret_value_1234567890"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> None:
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "-m", message)


@pytest.fixture
def personal(tmp_path, monkeypatch) -> Path:
    host = tmp_path / "host"
    host.mkdir()
    bare = host / "eternia-realms.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{host.as_posix()}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", HOST)
    return bare


def _credential(realm_id: str) -> RealmSyncCredential:
    return RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": realm_id, "api_base": "https://api.test.invalid/api",
        "api_token": "etk_test_api_token_000000", "git_url": PERSONAL, "git_authorization": SECRET,
        "expires_at": "2999-01-01T00:00:00Z",
    })


def _local_realm(name: str = "Personal Realm"):
    realm = RealmStore().create(name=name)
    return realm, _credential(f"local:{realm.id}")


def _shared_local_repo() -> Path:
    return runtime_paths.realm_sync_root() / "local"


def _other_machine_pushes(tmp_path: Path, bare: Path, files: dict[str, str]) -> None:
    other = tmp_path / "machine-a"
    subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True, capture_output=True)
    _commit(other, files, "machine a")
    _git(other, "push", "-q", str(bare), "HEAD:main")


def test_a_local_credential_sets_sync_manifest_ref_and_adds_origin_on_the_shared_local_repo(
    isolate_agent_runtime_root, personal
):
    realm, credential = _local_realm()

    realm_sync_status(realm.id, credential=credential)

    assert RealmStore().get(realm.id).sync_manifest_ref == PERSONAL
    repo = _shared_local_repo()
    assert _git(repo, "config", "--get", "remote.origin.url") == PERSONAL
    assert _git(repo, "symbolic-ref", "--short", "HEAD") == "main"


def test_first_publish_pushes_with_upstream_into_the_empty_personal_repo(isolate_agent_runtime_root, personal):
    realm, credential = _local_realm()
    WorkspaceStore().create(name="Launcher", realm_id=realm.id, agent_ids=["dev"])

    result = publish_realm_sync(realm.id, credential=credential)

    assert result["state"] == "published"
    repo = _shared_local_repo()
    assert _git(repo, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"
    on_origin = _git(personal, "ls-tree", "-r", "--name-only", "main").splitlines()
    assert any(p.startswith(f"realms/{runtime_paths.safe_path_token(realm.id)}/") for p in on_origin)


def test_pull_then_fast_forwards_from_origin(isolate_agent_runtime_root, personal, tmp_path):
    realm, credential = _local_realm()
    pull_realm_sync(realm.id, credential=credential)  # an EMPTY personal repo: nothing to pull, no refusal
    WorkspaceStore().create(name="Launcher", realm_id=realm.id, agent_ids=["dev"])
    publish_realm_sync(realm.id, credential=credential)
    member = tmp_path / "member"
    subprocess.run(["git", "clone", "-q", str(personal), str(member)], check=True, capture_output=True)
    _commit(member, {"NOTES.txt": "from another machine\n"}, "notes")
    _git(member, "push", "-q", "origin", "HEAD:main")

    pull_realm_sync(realm.id, credential=credential)

    assert _git(_shared_local_repo(), "rev-parse", "HEAD") == _git(personal, "rev-parse", "main")


@pytest.mark.parametrize("shared", [False, True], ids=["disjoint_subtrees_merge", "shared_path_refuses"])
def test_a_second_machine_merges_disjoint_subtrees_and_refuses_a_shared_path(
    isolate_agent_runtime_root, personal, tmp_path, shared
):
    realm, credential = _local_realm()
    token = runtime_paths.safe_path_token(realm.id)
    _other_machine_pushes(tmp_path, personal, {
        "realms/realm_from_machine_a/realm_sync.json": "{}\n", **({"README.md": "a\n"} if shared else {}),
    })
    repo = _shared_local_repo()  # this machine's own, unrelated local history
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
    _commit(repo, {f"realms/{token}/realm_sync.json": "{}\n", **({"README.md": "b\n"} if shared else {})}, "b")

    if shared:
        with pytest.raises(RealmSyncError) as excinfo:
            realm_sync_status(realm.id, credential=credential)
        assert excinfo.value.code == "sync_remote_diverged"
        assert "README.md" in excinfo.value.safe_details["detail"]
        return
    realm_sync_status(realm.id, credential=credential)
    tracked = set(_git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
    assert {"realms/realm_from_machine_a/realm_sync.json", f"realms/{token}/realm_sync.json"} <= tracked
    assert _git(repo, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"


def test_a_server_credential_never_adopts_into_the_local_repo(isolate_agent_runtime_root, personal):
    realm = RealmStore().create(name="Server-subject")
    credential = _credential(realm.id)  # no ``local:`` prefix: the SERVER subject

    realm_sync_status(realm.id, credential=credential)

    assert not RealmStore().get(realm.id).sync_manifest_ref
    assert _git(_shared_local_repo(), "remote") == ""


def test_a_course_credential_is_refused_before_any_git_call(isolate_agent_runtime_root, personal, monkeypatch):
    from agent_runtime import git_cmd

    realm = RealmStore().create(name="Course-subject")
    calls: list[list[str]] = []
    real_run = git_cmd.subprocess.run
    monkeypatch.setattr(git_cmd.subprocess, "run", lambda cmd, *a, **k: calls.append(list(cmd)) or real_run(cmd, *a, **k))

    with pytest.raises(RealmSyncError) as excinfo:
        pull_realm_sync(realm.id, credential=_credential(f"course:{realm.id}"))

    assert excinfo.value.code == "sync_auth_failed"
    assert calls == []


def test_the_authorization_header_never_lands_in_git_config(isolate_agent_runtime_root, personal, monkeypatch):
    from agent_runtime import git_cmd

    realm, credential = _local_realm()
    WorkspaceStore().create(name="Launcher", realm_id=realm.id, agent_ids=["dev"])
    calls: list[list[str]] = []
    real_run = git_cmd.subprocess.run
    monkeypatch.setattr(git_cmd.subprocess, "run", lambda cmd, *a, **k: calls.append(list(cmd)) or real_run(cmd, *a, **k))

    publish_realm_sync(realm.id, credential=credential)
    pull_realm_sync(realm.id, credential=credential)

    header = credential.git_extra_config()[0]
    assert any("remote" in cmd and "add" in cmd and header in cmd for cmd in calls)  # the adopter carried it
    assert any("push" in cmd and header in cmd for cmd in calls)
    config_text = (_shared_local_repo() / ".git" / "config").read_text(encoding="utf-8").lower()
    assert "extraheader" not in config_text
    assert "sekret" not in config_text
