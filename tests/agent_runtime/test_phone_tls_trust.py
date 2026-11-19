"""The phone's TLS trust: certifi's bundle as ``SSL_CERT_FILE`` on Android and iOS (row RT-PHONE-TLS-TRUST-UNPROVEN).

truststore sends Android and iOS to its OpenSSL arm, whose default paths and Linux bundle files a
phone does not have. The end-to-end test stands a phone up on this host: OpenSSL's default paths
(the reported ones and the ones ``set_default_verify_paths`` loads) answer only ``SSL_CERT_FILE``,
truststore's Linux file sweep is empty, and certifi is a private CA's bundle. There, BEFORE the
fix, the stdlib's default context refuses a server that CA signed (positive control: nothing selects
certifi); AFTER :func:`ensure_phone_tls_trust`, urllib and the
httpx clients ``resolve_httpx_verify`` configures both reach it, and both still refuse a server
signed by a CA nothing trusts. So does the realm sync client the phone engine clones and fetches with
(``git_dulwich._BrokeredHttpClient``, dulwich over urllib3, the client the Android emulator's verified
github.com clone used): through ``DulwichSyncGit``'s ``_wire`` it completes the handshake with the trusted
server (the server speaks no git, so the step fails on git's answer, never on the certificate) and is
refused the untrusted one with a certificate verification error (review w1118a.36 D5).

Killing mutations (applied, red recorded, reverted — see the commit message).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from agent_runtime import phone_tls_trust
from agent_runtime.phone_tls_trust import ensure_phone_tls_trust
from tests.agent.test_ssl_verify import _child_env, _private_https_server


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_a_phone_exports_the_certifi_bundle(tmp_path, platform):
    bundle = tmp_path / "cacert.pem"
    bundle.write_text("pem")
    env: dict[str, str] = {}
    assert ensure_phone_tls_trust(platform=platform, environ=env, bundle=lambda: str(bundle)) == str(bundle)
    assert env == {"SSL_CERT_FILE": str(bundle)}


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_off_a_phone_nothing_is_exported(tmp_path, platform):
    bundle = tmp_path / "cacert.pem"
    bundle.write_text("pem")
    env: dict[str, str] = {}
    assert ensure_phone_tls_trust(platform=platform, environ=env, bundle=lambda: str(bundle)) is None
    assert env == {}


@pytest.mark.parametrize("name", ["SSL_CERT_FILE", "SSL_CERT_DIR"])
def test_a_host_s_own_anchors_are_kept(tmp_path, name):
    bundle = tmp_path / "cacert.pem"
    bundle.write_text("pem")
    env = {name: "/host/anchors"}
    assert ensure_phone_tls_trust(platform="android", environ=env, bundle=lambda: str(bundle)) is None
    assert env == {name: "/host/anchors"}


def test_a_missing_bundle_exports_nothing_and_says_so(tmp_path, caplog):
    env: dict[str, str] = {}
    with caplog.at_level("WARNING", logger=phone_tls_trust.__name__):
        assert ensure_phone_tls_trust(platform="ios", environ=env,
                                      bundle=lambda: str(tmp_path / "gone.pem")) is None
    assert env == {}
    assert "every HTTPS call will be refused" in caplog.text


_PHONE = """
import os, ssl, sys, urllib.error, urllib.request

import certifi, certifi.core, httpx
import truststore._openssl as openssl_arm

url, ca, untrusted, workdir = sys.argv[1:]

# A phone, on this host: OpenSSL's compiled-in paths name nothing (only SSL_CERT_FILE answers),
# none of truststore's Linux bundle files exists, and certifi is the private CA's bundle.
openssl_arm._CA_FILE_CANDIDATES[:] = []
def phone_default_paths():
    cafile = os.environ.get("SSL_CERT_FILE")
    return ssl.DefaultVerifyPaths(cafile if cafile and os.path.isfile(cafile) else None, None,
                                  "SSL_CERT_FILE", "", "SSL_CERT_DIR", "")
ssl.get_default_verify_paths = phone_default_paths
from truststore._ssl_constants import _original_SSLContext
def phone_openssl_defaults(self):
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile and os.path.isfile(cafile):
        self.load_verify_locations(cafile=cafile)
_original_SSLContext.set_default_verify_paths = phone_openssl_defaults
certifi.where = certifi.core.where = lambda: ca

from agent.ssl_verify import install_truststore, resolve_httpx_verify
assert install_truststore()

def stdlib_refused(target):
    try:
        urllib.request.urlopen(target, timeout=5).read()
    except urllib.error.URLError as exc:
        assert isinstance(exc.reason, ssl.SSLCertVerificationError), exc
        return True
    return False

def httpx_refused(target):
    try:
        httpx.get(target, verify=resolve_httpx_verify(), timeout=5)
    except httpx.ConnectError:
        return True
    return False

assert stdlib_refused(url), "positive control: the phone's own store trusted the private CA"

from agent_runtime.phone_tls_trust import ensure_phone_tls_trust
assert ensure_phone_tls_trust(platform="android") == ca

assert not stdlib_refused(url), "urllib on a phone refused a server certifi trusts"
assert httpx.get(url, verify=resolve_httpx_verify(), timeout=5).content == b"private provider"
assert stdlib_refused(untrusted), "urllib trusted a CA nothing names"
assert httpx_refused(untrusted), "httpx trusted a CA nothing names"

from pathlib import Path
from agent_runtime.realm_sync.git_dulwich import DulwichSyncGit
from agent_runtime.realm_sync.models import RealmSyncError

def realm_clone_failure(target, name):
    try:
        DulwichSyncGit(Path(workdir) / name).clone(target + "realm.git", None)
    except RealmSyncError as exc:
        return exc.safe_details["stderr"]
    raise AssertionError(f"a realm clone from {target} succeeded against a server that speaks no git")

trusted_failure = realm_clone_failure(url, "trusted")
assert "CERTIFICATE_VERIFY_FAILED" not in trusted_failure, trusted_failure
assert "Invalid info/refs" in trusted_failure, "the realm client did not reach the trusted server: " + trusted_failure
untrusted_failure = realm_clone_failure(untrusted, "untrusted")
assert "CERTIFICATE_VERIFY_FAILED" in untrusted_failure, "the realm client trusted a CA nothing names: " + untrusted_failure
"""


def test_a_phone_with_no_os_bundle_verifies_through_certifi_and_refuses_the_rest(tmp_path):
    trusted_dir, untrusted_dir = tmp_path / "trusted", tmp_path / "untrusted"
    trusted_dir.mkdir()
    untrusted_dir.mkdir()
    with _private_https_server(trusted_dir) as (server, ca), \
            _private_https_server(untrusted_dir) as (other, _other_ca):
        child = subprocess.run(
            [sys.executable, "-c", _PHONE, f"https://127.0.0.1:{server.server_port}/", str(ca),
             f"https://127.0.0.1:{other.server_port}/", str(tmp_path)],
            env=_child_env(tmp_path), capture_output=True, text=True, timeout=60, check=False,
        )
    assert child.returncode == 0, child.stdout + child.stderr
