"""Bundled desktop sign-ins in the OS secure store (owner ruling 2026-09-28 item 4).

``auth.os_secure_store`` (on in ``bundled-desktop.yaml``) binds the phones' host-store seam
to DPAPI at every entry. After sign-in writes, a byte scan of the bundled data root finds
no secret; another DPAPI scope (standing in for another Windows user) cannot read a slot;
an older install's plaintext moves in at first start, and a move interrupted at any point
loses nothing. Every negative scan carries its POSITIVE CONTROL: the same writes unbound
leak every needle, so the scan is proven to look where the bytes would be.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime.bundle_profiles.manifest import apply_to_config, load_profile
from agent_runtime.host_store import binding, desktop, desktop_binding, secret_files

REPO_ROOT = Path(__file__).resolve().parents[2]
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")

ACCESS = "hdpapi-access-token-41c7"
REFRESH = "hdpapi-refresh-token-8e02"
API_KEY = "sk-or-hdpapi-api-key-5b93"
PKCE = "hdpapi-anthropic-pkce-7d1e"
MCP = "hdpapi-mcp-oauth-token-2f60"
HMAC = "hdpapi-webhook-hmac-9a3b"
NEEDLES = (ACCESS, REFRESH, API_KEY, PKCE, MCP, HMAC)


class _Crash(BaseException):
    """A process dying mid-migration (not an Exception: nothing may swallow it)."""


@pytest.fixture(autouse=True)
def _unbound_after():
    binding.unbind_host_store()
    yield
    binding.unbind_host_store()


@pytest.fixture()
def app(tmp_path, monkeypatch):
    root = tmp_path / "bundled"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("HERMES_SHARED_AUTH_DIR", str(root / "shared"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return root


def _install_profile(root: Path) -> None:
    (root / "config.yaml").write_text(json.dumps(apply_to_config(load_profile("bundled-desktop"), {})),
                                      encoding="utf-8")


def _sign_in(home: Path) -> None:
    """Sign-in writes through the real writers: a provider login, the shared Nous store, an API
    key, the Anthropic PKCE file, an MCP token and a webhook secret."""
    from agent.anthropic_credentials import _write_hermes_oauth_credentials
    from hermes_cli import auth, auth_nous, config, webhook
    from tools import mcp_oauth

    store = auth._load_auth_store()
    store.setdefault("providers", {})["nous"] = {"access_token": ACCESS, "refresh_token": REFRESH}
    auth._save_auth_store(store)
    auth_nous._write_shared_nous_state({"access_token": ACCESS, "refresh_token": REFRESH})
    config.save_env_value("OPENROUTER_API_KEY", API_KEY)
    _write_hermes_oauth_credentials(PKCE, PKCE + "-r", 1)
    mcp_oauth._write_json(mcp_oauth._get_token_dir() / "srv.json", {"access_token": MCP})
    webhook._save_subscriptions({"route": {"secret": HMAC}})
    os.environ.pop("OPENROUTER_API_KEY", None)


def _leaks(root: Path) -> set[str]:
    found: set[str] = set()
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            found.update(n for n in NEEDLES if n.encode("utf-8") in data or n.encode("utf-16-le") in data)
    return found


def _reads_back_through_the_seams() -> None:
    from agent.anthropic_credentials import read_hermes_oauth_credentials
    from hermes_cli import auth, config, webhook

    assert auth._load_auth_store()["providers"]["nous"]["refresh_token"] == REFRESH
    assert config.load_env()["OPENROUTER_API_KEY"] == API_KEY
    assert read_hermes_oauth_credentials()["accessToken"] == PKCE
    assert webhook._load_subscriptions()["route"]["secret"] == HMAC


@windows_only
def test_sign_ins_under_dpapi_leave_no_secret_in_the_data_root(app):
    _install_profile(app)
    bound = desktop_binding.bind_desktop_host_store()
    assert bound is not None and bound.callbacks.protect_history_dir is None  # credentials only
    _sign_in(app)

    assert _leaks(app) == set()
    assert list((app / desktop_binding.BLOB_DIR_NAME).glob(f"*{desktop.BLOB_SUFFIX}"))
    _reads_back_through_the_seams()


def test_positive_control_the_same_sign_ins_unbound_leak_every_needle(app):
    assert desktop_binding.bind_desktop_host_store() is None  # no config: the switch is off
    _sign_in(app)
    assert _leaks(app) == set(NEEDLES)


@windows_only
def test_another_user_cannot_read_the_slots(tmp_path):
    blobs = tmp_path / "secure-store"
    slot = "hermes/v1/default/auth.json"
    desktop.DpapiHostSecureStore(blobs).write(slot, ACCESS.encode())

    assert ACCESS.encode() not in desktop.DpapiHostSecureStore(blobs).blob_path(slot).read_bytes()
    assert desktop.DpapiHostSecureStore(blobs).read(slot) == ACCESS.encode()  # positive control: same user
    with pytest.raises(desktop.SecretUnreadable):
        desktop.DpapiHostSecureStore(blobs, scope=b"another-windows-user").read(slot)


class _CrashingStore(desktop.DpapiHostSecureStore):
    """Dies on the Nth verify read: after that slot's write, before its plaintext is unlinked."""

    def __init__(self, blob_dir, *, crash_on_read: int):
        super().__init__(blob_dir)
        self._reads_left = crash_on_read

    def read(self, slot):
        self._reads_left -= 1
        if self._reads_left == 0:
            raise _Crash()
        return super().read(slot)


