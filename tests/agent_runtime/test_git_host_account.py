"""The GitHub door (p10-work plan §2.4, stage A1): a fake ``urlopen`` records every request and the
credential chain is monkeypatched — nothing reaches a network or a real GitHub account."""

from __future__ import annotations

import base64
import io
import json
import logging
import urllib.error

import pytest

from agent_runtime import git_host_account as gh
from agent_runtime.work_store.reasons import Reason

TOKEN_A = "ghp_STALE_token_aaaa"
TOKEN_B = "ghp_LIVE_token_bbbb"


class _Reply(io.BytesIO):
    def __init__(self, status: int, body: dict) -> None:
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeGitHub:
    """Answers by the Authorization header's password: a table of ``token -> (status, body)``."""

    def __init__(self, user: dict[str, tuple[int, dict]], create: tuple[int, dict] | None = None,
                 fail: Exception | None = None) -> None:
        self.user, self.create, self.fail, self.calls = user, create, fail, []

    def __call__(self, request, timeout):
        token = base64.b64decode(request.get_header("Authorization").split()[1]).decode().split(":", 1)[1]
        body = json.loads(request.data) if request.data else None
        self.calls.append((request.get_method(), request.full_url, token, body))
        if self.fail is not None:
            raise self.fail
        status, reply = self.create if request.get_method() == "POST" else self.user.get(token, (401, {}))
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO(json.dumps(reply).encode()))
        return _Reply(status, reply)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    gh.reset_connected_cache()
    yield
    gh.reset_connected_cache()


def _chain(monkeypatch, *tokens: str) -> None:
    import hermes_cli.git_credentials as creds

    pairs = [(f"source-{i}", ("x-access-token", token)) for i, token in enumerate(tokens)]
    monkeypatch.setattr(creds, "iter_git_basic_auth", lambda url: iter(pairs) if url == "https://github.com" else iter(()))


def test_the_first_accepted_credential_names_the_login(monkeypatch):
    _chain(monkeypatch, TOKEN_B)
    fake = FakeGitHub({TOKEN_B: (200, {"login": "octo"})})
    monkeypatch.setattr(gh, "urlopen", fake)
    account = gh.connected_github()
    assert account is not None and account.login == "octo" and account.source == "source-0"
    assert fake.calls == [("GET", "https://api.github.com/user", TOKEN_B, None)]
    assert gh.connected_github() is account and len(fake.calls) == 1  # memoised
    assert TOKEN_B not in repr(account)


def test_a_rejected_token_yields_to_the_next_source(monkeypatch):
    _chain(monkeypatch, TOKEN_A, TOKEN_B)
    monkeypatch.setattr(gh, "urlopen", FakeGitHub({TOKEN_A: (401, {"message": "Bad credentials"}),
                                                   TOKEN_B: (200, {"login": "octo"})}))
    account = gh.connected_github()
    assert account is not None and account.source == "source-1"


def test_no_credential_is_not_connected(monkeypatch):
    _chain(monkeypatch)
    fake = FakeGitHub({})
    monkeypatch.setattr(gh, "urlopen", fake)
    assert gh.connected_github() is None and fake.calls == []


def test_network_failure_is_not_connected_and_not_an_error(monkeypatch):
    _chain(monkeypatch, TOKEN_B)
    monkeypatch.setattr(gh, "urlopen", FakeGitHub({}, fail=urllib.error.URLError("offline")))
    assert gh.connected_github() is None
    monkeypatch.setattr(gh, "urlopen", FakeGitHub({TOKEN_B: (200, {"login": "octo"})}))
    assert gh.connected_github().login == "octo"  # a network failure is not memoised


def _account() -> gh.GitHubAccount:
    return gh.GitHubAccount("octo", "source-0", ("x-access-token", TOKEN_B))


def test_create_private_repo_posts_private_no_init(monkeypatch):
    fake = FakeGitHub({}, create=(201, {"clone_url": "https://github.com/octo/eternia-work-w.git"}))
    monkeypatch.setattr(gh, "urlopen", fake)
    assert gh.create_private_repo(_account(), "eternia-work-w") == "https://github.com/octo/eternia-work-w.git"
    method, url, _token, body = fake.calls[0]
    assert (method, url) == ("POST", "https://api.github.com/user/repos")
    assert body == {"name": "eternia-work-w", "private": True, "auto_init": False, "description": "Eternia Work brain"}


def test_name_exists_refuses_remote_exists(monkeypatch):
    reply = {"message": "Repository creation failed.", "errors": [{"message": "name already exists on this account"}]}
    monkeypatch.setattr(gh, "urlopen", FakeGitHub({}, create=(422, reply)))
    with pytest.raises(gh.GitHostRefused) as refused:
        gh.create_private_repo(_account(), "eternia-work-w")
    assert refused.value.reason is Reason.REMOTE_EXISTS and refused.value.detail.endswith("octo/eternia-work-w.git")


@pytest.mark.parametrize(("status", "reason"), [(403, Reason.TOKEN_SCOPE), (500, Reason.HOST_UNREACHABLE)])
def test_other_create_failures_are_typed(monkeypatch, status, reason):
    monkeypatch.setattr(gh, "urlopen", FakeGitHub({}, create=(status, {"message": "no"})))
    with pytest.raises(gh.GitHostRefused) as refused:
        gh.create_private_repo(_account(), "eternia-work-w")
    assert refused.value.reason is reason


def test_the_token_is_absent_from_the_refusal_and_the_log(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _chain(monkeypatch, TOKEN_A, TOKEN_B)
    monkeypatch.setattr(gh, "urlopen", FakeGitHub({TOKEN_A: (401, {}), TOKEN_B: (200, {"login": "octo"})},
                                                  create=(403, {"message": "Resource not accessible"})))
    account = gh.connected_github()
    with pytest.raises(gh.GitHostRefused) as refused:
        gh.create_private_repo(account, "eternia-work-w")
    for text in (caplog.text, str(refused.value), refused.value.detail, repr(account)):
        assert TOKEN_A not in text and TOKEN_B not in text
