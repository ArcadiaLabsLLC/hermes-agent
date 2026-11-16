"""RT-REALM-PUBLISHING-PUSHES-A-FOLDER — a realm publishes a ready-made folder, as it is, to its publishing
repository (``agent_runtime.realm_publishing``; slice S3 of Eternia
``docs/mission_control/planned/REALM_ARTIFACTS_REPOSITORY_2026-11-16.md``).

The publishing repository is a local bare repository; the backend's permission answer is the stdlib transport
``realm_membership._request_json`` replaced, so the real ask runs and its URL is read. Killing mutations are
named per test."""

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_runtime import paths, realm_membership, serve_rpc
from agent_runtime.realm_membership import RealmSyncCredential
from agent_runtime.realm_publishing import publish_folder
from agent_runtime.realm_sync import RealmSyncError
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT

REALM = "rlm_site"
MEMBER = str(uuid.UUID(int=7))
SECRET = "ghs_publishing_secret"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _payload(remote: Path, realm_id: str = f"publishing:{REALM}") -> dict:
    return {
        "schema_version": 1, "realm_id": realm_id, "api_base": "https://api.test.invalid/api",
        "api_token": "etk_publish", "git_url": remote.as_uri(),
        "git_authorization": "Basic " + SECRET,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "member_public_id": MEMBER,
    }


@pytest.fixture
def remote(tmp_path) -> Path:
    bare = tmp_path / "site.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


@pytest.fixture
def asks(monkeypatch) -> list[str]:
    """The backend's permission route answers ``allowed``; every URL asked is recorded."""
    seen: list[str] = []

    def answer(method, url, *, headers=None, **_kw):
        seen.append(url)
        return 200, {"allowed": True}

    monkeypatch.setattr(realm_membership, "_request_json", answer)
    return seen


def _site(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_a_folder_is_published_as_it_is_and_republished_on_top(tmp_path, remote, asks):
    """The bare repository's ``gh-pages`` holds exactly the folder plus ``.nojekyll`` (a ``.git`` inside the
    folder left out), authored by the robot with the member's trailer; a second publish replaces the tree
    on top of the first commit, and a third with nothing new commits nothing. Red if ``.nojekyll`` is not
    written, if a removed file survives (the tree is not replaced), or if the second publish is not a
    fast-forward of the first (an orphan push is refused by the bare repository)."""
    folder = _site(tmp_path / "out", {"index.html": "<h1>hi</h1>\r\n", "css/a.css": "a{}", ".git/HEAD": "x"})
    credential = RealmSyncCredential.parse(_payload(remote))

    first = publish_folder(REALM, str(folder), credential=credential)
    assert first["kind"] == "realm_publishing_push" and first["changed"] is True and first["files"] == 2
    assert _git(remote, "ls-tree", "-r", "--name-only", "gh-pages").split() == [".nojekyll", "css/a.css", "index.html"]
    assert subprocess.run(["git", "-C", str(remote), "cat-file", "blob", "gh-pages:index.html"],
                          check=True, capture_output=True).stdout == b"<h1>hi</h1>\r\n"
    assert _git(remote, "log", "-1", "--format=%an|%(trailers:key=Eternia-Member,valueonly)", "gh-pages") \
        == f"Hermes Realm Publishing|{MEMBER}"
    assert asks == [f"https://api.test.invalid/api/realms/{REALM}/sync/permission?action=publish"]
    assert paths.realm_publishing_clone_dir(REALM).is_dir()

    (folder / "css/a.css").unlink()
    second = publish_folder(REALM, str(folder), credential=credential)
    assert _git(remote, "ls-tree", "-r", "--name-only", "gh-pages").split() == [".nojekyll", "index.html"]
    assert _git(remote, "rev-parse", "gh-pages^") == first["commit"]
    assert second["commit"] == _git(remote, "rev-parse", "gh-pages")

    third = publish_folder(REALM, str(folder), credential=credential)
    assert third["changed"] is False and third["commit"] == second["commit"]
    assert _git(remote, "rev-list", "--count", "gh-pages") == "2"


def test_a_member_the_backend_refuses_publishes_nothing(tmp_path, remote, monkeypatch):
    """The backend's ``sync_permission(…, "publish")`` is asked right before the push and its refusal is the
    verb's. Red if the ask is skipped (``_require_permission``): the folder is pushed."""
    monkeypatch.setattr(realm_membership, "_request_json",
                        lambda *a, **kw: (200, {"allowed": False, "code": "role_insufficient"}))
    folder = _site(tmp_path / "out", {"index.html": "x"})
    with pytest.raises(RealmSyncError) as refused:
        publish_folder(REALM, str(folder), credential=RealmSyncCredential.parse(_payload(remote)))
    assert refused.value.code == "role_insufficient"
    assert _git(remote, "for-each-ref") == ""


def test_nothing_connected_is_refused_plainly(tmp_path, asks):
    """No publishing credential = no publishing repository connected: ``publishing_not_connected`` with a
    sentence a player can act on, and nobody asked. Red if that arm is dropped (the verb then fails on the
    missing credential with an AttributeError, not a refusal)."""
    folder = _site(tmp_path / "out", {"index.html": "x"})
    with pytest.raises(RealmSyncError) as refused:
        publish_folder(REALM, str(folder), credential=None)
    assert refused.value.code == "publishing_not_connected"
    assert "no publishing repository connected" in str(refused.value)
    assert asks == []


@pytest.mark.parametrize("realm_id", [REALM, "publishing:other", f"course:{REALM}"])
def test_a_credential_for_anything_but_this_realms_publishing_repo_pushes_nothing(tmp_path, remote, asks, realm_id):
    """The realm's WORKING repository credential (a bare id), another realm's publishing one and a course's
    are refused before any ask or push: a site pushed into the working repository would overwrite the team's
    data. Red if the subject check or the realm match is dropped."""
    folder = _site(tmp_path / "out", {"index.html": "x"})
    with pytest.raises(RealmSyncError) as refused:
        publish_folder(REALM, str(folder), credential=RealmSyncCredential.parse(_payload(remote, realm_id)))
    assert refused.value.code == "sync_auth_failed"
    assert asks == [] and _git(remote, "for-each-ref") == ""


def test_the_method_lane_publishes_and_names_its_refusal(tmp_path, remote, asks):
    """``runtime.realm.publishing.push`` (console tier) answers the verb's envelope, and ``publishing_not_connected``
    as a conflict, the credential never echoed. Red if the method is not registered or the reason unmapped."""
    folder = _site(tmp_path / "out", {"index.html": "x"})

    def call(params):
        return serve_rpc.handle_request(
            {"jsonrpc": "2.0", "id": "p", "method": "runtime.realm.publishing.push", "params": params})

    published = call({"realm_id": REALM, "folder": str(folder), "credential": _payload(remote), "yes": True})
    assert published["result"]["changed"] is True, published
    assert SECRET not in str(published)
    refused = call({"realm_id": REALM, "folder": str(folder), "yes": True})
    assert refused["error"]["code"] == ERR_CONFLICT
    assert refused["error"]["data"]["reason"] == "publishing_not_connected"
    unconfirmed = call({"realm_id": REALM, "folder": str(folder), "credential": _payload(remote)})
    assert unconfirmed["error"]["data"]["reason"] == "confirmation_required"
