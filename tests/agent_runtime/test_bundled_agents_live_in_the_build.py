"""Base Agent and Neko Mission Lead come from the build, so every install gets each update.

Row ``RT-BUNDLED-AGENTS-LIVE-IN-THE-BUILD`` (owner 2026-11-19): only these two
ship; they always update; a local change is allowed, shown as ``locally_changed``
and reset by the next update. Read through the doors the app uses: the store
load, the turn's SOUL builder and ``runtime.agent.directory``.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.bundled_agents import catalog, sync_shipped_agents
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.fresh_install_seed import seed_fresh_install_persona
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.mission_chat_prompts import _mission_chat_soul_overlay
from agent_runtime.models import AgentPersona
from agent_runtime.store import AgentStore
from hermes_cli.profiles import get_profile_dir

NEKO = "neko_supervisor"


def _raw(persona_id: str) -> dict:
    return json.loads(paths.agent_path(persona_id).read_text(encoding="utf-8"))


def _store_bytes() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in paths.agents_dir().glob("*.json")}


def _ship_update(monkeypatch, tmp_path, *, soul: str | None = None, **definition) -> catalog.ShippedAgent:
    """Stand in for a newer build: Neko with another SOUL and/or definition."""

    current = catalog.shipped_agent(NEKO)
    souls = tmp_path / "next-build-souls"
    souls.mkdir(exist_ok=True)
    (souls / "neko.md").write_text(soul if soul is not None else current.soul_text(), encoding="utf-8")
    monkeypatch.setattr(catalog, "_SOULS", souls)
    newer = replace(current, definition={**current.definition, **definition})
    monkeypatch.setitem(catalog._BY_ID, NEKO, newer)
    return newer


def _rpc(method: str, **params) -> dict:
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "d", "method": method, "params": params})
    assert "result" in reply, reply
    return reply["result"]


def _directory() -> dict[str, dict]:
    ensure_install_identity(paths.store_root())
    result = _rpc("runtime.agent.directory")
    assert result["instance_conversations"] == 1
    return {row["persona_id"]: row for row in result["agents"] if row["canonical"]}


@pytest.fixture
def fresh_root():
    seeded = seed_fresh_install_persona(load_agent_runtime_config())
    assert [p.id for p in seeded] == [NEKO, "base"]


def test_a_fresh_roots_neko_and_base_are_references_to_the_build(fresh_root):
    for persona_id in (NEKO, "base"):
        raw = _raw(persona_id)
        assert raw["origin"] == "eternia"
        assert raw["bundled_version"] == catalog.shipped_agent(persona_id).version
    assert AgentStore().get("base").display_name == "Base Agent"


def test_a_changed_shipped_soul_reaches_the_next_turn_with_no_store_write(fresh_root, monkeypatch, tmp_path):
    before = _store_bytes()
    neko_home = get_profile_dir("neko")
    profile_before = (neko_home / "SOUL.md").read_bytes()

    _ship_update(monkeypatch, tmp_path, soul="You are Neko, rewritten by the next build.", skills=["harness-runtime-model", "new-skill"])

    neko = AgentStore().get(NEKO)
    assert _mission_chat_soul_overlay(neko) == "You are Neko, rewritten by the next build."
    assert neko.skills == ["harness-runtime-model", "new-skill"]
    assert _store_bytes() == before
    assert (neko_home / "SOUL.md").read_bytes() == profile_before


def test_the_directory_carries_origin_agent_name_and_locally_changed(fresh_root):
    AgentStore().save(AgentPersona(
        "my_copy", "My Neko", "agent", None, None, None,
        based_on={"id": NEKO, "name": "Neko Mission Lead"},
    ))

    rows = _directory()

    assert rows[NEKO]["origin"] == "eternia"
    assert rows[NEKO]["agent_name"] == "Neko Mission Lead"
    assert rows[NEKO]["locally_changed"] is False
    assert rows["base"]["origin"] == "eternia"
    assert rows["my_copy"]["based_on"] == {"id": NEKO, "name": "Neko Mission Lead"}
    assert "origin" not in rows["my_copy"] and "locally_changed" not in rows["my_copy"]

    detail = _rpc("runtime.persona.instance.detail", instance_id=rows[NEKO]["instance_id"])
    assert (detail["origin"], detail["agent_name"], detail["locally_changed"]) == ("eternia", "Neko Mission Lead", False)


def test_a_local_edit_is_kept_and_flagged_until_the_next_update_resets_it(fresh_root, monkeypatch, tmp_path):
    store = AgentStore()
    store.save(replace(store.get(NEKO), skills=["my-own-skill"]))
    (get_profile_dir("neko") / "SOUL.md").write_text("My own Neko.", encoding="utf-8")

    assert store.get(NEKO).skills == ["my-own-skill"]
    assert _mission_chat_soul_overlay(store.get(NEKO)) == "My own Neko."
    assert _directory()[NEKO]["locally_changed"] is True

    newer = _ship_update(monkeypatch, tmp_path, soul="Neko from the next build.")

    assert store.get(NEKO).skills == ["harness-runtime-model"]
    assert _mission_chat_soul_overlay(store.get(NEKO)) == "Neko from the next build."
    assert _directory()[NEKO]["locally_changed"] is False
    assert _raw(NEKO)["bundled_version"] == newer.version  # the directory read synced it
    assert _raw(NEKO)["skills"] == ["harness-runtime-model"]
    assert (get_profile_dir("neko") / "SOUL.md").read_text(encoding="utf-8") == "Neko from the next build."


def test_settings_stay_the_installs_and_are_not_a_local_change(fresh_root, monkeypatch, tmp_path):
    store = AgentStore()
    store.save(replace(store.get(NEKO), model="gpt-5.6-luna", provider="openai-codex"))

    _ship_update(monkeypatch, tmp_path, soul="Neko, updated.")
    assert sync_shipped_agents() == [NEKO]

    neko = store.get(NEKO)
    assert (neko.model, neko.provider) == ("gpt-5.6-luna", "openai-codex")
    assert _directory()[NEKO]["locally_changed"] is False


def test_a_users_own_record_under_a_shipped_id_is_left_alone(monkeypatch, tmp_path):
    mine = AgentPersona(NEKO, "My Neko", "alice_supervisor", None, None, None, skills=["mine"])
    AgentStore().save(mine)

    _ship_update(monkeypatch, tmp_path, soul="Neko, updated.")

    assert AgentStore().get(NEKO) == mine
    assert sync_shipped_agents() == []
    assert "origin" not in _raw(NEKO) or _raw(NEKO)["origin"] is None
