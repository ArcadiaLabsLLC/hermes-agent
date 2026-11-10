"""The Anthropic usage lane under ``credential_source`` (RT-USAGE-ANTHROPIC-SOURCE-LANE).

Both doors — ``runtime.provider.usage`` and the argv ``hermes harness usage --json`` lane — over a
temp home holding a fake API key (env) and a fake PKCE grant (patched reader). The OAuth usage
endpoint is a fake ``_get_json`` that records which bearer it was handed.
"""

from __future__ import annotations

import json
import time

import pytest

KEY = "sk-ant-api03-fake-key-for-tests-2222"
GRANT = "sk-ant-oat01-fake-grant-for-tests-2222"
PAYLOAD = {"five_hour": {"utilization": 0.25, "resets_at": "2026-11-02T18:00:00Z"},
           "seven_day": {"utilization": 0.5, "resets_at": "2026-11-07T00:00:00Z"}}


def _grant() -> dict:
    return {"accessToken": GRANT, "refreshToken": "fake-refresh", "expiresAt": int(time.time() * 1000) + 3_600_000}


@pytest.fixture
def bearers(tmp_path, monkeypatch):
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
    seen: list[str] = []

    def fake_get_json(url, headers, *, timeout):
        seen.append(headers["Authorization"].removeprefix("Bearer "))
        return PAYLOAD

    monkeypatch.setattr("agent.account_usage._get_json", fake_get_json)
    return seen


def _choose(source: str) -> None:
    from agent_runtime import provider_account

    provider_account.provider_source_set("anthropic", source)


def _no_secret(value) -> None:
    text = json.dumps(value)
    assert KEY not in text and GRANT not in text


def test_rpc_usage_with_the_key_effective_reads_no_balance_and_the_plan_with_the_grant(bearers):
    from agent_runtime.provider_account import provider_usage
    from agent_runtime.provider_usage_source import API_KEY_USAGE_DETAIL

    view = provider_usage("anthropic")
    _no_secret(view)
    assert (view["available"], view["windows"], view["details"], view["unavailable_reason"]) == (
        True, [], [API_KEY_USAGE_DETAIL], None)
    assert view["source"] == "api_key"
    assert view["credential_source"]["effective"] == "api_key"
    assert [w["label"] for w in view["plan_windows"]] == ["Current session", "Current week"]
    assert bearers == [GRANT]  # the plan half used the grant, explicitly; the key never hit /oauth/usage


def test_rpc_usage_with_the_account_chosen_is_the_plan_lane_unchanged(bearers):
    from agent_runtime.provider_account import provider_usage

    _choose("account")
    view = provider_usage("anthropic")
    _no_secret(view)
    assert [w["label"] for w in view["windows"]] == ["Current session", "Current week"]
    assert view["source"] == "oauth_usage_api"
    assert view["credential_source"]["chosen"] == "account"
    assert "plan_windows" not in view
    assert bearers == [GRANT]


def test_argv_usage_lane_carries_the_same_block_and_plan_windows(bearers, monkeypatch):
    from hermes_cli.harness_parts.usage import commands as usage_commands
    from agent_runtime.provider_usage_source import API_KEY_USAGE_DETAIL

    monkeypatch.setattr(usage_commands, "_resolve_active_provider_id", lambda: "anthropic")
    payload = usage_commands.build_account_usage(only_provider="anthropic", timeout=5.0)
    _no_secret(payload)
    (lane,) = payload["lanes"]
    assert (lane["available"], lane["windows"], lane["details"], lane["unavailable_reason"]) == (
        True, [], [API_KEY_USAGE_DETAIL], None)
    assert lane["credential_source"]["effective"] == "api_key"
    assert [w["label"] for w in lane["plan_windows"]] == ["Current session", "Current week"]

    _choose("account")
    (lane,) = usage_commands.build_account_usage(only_provider="anthropic", timeout=5.0)["lanes"]
    assert [w["label"] for w in lane["windows"]] == ["Current session", "Current week"]
    assert lane["credential_source"]["chosen"] == "account" and "plan_windows" not in lane


def test_a_provider_off_the_table_carries_a_null_block(bearers, monkeypatch):
    from agent_runtime import provider_account

    monkeypatch.setattr("agent.account_usage.fetch_account_usage", lambda provider, **kw: None)
    view = provider_account.provider_usage("openrouter")
    assert view["credential_source"] is None and "plan_windows" not in view