def _recoverable(root: Path) -> set[str]:
    """Needles still held somewhere a later start can reach: a plaintext file, or its slot."""
    probe = desktop.DpapiHostSecureStore(root / desktop_binding.BLOB_DIR_NAME)
    found = _leaks(root)
    for path in desktop_binding.plaintext_secret_paths(root, root, root / "shared"):
        rel = path.relative_to(root).as_posix().lower()
        value = probe.read(f"{binding.SLOT_PREFIX}/default/{rel}")
        if value is not None:
            found.update(n for n in NEEDLES if n.encode() in value)
    return found


@windows_only
def test_an_interrupted_migration_loses_nothing_and_the_next_start_finishes_it(app, monkeypatch):
    _sign_in(app)  # an older bundled install: every sign-in in plaintext
    assert _leaks(app) == set(NEEDLES)
    _install_profile(app)

    # Crash 1: inside the store's own write, after the protected temp file, before the rename.
    real_replace = os.replace

    def crash_on_blob_rename(src, dst):
        if str(dst).endswith(desktop.BLOB_SUFFIX):
            raise _Crash()
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", crash_on_blob_rename)
    with pytest.raises(_Crash):
        desktop_binding.bind_desktop_host_store()
    monkeypatch.setattr(os, "replace", real_replace)
    assert not binding.bound()
    assert _recoverable(app) == set(NEEDLES)

    # Crash 2: the third file's slot is written, its plaintext not yet removed.
    with pytest.raises(_Crash):
        desktop_binding.bind_desktop_host_store(store_factory=lambda d: _CrashingStore(d, crash_on_read=3))
    assert not binding.bound()
    assert _recoverable(app) == set(NEEDLES)
    assert _leaks(app) and _leaks(app) != set(NEEDLES)  # part-moved: the crash landed mid-way

    # The next start finishes the move.
    desktop_binding.bind_desktop_host_store()
    assert _leaks(app) == set()
    assert not list((app / desktop_binding.BLOB_DIR_NAME).glob("*.dpapi-tmp"))
    assert os.environ.get("OPENROUTER_API_KEY") == API_KEY  # the store-held .env was published again
    _reads_back_through_the_seams()


def test_the_migration_list_covers_every_seamed_resolver(app, monkeypatch):
    monkeypatch.setenv("HERMES_SHARED_AUTH_DIR", str(app / "nous-shared"))  # the resolver's pytest seat belt
    from agent.anthropic_credentials import _get_hermes_oauth_file
    from gateway import pairing
    from hermes_cli import auth, auth_nous, config, webhook
    from tools import mcp_oauth

    home = root = app
    files = set(desktop_binding.plaintext_secret_paths(home, root, desktop_binding.shared_auth_dir(root)))
    for resolved in (auth._auth_file_path(), config.get_env_path(), _get_hermes_oauth_file(),
                     webhook._subscriptions_path(), auth_nous._nous_shared_store_path()):
        assert Path(resolved) in files, resolved
    dirs = {home / name for name in desktop_binding.HOME_SECRET_DIRS}
    assert Path(mcp_oauth._get_token_dir()) in dirs
    assert Path(pairing._default_pairing_dir()) in dirs


