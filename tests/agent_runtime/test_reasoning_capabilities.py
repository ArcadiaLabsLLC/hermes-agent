"""Serving metadata crosses the snapshot, patch and next-turn model owners."""
from dataclasses import replace

from agent.reasoning_effort import route_supported_efforts
from agent_runtime.reasoning_capabilities import reasoning_capabilities
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_summary
from agent_runtime.persona_chat_session import _chat_effective_model_payload
from agent_runtime.state_patches.persona_instance import project_persona_instance_wire_fields
from hermes_cli.models_reasoning_caps import (
    cached_control_capabilities, record_control_catalog, _seed_reasoning_caps,
)
from tests.agent_runtime.test_persona_set_model import _persona, _cfg, _two_instances


def test_arbitrary_future_model_catalog_drives_transport_and_read_model(monkeypatch):
    record_control_catalog("openai-codex", [{
        "slug": "future-model", "supported_reasoning_levels": [
            {"effort": "max", "description": "A provider explanation"},
            {"effort": "low"}, {"effort": "high"},
        ], "default_reasoning_level": "high",
    }])
    caps = reasoning_capabilities("openai-codex", "future-model")
    assert caps.wire()["levels"] == ["low", "high", "max"]
    assert caps.default_effort == caps.provider_default_effort == "high"
    assert caps.descriptions == {"max": "A provider explanation"}
    assert route_supported_efforts("openai-codex", "future-model") == caps.levels
    assert route_supported_efforts("openai-codex", "future-model", "codex_app_server") == (*caps.levels, "ultra")
    assert reasoning_capabilities("openai-codex", "future-model", default_effort="low").default_effort == "low"
    assert cached_control_capabilities("openai-codex", "future-model-900k") is None

    persona = replace(_persona(model="future-model"), hermes_profile=None)
    store = PersonaInstanceStore()
    first, second = _two_instances(store, persona)
    summary = persona_instance_summary(store.get(first.id), persona)
    assert summary["reasoning_capabilities"]["levels"] == list(caps.levels)
    assert summary["reasoning_supported"] is True
    # The patch projection resolves the same stored persona, and provider-only
    # writes recompute its capabilities instead of carrying the former route.
    monkeypatch.setattr("agent_runtime.state_patches.persona_instance._resolve_persona_for", lambda _: persona)
    changed = project_persona_instance_wire_fields(store.get(first.id), ["provider"])
    assert changed["reasoning_capabilities"] == summary["reasoning_capabilities"]
    store.update_profile(second.id, provider="unreported-provider")
    shifted = project_persona_instance_wire_fields(store.get(second.id), ["provider"])
    assert shifted["reasoning_capabilities"]["state"] == "unknown"
    assert shifted["reasoning_supported"] is False
    assert persona_instance_summary(store.get(first.id), persona)["reasoning_capabilities"] == summary["reasoning_capabilities"]


def test_unknown_unsupported_and_unmapped_are_distinct():
    record_control_catalog("copilot", [
        {"id": "unknown", "capabilities": {}},
        {"id": "unsupported", "capabilities": {"supports": {"reasoning_effort": []}}},
        {"id": "new-terms", "capabilities": {"supports": {"reasoning_effort": ["turbo"]}}},
        {"id": "known", "capabilities": {"supports": {"reasoning_effort": ["high", "low"]}}},
    ])
    assert reasoning_capabilities("copilot", "unknown").wire()["state"] == "unknown"
    negative = reasoning_capabilities("copilot", "unsupported", default_effort="medium")
    assert negative.wire()["state"] == "unsupported" and negative.default_effort is None
    novel = reasoning_capabilities("copilot", "new-terms")
    assert novel.wire()["state"] == "supported"
    assert novel.levels == () and novel.unrecognised_levels == ("turbo",)
    assert reasoning_capabilities("copilot", "known").levels == ("low", "high")
    assert reasoning_capabilities("openai-codex", "unlisted-future-model").wire()["state"] == "unknown"


