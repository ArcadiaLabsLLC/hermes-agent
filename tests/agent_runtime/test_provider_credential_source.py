"""``providers.anthropic.credential_source``: an explicit choice of which STORED credential turns spend.

Real ``agent.credential_pool`` and ``resolve_anthropic_token`` against a temp home holding BOTH an
API key (env) and a Hermes PKCE grant (patched reader). Every secret here is fake text.
Row RT-ANTHROPIC-CREDENTIAL-SOURCE-CHOICE.
"""

from __future__ import annotations

import json
import time

import pytest

KEY = "sk-ant-api03-fake-key-for-tests-0000"
GRANT = "sk-ant-oat01-fake-grant-for-tests-0000"
ENV_OAUTH = "sk-ant-oat01-fake-env-token-for-tests"
MODEL = "claude-sonnet-4-5"


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
    for var in ("ANTHROPIC_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    import hermes_constants
    hermes_constants._default_hermes_root_memo = None  # type: ignore[attr-defined]
    (root / "auth.json").write_text(json.dumps({"version": 1, "providers": {}}))
    monkeypatch.setattr("hermes_cli.auth.is_provider_explicitly_configured", lambda pid: True)
    monkeypatch.setattr("agent.anthropic_credentials.read_hermes_oauth_credentials", _grant)
    monkeypatch.setattr("agent.anthropic_credentials.read_claude_code_credentials", lambda: None)
    return root


def _choose(root, source: str | None) -> None:
    body = "model:\n  provider: anthropic\n"
    if source is not None:
        body += f"providers:\n  anthropic:\n    credential_source: {source}\n"
    (root / "config.yaml").write_text(body, encoding="utf-8")


def _sources(pool) -> set[str]:
    return {entry.source for entry in pool.entries()}


# ── unset: upstream's ladder, unchanged ──────────────────────────────────────


def test_unset_keeps_the_ladder_the_key_wins_and_the_grant_is_pruned(home, monkeypatch):
    from agent.anthropic_credentials import resolve_anthropic_token
    from agent.credential_pool import load_pool

    _choose(home, None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert resolve_anthropic_token() == KEY
    assert _sources(load_pool("anthropic")) == {"env:ANTHROPIC_API_KEY"}


def test_a_value_the_table_does_not_declare_reads_as_unset(home, monkeypatch):
    from agent_runtime.provider_credential_source import chosen_credential_source

    _choose(home, "plan")
    assert chosen_credential_source("anthropic") is None
    assert chosen_credential_source("openrouter") is None


# ── account chosen ───────────────────────────────────────────────────────────


def test_account_chosen_spends_the_grant_and_keeps_the_key_row_benched(home, monkeypatch):
    from agent.anthropic_credentials import resolve_anthropic_token
    from agent.credential_pool import load_pool

    _choose(home, "account")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert resolve_anthropic_token() == GRANT
    assert resolve_anthropic_token(model=MODEL) == GRANT
    pool = load_pool("anthropic")
    assert {"hermes_pkce", "env:ANTHROPIC_API_KEY"} <= _sources(pool)  # benched, never pruned
    assert pool.select().source == "hermes_pkce"
    available, _pending = pool._available_entries()
    assert [entry.source for entry in available] == ["hermes_pkce"]


def test_account_chosen_with_no_grant_stored_falls_to_the_key(home, monkeypatch):
    from agent.anthropic_credentials import resolve_anthropic_token
    from agent.credential_pool import load_pool

    monkeypatch.setattr("agent.anthropic_credentials.read_hermes_oauth_credentials", lambda: None)
    _choose(home, "account")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert resolve_anthropic_token() == KEY
    assert load_pool("anthropic").select().source == "env:ANTHROPIC_API_KEY"  # no account row: no bench


# ── api_key chosen ───────────────────────────────────────────────────────────


def test_api_key_chosen_outranks_an_env_account_token(home, monkeypatch):
    from agent.anthropic_credentials import resolve_anthropic_token

    _choose(home, "api_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("ANTHROPIC_TOKEN", ENV_OAUTH)
    assert resolve_anthropic_token() == KEY


def test_api_key_chosen_a_429_on_the_key_never_rotates_onto_the_grant(home, monkeypatch):
    """The guarantee the pruning branch exists for, kept by the bench."""
    from agent.anthropic_credentials import resolve_anthropic_token
    from agent.credential_pool import load_pool

    _choose(home, "api_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    pool = load_pool("anthropic")
    assert "hermes_pkce" in _sources(pool)
    assert pool.select(model=MODEL).source == "env:ANTHROPIC_API_KEY"
    ctx = {"message": "This request would exceed your account's rate limit."}
    rotated = pool.mark_exhausted_and_rotate(
        status_code=429, error_context=ctx, api_key_hint=KEY, failure_reason="rate_limit", model=MODEL,
    )
    assert rotated is None
    assert pool.select(model=MODEL) is None
    assert resolve_anthropic_token(model=MODEL) is None  # benched for MODEL: does not fall to the grant


def test_api_key_chosen_with_no_key_stored_falls_to_the_grant(home):
    from agent.anthropic_credentials import resolve_anthropic_token

    _choose(home, "api_key")
    assert resolve_anthropic_token() == GRANT


# ── the fact a client reads ──────────────────────────────────────────────────


def test_block_unset_with_both_stored_reports_the_key_effective(home, monkeypatch):
    from agent_runtime.provider_credential_source import credential_source_block

    _choose(home, None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert credential_source_block("anthropic") == {
        "chosen": None,
        "effective": "api_key",
        "sources": [{"id": "account", "label": "Claude account", "present": True},
                    {"id": "api_key", "label": "API key", "present": True}],
    }
    assert credential_source_block("openai-codex") is None


def test_block_chosen_account_without_a_grant_reports_the_key_effective(home, monkeypatch):
    from agent_runtime.provider_credential_source import credential_source_block

    monkeypatch.setattr("agent.anthropic_credentials.read_hermes_oauth_credentials", lambda: None)
    _choose(home, "account")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    block = credential_source_block("anthropic")
    assert (block["chosen"], block["effective"]) == ("account", "api_key")
    assert [source["present"] for source in block["sources"]] == [False, True]


def test_a_bound_home_reads_the_choice_from_the_shared_store(home, tmp_path, monkeypatch):
    from agent_runtime.provider_credential_source import chosen_credential_source

    shared = tmp_path / "shared"
    shared.mkdir()
    _choose(home, "api_key")
    _choose(shared, "account")
    monkeypatch.setenv("HERMES_AUTH_HOME", str(shared))
    assert chosen_credential_source("anthropic") == "account"


def test_the_warm_read_costs_at_most_a_millisecond(home):
    from agent_runtime.provider_credential_source import chosen_credential_source

    _choose(home, "account")
    assert chosen_credential_source("anthropic") == "account"  # primes the config cache
    runs = 200
    started = time.perf_counter()
    for _ in range(runs):
        chosen_credential_source("anthropic")
    assert (time.perf_counter() - started) / runs < 0.001
