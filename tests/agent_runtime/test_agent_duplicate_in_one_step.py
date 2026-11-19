"""Duplicating a shipped agent under a new name takes one step and keeps its memory.

Row ``RT-BUNDLED-AGENT-DUPLICATE-IN-ONE-STEP`` (owner 2026-11-19): a copy is a full
duplicate, memory included; its name is one no other agent has (``agent_name_taken``
otherwise, never a suffix); it records ``based_on``; it can take an instance with
its chats; and a definition write to a shipped agent still succeeds, flagged
``locally_changed``. Driven through ``runtime.agent.duplicate``, the door the app uses.
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.bundled_agents import catalog
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.fresh_install_seed import seed_fresh_install_persona
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.mission_chat_prompts import _mission_chat_soul_overlay
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore
from hermes_cli.profiles import get_profile_dir

NEKO = "neko_supervisor"


def _rpc(method: str, **params) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "dup", "method": method, "params": params})


def _duplicate(**params) -> dict:
    return _rpc("runtime.agent.duplicate", **params)


def _snapshot() -> tuple:
    profiles = get_profile_dir("neko").parent
    return (
        sorted(p.name for p in paths.agents_dir().glob("*.json")),
        sorted(p.name for p in profiles.iterdir()),
    )


@pytest.fixture
def shipped_neko():
    seed_fresh_install_persona(load_agent_runtime_config())
    home = get_profile_dir("neko")
    (home / "memories").mkdir(exist_ok=True)
    (home / "memories" / "MEMORY.md").write_text("The owner likes short read-outs.", encoding="utf-8")
    (home / "auth.json").write_text('{"token": "neko-sign-in"}', encoding="utf-8")
    return home


def test_one_call_makes_a_full_named_copy_with_memory_and_no_sign_in(shipped_neko):
    reply = _duplicate(persona_id=NEKO, name="Neko Mission Lead Beta")["result"]

    copy = AgentStore().get(reply["persona_id"])
    assert copy.display_name == reply["agent_name"] == "Neko Mission Lead Beta"
    assert copy.based_on == reply["based_on"] == {"id": NEKO, "name": "Neko Mission Lead"}
    assert copy.origin is None
    assert copy.skills == catalog.shipped_agent(NEKO).definition["skills"]
    home = get_profile_dir(copy.hermes_profile)
    assert home != shipped_neko
    assert (home / "memories" / "MEMORY.md").read_text(encoding="utf-8") == "The owner likes short read-outs."
    assert not (home / "auth.json").exists()
    assert _mission_chat_soul_overlay(copy) == catalog.shipped_agent(NEKO).soul_text().strip()
    ensure_install_identity(paths.store_root())
    rows = _rpc("runtime.agent.directory")["result"]["agents"]
    row = next(r for r in rows if r["persona_id"] == copy.id)
    assert row["based_on"] == {"id": NEKO, "name": "Neko Mission Lead"} and "origin" not in row


@pytest.mark.parametrize("name", ["neko mission lead", "  NEKO   Mission Lead ", "Base Agent"])
def test_a_name_another_agent_has_is_refused_and_nothing_is_written(shipped_neko, name):
    before = _snapshot()

    reply = _duplicate(persona_id=NEKO, name=name)

    assert reply["error"]["data"]["reason"] == "agent_name_taken"
    assert _snapshot() == before


def test_a_users_own_agent_name_is_taken_too(shipped_neko):
    first = _duplicate(persona_id=NEKO, name="Beta")["result"]
    before = _snapshot()

    assert _duplicate(persona_id=first["persona_id"], name="beta")["error"]["data"]["reason"] == "agent_name_taken"
    assert _snapshot() == before


def test_an_instance_moves_to_the_copy_and_keeps_its_chats(shipped_neko):
    store = PersonaInstanceStore()
    seat = store.add_instance(
        persona_id=NEKO, placement_id="neko_testv4_agent_1", display_name="Neko Mission Lead", workspace_id="ws_testv4",
    )
    before = store.get(seat.id)

    reply = _duplicate(persona_id=NEKO, name="Neko Mission Lead Beta", instance_id=seat.id)["result"]

    after = store.get(seat.id)
    assert reply["instance_id"] == seat.id
    assert after.persona_id == reply["persona_id"]
    assert after.profile_id == AgentStore().get(reply["persona_id"]).hermes_profile
    assert (after.default_chat_session_id, after.chat_head_home, after.workspace_id) == (
        before.default_chat_session_id, before.chat_head_home, before.workspace_id,
    )


def test_the_agents_own_channel_stays_with_it(shipped_neko):
    canonical = PersonaInstanceStore().ensure_for_persona(AgentStore().get(NEKO))
    before = _snapshot()

    reply = _duplicate(persona_id=NEKO, name="Neko Mission Lead Beta", instance_id=canonical.id)

    assert reply["error"]["data"]["reason"] == "canonical_instance_stays"
    assert _snapshot() == before
    assert PersonaInstanceStore().get(canonical.id).persona_id == NEKO


def test_a_definition_write_to_a_shipped_agent_succeeds_and_is_flagged(shipped_neko, capsys):
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", "persona", "set-skills", NEKO, "--skill", "my-skill", "--json"])
    assert args.func(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "applied"

    assert AgentStore().get(NEKO).skills == ["my-skill"]
    ensure_install_identity(paths.store_root())
    rows = _rpc("runtime.agent.directory")["result"]["agents"]
    assert next(r for r in rows if r["persona_id"] == NEKO and r["canonical"])["locally_changed"] is True
