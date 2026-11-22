"""The directory says when each instance was last used and whether it sits in a running group chat.

Rows RT-AGENT-INSTANCE-SAYS-WHEN-IT-WAS-LAST-USED and RT-AGENT-INSTANCE-SAYS-WHEN-IT-SITS-IN-A-RUNNING-GROUP-CHAT:
Eternia reuses an idle instance (newest use first) before it places a new one, and "busy" includes a seat in a
running room between that member's turns. Both facts are derived from their one owner (the turn journal, the
discussion run store), so each test writes the owner's record and reads ``runtime.agent.directory``.
"""
from contextlib import closing
from types import SimpleNamespace

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.discussions import service as discussion_service
from agent_runtime.discussions.definition_store import DefinitionStore
from agent_runtime.discussions.room_definition import RoomSpec
from agent_runtime.discussions.run_store import RunStore
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.mission_chat_turns import mission_chat_turn_record, persist_mission_chat_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from tests.agent_runtime.test_native_discussion_room import spec
from tests.agent_runtime.test_discussion_runtime import command, engine, settled, wait_until  # noqa: F401
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent, PERSONA  # noqa: F401

pytestmark = pytest.mark.timeout(90)


def directory():
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "d", "method": "runtime.agent.directory", "params": {}})
    return {row["instance_id"]: row for row in reply["result"]["agents"]}


def turn(instance_id, key):
    session = "persona_chat_session_" + instance_id
    persist_mission_chat_turn(session_id=session, client_message_id=key, turn_id=key, elements=[],
                              state="running", write_ahead=True, metadata={"persona_instance_id": instance_id})
    return mission_chat_turn_record(session_id=session, client_message_id=key)["started_at"]


def instances():
    """The fixture's placement and a second instance of the same agent (the directory mints no hidden copy)."""
    from tests.agent_runtime.persona_instance_mint import mint_placed_instance

    placed = next(row.id for row in PersonaInstanceStore().list_all())
    return placed, mint_placed_instance(PERSONA, placement="second").id


def test_last_used_is_the_newest_turn_start_on_that_instance(placed_agent):
    """Mutation (run, red): keep the first stamp seen (``instance_id not in newest`` for the ``>`` compare)
    -> the second-turn assert reds."""
    ensure_install_identity(paths.store_root())
    placed, canonical = instances()
    assert {row["last_used_at"] for row in directory().values()} == {None}
    first = turn(placed, "cm-1")
    assert directory()[placed]["last_used_at"] == first
    assert directory()[canonical]["last_used_at"] is None
    second = turn(placed, "cm-2")
    assert second > first
    assert directory()[placed]["last_used_at"] == second
    turn(canonical, "cm-3")
    assert directory()[placed]["last_used_at"] == second


def test_seated_instances_follow_a_room_from_open_to_end(engine):
    """Mutations (run, red): drop the run-phase rule from ``seated_instances`` (``WHERE 1=1``) -> the after-end
    assert reds; void the ``install_id`` match (``OR 1``) -> the other-install assert reds."""
    service, _context = engine
    room = service.begin_room("ws", spec(), key="room", topic="Review", actor_id="operator")
    wait_until(lambda: settled(service, room))
    assert service.runs.get(room["run_id"])["phase"] == "open"
    assert service.runs.seated_instances("install_A") == {"personainst_0", "personainst_1"}
    assert service.runs.seated_instances("install_B") == frozenset()
    command(service, room, "end")
    wait_until(lambda: service.view("ws", room["run_id"])["run"]["phase"] == "ended")
    assert service.runs.seated_instances("install_A") == frozenset()


def test_directory_says_seated_only_while_the_room_runs(placed_agent, tmp_path, monkeypatch):
    """Mutations (run, red): ``False`` instead of ``None`` with no bound service -> the first assert reds; every
    instance seated -> the canonical assert reds; the RPC door passes no ``seated`` -> the seated assert reds;
    drop the run-phase rule -> the after-end assert reds."""
    install_id = ensure_install_identity(paths.store_root()).install_id
    placed, canonical = instances()
    assert {row["in_running_group_chat"] for row in directory().values()} == {None}
    runs = RunStore(DefinitionStore(tmp_path / "state.db"))
    monkeypatch.setattr(discussion_service, "_owner", SimpleNamespace(runs=runs))
    assert {row["in_running_group_chat"] for row in directory().values()} == {False}
    other = "personainst_elsewhere"
    room = RoomSpec.parse({"name": "Review", "settings": spec().settings.to_dict(), "participants": [
        {"install_id": install_id, "instance_id": placed}, {"install_id": install_id, "instance_id": other}]})
    run = runs.begin_room("ws", room, key="room", topic="Review", actor_id="operator", resolve=lambda ref, _ws: {
        "install_id": ref.install_id, "instance_id": ref.instance_id, "persona_id": PERSONA,
        "profile": "default", "display_name": ref.instance_id})
    runs.activate(run["run_id"])
    entries = directory()
    assert entries[placed]["in_running_group_chat"] is True
    assert entries[canonical]["in_running_group_chat"] is False
    with closing(runs.connect()) as conn, conn:
        conn.execute("UPDATE mc_discussion_runs SET phase='ended' WHERE run_id=?", (run["run_id"],))
    assert directory()[placed]["in_running_group_chat"] is False
