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

    answer = _add(lead, agent="qa")

    assert answer["stopped"]["budget_reason"] == "spawn_scope_exhausted"
    assert _qa_seats() == []


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
