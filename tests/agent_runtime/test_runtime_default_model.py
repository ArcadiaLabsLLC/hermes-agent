"""``runtime.default_model.set`` and the envelope's CLI-profile report.

``switch_model`` is faked (it can reach a provider catalog); ``save_config``,
``load_config`` and the event log are the real ones, against the hermetic home.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.config import load_agent_runtime_config
from agent_runtime.events import EventLog
from agent_runtime.serve_rpc import default_model as family
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS
from hermes_cli.config import get_config_path, read_user_config_raw
from hermes_cli.model_switch import ModelSwitchResult


def _events() -> list:
    return [event for event in EventLog().tail(10_000) if event.type == "runtime.default_model.set"]


def _write_config(data: dict) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")  # JSON is YAML


@pytest.fixture
def accepted_switch(monkeypatch):
    calls: list[dict] = []

    def fake_switch_model(**kwargs):
        calls.append(kwargs)
        return ModelSwitchResult(
            success=True,
            new_model=kwargs["raw_input"],
            target_provider=kwargs["explicit_provider"],
            api_mode="codex_responses",
            is_global=True,
        )

    monkeypatch.setattr("hermes_cli.model_switch.switch_model", fake_switch_model)
    return calls


def test_set_writes_the_serve_profiles_model_block_and_announces_it(accepted_switch):
    _write_config({"model": {"default": "gpt-5.6-luna", "provider": "openai-codex"}})

    frame = family._runtime_default_model_set(
        1, {"provider": "openai-codex", "model": "gpt-6-luna", "requested_by": "launcher"}
    )

    result = frame["result"]
    assert result["changed"] is True
    assert (result["provider"], result["model"]) == ("openai-codex", "gpt-6-luna")
    assert result["previous"] == {"provider": "openai-codex", "model": "gpt-5.6-luna"}
    assert accepted_switch[0]["is_global"] is True
    cfg = load_agent_runtime_config()
    assert (cfg.default_provider, cfg.default_model) == ("openai-codex", "gpt-6-luna")
    events = _events()
    assert len(events) == 1
    assert events[0].payload["model"] == "gpt-6-luna"
    assert events[0].payload["previous_model"] == "gpt-5.6-luna"
    assert events[0].payload["requested_by"] == "launcher"


def test_an_identical_pick_is_unchanged_and_silent(accepted_switch):
    _write_config({"model": {"default": "gpt-6-luna", "provider": "openai-codex"}})

    frame = family._runtime_default_model_set(1, {"provider": "openai-codex", "model": "gpt-6-luna"})

    assert frame["result"]["changed"] is False
    assert _events() == []


@pytest.mark.parametrize(
    ("params", "reason"),
    [({"model": "gpt-6-luna"}, "provider_required"), ({"provider": "openai-codex"}, "model_required")],
)
def test_missing_params_are_typed_refusals(accepted_switch, params, reason):
    frame = family._runtime_default_model_set(1, params)

    assert frame["error"]["code"] == ERR_INVALID_PARAMS
    assert frame["error"]["data"]["reason"] == reason
    assert accepted_switch == []


def test_a_runtime_pin_refuses_instead_of_writing_an_ineffective_default(accepted_switch):
    original = {
        "model": {"default": "gpt-5.6-luna", "provider": "openai-codex"},
        "agent_runtime": {"default_model": "pinned-model"},
    }
    _write_config(original)

    frame = family._runtime_default_model_set(1, {"provider": "openai-codex", "model": "gpt-6-luna"})

    assert frame["error"]["code"] == ERR_CONFLICT
    assert frame["error"]["data"]["reason"] == "shadowed_by_runtime_override"
    assert frame["error"]["data"]["pins"] == ["agent_runtime.default_model"]
    assert read_user_config_raw(get_config_path())["model"]["default"] == "gpt-5.6-luna"
    assert _events() == []


def test_a_pick_upstream_rejects_is_model_rejected(monkeypatch):
    _write_config({"model": {"default": "gpt-5.6-luna", "provider": "openai-codex"}})
    monkeypatch.setattr(
        "hermes_cli.model_switch.switch_model",
        lambda **kwargs: ModelSwitchResult(success=False, error_message="Unknown model 'nope'"),
    )

    frame = family._runtime_default_model_set(1, {"provider": "openai-codex", "model": "nope"})

    assert frame["error"]["code"] == ERR_INVALID_PARAMS
    assert frame["error"]["data"]["reason"] == "model_rejected"
    assert "Unknown model" in frame["error"]["message"]
    assert _events() == []


def test_envelope_reports_the_cli_sticky_profile_beside_the_serve_profile(monkeypatch):
    from hermes_cli.profiles import _get_active_profile_path

    from agent_runtime.snapshot.envelope import _runtime_profile_identity

    marker = _get_active_profile_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    # A serve pinned to ``base`` (live: HERMES_HOME=.../profiles/base).
    monkeypatch.setenv("HERMES_PROFILE", "base")
    marker.write_text("base\n", encoding="utf-8")
    same = _runtime_profile_identity()
    marker.write_text("alice\n", encoding="utf-8")
    split = _runtime_profile_identity()

    assert same == {"name": "base", "cli_active_profile": "base", "cli_active_profile_differs": False}
    assert split["cli_active_profile"] == "alice"
    assert split["name"] == "base"
    assert split["cli_active_profile_differs"] is True


def test_a_served_core_carries_the_sticky_profile_of_now_not_of_its_build(monkeypatch):
    from hermes_cli.profiles import _get_active_profile_path

    from agent_runtime.core_cache.read import label_core

    marker = _get_active_profile_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_PROFILE", "base")
    marker.write_text("alice\n", encoding="utf-8")
    core = {"parity": {"profile": {"name": "base", "cli_active_profile": "base", "cli_active_profile_differs": False}}}

    label_core(core, source="cache", stale=False)

    assert core["parity"]["profile"]["cli_active_profile"] == "alice"
    assert core["parity"]["profile"]["cli_active_profile_differs"] is True
