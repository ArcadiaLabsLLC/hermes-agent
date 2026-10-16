"""Account fields use provider facts, retain nulls, and agree across transports."""
import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from agent.account_usage import AccountUsageSnapshot
from agent_runtime import provider_account_metadata as metadata
from agent_runtime.provider_account import _usage_view
from agent_runtime.provider_account_view import account_view
from hermes_cli.harness_parts.usage.serialize import _serialize_usage_lane


def snapshot(provider, **kw):
    return AccountUsageSnapshot(provider=provider, source="fixture", fetched_at=datetime.now(UTC), **kw)


def test_reported_account_fields_match_rpc_and_argv():
    account = {"email": "fixture@example.invalid", "organisation": "FIXTURE_ORG", "plan": "Team"}
    value = snapshot("anthropic", plan="Team", raw={"account": account, "access_token": "SENTINEL"})
    rpc = _usage_view("anthropic", value)
    argv = _serialize_usage_lane("anthropic", value, active=True)
    assert rpc["account"] == argv["account"] == account
    assert "raw" not in rpc and "raw" not in argv
    assert "SENTINEL" not in json.dumps(rpc) + json.dumps(argv)


def test_unknown_and_opaque_identity_never_become_account_display():
    value = snapshot("anthropic", identity="opaque", raw={"account_id": "opaque"})
    expected = dict.fromkeys(("email", "organisation", "plan"))
    assert account_view("anthropic", value) == expected
    assert _usage_view("anthropic", None)["account"] == expected
    assert _serialize_usage_lane("anthropic", None, active=True)["account"] == expected


def test_nous_uses_the_existing_portal_report(monkeypatch):
    from hermes_cli import nous_account
    from agent import account_usage
    monkeypatch.setattr(nous_account, "get_nous_portal_account_info", lambda **kw: SimpleNamespace(logged_in=True, email="fixture@example.invalid", org_name="FIXTURE_ORG"))
    monkeypatch.setattr(account_usage, "build_nous_credits_snapshot", lambda account: snapshot("nous", plan="Team"))
    value = metadata.nous_usage_snapshot()
    assert account_view("nous", value) == {"email": "fixture@example.invalid", "organisation": "FIXTURE_ORG", "plan": "Team"}


def test_codex_claims_must_match_the_usage_credential(monkeypatch):
    from hermes_cli import auth
    from agent_runtime._upstream_doors import codex_account_claims
    claims = {"sub": "subject", "https://api.openai.com/auth": {"chatgpt_account_id": "account"}, "https://api.openai.com/profile": {"email": "fixture@example.invalid"}}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    token = "e30." + encoded + ".signature"
    def resolve(**kw):
        assert kw == {"read_only": True}
        return {"api_key": token}
    monkeypatch.setattr(auth, "resolve_codex_runtime_credentials", resolve)
    # Wrong-account usage must never acquire the currently selected identity.
    assert codex_account_claims(token, "other") == {}
    correct = snapshot("openai-codex", identity="codex:account:subject", plan="Plus")
    assert account_view("openai-codex", metadata.usage_snapshot("openai-codex", correct))["email"] == "fixture@example.invalid"
    wrong = snapshot("openai-codex", identity="codex:other:subject", plan="Plus")
    assert account_view("openai-codex", metadata.usage_snapshot("openai-codex", wrong))["email"] is None
