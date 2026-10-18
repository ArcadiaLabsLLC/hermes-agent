"""Model facts carry upstream's per-provider account usage verbatim, cache-only.

Killing mutation: drop the ``provider_usage`` key from ``session_model_catalog.facts``
(or read ``row["usage"]["windows"]`` only) -> the pooled account rows vanish, red."""
from agent_runtime.session_model_catalog import facts, provider_usage

ACCOUNTS = {"accounts": [
    {"id": "codex:a:1", "label": "work", "state": "limited", "resets_at": "2026-10-18T05:00:00+00:00",
     "windows": [{"label": "Weekly", "used_percent": 100.0, "resets_at": "2026-10-18T05:00:00+00:00",
                  "scope": "account"}]},
    {"id": "codex:b:2", "label": "home", "state": "unknown", "resets_at": None, "windows": []},
]}
WINDOWS = {"windows": [{"label": "Opus weekly", "used_percent": 40.0, "resets_at": None, "scope": "model"}]}
INVENTORY = {"providers": [
    {"slug": "openai-codex", "name": "Codex", "models": ["gpt"], "usage": ACCOUNTS},
    {"slug": "anthropic", "name": "Anthropic", "models": ["opus"], "usage": WINDOWS},
    {"slug": "openrouter", "name": "OpenRouter", "models": ["x"]},
    {"slug": "nous", "name": "Nous", "models": [], "usage": {}},
    {"name": "no slug", "usage": WINDOWS},
]}


def test_each_provider_with_a_fresh_usage_block_is_carried_exactly():
    assert provider_usage(INVENTORY) == {"openai-codex": ACCOUNTS, "anthropic": WINDOWS}


def test_facts_publish_provider_usage_beside_the_session_usage():
    result = facts("s1", {"info": {"provider": "anthropic", "model": "opus", "usage": {"input_tokens": 3}}},
                   INVENTORY)
    assert result["usage"] == {"input_tokens": 3}
    assert result["provider_usage"]["openai-codex"]["accounts"][0]["state"] == "limited"
    assert facts("s1", {}, {"providers": []})["provider_usage"] == {}
