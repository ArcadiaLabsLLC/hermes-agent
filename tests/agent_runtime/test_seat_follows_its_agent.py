"""A Beta seat's office desk and chats move with it to Neko Mission Lead Beta.

Launcher rows ``MC-OFFICE-SEATS-STILL-NAME-THE-SHIPPED-NEKO-AFTER-THE-SORT`` and
``MC-SHIPPED-NEKO-CHAT-HISTORY-LISTS-THE-BETA-COPYS-CHATS`` (seen 2026-11-20 on the
owner's install): after ``persona sort-shipped`` moved the changed Neko's two office
seats to the Beta copy, the seats' office actors still named ``neko_supervisor`` and
"Neko Mission Lead", and their chats kept the ``neko_supervisor`` stamp, so the
shipped Neko's Chat History listed them. The fixture is the owner's shape: a changed
Neko with a personal channel and two office seats, each seat with a desk and a
stamped chat. Driven through ``hermes harness persona sort-shipped`` and the history
list the app reads (``runtime.operator.conversation.list``).
"""

from __future__ import annotations

import argparse
import json
from contextlib import closing

import pytest

from agent_runtime import paths
from agent_runtime.chat_session_scope import resolve_process_chat_scope
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.instance_history import list_instance_conversations
from agent_runtime.models import AgentPersona
from agent_runtime.office_store import OfficeStore
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import ensure_persona_chat_session
from agent_runtime.store import AgentStore
from hermes_cli.profiles import get_profile_dir
from tests.agent_runtime.office_seed import seed_workspace_record

NEKO = "neko_supervisor"
BETA = "neko_mission_lead_beta"


def _profile(name: str, soul: str) -> None:
    home = get_profile_dir(name)
    (home / "memories").mkdir(parents=True)
    (home / "SOUL.md").write_text(soul, encoding="utf-8")
    (home / "config.yaml").write_text("{}\n", encoding="utf-8")


def _chat(session_id: str, persona_id: str) -> None:
    from hermes_state import SessionDB

    with closing(SessionDB(db_path=resolve_process_chat_scope().db_path)) as db:
        ensure_persona_chat_session(session_db=db, session_id=session_id, persona_id=persona_id,
                                    title="Neko Mission Lead chat", required=True)
        db.append_message(session_id=session_id, role="user", content="hello")


def _desk(workspace_id: str, seat) -> None:
    seed_workspace_record(workspace_id)
    OfficeStore().ensure_surface(workspace_id, created_by="seed")
    OfficeStore().upsert_actor(workspace_id, {
        "persona_id": NEKO, "persona_instance_id": seat.id,
        "items": [{"item_id": seat.id, "kind": "agent", "position": [3.0, 3.0], "folder": "Agents",
                   "display_name": "Neko Mission Lead"}],
    })


@pytest.fixture
def owner_shaped_root():
    _profile("base", "")
    _profile("neko", "You are Neko, the owner's own long-tuned SOUL.")
    store = AgentStore()
    store.save(AgentPersona("base", "Base Agent", "profile", None, None, "codex_responses", hermes_profile="base",
                            skills=["harness-runtime-model", "harness-charsheet-authoring"]))
    store.save(AgentPersona(NEKO, "Neko Mission Lead", "alice_supervisor", "gpt-5.6-luna", "openai-codex",
                            "codex_responses", hermes_profile="neko", skills=["systematic-debugging"],
                            soul_overlay_path="SOUL.md"))
    instances = PersonaInstanceStore()
    personal = instances.ensure_for_persona(store.get(NEKO))
    seats = {ws: instances.add_instance(persona_id=NEKO, placement_id=f"neko_{ws}_agent_1", workspace_id=ws)
             for ws in ("ws_testv4", "ws_default")}
    chats = {"personal": f"persona_chat_{personal.id}_00000000000a"}
    _chat(chats["personal"], NEKO)
    for n, (ws, seat) in enumerate(seats.items()):
        _desk(ws, seat)
        chats[ws] = f"persona_chat_{seat.id}_00000000000{n + 1:x}"
        _chat(chats[ws], NEKO)
    return {"personal": personal, "seats": seats, "chats": chats}


def _sort(capsys, *flags: str) -> dict:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", "persona", "sort-shipped", *flags, "--json"])
    capsys.readouterr()
    assert args.func(args) == 0
    return json.loads(capsys.readouterr().out)


def _history(persona_id: str) -> set[str]:
    install = ensure_install_identity(paths.store_root()).install_id
    page = list_instance_conversations({"install_id": install, "all_accounts": True, "limit": 50,
                                        "persona_id": persona_id})
    return {row["session_id"] for row in page["conversations"]}


