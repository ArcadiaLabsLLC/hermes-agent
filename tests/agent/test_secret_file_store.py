"""agent.secret_files: a registered SecretFileStore holds every credential file instead of the disk."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agent import secret_files
from agent.secret_files import SecretFileStore


class DictStore(SecretFileStore):
    def __init__(self) -> None:
        self.slots: dict[str, bytes] = {}

    @property
    def name(self) -> str:
        return "dict"

    def read(self, path: Path):
        return self.slots.get(str(path))

    def write(self, path: Path, data: bytes) -> None:
        self.slots[str(path)] = data

    def delete(self, path: Path) -> bool:
        return self.slots.pop(str(path), None) is not None

    def list(self, directory: Path, suffix: str) -> list[str]:
        prefix = str(directory) + os.sep
        return [key[len(prefix):-len(suffix)] for key in self.slots
                if key.startswith(prefix) and key.endswith(suffix) and os.sep not in key[len(prefix):]]


@pytest.fixture
def store():
    value = DictStore()
    secret_files.register_provider(value)
    try:
        yield value
    finally:
        secret_files._reset_for_tests()


def test_unbound_helpers_are_the_disk_calls(tmp_path):
    path = tmp_path / "creds.json"
    assert not secret_files.secret_store_bound()
    assert secret_files.secret_path(path) is path
    secret_files.write_secret_json(path, {"token": "t"})
    assert path.is_file()
    assert secret_files.read_secret_bytes(path) == path.read_bytes()
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
    assert secret_files.unlink_secret(path) is True
    assert not path.exists()


def test_bound_anthropic_credentials_never_touch_the_disk(store, tmp_path):
    from agent import anthropic_credentials

    path = tmp_path / ".anthropic_oauth.json"
    anthropic_credentials._atomic_write_private_json(path, {"access_token": "sk-x"})
    assert not path.exists()
    assert anthropic_credentials._load_json_if_exists(path, "x") == {"access_token": "sk-x"}


def test_bound_webhook_subscriptions_round_trip_through_the_store(store, tmp_path, monkeypatch):
    from hermes_cli import webhook

    monkeypatch.setattr(webhook, "_subscriptions_path", lambda: tmp_path / "webhook_subscriptions.json")
    webhook._save_subscriptions_unlocked({"route": {"secret": "hmac"}})
    assert not (tmp_path / "webhook_subscriptions.json").exists()
    assert webhook._load_subscriptions() == {"route": {"secret": "hmac"}}


def test_bound_pairing_lists_a_platform_only_the_store_holds(store, tmp_path):
    from gateway import pairing

    (tmp_path / "telegram-approved.json").write_text("{}", encoding="utf-8")
    pairing._save_json_file(tmp_path / "signal-approved.json", {"u": {}})
    assert not (tmp_path / "signal-approved.json").exists()
    paired = pairing.PairingStore.__new__(pairing.PairingStore)
    paired._dir = tmp_path
    assert sorted(paired._all_platforms("approved")) == ["signal", "telegram"]
    assert pairing._load_json_file(tmp_path / "signal-approved.json") == {"u": {}}


def test_bound_mcp_token_remove_empties_the_store(store, tmp_path):
    from tools import mcp_oauth

    storage = mcp_oauth.HermesTokenStorage("srv", hermes_home=tmp_path)
    mcp_oauth._write_json(storage._tokens_path(), {"access_token": "a"})
    mcp_oauth._write_json(storage._client_info_path(), {"client_id": "c"})
    assert not storage._tokens_path().exists()
    assert mcp_oauth._read_json(storage._tokens_path()) == {"access_token": "a"}
    storage.remove()
    assert store.slots == {}


def test_bound_env_file_parses_the_store_bytes(store, tmp_path):
    from agent.secret_scope import load_env_file

    env = tmp_path / ".env"
    secret_files.write_secret_bytes(env, b"FOO_DOOR=bar\n")
    assert not env.exists()
    assert load_env_file(env) == {"FOO_DOOR": "bar"}


def test_bound_dotenv_publishes_from_the_store_and_never_sanitizes(store, tmp_path, monkeypatch):
    from hermes_cli import env_loader

    monkeypatch.setenv("FOO_DOOR", "shell")
    monkeypatch.delenv("FOO_DOOR")
    secret_files.write_secret_bytes(tmp_path / ".env", b"FOO_DOOR=bar\n")

    def _no_disk(self):
        raise AssertionError("the in-place sanitizer must not inspect a store-held .env")

    with monkeypatch.context() as m:
        m.setattr(secret_files.SecretFileView, "exists", _no_disk)
        env_loader._sanitize_env_file_if_needed(secret_files.secret_path(tmp_path / ".env"))
    env_loader.load_hermes_dotenv(hermes_home=tmp_path, load_external_secrets=False)
    assert os.environ.get("FOO_DOOR") == "bar"
    assert not (tmp_path / ".env").exists()


def test_the_plugin_registrar_and_isolation_row_exist():
    from hermes_cli.plugin_isolation import HOST_OBJECT_BASES
    from hermes_cli.plugins import PluginContext

    assert callable(PluginContext.register_secret_file_store)
    assert HOST_OBJECT_BASES["register_secret_file_store"] == "agent.secret_files:SecretFileStore"
