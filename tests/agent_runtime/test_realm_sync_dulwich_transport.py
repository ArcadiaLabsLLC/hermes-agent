"""The realm-sync port over smart HTTP with the credential Eternia brokers per call (plan
phone-realm-sync-dulwich-2026-11-16 S4, §4.2), on both backends.

An in-thread ``dulwich.web`` server refuses any request whose ``Authorization`` is not the brokered one.
Both backends must: send it, keep it out of ``.git/config``, answer a 401 ``sync_auth_failed``, and
answer a push onto a teammate's newer publish ``REJECTED`` with the remote untouched. The dulwich
backend must also: never carry it to another origin after a redirect, and refuse an ssh remote
(it starts no process, so it has no ssh).

Killing mutation (recorded in the S4 commit): drop the fast-forward check in
``git_dulwich.DulwichSyncGit.push``'s ``update_refs`` -> the diverged push replaces the teammate's
commit and ``test_a_push_onto_a_teammates_newer_publish_is_rejected_and_sends_nothing[dulwich]`` reds.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from dulwich.repo import Repo
from dulwich.server import DictBackend
from dulwich.web import WSGIRequestHandlerLogger, WSGIServerLogger, make_server, make_wsgi_chain

from agent_runtime.realm_membership import RealmSyncCredential
from agent_runtime.realm_sync.git import SyncGitBackend, sync_git
from agent_runtime.realm_sync.git_port import PushOutcome
from agent_runtime.realm_sync.models import RealmSyncError

pytestmark = pytest.mark.usefixtures("sync_git_backend")

TOKEN = "Bearer brokered-sekret-0123456789"


def _sh(cwd: Path, *args: str) -> str:
    """The FIXTURE's git (a teammate's machine), never the code under test."""

    proc = subprocess.run(["git", "-c", "user.name=Mate", "-c", "user.email=mate@example.invalid",
                           "-c", "init.defaultBranch=main", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


class _Server:
    """``dulwich.web`` serving ``root/remote.git`` at ``/remote.git``, behind an Authorization check;
    ``seen`` records each request's header."""

    def __init__(self, root: Path, *, token: str | None = TOKEN, redirect_to: str | None = None) -> None:
        self.seen: list[tuple[str, str | None]] = []
        self.repo = Repo(str(root / "remote.git"))
        backend_app = make_wsgi_chain(DictBackend({"/remote.git": self.repo}))

        def app(environ, start_response):
            header = environ.get("HTTP_AUTHORIZATION")
            self.seen.append((environ.get("PATH_INFO", ""), header))
            if redirect_to is not None:
                query = environ.get("QUERY_STRING", "")
                start_response("302 Found", [("Location", redirect_to + environ["PATH_INFO"] + (f"?{query}" if query else ""))])
                return [b""]
            if token is not None and header != token:
                start_response("401 Unauthorized", [("WWW-Authenticate", 'Basic realm="realm"'), ("Content-Length", "0")])
                return [b""]
            return backend_app(environ, start_response)

        self.httpd = make_server("127.0.0.1", 0, app, handler_class=WSGIRequestHandlerLogger,
                                 server_class=WSGIServerLogger)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.repo.close()


@pytest.fixture
def served(tmp_path) -> Iterator[tuple[_Server, Path]]:
    """A bare ``remote.git`` with one commit, served over smart HTTP behind the token."""

    root = tmp_path / "served"
    root.mkdir()
    bare = root / "remote.git"
    _sh(root, "init", "-q", "--bare", str(bare))
    _sh(bare, "config", "http.receivepack", "true")
    seed = tmp_path / "seed"
    _sh(tmp_path, "clone", "-q", str(bare), str(seed))
    (seed / "realms").mkdir()
    (seed / "realms/a.txt").write_text("one\n", encoding="utf-8")
    _sh(seed, "add", "-A")
    _sh(seed, "commit", "-q", "-m", "seed")
    _sh(seed, "push", "-q", "origin", "HEAD:main")
    server = _Server(root)
    yield server, bare
    server.close()


def _credential(url: str, token: str = TOKEN) -> RealmSyncCredential:
    return RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": "local:realm_t", "api_base": "https://api.test.invalid/api",
        "api_token": "etk_test_api_token_000000", "git_url": url, "git_authorization": token,
        "expires_at": "2999-01-01T00:00:00Z",
    })


def _member_commits(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, encoding="utf-8")
    git = sync_git(repo)
    git.add([rel])
    git.commit("member")


