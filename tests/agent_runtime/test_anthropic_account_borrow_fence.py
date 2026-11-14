"""Eternia's Anthropic Account never borrows Claude Code's login.

Row RT-ANTHROPIC-ACCOUNT-NEVER-BORROWS-CLAUDE-CODE-LOGIN (owner 2026-11-14: "the boundry its being
put in is its own connector login button"). A temp HOME holds a FAKE ``.claude/.credentials.json``
read by upstream's real reader; the Hermes PKCE grant is the ``manual:hermes_pkce`` pool row the Sign
in button writes to the temp ``auth.json``. Every secret here is fake text. The fence is
``agent_runtime.provider_credential_source.borrowed_login_fenced`` (HERMES_LAUNCHER_SPAWNED=1).
"""

from __future__ import annotations

import json
import pathlib
import time

import pytest

#: The real reader runs, against the fixture's tmp HOME only (``Path.home`` redirected below).
pytestmark = pytest.mark.allow_claude_code_credentials_file

BORROWED = "sk-ant-oat01-fake-claude-code-login-0000"
GRANT = "sk-ant-oat01-fake-hermes-pkce-grant-0000"
ENV_OAUTH = "sk-ant-oat01-fake-env-token-for-tests-00"


def _expiry() -> int:
    return int(time.time() * 1000) + 3_600_000


@pytest.fixture
def home(tmp_path, monkeypatch):
    root, claude = tmp_path / "hermes", tmp_path / "claude"
    root.mkdir()
    claude.mkdir()
    (claude / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": BORROWED, "refreshToken": "fake-claude-refresh", "expiresAt": _expiry()}}))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("HERMES_LAUNCHER_SPAWNED", "1")
    for var in ("HERMES_AUTH_HOME", "ANTHROPIC_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    import hermes_constants
    hermes_constants._default_hermes_root_memo = None  # type: ignore[attr-defined]
    monkeypatch.setattr("agent.anthropic_credentials._read_claude_code_keychain_payload", lambda: None)
    (root / "auth.json").write_text(json.dumps({"version": 1, "providers": {}}))
    (root / "config.yaml").write_text("model:\n  provider: anthropic\n", encoding="utf-8")
    return root


def _sign_in(root) -> None:
    """What the Sign in button's hermes PKCE flow leaves (``hermes auth add anthropic --type oauth``)."""
    (root / "auth.json").write_text(json.dumps({"version": 1, "providers": {}, "credential_pool": {"anthropic": [{
        "id": "pkce01", "label": "Claude account", "auth_type": "oauth", "priority": 0,
        "source": "manual:hermes_pkce", "access_token": GRANT, "refresh_token": "fake-pkce-refresh",
        "expires_at_ms": _expiry()}]}}))


def _anthropic_rows() -> list[str]:
    from hermes_cli.harness_parts.provider_visibility import build_provider_visibility

    rows = [p for p in build_provider_visibility()["providers"] if p["id"] == "anthropic"]
    return [c["source"] for c in rows[0]["credentials"]] if rows else []


def _turn_token():
    from agent.anthropic_credentials import resolve_anthropic_token
    from agent.credential_pool import load_pool

    leased = load_pool("anthropic").select()
    return resolve_anthropic_token(model="claude-sonnet-4-5"), getattr(leased, "access_token", None)


def test_anthropic_account_never_borrows_claude_code_login(home):
    from agent_runtime.provider_account import _signed_in
    from agent_runtime.provider_credential_source import present_credential_sources

    assert _anthropic_rows() == []
    assert present_credential_sources("anthropic")["account"] is False
    assert _signed_in("anthropic") is False
    assert BORROWED not in _turn_token()


def test_the_sign_in_button_grant_connects_and_is_what_a_turn_spends(home):
    from agent_runtime.provider_account import _signed_in

    _sign_in(home)
    assert _anthropic_rows() and all("claude" not in source.lower() for source in _anthropic_rows())
    assert _signed_in("anthropic") is True
    assert _turn_token() == (GRANT, GRANT)


def test_sign_out_reads_signed_out_with_a_claude_code_login_present(home):
    from agent_runtime.provider_account import provider_signout

    _sign_in(home)
    answer = provider_signout("anthropic")
    assert (answer["was_signed_in"], answer["signed_in"]) == (True, False)
    assert _anthropic_rows() == []
    assert BORROWED not in _turn_token()


def test_a_chosen_account_with_a_static_env_token_is_never_swapped_for_the_borrowed_login(home, monkeypatch):
    from agent.anthropic_credentials import resolve_anthropic_token

    (home / "config.yaml").write_text(
        "model:\n  provider: anthropic\nproviders:\n  anthropic:\n    credential_source: account\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_TOKEN", ENV_OAUTH)
    assert resolve_anthropic_token() == ENV_OAUTH


def test_outside_eternia_the_ladder_is_upstreams(home, monkeypatch):
    from agent.anthropic_credentials import resolve_anthropic_token

    monkeypatch.delenv("HERMES_LAUNCHER_SPAWNED")
    assert resolve_anthropic_token() == BORROWED
    assert _anthropic_rows() == ["claude_code"]
