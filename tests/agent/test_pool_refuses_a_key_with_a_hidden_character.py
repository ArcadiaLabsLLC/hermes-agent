"""A key already stored with a hidden character reads DEAD at its first lease, with the reason.

RT-FU-AN-API-KEY-WITH-A-HIDDEN-CONTROL-CHARACTER-IS-REFUSED-WHEN-IT-IS-SAVED (review w1118a.69): a
key pasted at ``hermes auth add`` kept a trailing NUL, and every Anthropic call failed as
``APIConnectionError`` (``Illegal header value``) for ~6 minutes of transport retries. The pool's
fork seam (``agent/credential_pool.py::_available_entries``) asks the one key check
(``agent_runtime/api_key_check.py``) and the turn's refusal names it. Every key here is fake text.
"""

from types import SimpleNamespace

import pytest

from agent.credential_pool import STATUS_DEAD, CredentialPool, PooledCredential

BAD = "sk-ant-api03-fake-key-for-tests-0000\0"
GOOD = "sk-ant-api03-fake-good-key-for-tests-1111"


def _row(key, row_id="k1"):
    return PooledCredential(provider="anthropic", id=row_id, label=row_id, auth_type="api_key",
                            priority=0, source="manual", access_token=key)


def _pool(*rows):
    pool = CredentialPool("anthropic", list(rows))
    pool._persist = lambda *a, **k: None  # no auth.json in this test
    return pool


def test_a_stored_key_with_a_nul_reads_dead_at_its_first_lease():
    """MUTATION (kill): ``api_key_refusal`` answering None — red (the bad key is leased)."""
    pool = _pool(_row(BAD))

    assert pool.select() is None
    (entry,) = pool.entries()
    assert (entry.last_status, entry.last_error_reason) == (STATUS_DEAD, "api_key_control_character")


def test_a_good_key_beside_it_is_leased():
    pool = _pool(_row(BAD, "bad"), _row(GOOD, "good"))

    assert pool.select().id == "good"
    assert {e.id: e.last_status for e in pool.entries()}["bad"] == STATUS_DEAD


def test_a_turn_on_a_refused_key_names_the_hidden_character(monkeypatch):
    """Through upstream's init raise and the fork seam it already carries
    (``agent_runtime/provider_login_expiry.py::named_missing_provider_error``).

    MUTATION (kill): ``pool_key_refused`` answering False — red (``credentials_reason`` is None)."""
    from agent import agent_init
    from agent.auxiliary_unavailable import ProviderNotConfiguredError
    from agent_runtime.mission_chat_outcome import classify_turn_failure

    pool = _pool(_row(BAD))
    monkeypatch.setattr("agent.auxiliary_client.resolve_provider_client", lambda *a, **k: (None, None))
    monkeypatch.setattr("hermes_cli.fallback_config.resolve_entry_api_key", lambda entry: None)
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda p: pool)
    monkeypatch.setattr("hermes_cli.auth.read_credential_pool", lambda p: [])
    agent = SimpleNamespace(provider="anthropic", model="claude-sonnet-5", base_url=None, api_key=None,
                            _fallback_activated=False)
    with pytest.raises(ProviderNotConfiguredError) as excinfo:
        agent_init._routed_client_kwargs(agent, None, 60)

    exc = excinfo.value
    assert (exc.provider, exc.credentials_reason) == ("anthropic", "api_key_control_character")
    assert "fake-key" not in str(exc)
    block = classify_turn_failure(exc, provider_submitted=True, request_started=False).provider_refusal
    assert block.as_dict()["failure_reason"] == "api_key_control_character"
    assert "hidden character" in block.next_expected()


def test_a_run_that_found_no_credential_names_the_refused_key(monkeypatch):
    """Read live 2026-11-21 (lane w1118a-sw69-keys): the anthropic resolve raised ``AuthError`` "No
    Anthropic credentials found" before agent init's seam, so the turn said nothing of the key. The
    runner asks ``refused_key_error`` on failure; any other error is left alone.

    MUTATION (kill): ``refused_key_error`` answering None — red."""
    from agent_runtime.provider_login_expiry import refused_key_error
    from hermes_cli.auth_constants import AuthError

    pool = _pool(_row(BAD))
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda p: pool)
    assert pool.select() is None
    named = refused_key_error(AuthError("No Anthropic credentials found."), "anthropic")
    assert (named.provider, named.credentials_reason) == ("anthropic", "api_key_control_character")
    assert refused_key_error(RuntimeError("boom"), "anthropic") is None
    assert refused_key_error(AuthError("x"), None) is None
    good = _pool(_row(GOOD))
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda p: good)
    assert refused_key_error(AuthError("No Anthropic credentials found."), "anthropic") is None


def test_the_runner_raises_the_named_refusal_in_place_of_the_bare_failure(tmp_path, monkeypatch):
    """MUTATION (kill): drop the ``refused_key_error`` arm in ``ProfileAgentRunner._run`` — red."""
    from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner
    from agent_runtime.provider_login_expiry import NamedProviderNotConfiguredError
    from hermes_cli.auth_constants import AuthError

    class Boom:
        def __init__(self, *a, **k):
            raise AuthError("No Anthropic credentials found.")

    pool = _pool(_row(BAD))
    pool.select()
    monkeypatch.setattr("agent.credential_pool.load_pool", lambda p: pool)
    monkeypatch.setattr("agent_runtime.profile_runner.execute.AgentRunExecution.run",
                        lambda self: (_ for _ in ()).throw(AuthError("No Anthropic credentials found.")))
    with pytest.raises(NamedProviderNotConfiguredError) as excinfo:
        ProfileAgentRunner(agent_factory=Boom).run(AgentRunRequest(
            profile=None, user_message="hi", provider="anthropic", runtime_root=tmp_path))
    assert excinfo.value.credentials_reason == "api_key_control_character"
