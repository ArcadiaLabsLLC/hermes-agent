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

    first = publish_folder(REALM, str(folder), credential=credential, confirmed_paths=["css/a.css", "index.html"])
    assert first["kind"] == "realm_publishing_push" and first["changed"] is True and first["files"] == 2
    assert _git(remote, "ls-tree", "-r", "--name-only", "gh-pages").split() == [".nojekyll", "css/a.css", "index.html"]
    assert subprocess.run(["git", "-C", str(remote), "cat-file", "blob", "gh-pages:index.html"],
                          check=True, capture_output=True).stdout == b"<h1>hi</h1>\r\n"
    assert _git(remote, "log", "-1", "--format=%an|%(trailers:key=Eternia-Member,valueonly)", "gh-pages") \
        == f"Hermes Realm Publishing|{MEMBER}"
    assert asks == [f"https://api.test.invalid/api/realms/{REALM}/sync/permission?action=publish"]
    assert paths.realm_publishing_clone_dir(REALM).is_dir()

    (folder / "css/a.css").unlink()
    second = publish_folder(REALM, str(folder), credential=credential, confirmed_paths=["index.html"])
    assert _git(remote, "ls-tree", "-r", "--name-only", "gh-pages").split() == [".nojekyll", "index.html"]
    assert _git(remote, "rev-parse", "gh-pages^") == first["commit"]
    assert second["commit"] == _git(remote, "rev-parse", "gh-pages")

    third = publish_folder(REALM, str(folder), credential=credential, confirmed_paths=["index.html"])
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

    published = call({"realm_id": REALM, "folder": str(folder), "credential": _payload(remote), "yes": True,
                      "paths": ["index.html"]})
    assert published["result"]["changed"] is True, published
    assert SECRET not in str(published)
    refused = call({"realm_id": REALM, "folder": str(folder), "yes": True})
    assert refused["error"]["code"] == ERR_CONFLICT
    assert refused["error"]["data"]["reason"] == "publishing_not_connected"
    unconfirmed = call({"realm_id": REALM, "folder": str(folder), "credential": _payload(remote)})
    assert unconfirmed["error"]["data"]["reason"] == "confirmation_required"


# ── RT-REALM-PUBLISHING-PUBLISHES-SECRETS-IN-THE-FOLDER: what goes up is one list, and no secret goes up ──


def _pushed(remote: Path) -> list[str]:
    return _git(remote, "ls-tree", "-r", "--name-only", "gh-pages").split()


def test_hidden_files_and_folders_never_go_up(tmp_path, remote, asks):
    """A dotfile (``.env``, ``.htaccess``) and a dot folder (``.ssh/``, ``.well-known/``, documented as left out)
    are skipped at any depth; the dry run's ``paths`` and the push agree. Red if the hidden-file arm or the
    hidden-folder arm of ``site_paths`` is dropped."""
    folder = _site(tmp_path / "out", {
        "index.html": "x", ".htaccess": "deny", "a/.env": "A=1", ".ssh/known_hosts": "h",
        ".well-known/security.txt": "s", "a/b.js": "b",
    })
    credential = RealmSyncCredential.parse(_payload(remote))
    dry = publish_folder(REALM, str(folder), credential=credential, dry_run=True)
    assert dry["paths"] == ["a/b.js", "index.html"] and dry["files"] == 2
    publish_folder(REALM, str(folder), credential=credential, confirmed_paths=dry["paths"])
    assert _pushed(remote) == [".nojekyll", "a/b.js", "index.html"]


def test_an_ignore_file_entry_is_left_out(tmp_path, remote, asks):
    """``.publishignore``: a bare name at any depth, a folder-only pattern, an anchored glob; comments and blank
    lines skipped; the ignore file itself never goes up. Red if ``_ignored`` answers False."""
    folder = _site(tmp_path / "out", {
        ".publishignore": "# build leftovers\n\n*.map\ndrafts/\n/notes/*.txt\n",
        "index.html": "x", "js/app.js": "a", "js/app.js.map": "m", "drafts/x.html": "d",
        "notes/a.txt": "n", "notes/keep.md": "k", "deep/notes/a.txt": "kept: not anchored here",
    })
    credential = RealmSyncCredential.parse(_payload(remote))
    expected = ["deep/notes/a.txt", "index.html", "js/app.js", "notes/keep.md"]
    assert publish_folder(REALM, str(folder), credential=credential, dry_run=True)["paths"] == expected
    publish_folder(REALM, str(folder), credential=credential, confirmed_paths=expected)
    assert _pushed(remote) == [".nojekyll", *expected]


