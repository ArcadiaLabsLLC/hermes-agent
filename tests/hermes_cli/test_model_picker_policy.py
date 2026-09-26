"""Account-scoped picker contract and safe failure states."""
import base64
import json
from pathlib import Path

from hermes_cli import auth, auth_codex, model_picker_policy, provider_catalog
from hermes_cli.model_picker_policy import model_picker_policy_for


def _token(account: str) -> str:
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": account}}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


def test_descriptor_projection_matches_shared_wire_fixture(monkeypatch):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/model_picker_policy_v1.json").read_text())
    ids = fixture["policies"]["openai-codex"]["model_ids"]
    token = _token("account-a")
    monkeypatch.setattr(auth_codex, "_read_codex_tokens", lambda: {"tokens": {"access_token": token}})
    monkeypatch.setattr(model_picker_policy, "get_verified_codex_model_ids", lambda value: list(ids))
    monkeypatch.setattr(provider_catalog, "provider_catalog", lambda: [])
    rows = {row["id"]: row for row in provider_catalog.provider_login_catalog()}
    for slug, policy in fixture["policies"].items():
        assert rows[slug]["model_picker"] == policy
    assert token not in json.dumps(rows)


def test_unverified_and_empty_catalog_are_distinct(monkeypatch):
    monkeypatch.setattr(auth_codex, "_read_codex_tokens", lambda: {"tokens": {"access_token": _token("a")}})
    monkeypatch.setattr(model_picker_policy, "get_verified_codex_model_ids", lambda value: None)
    unavailable = model_picker_policy_for("openai-codex")
    assert unavailable["catalog_mode"] == "unavailable"
    assert "model_ids" not in unavailable
    monkeypatch.setattr(model_picker_policy, "get_verified_codex_model_ids", lambda value: [])
    empty = model_picker_policy_for("openai-codex")
    assert empty["catalog_mode"] == "verified"
    assert empty["model_ids"] == []


def test_failure_isolation_and_secret_redaction(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("secret-token-and-account-id")
    monkeypatch.setattr(auth_codex, "_read_codex_tokens", fail)
    monkeypatch.setattr(auth_codex, "_pool_codex_credential", lambda: ("", ""))
    monkeypatch.setattr(provider_catalog, "provider_catalog", lambda: [])
    rows = {row["id"]: row for row in provider_catalog.provider_login_catalog()}
    assert rows["openai-codex"]["model_picker"]["catalog_mode"] == "unavailable"
    assert "secret-token" not in json.dumps(rows)
    assert rows["anthropic"]["model_picker"]["catalog_mode"] == "reference"


def test_verified_cache_is_account_scoped_and_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    calls = []
    def fetch(token):
        calls.append(token)
        return ["gpt-6-astra"] if token == _token("a") else ["gpt-5.6-sol"]
    monkeypatch.setattr(model_picker_policy, "_fetch_verified_models_from_api", fetch)
    a, b = _token("a"), _token("b")
    assert model_picker_policy.get_verified_codex_model_ids(a) == ["gpt-6-astra"]
    assert model_picker_policy.get_verified_codex_model_ids(a) == ["gpt-6-astra"]
    assert model_picker_policy.get_verified_codex_model_ids(b) == ["gpt-5.6-sol"]
    assert calls == [a, b]
    cache = json.loads(model_picker_policy._picker_cache_path().read_text())
    assert a not in json.dumps(cache) and b not in json.dumps(cache)
    cache["expires"] = 0
    model_picker_policy._picker_cache_path().write_text(json.dumps(cache))
    assert model_picker_policy.get_verified_codex_model_ids(b) == ["gpt-5.6-sol"]
    assert calls == [a, b, b]


def test_live_result_never_synthesizes_spark_or_astra(monkeypatch):
    token = _token("account-a")
    class Response:
        status_code = 200
        def json(self):
            return {"models": [{"slug": "gpt-5.6-terra", "visibility": "show"}]}
    import httpx
    sent = []
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: sent.append((url, kwargs["headers"])) or Response())
    assert model_picker_policy._fetch_verified_models_from_api(token) == [
        "gpt-5.6-terra", "gpt-5.6-terra-900k"]
    # Upstream's reader asks as the newest client, with upstream's account header.
    url, headers = sent[0]
    assert url.endswith("client_version=99.0.0")
    assert headers["ChatGPT-Account-ID"] == "account-a"


def test_picker_cache_follows_the_profile_home_override(tmp_path, monkeypatch):
    """The cache lives under ``get_hermes_home()``, so a profile override moves it."""

    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    ambient = tmp_path / "ambient"
    profile = tmp_path / "profiles" / "alice"
    monkeypatch.setenv("HERMES_HOME", str(ambient))
    # Positive control: with no override the ambient home answers.
    assert model_picker_policy._picker_cache_path().parent.parent == ambient
    token = set_hermes_home_override(profile)
    try:
        assert model_picker_policy._picker_cache_path() == (
            profile / "cache" / "codex-model-picker.json"
        )
    finally:
        reset_hermes_home_override(token)
