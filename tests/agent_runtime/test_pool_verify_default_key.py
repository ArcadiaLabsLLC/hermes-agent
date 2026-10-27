"""FH-POOL-VERIFY-KEY-ONE-AUTHORITY: the default ``verify`` joins the pool of the shared context.

Since the shared-truststore carry (``212458ec8d``) every resolved default ``verify`` is ONE
``SSLContext``; a keep-alive client built with the plain default ``verify=True`` must mount the
SAME process-shared transport, so a caller that forgets ``turn_pool_verify`` (upstream
``agent/video_gen_provider.py``) still reuses the turn's connections.
"""

from __future__ import annotations

import ssl

import pytest

from agent import process_bootstrap
from agent.ssl_verify import resolve_httpx_verify

URL = "https://pool-key.invalid/v1"


@pytest.fixture(autouse=True)
def _no_proxy_and_fresh_pool(monkeypatch):
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    process_bootstrap.close_shared_transports()
    yield
    process_bootstrap.close_shared_transports()


def _inner(client):
    return client._transport._inner


def test_the_default_verify_mounts_the_shared_contexts_transport():
    resolved = resolve_httpx_verify()
    if not isinstance(resolved, ssl.SSLContext):
        pytest.skip("truststore is not in force here: the default resolves to True and keys as True")
    default = process_bootstrap.build_keepalive_http_client(URL)
    shared = process_bootstrap.build_keepalive_http_client(URL, verify=resolved)
    assert default is not shared
    assert _inner(default) is _inner(shared)


def test_a_different_context_still_keys_its_own_pool():
    """Positive control: identity keying is intact, so the test above can tell pools apart."""
    other = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    default = process_bootstrap.build_keepalive_http_client(URL)
    own = process_bootstrap.build_keepalive_http_client(URL, verify=other)
    assert _inner(default) is not _inner(own)
