"""The default SSL context and the CA-bundle check are memoized per CA configuration.

Each parses the whole CA bundle (hundreds of ms on Windows). Every agent construction runs the
check, and every async client builds two transports; without the memo each of them parses again.
"""

from __future__ import annotations

import shutil

import certifi
import pytest

import agent.process_bootstrap as pb
import agent.ssl_guard as ssl_guard
from agent.errors import SSLConfigurationError


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    for key in ("HERMES_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(pb, "_SSL_CONTEXT_CACHE", None)
    monkeypatch.setattr(ssl_guard, "_VERIFIED_FINGERPRINT", None)


def _capture_async_transport_verify(monkeypatch) -> list:
    import httpx

    seen: list = []
    real = httpx.AsyncHTTPTransport

    def capturing(*args, **kwargs):
        seen.append(kwargs.get("verify"))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", capturing)
    return seen


def test_shared_ssl_context_is_reused():
    first = pb.shared_ssl_context()
    assert first is not None
    assert pb.shared_ssl_context() is first


def test_shared_ssl_context_rebuilds_when_ca_env_changes(monkeypatch, tmp_path):
    first = pb.shared_ssl_context()
    relocated = tmp_path / "cacert.pem"
    shutil.copyfile(certifi.where(), relocated)
    monkeypatch.setenv("SSL_CERT_FILE", str(relocated))
    second = pb.shared_ssl_context()
    assert second is not None
    assert second is not first


def test_async_client_transports_share_the_context(monkeypatch):
    seen = _capture_async_transport_verify(monkeypatch)
    assert pb.build_keepalive_http_client("https://api.example.com", async_mode=True) is not None
    assert pb.build_keepalive_http_client("https://api.example.com", async_mode=True) is not None
    assert len(seen) == 4
    assert all(v is pb.shared_ssl_context() for v in seen)


def test_explicit_verify_is_passed_through(monkeypatch):
    seen = _capture_async_transport_verify(monkeypatch)
    assert pb.build_keepalive_http_client("https://api.example.com", async_mode=True, verify=False) is not None
    assert seen == [False, False]


def test_verify_ca_bundle_memoizes_success(monkeypatch):
    calls: list = []
    real = ssl_guard._validate_bundle_path
    monkeypatch.setattr(ssl_guard, "_validate_bundle_path", lambda *a, **k: calls.append(a) or real(*a, **k))
    ssl_guard.verify_ca_bundle()
    after_first = len(calls)
    assert after_first >= 1
    ssl_guard.verify_ca_bundle()
    assert len(calls) == after_first


def test_verify_ca_bundle_reverifies_when_env_changes(monkeypatch, tmp_path):
    ssl_guard.verify_ca_bundle()
    monkeypatch.setenv("HERMES_CA_BUNDLE", str(tmp_path / "missing.pem"))
    with pytest.raises(SSLConfigurationError):
        ssl_guard.verify_ca_bundle()


def test_verify_ca_bundle_never_memoizes_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_CA_BUNDLE", str(tmp_path / "missing.pem"))
    for _ in range(2):
        with pytest.raises(SSLConfigurationError):
            ssl_guard.verify_ca_bundle()