def test_the_sort_moves_each_seats_desk_to_the_beta_copy(owner_shaped_root, capsys):
    out = _sort(capsys)

    beta = next(entry for entry in out["plan"] if entry["persona_id"] == NEKO)["copy_id"]
    assert beta == BETA
    for ws, seat in owner_shaped_root["seats"].items():
        actor = OfficeStore().get_actor(ws, seat.id)
        assert actor.persona_id == BETA
        assert [(item.persona_id, item.display_name) for item in actor.items] == [(BETA, "Neko Mission Lead Beta")]


def test_the_shipped_nekos_history_lists_only_her_own_chats_and_beta_lists_the_seats(owner_shaped_root, capsys):
    _sort(capsys)

    chats, seats = owner_shaped_root["chats"], owner_shaped_root["seats"].values()
    seat_chats = {row for row in _history(BETA) if any(row.startswith(f"persona_chat_{seat.id}_") for seat in seats)}
    assert _history(NEKO) == {chats["personal"]}
    assert _history(BETA) == seat_chats >= {chats["ws_testv4"], chats["ws_default"]}


def test_an_install_sorted_before_seats_followed_is_repaired_by_a_second_run(owner_shaped_root, capsys, monkeypatch):
    from agent_runtime import agent_duplicate
    from hermes_cli.harness_parts.persona import shipped_commands

    # The sort as it ran on the owner's install: the seat record moved, nothing else.
    monkeypatch.setattr(agent_duplicate, "follow_seat", lambda instance_id: None)
    monkeypatch.setattr(shipped_commands, "stray_seats", lambda: [])
    _sort(capsys)
    monkeypatch.undo()
    assert _history(NEKO) >= set(owner_shaped_root["chats"].values())

    seats = owner_shaped_root["seats"]
    dry = _sort(capsys, "--dry-run")
    assert {entry["persona_id"]: entry["action"] for entry in dry["plan"]}[NEKO] == "none"
    assert dry["seats"] == [
        {"instance_id": seats[ws].id, "persona_id": BETA, "office_actors": [f"{ws}/{seats[ws].id}"], "chats": 2}  # its default chat and ours
        for ws in sorted(seats, key=lambda ws: seats[ws].id)
    ]
    assert OfficeStore().get_actor("ws_default", seats["ws_default"].id).persona_id == NEKO  # dry run wrote nothing

    applied = _sort(capsys)
    assert applied["seats"] == dry["seats"]
    assert _history(NEKO) == {owner_shaped_root["chats"]["personal"]}
    assert OfficeStore().get_actor("ws_default", seats["ws_default"].id).persona_id == BETA
    assert _sort(capsys, "--dry-run")["seats"] == []


def test_copying_an_agent_onto_one_seat_moves_that_seats_desk_and_chats(owner_shaped_root):
    from agent_runtime.agent_duplicate import duplicate_agent

    seat = owner_shaped_root["seats"]["ws_testv4"]
    copy = duplicate_agent(NEKO, "Neko Two", instance_id=seat.id).persona

    actor = OfficeStore().get_actor("ws_testv4", seat.id)
    assert (actor.persona_id, actor.items[0].display_name) == (copy.id, "Neko Two")
    assert owner_shaped_root["chats"]["ws_testv4"] in _history(copy.id)
    assert owner_shaped_root["chats"]["ws_testv4"] not in _history(NEKO)
    assert OfficeStore().get_actor("ws_default", owner_shaped_root["seats"]["ws_default"].id).persona_id == NEKO


def test_a_refused_desk_is_named_and_the_seats_chats_still_move(owner_shaped_root, monkeypatch):
    from agent_runtime import seat_follow
    from agent_runtime.agent_duplicate import duplicate_agent
    from agent_runtime.errors import WorkspaceUnresolved

    def refused(office, actor, instance):
        raise WorkspaceUnresolved("held", safe_details={"workspace_id": actor.workspace_id})

    monkeypatch.setattr(seat_follow, "_follow_actor", refused)
    seat = owner_shaped_root["seats"]["ws_testv4"]
    copy = duplicate_agent(NEKO, "Neko Two", instance_id=seat.id).persona
    monkeypatch.undo()

    assert owner_shaped_root["chats"]["ws_testv4"] in _history(copy.id)
    drift = seat_follow.seat_drift(PersonaInstanceStore().get(seat.id))
    assert drift.office_actors == (f"ws_testv4/{seat.id}",) and drift.chats == ()
