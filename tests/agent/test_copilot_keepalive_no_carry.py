"""Copilot gets upstream's keepalive client — the fork's plain-client carry is gone.

The fork used to return a bare ``httpx.Client(verify=...)`` for
``api.githubcopilot.com`` from ``build_keepalive_http_client``; the "second
request stalls" cause never reproduced on upstream and the owner dropped the
carry 2026-10-02. Copilot now rides the same shared, pool-limited transport as
every other direct host.
"""

import httpx
import pytest

from agent import process_bootstrap
from agent.process_bootstrap import build_keepalive_http_client


@pytest.fixture
def no_proxy_env(monkeypatch):
    for name in (
        "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
        "https_proxy", "http_proxy", "all_proxy", "NO_PROXY", "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    process_bootstrap.close_shared_transports()
    yield
    process_bootstrap.close_shared_transports()


def _inner(client):
    mount = next(t for pat, t in client._mounts.items() if str(pat.pattern) == "https://")
    return mount._inner


def test_copilot_shares_the_keepalive_transport_like_any_direct_host(no_proxy_env):
    copilot = build_keepalive_http_client("https://api.githubcopilot.com")
    other = build_keepalive_http_client("https://api.example.com/v1")
    assert isinstance(copilot, httpx.Client)
    assert copilot.timeout.read is None  # upstream's SSE timeout, not httpx's 5 s default
    assert _inner(copilot) is _inner(other)
    copilot.close()
    other.close()
