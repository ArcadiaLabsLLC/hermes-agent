"""The live-shape sanitizer keeps names and types, and never a secret, path, URL or free text (D3.05)."""

from __future__ import annotations

from scripts.sanitize_profile_config import sanitize


def test_names_numbers_and_types_survive_and_private_values_do_not():
    raw = {
        "model": {"default": "gpt-5.6-luna", "provider": "openai-codex", "base_url": "https://example.invalid/v1"},
        "toolsets": ["hermes-cli", "file"],
        "agent": {"max_turns": 180, "verbose": False, "threshold": 0.75, "hint": None},
        "auxiliary": {"vision": {"api_key": "sk-live-abcdef0123456789abcdef", "model": ""}},
        "agent_runtime": {"personas": {"dev": {
            "hermes_profile": "gpt-launcher",
            "display_name": "Dev Agent of the Launcher",
            "repo_scope": "Q:/Somewhere/Repo",
            "soul_overlay_path": "souls/dev.md",
        }}},
        "tts": {"mistral": {"voice_id": "c69964a6-ab8b-4f8a-9465-ec0925096ec8"}},
        "owner": "someone@example.invalid",
        "opaque": "AbCdEfGhIjKlMnOpQrStUv",
        "Q:\\data\\someone\\project": {"trusted": True},
    }

    out = sanitize(raw)

    assert out["model"] == {"default": "gpt-5.6-luna", "provider": "openai-codex", "base_url": "<redacted:url>"}
    assert out["toolsets"] == ["hermes-cli", "file"]
    assert out["agent"] == {"max_turns": 180, "verbose": False, "threshold": 0.75, "hint": None}
    assert out["auxiliary"]["vision"] == {"api_key": "<redacted:key>", "model": ""}
    dev = out["agent_runtime"]["personas"]["dev"]
    assert dev["hermes_profile"] == "gpt-launcher"
    assert dev["display_name"] == "<redacted:text>"
    assert dev["repo_scope"] == "<redacted:path>"
    assert dev["soul_overlay_path"] == "<redacted:path>"
    assert out["tts"]["mistral"]["voice_id"] == "<redacted:voice>"
    assert out["owner"] == "<redacted:email>"
    assert out["opaque"] == "<redacted:secret>"
    assert "<redacted-key:path-1>" in out and not any("someone" in str(k) for k in out)
