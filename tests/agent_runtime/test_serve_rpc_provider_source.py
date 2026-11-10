"""``runtime.provider.source.set`` and ``list``'s ``credential_source`` block (RT-PROVIDER-SOURCE-SET-METHOD).

A temp home holding BOTH an Anthropic API key (env) and a Hermes PKCE grant (patched reader);
every secret is fake text and no frame may carry one.
"""

from __future__ import annotations

import json
import time

import pytest

from agent_runtime.serve_rpc import provider as family
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS

KEY = "sk-ant-api03-fake-key-for-tests-1111"
GRANT = "sk-ant-oat01-fake-grant-for-tests-1111"


def _grant() -> dict:
    return {"accessToken": GRANT, "refreshToken": "fake-refresh", "expiresAt": int(time.time() * 1000) + 3_600_000}


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    root.mkdir()
    (tmp_path / "fakehome").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fakehome"))
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)
    for var in ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    import hermes_constants
    hermes_constants._default_hermes_root_memo = None  # type: ignore[attr-defined]
    (root / "auth.json").write_text(json.dumps({"version": 1, "providers": {}}))
    (root / "config.yaml").write_text("# keep me\nmodel:\n  default: gpt-5.5\n  provider: openrouter\n",
                                      encoding="utf-8")
    monkeypatch.setattr("hermes_cli.auth.is_provider_explicitly_configured", lambda pid: True)
    monkeypatch.setattr("agent.anthropic_credentials.read_hermes_oauth_credentials", _grant)
    monkeypatch.setattr("agent.anthropic_credentials.read_claude_code_credentials", lambda: None)
    return root


def _frame(params: dict) -> dict:
    frame = family._runtime_provider_source_set(1, params)
    text = json.dumps(frame)
    assert KEY not in text and GRANT not in text
    return frame


def _config(root) -> dict:
    from agent_runtime import yaml_io

    return yaml_io.load((root / "config.yaml").read_text(encoding="utf-8"))


def test_source_set_writes_the_choice_and_selects_nothing_else(home):
    from agent.anthropic_credentials import resolve_anthropic_token

    assert resolve_anthropic_token() == KEY  # unset: the ladder spends the key
    result = _frame({"provider": "Anthropic", "source": "account"})["result"]
    assert result == {
        "contract": 1, "provider": "anthropic", "source": "account", "effective": "account",
        "sources": [{"id": "account", "label": "Claude account", "present": True},
                    {"id": "api_key", "label": "API key", "present": True}],
    }
    config = _config(home)
    assert config["providers"] == {"anthropic": {"credential_source": "account"}}
    assert config["model"] == {"default": "gpt-5.5", "provider": "openrouter"}  # not re-selected
    assert "# keep me" in (home / "config.yaml").read_text(encoding="utf-8")
    assert resolve_anthropic_token() == GRANT

    assert _frame({"provider": "anthropic", "source": "api_key"})["result"]["effective"] == "api_key"
    assert resolve_anthropic_token() == KEY


def test_source_set_refusals_write_nothing(home, monkeypatch):
    before = (home / "config.yaml").read_text(encoding="utf-8")
    cases = [({"source": "account"}, ERR_INVALID_PARAMS, "provider_required"),
             ({"provider": "anthropic"}, ERR_INVALID_PARAMS, "source_required"),
             ({"provider": "openrouter", "source": "api_key"}, ERR_INVALID_PARAMS, "source_unsupported"),
             ({"provider": "anthropic", "source": "plan"}, ERR_INVALID_PARAMS, "source_unknown")]
    for params, code, reason in cases:
        error = _frame(params)["error"]
        assert (error["code"], error["data"]["reason"]) == (code, reason), params
    assert _frame({"provider": "anthropic", "source": "plan"})["error"]["data"]["sources"] == ["account", "api_key"]

    monkeypatch.setattr("agent.anthropic_credentials.read_hermes_oauth_credentials", lambda: None)
    error = _frame({"provider": "anthropic", "source": "account"})["error"]
    assert (error["code"], error["data"]["reason"], error["data"]["source"]) == (
        ERR_CONFLICT, "source_absent", "account")
    assert (home / "config.yaml").read_text(encoding="utf-8") == before


def test_list_rows_carry_the_block_for_a_declared_provider_and_null_otherwise(home, monkeypatch):
    from agent_runtime import provider_account

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake-key-for-tests-1111")
    rows = {row["id"]: row for row in provider_account.provider_list()["providers"]}
    assert rows["anthropic"]["credential_source"] == {
        "chosen": None, "effective": "api_key",
        "sources": [{"id": "account", "label": "Claude account", "present": True},
                    {"id": "api_key", "label": "API key", "present": True}],
    }
    assert rows["openrouter"]["credential_source"] is None