def test_cache_inspection_is_read_only_isolated_and_expires(monkeypatch, tmp_path):
    from hermes_cli import models_reasoning_caps as cache
    from hermes_constants import get_hermes_home
    original_home = get_hermes_home()
    record_control_catalog("copilot", [{"id": "shared", "capabilities": {"supports": {"reasoning_effort": ["high"]}}}])
    disk = cache._reasoning_caps_disk_path()
    before = disk.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError("inspection must never fetch, warm, refresh, or write")
    monkeypatch.setattr(cache, "_fetch_reasoning_caps_catalog", forbidden)
    monkeypatch.setattr(cache, "_warm_reasoning_caps_async", forbidden)
    monkeypatch.setattr(cache, "_save_reasoning_caps_disk", forbidden)
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider", forbidden)
    assert reasoning_capabilities("copilot", "shared").levels == ("high",)
    assert disk.read_bytes() == before
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "other"))
    assert cached_control_capabilities("copilot", "shared") is None
    monkeypatch.setenv("HERMES_HOME", str(original_home))
    monkeypatch.setenv("GH_TOKEN", "different-account")
    assert cached_control_capabilities("copilot", "shared") is None
    monkeypatch.delenv("GH_TOKEN")
    clock = cache.time.time()
    monkeypatch.setattr(cache.time, "time", lambda: clock + cache._REASONING_CAPS_DISK_TTL_SECONDS + 1)
    assert cached_control_capabilities("copilot", "shared") is None


def test_router_catalog_mandatory_and_missing_level_list():
    _seed_reasoning_caps("https://openrouter.ai/api/v1/models", [
        {"id": "a", "supported_parameters": ["reasoning"],
         "reasoning": {"supported_efforts": ["none", "high", "low"], "mandatory": True}},
        {"id": "b", "supported_parameters": ["reasoning"]},
        {"id": "c", "supported_parameters": []},
    ])
    assert reasoning_capabilities("openrouter", "a").levels == ("low", "high")
    assert reasoning_capabilities("openrouter", "b").levels is None
    assert reasoning_capabilities("openrouter", "c").wire()["state"] == "unsupported"


def test_session_override_and_inherited_model_use_the_existing_cascade():
    record_control_catalog("openai-codex", [
        {"slug": "inherited", "supported_reasoning_levels": ["low", "high"]},
        {"slug": "chat-override", "supported_reasoning_levels": ["minimal", "max"]},
    ])
    persona = replace(_persona(model=None, provider=None), hermes_profile=None)
    cfg = replace(_cfg(), default_model="inherited")
    inherited = _chat_effective_model_payload(persona=persona, config=cfg, override=None)
    overridden = _chat_effective_model_payload(persona=persona, config=cfg, override={"model": "chat-override"})
    assert inherited["reasoning_capabilities"]["levels"] == ["low", "high"]
    assert overridden["reasoning_capabilities"]["levels"] == ["minimal", "max"]
    assert overridden["default_model"] == "inherited"


def test_provider_hook_inspection_never_starts_a_catalog_warmer(monkeypatch):
    import sys
    from providers import get_provider_profile
    from agent.transports.codex import declared_reasoning_efforts
    profile = get_provider_profile("router")
    module = sys.modules[profile.__class__.__module__]
    attempted = []
    def forbidden():
        attempted.append("warm")
        raise AssertionError("inspection attempted background HTTP")
    monkeypatch.setattr(module, "_warm_efforts_async", forbidden)
    assert declared_reasoning_efforts("router", "unlisted") is None
    assert attempted == []


def test_explicit_endpoint_does_not_borrow_another_serving_catalog():
    from agent.transports.codex import declared_reasoning_efforts
    record_control_catalog("openai-codex", [{
        "slug": "endpoint-model", "supported_reasoning_levels": ["low", "max"],
    }], base_url="https://serving-a.example/v1")
    assert reasoning_capabilities("openai-codex", "endpoint-model", base_url="https://serving-a.example/v1/").levels == ("low", "max")
    assert reasoning_capabilities("openai-codex", "endpoint-model", base_url="https://serving-b.example/v1").levels is None
    assert declared_reasoning_efforts("openai-codex", "endpoint-model", "https://serving-b.example/v1") is None