@pytest.mark.parametrize("files, named", [
    ({"id_rsa": "ssh key"}, ["id_rsa"]),
    ({"keys/site.pem": "x", "keys/tls.key": "y"}, ["keys/site.pem", "keys/tls.key"]),
    ({"config.js": "const api_key = 'sk_live_0123456789abcdefXYZ';"}, ["config.js"]),
    ({"notes.txt": "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n"}, ["notes.txt"]),
    ({"secrets/x.json": "{}"}, ["secrets/x.json"]),
])
def test_a_secret_left_in_the_folder_refuses_the_publish_naming_it(tmp_path, remote, asks, files, named):
    """``id_rsa``, ``*.pem`` / ``*.key``, token-shaped text (realm sync's ``file_contains_secret_assignment``), a
    private-key block and a realm-sync secret marker refuse the whole publish with ``sync_secret_excluded``,
    naming the files, for the dry run too, and nothing is pushed — the publishing clone is not even made. Red
    if ``_refuse_secrets`` returns early."""
    folder = _site(tmp_path / "out", {"index.html": "x", **files})
    credential = RealmSyncCredential.parse(_payload(remote))
    for dry_run in (True, False):
        with pytest.raises(RealmSyncError) as refused:
            publish_folder(REALM, str(folder), credential=credential, dry_run=dry_run)
        assert refused.value.code == "sync_secret_excluded"
        assert refused.value.safe_details["paths"] == named
        assert all(name in str(refused.value) for name in named)
    assert _git(remote, "for-each-ref") == ""
    assert not paths.realm_publishing_clone_dir(REALM).exists()


@pytest.mark.parametrize("rel", ["id_rsa.pub", "id_ed25519", "a/server.PEM", "cert.p12", "credentials.json"])
def test_publishing_adds_its_own_secret_names(tmp_path, remote, asks, rel):
    """The publishing name patterns beside realm sync's markers, case-insensitive (``SECRET_NAME_PATTERNS``):
    none of these is a ``SECRET_PATH_MARKERS`` part, so each is refused only by publishing's own list. Red if
    ``_secret_name`` answers False."""
    folder = _site(tmp_path / "out", {"index.html": "x", rel: "bytes"})
    with pytest.raises(RealmSyncError) as refused:
        publish_folder(REALM, str(folder), credential=RealmSyncCredential.parse(_payload(remote)), dry_run=True)
    assert refused.value.safe_details["paths"] == [rel]


def test_the_dry_run_paths_are_exactly_what_is_pushed(tmp_path, remote, asks, monkeypatch):
    """The list is built once: the copy takes the list the dry run answers, never a second walk. Pinned by
    making the walk answer a strict subset of the folder (as a skip added to the walk only would): the push
    must hold exactly that subset. Red if ``_replace_tree`` copies the folder (``shutil.copytree``) instead of
    the list."""
    from agent_runtime.realm_publishing import push as push_module

    folder = _site(tmp_path / "out", {"index.html": "x", "b.html": "y", "c/d.css": "z"})
    real = push_module.site_paths
    monkeypatch.setattr(push_module, "site_paths", lambda source: [p for p in real(source) if p != "b.html"])
    credential = RealmSyncCredential.parse(_payload(remote))
    dry = publish_folder(REALM, str(folder), credential=credential, dry_run=True)
    pushed = publish_folder(REALM, str(folder), credential=credential, confirmed_paths=dry["paths"])
    assert dry["paths"] == pushed["paths"] == ["c/d.css", "index.html"]
    assert _pushed(remote) == [".nojekyll", *dry["paths"]]


def test_the_method_lane_names_the_secret_files(tmp_path, remote, asks):
    """Over ``runtime.realm.publishing.push`` the refusal is a conflict whose ``data.paths`` lists the files,
    and the dry run's result carries ``paths``. Red if the reason is unmapped or ``paths`` leaves the
    envelope."""
    folder = _site(tmp_path / "out", {"index.html": "x"})

    def call(params):
        return serve_rpc.handle_request(
            {"jsonrpc": "2.0", "id": "p", "method": "runtime.realm.publishing.push", "params": params})

    params = {"realm_id": REALM, "folder": str(folder), "credential": _payload(remote), "dry_run": True}
    assert call(params)["result"]["paths"] == ["index.html"]
    (folder / "id_rsa").write_text("k", encoding="utf-8")
    refused = call(params)
    assert refused["error"]["code"] == ERR_CONFLICT
    assert refused["error"]["data"]["reason"] == "sync_secret_excluded"
    assert refused["error"]["data"]["paths"] == ["id_rsa"]


# ── RT-REALM-PUBLISHING-PUSH-SENDS-ONLY-THE-CONFIRMED-LIST: a push sends the list the player confirmed, or nothing ──


