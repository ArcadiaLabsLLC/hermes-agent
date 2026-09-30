"""Provider definitions stay shared; preferences and tool configuration stay local."""
import json

from agent_runtime.conversations.model_preferences import default_id
from agent_runtime.provider_configuration import provider_configuration
from tests.agent_runtime.test_shared_provider_credentials import bound


def test_shared_custom_provider_resolves_without_copying_profile_config(tmp_path, monkeypatch):
    from hermes_cli.config import load_config
    from hermes_cli.inventory import load_picker_context
    from hermes_cli.model_switch import _scoped_key_env
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from agent.credential_pool import custom_provider_pool_key_candidates

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    owners = [tmp_path / name for name in ("owner-a", "owner-b")]
    profile = tmp_path / "agent"
    profile.mkdir()
    path = profile / "config.yaml"
    path.write_text('model: {default: agent-model, provider: custom:shared}\n'
                    'terminal: {backend: docker}\n', encoding="utf-8")
    original = path.read_bytes()
    for owner in owners:
        owner.mkdir()
        (owner / ".env").write_text(f"PRIVATE_LLM_KEY=synthetic-{owner.name}\n", encoding="utf-8")
        (owner / "config.yaml").write_text(
            'model: {default: owner-model, provider: custom:shared}\n'
            'terminal: {backend: local}\n'
            'providers:\n  shared:\n    name: Shared\n'
            '    base_url: https://example.invalid/v1\n    key_env: PRIVATE_LLM_KEY\n'
            '    models: [agent-model, owner-model]\n    discover_models: false\n', encoding="utf-8")
    for owner in (owners[0], owners[1], owners[0]):
        with bound(profile, owner):
            config = provider_configuration(load_config())
            assert config["terminal"]["backend"] == "docker"
            assert config["model"]["default"] == "agent-model"
            context = load_picker_context()
            assert context.user_providers["shared"]["models"] == ["agent-model", "owner-model"]
            runtime = resolve_runtime_provider(requested="custom:shared", target_model="agent-model")
            assert runtime["api_key"] == f"synthetic-{owner.name}"
            assert _scoped_key_env("PRIVATE_LLM_KEY") == f"synthetic-{owner.name}"
            assert custom_provider_pool_key_candidates("https://example.invalid/v1", "custom:shared")[0] == "shared"
            assert path.read_bytes() == original
            assert not (profile / "auth.json").exists()
    assert default_id(profile, owners[0]) == json.dumps(["custom:shared", "agent-model"], separators=(",", ":"))


def test_default_inheritance_uses_existing_writer_and_never_copies_credentials(tmp_path):
    from hermes_cli.model_switch import ModelSwitchResult, persist_model_selection

    owner, a, b = [tmp_path / name for name in ("owner", "a", "b")]
    for home in (owner, a, b):
        home.mkdir()
    (owner / "config.yaml").write_text('model: {default: base, provider: openrouter}\n', encoding="utf-8")
    (a / "config.yaml").write_text('terminal: {backend: docker}\n', encoding="utf-8")
    for home in (a, b, a):
        assert default_id(home, owner) == '["openrouter","base"]'
    with bound(a, owner):
        persist_model_selection(ModelSwitchResult(success=True, new_model="chosen",
            target_provider="openrouter", api_key="synthetic-do-not-copy"))
    assert default_id(a, owner) == '["openrouter","chosen"]'
    assert default_id(b, owner) == '["openrouter","base"]'
    assert default_id(owner, owner) == '["openrouter","base"]'
    saved = (a / "config.yaml").read_text(encoding="utf-8")
    assert "docker" in saved and "synthetic-do-not-copy" not in saved