def _teammate_publishes(tmp_path: Path, bare: Path, rel: str, text: str) -> str:
    mate = tmp_path / "mate"
    if not mate.exists():
        _sh(tmp_path, "clone", "-q", str(bare), str(mate))
    (mate / rel).parent.mkdir(parents=True, exist_ok=True)
    (mate / rel).write_text(text, encoding="utf-8")
    _sh(mate, "add", "-A")
    _sh(mate, "commit", "-q", "-m", "mate")
    _sh(mate, "push", "-q", "origin", "HEAD:main")
    return _sh(mate, "rev-parse", "HEAD")


def _tip(bare: Path) -> str:
    return _sh(bare, "rev-parse", "main")


def test_clone_fetch_pull_and_push_carry_the_header_and_never_store_it(tmp_path, served):
    server, bare = served
    url = f"{server.url}/remote.git"
    credential = _credential(url)
    repo = tmp_path / "member"
    git = sync_git(repo)
    git.clone(url, credential)
    assert (repo / "realms/a.txt").read_text(encoding="utf-8") == "one\n"
    assert git.upstream() == "origin/main"

    theirs = _teammate_publishes(tmp_path, bare, "realms/b.txt", "b\n")
    git.fetch(credential)
    assert git.state().behind == 1
    git.pull_fast_forward(credential)
    assert git.resolve("HEAD") == theirs

    _member_commits(repo, "realms/c.txt", "c\n")
    assert git.push(credential, set_upstream=False).outcome is PushOutcome.PUSHED
    assert _tip(bare) == git.resolve("HEAD")
    assert git.state().ahead == 0

    assert server.seen and all(header == TOKEN for _path, header in server.seen)
    config = (repo / ".git" / "config").read_text(encoding="utf-8")
    assert "brokered-sekret" not in config and "extraheader" not in config.lower()


def test_a_push_onto_a_teammates_newer_publish_is_rejected_and_sends_nothing(tmp_path, served):
    server, bare = served
    url = f"{server.url}/remote.git"
    credential = _credential(url)
    repo = tmp_path / "member"
    git = sync_git(repo)
    git.clone(url, credential)
    theirs = _teammate_publishes(tmp_path, bare, "realms/b.txt", "b\n")
    _member_commits(repo, "realms/mine.txt", "mine\n")

    report = git.push(credential, set_upstream=False)

    assert report.outcome is PushOutcome.REJECTED
    assert _tip(bare) == theirs  # the teammate's publish stands
    assert "brokered-sekret" not in repr(report.safe_details)


def test_a_refused_credential_reads_as_the_hosts_401_and_is_never_echoed(tmp_path, served, sync_git_backend):
    """Both read as the host's 401 (``host_refusal``, which reports it to the backend). The git program,
    prompts off, says only "terminal prompts disabled" (``sync_remote_unreachable``, as before the port);
    the phone's git knows it was a 401 and says ``sync_auth_failed``."""

    from agent_runtime.realm_sync.host_refusal import host_refusal_status

    server, _bare = served
    url = f"{server.url}/remote.git"
    with pytest.raises(RealmSyncError) as refused:
        sync_git(tmp_path / "member").clone(url, _credential(url, token="Bearer wrong-sekret-999"))
    assert host_refusal_status(refused.value) == 401
    if sync_git_backend is SyncGitBackend.DULWICH:
        assert refused.value.code == "sync_auth_failed"
    assert "wrong-sekret" not in repr(refused.value.safe_details)
    assert not (tmp_path / "member").exists()  # a failed clone leaves nothing behind


def test_a_redirect_to_another_origin_never_carries_the_header(tmp_path, served, sync_git_backend):
    if sync_git_backend is not SyncGitBackend.DULWICH:
        pytest.skip("the git program's extraHeader rides every request; the origin check is the phone backend's")
    _server, _bare = served
    elsewhere = _Server(tmp_path / "served", token="Bearer nobody-has-this")
    redirector = _Server(tmp_path / "served", redirect_to=elsewhere.url)
    try:
        url = f"{redirector.url}/remote.git"
        with pytest.raises(RealmSyncError):
            sync_git(tmp_path / "member").clone(url, _credential(url))
        assert redirector.seen and redirector.seen[0][1] == TOKEN  # positive control: the origin got it
        assert elsewhere.seen, "the redirect was never followed: this test proves nothing"
        assert all(header is None for _path, header in elsewhere.seen)
    finally:
        redirector.close()
        elsewhere.close()


def test_an_ssh_remote_is_refused_on_the_phone(tmp_path, sync_git_backend):
    if sync_git_backend is not SyncGitBackend.DULWICH:
        pytest.skip("the git program reaches ssh; the phone backend starts no process")
    for url in ("ssh://git@example.invalid/r.git", "git@example.invalid:r.git"):
        with pytest.raises(RealmSyncError) as refused:
            sync_git(tmp_path / f"m{len(url)}").clone(url, None)
        assert refused.value.code == "sync_remote_unreachable"
        assert refused.value.safe_details["reason"] == "transport_not_on_this_device"
