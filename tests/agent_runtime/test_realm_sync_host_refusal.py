"""A push, fetch or clone the git host refuses for its authorization is reported to the backend
(RT-REALM-SYNC-REPORTS-A-REJECTED-PUSH; backend ``603184bc``).

Real ``git`` against a local HTTP server that refuses every request (401 or 403, as github.com does
for a token whose installation lost the repository); the backend is the ``_request_json`` seam, which
records each call and answers the report the way the backend does: 204 alive (re-broker) or
409 ``realms.git_host_binding_lost`` (the binding is gone: reconnect).
"""
from __future__ import annotations

import subprocess
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import agent_runtime.realm_membership as membership
from agent_runtime.realm_membership import RealmSyncCredential
from agent_runtime.realm_sync import RealmSyncError, publish_realm_sync, pull_realm_sync, realm_sync_status
from agent_runtime.realm_sync.git import _sync_repo_path
from agent_runtime.realm_sync.revocation import read_realm_revocation
from agent_runtime.realm_sync.sidecar import read_realm_sync_sidecar
from agent_runtime.store import RealmStore, WorkspaceStore

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

API = "https://api.test/api"


class _Refusing(BaseHTTPRequestHandler):
    status = 403

    def _refuse(self) -> None:
        self.send_response(self.status)
        if self.status == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="GitHub"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = _refuse

    def log_message(self, *_args) -> None:  # keep the test output quiet
        return None


@pytest.fixture(params=[403, 401], ids=["host-403", "host-401"])
def refusing_host(request):
    handler = type("Refusing", (_Refusing,), {"status": request.param})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/team/realm.git"
    server.shutdown()
    server.server_close()


class _Backend:
    """The ``_request_json`` seam: permission allowed, publish notify taken, the report answered."""

    def __init__(self, report: tuple[int, object]):
        self.report = report
        self.reports: list[str] = []

    def __call__(self, method, url, *, headers=None, body=None, timeout=None):
        if url.endswith("/sync/auth-rejected"):
            assert method == "POST" and headers["Authorization"] == "Bearer api-token"
            self.reports.append(url)
            return self.report
        if "/sync/permission" in url:
            return 200, {"allowed": True}
        if url.endswith("/sync/published"):
            return 204, None
        raise AssertionError(f"unexpected backend call {method} {url}")


BINDING_LOST = (409, {"code": "realms.git_host_binding_lost", "message": "gone"})
ALIVE = (204, None)


def _credential(subject: str, git_url: str) -> RealmSyncCredential:
    return RealmSyncCredential.parse({
        "schema_version": 1, "realm_id": subject, "api_base": API, "api_token": "api-token",
        "git_url": git_url, "git_authorization": "Basic dG9rZW4=",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    })


def _server_realm(url: str):
    realm = RealmStore().create(name="Team", server_id="srv_team")
    realm.sync_manifest_ref = url
    realm = RealmStore().save(realm)
    WorkspaceStore().create(name="Team desk", realm_id=realm.id)
    return realm


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_a_dead_binding_marks_the_realm_for_reconnect_not_retry(isolate_agent_runtime_root, monkeypatch, refusing_host):
    """The clone is refused; the report answers 409 binding lost: one report, the host-state mark
    (what the snapshot's ``sync.revoked`` carries), ``realm_revoked`` not retryable.

    KILLING MUTATION: drop the ``with host_refusal_reported(...)`` in ``pull_realm_sync`` -> the pull
    answers ``sync_remote_unreachable`` / ``sync_auth_failed`` and no report is made, red."""
    backend = _Backend(BINDING_LOST)
    monkeypatch.setattr(membership, "_request_json", backend)
    realm = _server_realm(refusing_host)

    with pytest.raises(RealmSyncError) as refused:
        pull_realm_sync(realm.id, credential=_credential(realm.id, refusing_host))

    assert refused.value.code == "realm_revoked"
    assert refused.value.retryable is False
    assert refused.value.safe_details["revoked_reason"] == "git_host_binding_lost"
    assert backend.reports == [f"{API}/realms/{realm.id}/sync/auth-rejected"]
    assert read_realm_revocation(realm.id) == {
        "reason": "git_host_binding_lost", "revoked_at": read_realm_revocation(realm.id)["revoked_at"], "host_state": True,
    }
    assert read_realm_sync_sidecar(realm.id)["revoked"]["reason"] == "git_host_binding_lost"


