"""``runtime.provider.env_token.remove`` deletes a stale env token's lines and pool entries
(RT-SIGNOUT-ENV-TOKEN-REMOVE). Fake values only; no provider is reached."""

from __future__ import annotations

import json
import os

import pytest

import hermes_constants
from agent import credential_pool
from agent_runtime import provider_account
from agent_runtime.serve_rpc import provider as family
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS

SECRET = "SENTINEL-ENV-TOKEN-0000000000"


class _Entry:
    def __init__(self, source):
        self.source = source


class _Pool:
    """One pool per home: ``remove_index`` records which home it ran under."""

    removed: list[tuple[str, int]] = []

    def __init__(self, home):
        self.home = home

    def entries(self):
        return [_Entry("manual"), _Entry("env:ANTHROPIC_TOKEN")]

    def remove_index(self, index):
        _Pool.removed.append((self.home, index))


@pytest.fixture
def namespace(tmp_path, monkeypatch):
    root = tmp_path / "root"
    for profile in ("base", "neko"):
        (root / "profiles" / profile).mkdir(parents=True)
    (root / ".env").write_text(f"ANTHROPIC_TOKEN={SECRET}\nKEEP=1\n", encoding="utf-8")
    (root / "profiles" / "neko" / ".env").write_text(f"export ANTHROPIC_TOKEN={SECRET}\nOTHER=2\n", encoding="utf-8")
    (root / "profiles" / "base" / ".env").write_text("KEEP=3\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "base"))
    monkeypatch.setattr(hermes_constants, "get_default_hermes_root", lambda home=None: root)
    _Pool.removed = []

    def load_pool(provider):
        return _Pool(str(hermes_constants.get_hermes_home()))

    monkeypatch.setattr(credential_pool, "load_pool", load_pool)
    from hermes_cli import auth

    monkeypatch.setattr(auth, "get_auth_status", lambda provider: {"logged_in": False})
    return root


def test_remove_deletes_every_line_and_the_entry_each_seeded(namespace, monkeypatch):
    """Killing mutation: ``_remove_env_token_in_home`` without the home override -> the base .env is
    edited and the token lines stay, red; drop the ``remove_index`` loop -> no entry removed, red."""
    monkeypatch.setattr(provider_account, "_env_tokens_left", lambda provider: [
        {"variable": "ANTHROPIC_TOKEN", "files": [".env", "profiles/neko/.env"]}])
    result = provider_account.provider_env_token_remove("anthropic", "ANTHROPIC_TOKEN")
    assert SECRET not in json.dumps(result)
    assert result["removed_from"] == [".env", "profiles/neko/.env"]
    assert (namespace / ".env").read_text(encoding="utf-8") == "KEEP=1\n"
    assert (namespace / "profiles" / "neko" / ".env").read_text(encoding="utf-8") == "OTHER=2\n"
    assert (namespace / "profiles" / "base" / ".env").read_text(encoding="utf-8") == "KEEP=3\n"
    assert sorted(_Pool.removed) == sorted([(str(namespace), 2), (str(namespace / "profiles" / "neko"), 2)])
    assert os.environ.get("ANTHROPIC_TOKEN") is None


def test_only_a_variable_signout_reported_can_be_removed(namespace, monkeypatch):
    """Killing mutation: drop the ``variable not in left`` refusal -> KEEP is erased, red."""
    monkeypatch.setattr(provider_account, "_env_tokens_left", lambda provider: [
        {"variable": "ANTHROPIC_TOKEN", "files": [".env"]}])
    frame = family._runtime_provider_env_token_remove(1, {"provider": "anthropic", "variable": "KEEP"})
    assert (frame["error"]["code"], frame["error"]["data"]["reason"]) == (ERR_CONFLICT, "env_token_unknown")
    assert "KEEP=1" in (namespace / ".env").read_text(encoding="utf-8")


def test_the_verb_requires_a_variable_and_answers_over_the_wire(namespace, monkeypatch):
    """Killing mutation: drop the ``variable_required`` check -> a refusal from the account layer, red."""
    frame = family._runtime_provider_env_token_remove(1, {"provider": "anthropic"})
    assert (frame["error"]["code"], frame["error"]["data"]["reason"]) == (ERR_INVALID_PARAMS, "variable_required")
    monkeypatch.setattr(provider_account, "_env_tokens_left", lambda provider: [
        {"variable": "ANTHROPIC_TOKEN", "files": [".env"]}])
    frame = family._runtime_provider_env_token_remove(1, {"provider": "anthropic", "variable": "ANTHROPIC_TOKEN"})
    assert SECRET not in json.dumps(frame)
    assert frame["result"]["removed_from"] == [".env"]


def test_a_locked_env_refuses_instead_of_reading_as_done(namespace, monkeypatch):
    """Killing mutation: drop ``require_env_writable`` -> the verb answers removed while the line stays, red."""
    from hermes_cli import config

    monkeypatch.setattr(config, "env_write_refusal", lambda key, action: "locked")
    monkeypatch.setattr(provider_account, "_env_tokens_left", lambda provider: [
        {"variable": "ANTHROPIC_TOKEN", "files": [".env"]}])
    frame = family._runtime_provider_env_token_remove(1, {"provider": "anthropic", "variable": "ANTHROPIC_TOKEN"})
    assert frame["error"]["data"]["reason"] == "env_token_remove_failed"
    assert SECRET in (namespace / ".env").read_text(encoding="utf-8")
