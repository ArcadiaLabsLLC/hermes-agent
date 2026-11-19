"""The owner's changed Neko becomes "Neko Mission Lead Beta", with the shipped Neko beside it.

Row ``RT-BUNDLED-AGENTS-EXISTING-RECORDS-SORTED`` (owner 2026-11-19). The fixture is
shaped like the owner's namespace, seen read-only 2026-11-19: a Base record equal
to the shipped one (plus a model-mode setting) with an empty profile SOUL, and a
Neko whose skills, model and SOUL are his own, with a personal channel and two
office placements. Driven through ``hermes harness persona sort-shipped``.
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime import paths
from agent_runtime.bundled_agents import catalog
from agent_runtime.mission_chat_prompts import _mission_chat_soul_overlay
from agent_runtime.models import AgentPersona
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore
from hermes_cli.profiles import get_profile_dir

NEKO = "neko_supervisor"
OWNER_SKILLS = ["eternia-backend-tests", "eternia-hermes-agent", "harness-runtime-model", "systematic-debugging"]


def _profile(name: str, soul: str) -> None:
    home = get_profile_dir(name)
    (home / "memories").mkdir(parents=True)
    (home / "SOUL.md").write_text(soul, encoding="utf-8")
    (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    (home / "memories" / "MEMORY.md").write_text(f"{name} remembers the owner.", encoding="utf-8")
    (home / "auth.json").write_text('{"token": "sign-in"}', encoding="utf-8")


@pytest.fixture
def owner_shaped_root():
    _profile("base", "")
    _profile("neko", "You are Neko, the owner's own long-tuned SOUL.")
    store = AgentStore()
    store.save(AgentPersona(
        "base", "Base Agent", "profile", None, None, "codex_responses", hermes_profile="base",
        skills=["harness-runtime-model", "harness-charsheet-authoring"], include_profile_memory=True,
    ))
    store.save(AgentPersona(
        NEKO, "Neko Mission Lead", "alice_supervisor", "gpt-5.6-luna", "openai-codex", "codex_responses",
        hermes_profile="neko", skills=list(OWNER_SKILLS), soul_overlay_path="SOUL.md", include_profile_memory=True,
    ))
    instances = PersonaInstanceStore()
    personal = instances.ensure_for_persona(store.get(NEKO))
    seats = [
        instances.add_instance(persona_id=NEKO, placement_id=f"neko_{ws}_agent_1", workspace_id=ws)
        for ws in ("ws_testv4", "ws_default")
    ]
    base_seat = instances.ensure_for_persona(store.get("base"))
    return {"personal": personal, "seats": seats, "base_seat": base_seat}


def _sort(capsys, *flags: str) -> tuple[int, dict]:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", "persona", "sort-shipped", *flags, "--json"])
    capsys.readouterr()
    code = args.func(args)
    return code, json.loads(capsys.readouterr().out)


def _tree() -> list[tuple[str, bytes]]:
    roots = (paths.store_root(), get_profile_dir("neko").parent)
    return sorted(
        (str(p), p.read_bytes() if p.is_file() else b"")
        for root in roots for p in root.rglob("*")
        if "locks" not in p.parts and p.suffix != ".lock"
    )


def test_a_dry_run_prints_the_plan_and_writes_nothing(owner_shaped_root, capsys):
    before = _tree()

    code, out = _sort(capsys, "--dry-run")

    assert code == 0 and out["dry_run"] is True
    plan = {entry["persona_id"]: entry for entry in out["plan"]}
    assert plan["base"]["action"] == "adopt"
    neko = plan[NEKO]
    assert neko["action"] == "copy" and neko["copy_name"] == "Neko Mission Lead Beta"
    assert set(neko["differences"]) == {"skills", "soul"}
    assert neko["instances_moved"] == sorted(seat.id for seat in owner_shaped_root["seats"])
    assert neko["instances_kept"] == [owner_shaped_root["personal"].id]
    assert _tree() == before


def test_the_changed_neko_is_kept_as_beta_and_the_shipped_neko_takes_her_id(owner_shaped_root, capsys):
    code, out = _sort(capsys)

    assert code == 0
    receipt = {entry["persona_id"]: entry for entry in out["plan"]}
    store = AgentStore()
    beta = store.get(receipt[NEKO]["copy_id"])
    assert beta.display_name == "Neko Mission Lead Beta"
    assert beta.based_on == {"id": NEKO, "name": "Neko Mission Lead"}
    assert (beta.skills, beta.model) == (OWNER_SKILLS, "gpt-5.6-luna")
    assert _mission_chat_soul_overlay(beta) == "You are Neko, the owner's own long-tuned SOUL."
    beta_home = get_profile_dir(beta.hermes_profile)
    assert (beta_home / "memories" / "MEMORY.md").read_text(encoding="utf-8") == "neko remembers the owner."
    assert not (beta_home / "auth.json").exists()

    instances = PersonaInstanceStore()
    for seat in owner_shaped_root["seats"]:
        moved = instances.get(seat.id)
        assert moved.persona_id == beta.id
        assert moved.default_chat_session_id == seat.default_chat_session_id
    personal = instances.get(owner_shaped_root["personal"].id)
    assert personal.persona_id == NEKO and personal.default_chat_session_id == owner_shaped_root["personal"].default_chat_session_id

    shipped = store.get(NEKO)
    assert shipped.origin == "eternia"
    assert shipped.skills == catalog.shipped_agent(NEKO).definition["skills"]
    assert _mission_chat_soul_overlay(shipped) == catalog.shipped_agent(NEKO).soul_text().strip()
    assert (get_profile_dir("neko") / "auth.json").exists()  # her sign-in stays where it was


def test_an_unchanged_base_becomes_a_reference_and_keeps_its_settings_and_channel(owner_shaped_root, capsys):
    _sort(capsys)

    base = AgentStore().get("base")
    assert base.origin == "eternia" and base.api_mode == "codex_responses"
    assert PersonaInstanceStore().get(owner_shaped_root["base_seat"].id) == owner_shaped_root["base_seat"]


def test_a_second_run_changes_nothing(owner_shaped_root, capsys):
    _sort(capsys)
    before = _tree()

    code, out = _sort(capsys)

    assert code == 0
    assert {entry["action"] for entry in out["plan"]} == {"none"}
    assert _tree() == before


def test_a_taken_copy_name_refuses_that_record_and_writes_nothing_for_it(owner_shaped_root, capsys):
    AgentStore().save(AgentPersona("someone", "Neko Mission Lead Beta", "agent", None, None, None))
    neko_before = paths.agent_path(NEKO).read_bytes()

    code, out = _sort(capsys)

    assert code == 1
    entry = next(e for e in out["plan"] if e["persona_id"] == NEKO)
    assert entry["refused"] == "agent_name_taken" and entry["applied"] is False
    assert paths.agent_path(NEKO).read_bytes() == neko_before
