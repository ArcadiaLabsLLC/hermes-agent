"""The dashboard's "Anthropic Account" card names the EFFECTIVE source (RT-DASHBOARD-ANTHROPIC-CARD-EFFECTIVE-SOURCE).

Before: with a key and a grant stored the card said "Hermes PKCE" while every turn spent the key.
A temp home with a fake key (env) and a fake grant (patched reader); no secret leaves the card.
"""

from __future__ import annotations

import json
import time

import pytest

KEY = "sk-ant-api03-fake-key-for-tests-3333"
GRANT = "sk-ant-oat01-fake-grant-for-tests-3333"


def _grant() -> dict:
    return {"accessToken": GRANT, "refreshToken": "fake-refresh", "expiresAt": int(time.time() * 1000) + 3_600_000}


@pytest.fixture
def card(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    root.mkdir()
    (tmp_path / "fakehome").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fakehome"))
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)
    for var in ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    import hermes_constants
    hermes_constants._default_hermes_root_memo = None  # type: ignore[attr-defined]
    (root / "auth.json").write_text(json.dumps({"version": 1, "providers": {}}))
    (root / "config.yaml").write_text("model:\n  provider: anthropic\n", encoding="utf-8")
    monkeypatch.setattr("hermes_cli.auth.is_provider_explicitly_configured", lambda pid: True)
    monkeypatch.setattr("agent.anthropic_credentials.read_hermes_oauth_credentials", _grant)
    monkeypatch.setattr("agent.anthropic_credentials.read_claude_code_credentials", lambda: None)
    from hermes_cli import web_server_oauth

    def read() -> dict:
        status = web_server_oauth._anthropic_oauth_status()
        text = json.dumps(status)
        assert KEY not in text and GRANT not in text
        return status

    return read


def test_unset_with_both_stored_names_the_key_turns_spend_and_the_benched_account(card):
    status = card()
    assert (status["source"], status["effective_source"], status["chosen_source"]) == ("env_var", "api_key", None)
    assert status["source_label"].startswith("ANTHROPIC_API_KEY")
    assert status["source_label"].endswith("· Claude account stored, not spent")
    assert status["benched_sources"] == ["account"]
    assert status["token_preview"] == "…s-3333"


def test_account_chosen_names_the_grant_and_the_benched_key(card):
    from agent_runtime import provider_account

    provider_account.provider_source_set("anthropic", "account")
    status = card()
    assert (status["source"], status["effective_source"], status["chosen_source"]) == (
        "hermes_pkce", "account", "account")
    assert status["source_label"].endswith("· API key stored, not spent")
    assert status["has_refresh_token"] is True


def test_only_a_grant_stored_is_upstreams_card_plus_the_fact(card, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    status = card()
    assert status["source"] == "hermes_pkce" and status["benched_sources"] == []
    assert "not spent" not in status["source_label"]


def test_nothing_stored_runs_upstreams_body(card, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr("agent.anthropic_credentials.read_hermes_oauth_credentials", lambda: None)
    assert card() == {"logged_in": False, "source": None}
