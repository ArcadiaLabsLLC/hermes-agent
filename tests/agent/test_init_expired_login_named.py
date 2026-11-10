"""An explicit provider whose OAuth login expired is refused NAMED, with the expiry as its reason.

RT-EXPIRED-LOGIN-REFUSAL-UNNAMED (owner, 2026-11-08): Neko's ``claude_code`` refresh token went
"terminally invalid (Refresh token expired)", the anthropic pool had no available entry, and the
turn settled ``provider_unavailable`` with NO provider, so Eternia said "No model provider is
configured for this profile". Init must name the provider, and an expired sign-in as
``login_expired``, and the turn's refusal block must carry both.
"""

from types import SimpleNamespace

import pytest

from agent.credential_pool import STATUS_DEAD, STATUS_OK, CredentialPool, PooledCredential


def _agent(provider="anthropic", model="claude-opus-5-5"):
    return SimpleNamespace(provider=provider, model=model, base_url=None, api_key=None,
                           _fallback_activated=False)


def _credential(auth_type, **overrides):
    fields = dict(provider="anthropic", id="e1", label="claude_code", auth_type=auth_type,
                  priority=0, source="claude_code", access_token="tok-test-0000", refresh_token="r")
    fields.update(overrides)
    return PooledCredential(**fields)


def _refuse(monkeypatch, pool):
    from agent import agent_init
    from agent.auxiliary_unavailable import ProviderNotConfiguredError

    monkeypatch.setattr("agent.auxiliary_client.resolve_provider_client", lambda *a, **k: (None, None))
    monkeypatch.setattr("hermes_cli.fallback_config.resolve_entry_api_key", lambda entry: None)
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda p: pool)
    monkeypatch.setattr("hermes_cli.auth.read_credential_pool", lambda p: [])
    with pytest.raises(ProviderNotConfiguredError) as excinfo:
        agent_init._routed_client_kwargs(_agent(), None, 60)
    return excinfo.value


def test_a_dead_oauth_login_is_refused_named_and_expired(monkeypatch):
    from agent_runtime.provider_login_expiry import LOGIN_EXPIRED_REASON

    dead = _credential("oauth", last_status=STATUS_DEAD, last_error_reason="invalid_grant")
    exc = _refuse(monkeypatch, CredentialPool("anthropic", [dead]))

    assert (exc.provider, exc.credentials_reason) == ("anthropic", LOGIN_EXPIRED_REASON)
    assert "sign-in has expired" in str(exc) and "hermes auth add anthropic" in str(exc)


def test_a_dead_api_key_is_named_but_not_an_expired_login(monkeypatch):
    dead = _credential("api_key", last_status=STATUS_DEAD, refresh_token=None)
    exc = _refuse(monkeypatch, CredentialPool("anthropic", [dead]))

    assert (exc.provider, exc.credentials_reason) == ("anthropic", None)


def test_no_credential_at_all_still_names_the_configured_provider(monkeypatch):
    exc = _refuse(monkeypatch, CredentialPool("anthropic", []))

    assert (exc.provider, exc.credentials_reason) == ("anthropic", None)
    assert "expired" not in str(exc)


def test_the_turn_refusal_block_carries_the_provider_and_the_expiry():
    from agent_runtime.mission_chat_outcome import ChatErrorKind, classify_turn_failure
    from agent_runtime.provider_login_expiry import LOGIN_EXPIRED_REASON, NamedProviderNotConfiguredError

    exc = NamedProviderNotConfiguredError("expired", provider="anthropic", credentials_reason=LOGIN_EXPIRED_REASON)
    outcome = classify_turn_failure(exc, provider_submitted=True, request_started=False)

    assert outcome.error_kind == ChatErrorKind.CHAT_TURN_PROVIDER_UNAVAILABLE
    block = outcome.provider_refusal.as_dict()
    assert block["reason"] == "provider_unavailable"
    assert (block["provider"], block["failure_reason"]) == ("anthropic", LOGIN_EXPIRED_REASON)
    assert "anthropic sign-in has expired" in outcome.provider_refusal.next_expected()


def test_an_unconfigured_profile_still_names_no_provider():
    from agent.auxiliary_unavailable import ProviderNotConfiguredError
    from agent_runtime.mission_chat_outcome import classify_turn_failure

    outcome = classify_turn_failure(ProviderNotConfiguredError("No LLM provider configured."),
                                    provider_submitted=True, request_started=False)
    block = outcome.provider_refusal.as_dict()
    assert "provider" not in block and "failure_reason" not in block
    assert "configure a provider" in outcome.provider_refusal.next_expected()
