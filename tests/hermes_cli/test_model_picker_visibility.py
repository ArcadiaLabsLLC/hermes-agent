"""The descriptor policy must survive the actual v2 visibility producer."""
import json

from hermes_cli import codex_models, harness


def test_visibility_carries_route_policy_and_isolates_discovery_failure(monkeypatch):
    # conftest fences HERMES_HOME. Only the external model-list boundary is
    # controlled; descriptor composition and the visibility envelope are real.
    ids = ["fixture-chat", "fixture-chat-900k"]
    calls = []

    def discovery(*args, **kwargs):
        calls.append((args, kwargs))
        return list(ids)

    monkeypatch.setattr(codex_models, "get_codex_model_ids", discovery)
    payload = harness.build_provider_visibility()
    rows = {row["id"]: row for row in payload["catalog"]}
    policy = rows["openai-codex"]["model_picker"]
    assert payload["schema"] == "hermes.provider_visibility/v2"
    assert policy["schema"] == "hermes.model_picker_policy/v1"
    assert policy["model_ids"] == ids
    assert policy["billing_mode"] == "account"
    assert calls == [((), {})]
    assert isinstance(payload["providers"], list)
    assert rows["anthropic"]["model_picker"]["billing_mode"] == "catalog"

    def broken():
        raise RuntimeError("fixture-secret-must-not-cross-the-wire")

    monkeypatch.setattr(codex_models, "get_codex_model_ids", broken)
    failed = harness.build_provider_visibility()
    after = {row["id"]: row for row in failed["catalog"]}
    assert after["openai-codex"]["model_picker"]["catalog_mode"] == "unavailable"
    assert after["anthropic"] == rows["anthropic"]
    assert isinstance(failed["providers"], list)
    assert "fixture-secret" not in json.dumps(failed, allow_nan=False)
