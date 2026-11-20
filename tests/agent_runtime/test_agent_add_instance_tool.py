"""``agent_add_instance`` — a lead agent staffs a workspace with instances of an agent in one call.

Row ``RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE`` (review w1118a.53 D8). Done when: instances added
through the tool read ``<agent> · 2`` and carry who asked, an idle instance is reused before a new one
is placed, and the asker's spawn budget holds. Every witness is the persona-instance store, which the
tool's answer could disagree with.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.models import AutonomyLevel
from tests.agent_runtime.test_serve_rpc_agent_create import (
    WORKSPACE,
    _instances,
    _seed_workspace,
    dev_persona,  # noqa: F401 — the fixture, re-exported for this file
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)


def _no_seats(_install_id):
    return frozenset()


@pytest.fixture
def lead(qa_persona, dev_persona):
    """A seated ``dev`` instance whose agent may spawn (autonomous), and its chat session."""

    from agent_runtime.agent_create import perform_agent_place
    from agent_runtime.store import AgentStore

    dev_persona.autonomy = AutonomyLevel.AUTONOMOUS
    AgentStore().save(dev_persona)
    _seed_workspace()
    placed = perform_agent_place({"persona_id": "dev", "workspace_id": WORKSPACE, "idempotency_key": "lead"})
    assert placed.refusal is None, placed.refusal
    return placed.result


def _add(lead_result, **args) -> dict:
    from tools.agent_chat.instances import agent_add_instance

    return json.loads(agent_add_instance(requested_by_session=lead_result["default_chat_session_id"], **args))


def _qa_seats() -> list:
    return sorted(
        (i for i in _instances().values() if i.persona_id == "qa" and i.workspace_id == WORKSPACE),
        key=lambda i: i.display_name,
    )


def test_the_tool_places_a_numbered_instance_that_names_the_asking_instance(lead, monkeypatch):
    # Mutation: stamp ``spawned_by = "operator"`` in ``AgentCreate.mint`` again (whatever asked)
    # -> the stored row's spawned_by is "operator" and the first assert reds.
    from agent_runtime.agent_create import staff

    monkeypatch.setattr(staff, "running_group_chat_seats", _no_seats)
    answer = _add(lead, agent="QA Agent")

    assert answer["ok"] is True, answer
    assert answer["requested_by"] == lead["persona_instance_id"]
    assert [row["reused"] for row in answer["instances"]] == [False]
    (seat,) = _qa_seats()
    assert seat.spawned_by == lead["persona_instance_id"]
    assert seat.workspace_id == WORKSPACE
    assert answer["instances"][0]["persona_instance_id"] == seat.id


def test_an_idle_instance_is_reused_before_a_new_one_is_placed(lead, monkeypatch):
    # Mutation: skip ``idle_instances`` in ``staff_agent_instances`` -> a second seat is placed
    # and the store holds two qa seats.
    from agent_runtime.agent_create import perform_agent_place, staff

    monkeypatch.setattr(staff, "running_group_chat_seats", _no_seats)
    first = perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "seat-1"})
    assert first.refusal is None

    answer = _add(lead, agent="qa")

    assert answer["instances"][0]["persona_instance_id"] == first.result["persona_instance_id"]
    assert answer["instances"][0]["reused"] is True
    assert len(_qa_seats()) == 1


def test_a_busy_instance_is_never_reused(lead, monkeypatch):
    # Mutation: drop the busy test in ``idle_instances`` -> the busy seat is handed back as
    # reused and no second seat is placed.
    from agent_runtime.agent_create import perform_agent_place, staff

    first = perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "seat-1"})
    busy = first.result["persona_instance_id"]
    monkeypatch.setattr(staff, "running_group_chat_seats", lambda _install: frozenset({busy}))

    answer = _add(lead, agent="qa")

    assert [row["reused"] for row in answer["instances"]] == [False]
    assert answer["instances"][0]["persona_instance_id"] != busy
    assert {seat.display_name for seat in _qa_seats()} == {"QA Agent", "QA Agent · 2"}


def test_the_spawn_budget_stops_the_rest_and_says_to_ask_the_operator(lead, monkeypatch):
    # Mutation: skip ``_spawn_review`` in the placing loop -> both seats are placed and
    # ``stopped`` is absent.
    from agent_runtime.agent_create import staff

    monkeypatch.setattr(staff, "running_group_chat_seats", _no_seats)
    # An autonomous agent's default budget is one spawn (``scope_for_persona``: max(1, 0)).
    answer = _add(lead, agent="qa", count=2)

    assert answer["ok"] is False
    assert answer["placed"] == 1
    assert answer["stopped"]["reason"] == "needs_operator_confirm"
    assert len(_qa_seats()) == 1


def test_an_agent_that_only_proposes_places_nothing(lead, dev_persona, monkeypatch):
    # Mutation: answer ``ok`` from ``_spawn_review`` -> a seat is placed for a propose-only lead.
    from agent_runtime.agent_create import staff
    from agent_runtime.store import AgentStore

    monkeypatch.setattr(staff, "running_group_chat_seats", _no_seats)
    dev_persona.autonomy = AutonomyLevel.PROPOSE_ONLY
    AgentStore().save(dev_persona)

    answer = _add(lead, agent="qa", count=2)

    assert answer["stopped"]["budget_reason"] == "spawn_scope_exhausted"
    assert _qa_seats() == []


def test_a_shipped_leads_refusal_names_the_setting_and_what_was_left(lead, dev_persona, monkeypatch):
    # RT-A-SHIPPED-LEAD-AGENT-CANNOT-ADD-ANY-INSTANCE-WITHOUT-ASKING-YOU, RULED (b): the zero budget
    # stays; the refusal says which settings grant one and how many seats are still wanted.
    # Mutation: answer the old fixed sentence from ``staff_agent_instances`` -> no ``settings`` or
    # ``still_wanted`` and the message names neither setting; the asserts red.
    from agent_runtime.agent_create import perform_agent_place, staff
    from agent_runtime.store import AgentStore

    monkeypatch.setattr(staff, "running_group_chat_seats", _no_seats)
    dev_persona.autonomy = AutonomyLevel.PROPOSE_ONLY
    AgentStore().save(dev_persona)
    idle = perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "seat-1"})
    assert idle.refusal is None

    stopped = _add(lead, agent="qa", count=3)["stopped"]

    assert stopped["still_wanted"] == 2  # one idle seat reused, two more wanted
    assert stopped["settings"] == {"autonomy": "propose_only", "max_spawns": 0, "spawns_used": 0}
    assert "autonomy is propose_only" in stopped["message"]
    assert "agent_runtime.coordinator_permissions.max_spawns" in stopped["message"]
    assert "the other 2" in stopped["message"]


def test_an_autonomous_leads_refusal_names_its_budget(lead, monkeypatch):
    from agent_runtime.agent_create import staff

    monkeypatch.setattr(staff, "running_group_chat_seats", _no_seats)

    stopped = _add(lead, agent="qa", count=2)["stopped"]

    # ``scope_for_persona``: an autonomous agent's budget is max(1, the install's max_spawns=0).
    assert stopped["settings"] == {"autonomy": "autonomous", "max_spawns": 1, "spawns_used": 1}
    assert "Your spawn budget is 1 and you have used 1" in stopped["message"]
    assert stopped["still_wanted"] == 1


def test_a_budget_of_three_places_three(lead, monkeypatch):
    # Seen in code 2026-11-20 (w1118a-hrt2): each loop turn counted the seats this call placed twice
    # (the store's ``spawned_by`` count AND the call's own), so a budget of 3 stopped after 2.
    # Mutation: add the call's placed count to ``spawns_used`` again -> two seats and a ``stopped``.
    from agent_runtime import config as runtime_config
    from agent_runtime.agent_create import staff
    from agent_runtime.runtime_config import CoordinatorPermissionConfig

    monkeypatch.setattr(staff, "running_group_chat_seats", _no_seats)
    loaded = runtime_config.load_agent_runtime_config()
    loaded.coordinator_permissions = CoordinatorPermissionConfig(max_spawns=3)
    monkeypatch.setattr(runtime_config, "load_agent_runtime_config", lambda *a, **k: loaded)

    answer = _add(lead, agent="qa", count=3)

    assert "stopped" not in answer, answer.get("stopped")
    assert answer["placed"] == 3
    assert len(_qa_seats()) == 3


def test_an_unknown_agent_or_a_bad_count_is_refused_before_any_write(lead):
    before = set(_instances())

    assert _add(lead, agent="nobody")["reason"] == "agent_not_found"
    assert _add(lead, agent="qa", count=9)["reason"] == "count_invalid"
    assert set(_instances()) == before


def test_a_read_only_chat_may_not_add_instances():
    # Mutation: drop ``agent_add_instance`` from ``tool_permissions.READ_ONLY_BLOCKS`` -> a chat the
    # operator held read-only can still seat agents on the level.
    from agent_runtime.tool_permissions import PERMISSION_MODE_READ_ONLY, extra_blocked_tools_for_permission_mode

    assert "agent_add_instance" in extra_blocked_tools_for_permission_mode(PERMISSION_MODE_READ_ONLY)


def _idle_verb(params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "idle", "method": "runtime.agent.idle_instances", "params": params}
    )


def test_the_verb_answers_the_tools_order(lead, monkeypatch):
    # Row RT-ETERNIA-ASKS-THE-RUNTIME-WHICH-IDLE-INSTANCE-A-NEW-CHAT-REUSES: Eternia reads the order
    # the tool reuses in, from the one owner. Mutation: answer ``idle_instances(...)[::-1]`` in
    # ``_runtime_agent_idle_instances`` -> the verb names the older seat first and the first assert reds.
    from agent_runtime import mission_chat_turns
    from agent_runtime.agent_create import perform_agent_place, staff

    seats = [
        perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": f"seat-{n}"})
        .result["persona_instance_id"]
        for n in (1, 2, 3)
    ]
    older, newer, busy = seats
    monkeypatch.setattr(
        mission_chat_turns,
        "last_turn_started_by_instance",
        lambda: {older: "2026-11-20T01:00:00.000000Z", newer: "2026-11-20T02:00:00.000000Z"},
    )
    monkeypatch.setattr(staff, "running_group_chat_seats", lambda _install: frozenset({busy}))

    reply = _idle_verb({"persona_id": "qa", "workspace_id": WORKSPACE})
    named = [row["persona_instance_id"] for row in reply["result"]["instances"]]
    tool = _add(lead, agent="qa", count=2)

    assert named == [newer, older]
    assert named == [row["persona_instance_id"] for row in tool["instances"] if row["reused"]]
    assert reply["result"]["workspace_id"] == WORKSPACE


def test_the_verb_refuses_a_call_that_names_no_agent_or_workspace():
    for params in ({}, {"persona_id": "qa"}, {"persona_id": " ", "workspace_id": WORKSPACE},
                   {"persona_id": "qa", "workspace_id": WORKSPACE, "extra": 1}):
        reply = _idle_verb(params)
        assert reply["error"]["data"]["reason"] == "invalid_params", params
