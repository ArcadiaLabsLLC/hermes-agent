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
