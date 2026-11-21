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


# ── a sign-in gives an install with no default model one (RT-FU-A-PHONE-SIGNED-IN-TO-ONE-PROVIDER-…) ──

from agent_runtime import runtime_default_model as rdm  # noqa: E402


@pytest.fixture
def recommended(monkeypatch):
    asked: list[str] = []

    def recommend(provider_id):
        asked.append(provider_id)
        return "gpt-6-luna"

    monkeypatch.setattr(rdm, "_recommended_default", recommend)
    return asked


def test_a_sign_in_on_an_install_with_no_default_writes_the_recommended_model(accepted_switch, recommended):
    """Killing mutation: ``seed_default_model_after_signin`` returning before the write -> no
    ``model.default``, red (the phone's agents then have no model)."""
    _write_config({"model": {"provider": "openai-codex"}})

    answer = rdm.seed_default_model_after_signin("OpenAI-Codex", requested_by="runtime.provider.signin")

    assert answer is not None and answer["changed"] is True
    assert recommended == ["openai-codex"]
    cfg = load_agent_runtime_config()
    assert (cfg.default_provider, cfg.default_model) == ("openai-codex", "gpt-6-luna")
    assert _events()[0].payload["requested_by"] == "runtime.provider.signin"


@pytest.mark.parametrize("config", [
    {"model": {"default": "kept-model", "provider": "anthropic"}},
    {"model": {"provider": "openai-codex"}, "agent_runtime": {"default_model": "pinned"}},
], ids=["names-a-default", "pinned"])
def test_an_install_that_names_a_default_keeps_it(accepted_switch, recommended, config):
    """Killing mutation: drop the ``_current_pair(cfg)[1]`` check in ``_install_names_no_default`` -> the
    kept default is replaced, red."""
    _write_config(config)

    assert rdm.seed_default_model_after_signin("openai-codex", requested_by="t") is None
    assert accepted_switch == [] and recommended == [] and _events() == []


def test_an_empty_recommendation_writes_nothing(accepted_switch, monkeypatch):
    _write_config({})
    monkeypatch.setattr(rdm, "_recommended_default", lambda provider_id: "")

    assert rdm.seed_default_model_after_signin("openai-codex", requested_by="t") is None
    assert accepted_switch == [] and _events() == []


def test_the_recommendation_is_upstreams_silent_pick_from_the_providers_curated_list(monkeypatch):
    """The model comes from upstream's picker and ``pick_silent_default_model``, never a fork list."""
    import hermes_cli.inventory as inventory

    monkeypatch.setattr(inventory, "load_picker_context", lambda: object())
    monkeypatch.setattr(inventory, "build_models_payload", lambda ctx: {"providers": [
        {"slug": "other", "models": ["x"]},
        {"slug": "openai-codex", "models": ["gpt-a", "gpt-b"]},
    ]})
    picked = []
    monkeypatch.setattr("hermes_cli.models.pick_silent_default_model",
                        lambda models, provider: picked.append((models, provider)) or models[-1])

    assert rdm._recommended_default("openai-codex") == "gpt-b"
    assert picked == [(["gpt-a", "gpt-b"], "openai-codex")]
    assert rdm._recommended_default("absent") == ""


# ── RT-FU-A-PHONE-SIGNED-IN-BEFORE-AN-UPGRADE-GETS-A-DEFAULT-MODEL-TOO: the serve-start reconcile ──


@pytest.fixture
def signed_in(monkeypatch):
    """The sign-in table and which of its providers read signed in; records every status probe."""
    import agent_runtime.provider_account as provider_account
    import hermes_cli.provider_browser_login as browser_login

    state = {"table": ("openai-codex", "xai-oauth", "nous"), "in": set(), "probed": []}
    monkeypatch.setattr(browser_login, "sign_in_providers", lambda: state["table"])

    def probe(provider):
        state["probed"].append(provider)
        return provider in state["in"]

    monkeypatch.setattr(provider_account, "_signed_in", probe)
    return state


def test_an_install_signed_in_before_the_seed_existed_gets_the_default_at_serve_start(
        accepted_switch, recommended, signed_in):
    """The owner's phone: signed in to Codex before the sign-in seed shipped, no ``model.default``.
    Killing mutation: ``reconcile_default_model_at_start`` returning None before its seed call -> no
    default written, red."""
    _write_config({})
    signed_in["in"] = {"openai-codex"}

    answer = rdm.reconcile_default_model_at_start()

    assert answer is not None and answer["changed"] is True
    assert recommended == ["openai-codex"]
    cfg = load_agent_runtime_config()
    assert (cfg.default_provider, cfg.default_model) == ("openai-codex", "gpt-6-luna")
    assert _events()[0].payload["requested_by"] == "serve.start"


@pytest.mark.parametrize("config", [
    {"model": {"default": "kept-model", "provider": "anthropic"}},
    {"agent_runtime": {"default_model": "pinned"}},
], ids=["names-a-default", "pinned"])
def test_the_reconcile_keeps_an_existing_default_and_reads_no_sign_in(accepted_switch, recommended, signed_in,
                                                                     config):
    """Killing mutation: drop the reconcile's own ``_install_names_no_default()`` guard -> every serve
    start on an install that names a default probes each provider's sign-in status, red."""
    _write_config(config)
    signed_in["in"] = {"openai-codex"}

    assert rdm.reconcile_default_model_at_start() is None
    assert signed_in["probed"] == [] and accepted_switch == [] and recommended == [] and _events() == []
    assert load_agent_runtime_config().default_model in {"kept-model", "pinned"}


def test_the_reconcile_does_nothing_with_no_signed_in_provider(accepted_switch, recommended, signed_in):
    """A one-provider table, signed out. Killing mutation: drop the ``_signed_in`` filter in
    ``_signed_in_providers`` (a signed-out provider counted) -> its default is seeded, red."""
    _write_config({})
    signed_in["table"] = ("openai-codex",)

    assert rdm.reconcile_default_model_at_start() is None
    assert signed_in["probed"] == ["openai-codex"]
    assert accepted_switch == [] and recommended == [] and _events() == []


def test_the_reconcile_does_not_choose_between_two_signed_in_providers(accepted_switch, recommended, signed_in):
    """Killing mutation: ``len(signed_in) != 1`` -> ``len(signed_in) < 1`` (seed the first of several)
    -> a default the operator never chose is written, red."""
    _write_config({})
    signed_in["in"] = {"openai-codex", "nous"}

    assert rdm.reconcile_default_model_at_start() is None
    assert accepted_switch == [] and recommended == [] and _events() == []


def test_the_reconcile_never_raises(monkeypatch):
    _write_config({})

    def unreadable_status():
        raise OSError("status")

    monkeypatch.setattr(rdm, "_signed_in_providers", unreadable_status)
    assert rdm.reconcile_default_model_at_start() is None