def test_the_switch_is_off_by_default_and_on_in_bundled_desktop(app):
    assert desktop_binding.bind_desktop_host_store(store_factory=_fake_store) is None
    assert not binding.bound()
    _install_profile(app)
    bound = desktop_binding.bind_desktop_host_store(store_factory=_fake_store)
    assert bound is binding.current() and bound.store_root == app
    assert secret_files.bound()  # sign-ins only: history stays upstream's file


def _fake_store(_blob_dir):
    from agent_runtime.host_store.fake import FakeHostSecureStore

    return FakeHostSecureStore()


def _unavailable(_blob_dir):
    raise desktop.SecureStoreUnavailable("no OS secure store in this bundle")


def test_an_unavailable_store_is_a_typed_refusal_never_plaintext(app, monkeypatch, capsys):
    _install_profile(app)
    with pytest.raises(desktop.SecureStoreUnavailable):
        desktop_binding.bind_desktop_host_store(store_factory=_unavailable)
    assert not binding.bound()

    monkeypatch.setattr(desktop, "os_secure_store", _unavailable)
    with pytest.raises(SystemExit) as exited:
        desktop_binding.bind_desktop_host_store_or_exit()
    assert exited.value.code == 2
    assert json.loads(capsys.readouterr().out)["error"] == "secure_store_unavailable"


def test_serve_start_binds_before_it_claims_the_protocol_pipes(app, monkeypatch, capsys):
    from argparse import Namespace

    from hermes_cli.harness_parts.serve import commands

    _install_profile(app)
    monkeypatch.setattr(desktop, "os_secure_store", _unavailable)
    monkeypatch.setattr(commands, "_claim_protocol_pipes", lambda: pytest.fail("reached the loop unbound"))
    with pytest.raises(SystemExit) as exited:
        commands._cmd_serve(Namespace(ndjson=True, service=False, no_socket=True, parent_pid=None))
    assert exited.value.code == 2


def test_keyring_backends_are_admitted_only_when_they_are_an_os_store():
    class _Keyring:
        def __init__(self, backend):
            self._backend = backend

        def get_keyring(self):
            return self._backend

    keychain = type("Keyring", (), {"__module__": "keyring.backends.macOS"})()
    plaintext = type("PlaintextKeyring", (), {"__module__": "keyrings.alt.file"})()
    assert desktop.admitted_keyring_backend(lambda: _Keyring(keychain)) is keychain  # positive control
    with pytest.raises(desktop.SecureStoreUnavailable):
        desktop.admitted_keyring_backend(lambda: _Keyring(plaintext))

    def no_keyring():
        raise ImportError("No module named 'keyring'")

    with pytest.raises(desktop.SecureStoreUnavailable):
        desktop.admitted_keyring_backend(no_keyring)
    with pytest.raises(desktop.SecureStoreUnavailable):
        desktop.os_secure_store("unused", platform="sunos5")


@windows_only
def test_the_cli_entry_binds_and_migrates_in_a_real_process(app):
    _install_profile(app)
    (app / "auth.json").write_text(json.dumps({"providers": {"nous": {"access_token": ACCESS}}}), encoding="utf-8")
    env = {**os.environ, "HERMES_HOME": str(app), "HERMES_SHARED_AUTH_DIR": str(app / "shared")}
    done = subprocess.run([sys.executable, "-c", "import hermes_cli.main"], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-2000:]

    assert not (app / "auth.json").exists()
    assert _leaks(app) == set()
    held = desktop.DpapiHostSecureStore(app / desktop_binding.BLOB_DIR_NAME).read(
        f"{binding.SLOT_PREFIX}/default/auth.json")
    assert ACCESS.encode() in held  # this process, the same Windows user, reads what the child stored


def test_the_conversation_worker_binds_before_its_engine_reads_a_credential(app, monkeypatch, capsys):
    from agent_runtime.conversations import worker_entry, worker_skills

    _install_profile(app)
    monkeypatch.setattr(desktop, "os_secure_store", _unavailable)
    monkeypatch.setattr(worker_skills, "install", lambda: pytest.fail("the worker started unbound"))
    with pytest.raises(SystemExit) as exited:
        worker_entry.main()
    assert exited.value.code == 2
