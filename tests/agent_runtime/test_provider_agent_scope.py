"""``runtime.provider.usage`` / ``list`` for ONE agent (RT-PROVIDER-USAGE-PER-AGENT-PROFILE).

The read runs inside the agent's own ``persona_profile_context`` — the binding a turn of that
agent runs in — so a fake usage fetch records the home it was called under. Each test names its
killing mutation; the reds are recorded in the commit that added this file.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import profile_context
from agent_runtime.serve_rpc import DEFERRED, RpcContext
from agent_runtime.serve_rpc import provider as family
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_NOT_FOUND
from tests._downstream.split_package_source import patch_where_bound


@pytest.fixture
def agents(tmp_path, monkeypatch):
    """Two personas: ``neko`` bound to profile ``neko``, ``plain`` bound to none; one instance of neko."""
    from agent_runtime import config as runtime_config
    from agent_runtime.persona_assignments import store

    root = tmp_path / "hermes"
    homes = {name: root / "profiles" / name for name in ("base", "neko")}
    for home in homes.values():
        home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(homes["base"]))
    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    personas = [SimpleNamespace(id="neko", hermes_profile="neko"), SimpleNamespace(id="plain", hermes_profile=None),
                SimpleNamespace(id="ghost", hermes_profile="nowhere")]
    patch_where_bound(monkeypatch, runtime_config, "load_agent_runtime_config", lambda: None)
    patch_where_bound(monkeypatch, runtime_config, "ensure_persisted_personas", lambda _config: personas)
    monkeypatch.setattr(profile_context, "profile_exists", lambda name: name in homes)
    monkeypatch.setattr(profile_context, "get_profile_dir", lambda name: homes[name])
    monkeypatch.setattr(profile_context, "_resolved_runtime_root", lambda: tmp_path / "store")
    from agent_runtime import paths
    monkeypatch.setattr(paths, "store_root", lambda: tmp_path / "store")

    def get(_self, instance_id):
        if instance_id != "inst-neko":
            raise FileNotFoundError(instance_id)
        return SimpleNamespace(persona_id="neko")

    monkeypatch.setattr(store.PersonaInstanceStore, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(store.PersonaInstanceStore, "get", get)
    return homes


@pytest.fixture
def usage_homes(monkeypatch):
    """A fake usage fetch that records the Hermes home it ran under."""
    from agent import account_usage
    from hermes_constants import get_hermes_home

    seen = []
    monkeypatch.setattr(account_usage, "fetch_account_usage",
                        lambda provider, **_: seen.append(get_hermes_home().resolve()))
    return seen


def test_usage_for_an_instance_runs_under_its_profile_and_echoes_it(agents, usage_homes):
    """Killing mutation: ``answer_for_agent`` calling ``work()`` outside ``agent_provider_scope`` ->
    the fetch reads base's home, red."""
    result = family._runtime_provider_usage(1, {"provider": "anthropic", "persona_instance_id": "inst-neko"})["result"]
    assert usage_homes == [agents["neko"].resolve()]
    assert result["agent"] == {"persona_id": "neko", "persona_instance_id": "inst-neko", "profile": "neko"}


def test_usage_without_an_agent_is_the_serves_home_and_carries_no_echo(agents, usage_homes):
    """Positive control: the unnamed read is unchanged. Killing mutation: ``named`` always True ->
    ``agent_unknown`` refusal, red."""
    result = family._runtime_provider_usage(1, {"provider": "anthropic"})["result"]
    assert usage_homes == [agents["base"].resolve()]
    assert "agent" not in result


def test_usage_by_persona_id_and_a_profileless_persona_inherits_the_serve(agents, usage_homes):
    """Killing mutation: echo ``binding.hermes_profile`` without the active-profile fallback ->
    ``profile: None``, red."""
    neko = family._runtime_provider_usage(1, {"provider": "anthropic", "persona_id": "neko"})["result"]
    plain = family._runtime_provider_usage(2, {"provider": "anthropic", "persona_id": "plain"})["result"]
    assert usage_homes == [agents["neko"].resolve(), agents["base"].resolve()]
    assert (neko["agent"]["profile"], plain["agent"]["profile"]) == ("neko", "base")


def test_an_unknown_agent_is_refused_not_found_and_a_missing_profile_conflicts(agents, usage_homes):
    """Killing mutation: drop ``agent_unknown`` from ``_NOT_FOUND_REASONS`` -> -32000, red."""
    for params in ({"persona_instance_id": "inst-gone"}, {"persona_id": "gone"},
                   {"persona_instance_id": "inst-neko", "persona_id": "plain"}):
        error = family._runtime_provider_usage(1, {"provider": "anthropic", **params})["error"]
        assert (error["code"], error["data"]["reason"]) == (ERR_NOT_FOUND, "agent_unknown"), params
    error = family._runtime_provider_usage(1, {"provider": "anthropic", "persona_id": "ghost"})["error"]
    assert (error["code"], error["data"]["reason"]) == (ERR_CONFLICT, "agent_profile_unavailable")
    assert usage_homes == []


def test_list_for_an_agent_runs_on_the_worker_lane_under_its_profile(agents, monkeypatch):
    """The binding is entered on the worker thread, not the reader's. Killing mutation: enter
    the scope in the handler around ``_off_reader`` -> the deferred build reads base, red."""
    from hermes_cli.harness_parts import provider_visibility
    from hermes_constants import get_hermes_home

    monkeypatch.setattr(provider_visibility, "build_provider_visibility",
                        lambda: {"home": str(get_hermes_home().resolve())})
    spawned = []
    context = RpcContext(spawn_reply=lambda build: spawned.append(build) or True)
    assert family._runtime_provider_list(7, {"persona_instance_id": "inst-neko"}, context) is DEFERRED
    result = spawned[0]()["result"]
    assert result["home"] == str(agents["neko"].resolve())
    assert result["agent"]["profile"] == "neko"
