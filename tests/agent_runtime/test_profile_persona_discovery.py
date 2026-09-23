"""Automatic profile-to-Persona admission preserves authored identities."""
from types import SimpleNamespace

import pytest

from agent_runtime.config import AgentRuntimeConfig, ensure_persisted_personas
from agent_runtime.models import AgentPersona
from agent_runtime.profile_persona_discovery import reconcile_profile_personas
from agent_runtime import snapshot as snapshot_mod
from agent_runtime.snapshot import build_snapshot
from agent_runtime.store import AgentStore
from hermes_cli import profiles as profile_mod
import hermes_constants


def _profile(name):
    return SimpleNamespace(name=name, path=name)


def _discover(monkeypatch, *, names, templates=None):
    monkeypatch.setattr(hermes_constants, "named_profile_has_servable_identity", lambda path: True)
    monkeypatch.setattr(profile_mod, "list_profile_names", lambda: ["default", *names])
    monkeypatch.setattr(
        profile_mod,
        "available_profile_template_summaries",
        lambda: [_profile(name) for name in (templates if templates is not None else names)],
    )


def _persona(persona_id, profile=None):
    return AgentPersona(persona_id, persona_id, "custom", None, None, None, [], hermes_profile=profile)


def test_new_named_profile_is_persisted_once_without_creating_instance(monkeypatch):
    _discover(monkeypatch, names=["alice", "bob"])
    cfg = AgentRuntimeConfig()
    first = reconcile_profile_personas(cfg)
    assert [item.id for item in first] == ["profile_alice", "profile_bob"]
    assert [item.id for item in reconcile_profile_personas(cfg)] == []
    assert {item.id for item in AgentStore().list_all()} == {"profile_alice", "profile_bob"}
    assert all(item.role == "profile" and item.autonomy == "propose_only" for item in first)
    assert all(item.include_profile_memory and not item.toolsets for item in first)
    assert all(item.readiness["auto_discovered_profile"] for item in first)
    assert {item.id for item in ensure_persisted_personas(cfg)} == {"profile_alice", "profile_bob"}
    edited = AgentStore().get("profile_alice")
    edited.display_name = "Tony's Alice"
    AgentStore().save(edited)
    assert reconcile_profile_personas(cfg) == []
    assert AgentStore().get("profile_alice").display_name == "Tony's Alice"


def test_authored_binding_and_config_binding_are_never_overwritten(monkeypatch):
    _discover(monkeypatch, names=["alice", "bob"])
    AgentStore().save(_persona("human", "alice"))
    cfg = AgentRuntimeConfig(personas={"reviewer": {"role": "reviewer", "hermes_profile": "bob"}})
    assert reconcile_profile_personas(cfg) == []
    assert [item.id for item in AgentStore().list_all()] == ["human"]


def test_unrelated_id_collision_is_a_refusal_not_an_overwrite(monkeypatch, caplog):
    _discover(monkeypatch, names=["alice"])
    AgentStore().save(_persona("profile_alice"))
    assert reconcile_profile_personas(AgentRuntimeConfig()) == []
    assert AgentStore().get("profile_alice").hermes_profile is None
    assert "occupied" in caplog.text


def test_tombstones_ghosts_and_default_are_not_admitted(monkeypatch):
    _discover(monkeypatch, names=["alice"], templates=["alice", "ghost", "deleted", "default"])
    assert [item.hermes_profile for item in reconcile_profile_personas(AgentRuntimeConfig())] == ["alice"]


def test_discovery_failure_does_not_write_partial_personas(monkeypatch):
    _discover(monkeypatch, names=["alice"])
    def fail():
        raise OSError("cannot read profile root")
    monkeypatch.setattr(profile_mod, "available_profile_template_summaries", fail)
    with pytest.raises(OSError, match="cannot read profile root"):
        reconcile_profile_personas(AgentRuntimeConfig())
    assert AgentStore().list_all() == []


def test_real_named_profile_is_admitted_before_snapshot_and_backs_template():
    home = profile_mod._get_profiles_root() / "sample_agent"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    crashed = profile_mod._get_profiles_root() / "crashed_shell"
    crashed.mkdir(parents=True)
    (crashed / ".env").touch()  # enough to list, not enough to serve

    first = build_snapshot()
    personas = [item for item in first["agents"] if item["persona_id"] == "profile_sample_agent"]
    assert len(personas) == 1
    templates = [item for item in first["available_personas"] if item["persona_id"] == "profile:sample_agent"]
    assert len(templates) == 1
    assert templates[0]["backs_persona_id"] == "profile_sample_agent"
    assert [item.id for item in AgentStore().list_all()] == ["profile_sample_agent"]
    build_snapshot()
    assert [item.id for item in AgentStore().list_all()] == ["profile_sample_agent"]

    second = profile_mod._get_profiles_root() / "second_agent"
    second.mkdir(parents=True)
    (second / "config.yaml").write_text("{}\n", encoding="utf-8")
    snapshot_mod._profile_persona_reconcile_tick["at"] = 0.0  # elapsed discovery window
    refreshed = build_snapshot()
    assert {item["persona_id"] for item in refreshed["agents"]} == {
        "profile_sample_agent", "profile_second_agent"
    }
