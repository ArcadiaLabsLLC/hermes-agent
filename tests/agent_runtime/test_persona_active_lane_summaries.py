"""Which persona instances ship as ACTIVE agent summaries.

``active_persona_instance_agent_summaries`` (the status and snapshot lanes'
roster of working agents) keeps an instance when its worker state is one of the
active-lane states, or when it still carries a task/goal/assignment/run pointer.
Until this file no test reached that membership test at all, so dropping a state
from the vocabulary stayed green (god-file program §3.1b, ruling Q6: the control
lands before the vocabulary becomes a table).

Each case is a positive control over the same instance with one variable
changed: the state. An idle, pointer-free twin is the negative arm, so a
membership check that let every instance through reds here too.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    active_persona_instance_agent_summaries,
)
from agent_runtime.states import WorkerSessionState

ACTIVE_LANE = (
    WorkerSessionState.ASSIGNED,
    WorkerSessionState.RUNNING,
    WorkerSessionState.WAITING_ON_TOOL,
    WorkerSessionState.WAITING_ON_PROOF,
    WorkerSessionState.SELF_HEALING,
    WorkerSessionState.WAITING_ON_HUMAN,
    WorkerSessionState.POSSESSED,
)
IDLE_LANE = (
    WorkerSessionState.IDLE,
    WorkerSessionState.COMPLETED,
    WorkerSessionState.BLOCKED,
    WorkerSessionState.CLOSED,
)


def _idle_instance():
    placed = PersonaInstanceStore().add_instance(
        persona_id="qa",
        placement_id="agent_a1b2c3d4_agent_2",
        display_name="QA Agent (2)",
    )
    return replace(
        placed,
        state=WorkerSessionState.IDLE,
        current_task_id=None,
        goal_id=None,
        current_assignment_id=None,
        active_run_id=None,
    )


@pytest.mark.parametrize("state", ACTIVE_LANE, ids=lambda s: s.value)
def test_an_instance_in_an_active_lane_state_ships_as_an_active_agent(isolate_agent_runtime_root, state):
    idle = _idle_instance()
    assert active_persona_instance_agent_summaries([idle]) == []  # the negative twin

    rows = active_persona_instance_agent_summaries([replace(idle, state=state)])

    assert [row["persona_instance_id"] for row in rows] == [idle.id]
    assert rows[0]["runtime_agent_kind"] == "persona_instance"


@pytest.mark.parametrize("state", ACTIVE_LANE, ids=lambda s: s.value)
def test_a_plain_string_state_is_read_the_same_as_the_enum(isolate_agent_runtime_root, state):
    idle = _idle_instance()

    rows = active_persona_instance_agent_summaries([replace(idle, state=state.value)])

    assert [row["persona_instance_id"] for row in rows] == [idle.id]


@pytest.mark.parametrize("state", IDLE_LANE, ids=lambda s: s.value)
def test_a_settled_instance_with_no_work_pointer_is_not_active(isolate_agent_runtime_root, state):
    idle = _idle_instance()

    assert active_persona_instance_agent_summaries([replace(idle, state=state)]) == []
    # ...until it carries a work pointer: the pointer arm is independent of state.
    rows = active_persona_instance_agent_summaries([replace(idle, state=state, current_task_id="task_1")])
    assert [row["persona_instance_id"] for row in rows] == [idle.id]