def test_a_file_added_after_the_check_is_refused_by_name(tmp_path, remote, asks):
    """The dry run's ``paths`` handed back as ``confirmed_paths``: a file added after the check refuses the push
    with ``publishing_list_changed`` naming it in ``added`` (a removed one in ``removed``), before the clone is
    made; a hidden file added meanwhile is no change (it never goes up); the same list pushes. Killing
    mutation: ``_require_confirmed_list`` returns before the compare -> the added file is pushed."""
    folder = _site(tmp_path / "out", {"index.html": "x", "a.css": "a"})
    credential = RealmSyncCredential.parse(_payload(remote))
    confirmed = publish_folder(REALM, str(folder), credential=credential, dry_run=True)["paths"]
    _site(folder, {"late.html": "added after the check", ".DS_Store": "hidden"})
    (folder / "a.css").unlink()
    with pytest.raises(RealmSyncError) as refused:
        publish_folder(REALM, str(folder), credential=credential, confirmed_paths=confirmed)
    assert refused.value.code == "publishing_list_changed"
    assert refused.value.safe_details == {"added": ["late.html"], "removed": ["a.css"]}
    assert "added late.html" in str(refused.value) and "removed a.css" in str(refused.value)
    assert _git(remote, "for-each-ref") == ""
    assert not paths.realm_publishing_clone_dir(REALM).exists()

    again = publish_folder(REALM, str(folder), credential=credential, dry_run=True)["paths"]
    assert publish_folder(REALM, str(folder), credential=credential, confirmed_paths=again)["changed"] is True
    assert _pushed(remote) == [".nojekyll", "index.html", "late.html"]


def test_a_push_without_the_confirmed_list_pushes_nothing(tmp_path, remote, asks):
    """``yes`` with no ``paths`` (``confirmed_paths=None``) is ``confirmation_required`` and nothing is pushed;
    a dry run needs no list. Killing mutation: drop the ``confirmed is None`` arm -> the bare ``yes`` pushes."""
    folder = _site(tmp_path / "out", {"index.html": "x"})
    credential = RealmSyncCredential.parse(_payload(remote))
    assert publish_folder(REALM, str(folder), credential=credential, dry_run=True)["paths"] == ["index.html"]
    with pytest.raises(RealmSyncError) as refused:
        publish_folder(REALM, str(folder), credential=credential)
    assert refused.value.code == "confirmation_required"
    assert _git(remote, "for-each-ref") == ""


def test_the_method_lane_takes_the_confirmed_paths(tmp_path, remote, asks):
    """Over ``runtime.realm.publishing.push``: ``yes`` without ``paths`` is ``confirmation_required``, a changed
    list is a conflict whose ``data`` carries ``added`` / ``removed``, and a ``paths`` that is not a list of
    strings is ``invalid_request``. Killing mutations: the reason unmapped -> not ERR_CONFLICT; ``paths`` not
    passed through -> the matching call is refused."""
    folder = _site(tmp_path / "out", {"index.html": "x"})

    def call(params):
        return serve_rpc.handle_request(
            {"jsonrpc": "2.0", "id": "p", "method": "runtime.realm.publishing.push", "params": params})

    base = {"realm_id": REALM, "folder": str(folder), "credential": _payload(remote), "yes": True}
    assert call(base)["error"]["data"]["reason"] == "confirmation_required"
    assert call({**base, "paths": "index.html"})["error"]["data"]["reason"] == "invalid_request"
    changed = call({**base, "paths": ["index.html", "gone.html"]})
    assert changed["error"]["code"] == ERR_CONFLICT
    assert changed["error"]["data"]["reason"] == "publishing_list_changed"
    assert (changed["error"]["data"]["added"], changed["error"]["data"]["removed"]) == ([], ["gone.html"])
    assert _git(remote, "for-each-ref") == ""
    assert call({**base, "paths": ["index.html"]})["result"]["changed"] is True


@pytest.mark.parametrize("backend", ["binary", "dulwich"])
def test_a_phone_says_publishing_is_not_on_this_device_before_touching_git(tmp_path, remote, asks, monkeypatch, backend):
    """RT-PHONE-REALM-PUBLISHING-SAYS-NOT-ON-THIS-DEVICE: on the phone's backend (config ``realm_sync.git_backend:
    dulwich``, the git program's stand-in placed as on a phone) the verb answers a typed refusal the Launcher can
    word — on the method lane a conflict with ``data.reason`` — before git, the folder or the backend is touched.
    ``binary`` is the positive control: the same call on the desktop's backend publishes. Red if
    ``_require_this_device`` is dropped (the stand-in's LifecycleNotShipped escapes as an internal error)."""
    from tests.agent_runtime.conftest import _use_realm_sync_backend

    _use_realm_sync_backend(monkeypatch, backend)
    folder = _site(tmp_path / "out", {"index.html": "x"})
    answer = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "p", "method": "runtime.realm.publishing.push", "params": {
        "realm_id": REALM, "folder": str(folder), "credential": _payload(remote), "yes": True, "paths": ["index.html"]}})
    if backend == "binary":
        assert answer["result"]["changed"] is True, answer
        return
    assert answer["error"]["code"] == ERR_CONFLICT, answer
    assert answer["error"]["data"]["reason"] == "publishing_not_on_this_device"
    assert answer["error"]["data"]["retryable"] is False
    with pytest.raises(RealmSyncError) as direct:
        publish_folder(REALM, str(folder), credential=RealmSyncCredential.parse(_payload(remote)), dry_run=True)
    assert direct.value.code == "publishing_not_on_this_device"
    assert asks == [] and _git(remote, "for-each-ref") == ""
