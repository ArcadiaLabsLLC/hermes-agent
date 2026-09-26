"""The descriptor policy must survive the actual v2 visibility producer."""
import base64
import json

from hermes_cli import auth_codex, model_picker_policy
from hermes_cli.harness_parts.provider_visibility import build_provider_visibility


def _fixture_access_token(account_id: str) -> str:
    """A JWT-shaped token carrying only the account claim the picker checks."""

    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"fixture-header.{body}.fixture-signature"


def test_visibility_carries_route_policy_and_isolates_discovery_failure(monkeypatch):
    # conftest fences HERMES_HOME. Only the two external boundaries the picker
    # crosses are controlled — the stored Codex token and the live catalog
    # request; the account-header check, the bounded disk cache, descriptor
    # composition and the visibility envelope are real.
    ids = ["fixture-chat", "fixture-chat-900k"]
    token = _fixture_access_token("fixture-account")
    calls = []

    def live_catalog(access_token):
        calls.append(access_token)
        return list(ids)

    monkeypatch.setattr(auth_codex, "_read_codex_tokens", lambda **_: {"tokens": {"access_token": token}})
    monkeypatch.setattr(model_picker_policy, "_fetch_verified_models_from_api", live_catalog)
    payload = build_provider_visibility()
    rows = {row["id"]: row for row in payload["catalog"]}
    policy = rows["openai-codex"]["model_picker"]
    assert payload["schema"] == "hermes.provider_visibility/v2"
    assert policy["schema"] == "hermes.model_picker_policy/v1"
    assert policy["catalog_mode"] == "verified"
    assert policy["model_ids"] == ids
    assert policy["billing_mode"] == "account"
    assert calls == [token]
    assert isinstance(payload["providers"], list)
    assert rows["anthropic"]["model_picker"]["billing_mode"] == "catalog"
    assert token not in json.dumps(payload, allow_nan=False)

    def broken(access_token):
        raise RuntimeError("fixture-secret-must-not-cross-the-wire")

    monkeypatch.setattr(model_picker_policy, "get_verified_codex_model_ids", broken)
    failed = build_provider_visibility()
    after = {row["id"]: row for row in failed["catalog"]}
    assert after["openai-codex"]["model_picker"]["catalog_mode"] == "unavailable"
    assert "model_ids" not in after["openai-codex"]["model_picker"]
    assert after["anthropic"] == rows["anthropic"]
    assert isinstance(failed["providers"], list)
    assert "fixture-secret" not in json.dumps(failed, allow_nan=False)