def test_a_live_binding_answers_rebroker_and_leaves_no_mark(isolate_agent_runtime_root, monkeypatch, refusing_host):
    """204: the backend dropped its cached token; the verb says the next sync gets a fresh one."""
    backend = _Backend(ALIVE)
    monkeypatch.setattr(membership, "_request_json", backend)
    realm = _server_realm(refusing_host)

    with pytest.raises(RealmSyncError) as refused:
        pull_realm_sync(realm.id, credential=_credential(realm.id, refusing_host))

    assert refused.value.code == "sync_auth_failed"
    assert refused.value.retryable is True
    assert refused.value.safe_details["auth_rejected"] == "rebroker"
    assert len(backend.reports) == 1
    assert read_realm_revocation(realm.id) is None


def _clone_on(realm, url: str) -> Path:
    """The realm's clone, made while the host still answered: one commit, ``origin`` the host."""
    clone = _sync_repo_path(realm)
    clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True, capture_output=True)
    _git(clone, "-c", "user.email=t@localhost", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "seed")
    _git(clone, "remote", "add", "origin", url)
    return clone


def test_a_refused_push_reports_once(isolate_agent_runtime_root, monkeypatch, refusing_host):
    """The repository was disconnected: the publish's fetch AND its push are refused, and it reports once.

    KILLING MUTATION: drop the ``with host_refusal_reported(...)`` in ``publish_realm_sync`` -> the
    publish answers ``sync_remote_unreachable`` with no report, red."""
    backend = _Backend(BINDING_LOST)
    monkeypatch.setattr(membership, "_request_json", backend)
    realm = _server_realm(refusing_host)
    _clone_on(realm, refusing_host)

    with pytest.raises(RealmSyncError) as refused:
        publish_realm_sync(realm.id, credential=_credential(realm.id, refusing_host))

    assert refused.value.code == "realm_revoked"
    assert backend.reports == [f"{API}/realms/{realm.id}/sync/auth-rejected"]


def test_a_refused_status_fetch_reports_and_names_the_mark(isolate_agent_runtime_root, monkeypatch, refusing_host):
    """The status read degrades (it never raises over the remote half) and its error is the mark's code."""
    backend = _Backend(BINDING_LOST)
    monkeypatch.setattr(membership, "_request_json", backend)
    realm = _server_realm(refusing_host)
    _clone_on(realm, refusing_host)

    status = realm_sync_status(realm.id, credential=_credential(realm.id, refusing_host))

    assert status["remote_checked"] is False
    assert status["remote_check_error"] == "realm_revoked"
    assert len(backend.reports) == 1
    assert read_realm_revocation(realm.id)["reason"] == "git_host_binding_lost"


def test_a_local_realm_reports_on_its_own_ref(isolate_agent_runtime_root, monkeypatch, refusing_host):
    """A local realm's credential is minted for ``local:<id>``: the report goes to ``/me/realms/local:<id>``."""
    backend = _Backend(ALIVE)
    monkeypatch.setattr(membership, "_request_json", backend)
    realm = RealmStore().create(name="Mine")
    realm.sync_manifest_ref = refusing_host
    realm = RealmStore().save(realm)

    with pytest.raises(RealmSyncError):
        pull_realm_sync(realm.id, credential=_credential(f"local:{realm.id}", refusing_host))

    assert backend.reports == [f"{API}/me/realms/local:{realm.id}/sync/auth-rejected"]


def test_no_brokered_credential_means_nothing_to_report(isolate_agent_runtime_root, monkeypatch, refusing_host):
    """A local backup remote set by hand carries no credential: no backend to tell, the refusal stands."""
    backend = _Backend(BINDING_LOST)
    monkeypatch.setattr(membership, "_request_json", backend)
    realm = RealmStore().create(name="Mine")
    realm.sync_manifest_ref = refusing_host
    realm = RealmStore().save(realm)

    with pytest.raises(RealmSyncError) as refused:
        pull_realm_sync(realm.id)

    assert refused.value.code != "realm_revoked"
    assert backend.reports == []
    assert read_realm_revocation(realm.id) is None


def test_a_realm_sync_git_call_never_waits_on_a_username_prompt(monkeypatch):
    """A 401 makes git ask for a username; a realm sync has no one to answer (a serve with a
    terminal would hang there instead of reporting).

    KILLING MUTATION: drop ``GIT_TERMINAL_PROMPT=0`` in ``run_sync_git`` -> red."""
    from agent_runtime.realm_sync import git as realm_git

    seen: dict[str, str] = {}
    monkeypatch.setattr(realm_git, "run_git", lambda args, **kw: seen.update(kw["env"]))
    realm_git.run_sync_git(("fetch",), env={"PATH": "/usr/bin"})
    assert seen["GIT_TERMINAL_PROMPT"] == "0"
