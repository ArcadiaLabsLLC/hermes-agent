"""RT-RUNNING-WORK-ROWS-SAY-WHO-ASKED-WHERE-AND-WHICH-STEPS (review w1118a.55 D12).

Running now's open card shows who asked an agent for the work, its workspace and folder,
its steps, and a build's full log. The rows carried none of it. Pinned through the
running-work collector (``build_running_work``), the projection the card reads:

* a running agent turn's row: ``asked_by`` (the relaying agent, else the operator), the
  instance's ``workspace_id`` / ``workspace_name``, ``cwd`` (its run's folder), and
  ``plan.items`` — each step with its state and ``seconds: None`` (no time is kept per step);
* an agent request's row: ``asked_by`` (the sending agent), the target's workspace;
* an announced build's row: ``log_path`` — only a log under its project root.

Killing mutations (reds recorded in the commit body):
* ``enrich_live`` drops the ``asked_by`` / ``cwd`` lines -> the live turn test red;
* ``enrich_live`` keeps the summary without ``items`` -> the live turn test red;
* ``DispatchLane.running_row`` drops ``extra=self.asked_where(record)`` -> the request test red;
* ``readable_log_path`` drops its under-the-root check -> the build log test red.
"""

from __future__ import annotations

import time

import pytest

from agent_runtime import live_turns
from agent_runtime.builds.registry import readable_log_path
from agent_runtime.builds.vocabulary import SOURCE_ANNOUNCED
from agent_runtime.dispatch_store import mint_dispatch_id, record_dispatch, set_dispatch_owner
from agent_runtime.relay_policy import build_relay_sender_marker
from agent_runtime.running_work import KIND_CHAT_TURN, build_running_work, lanes_chat
from agent_runtime.running_work.build_rows import BuildFacts, build_extra
from agent_runtime.running_work.lanes_chat import DispatchLane
from agent_runtime.running_work.row_context import RowContext
from tests.agent_runtime.test_running_chat_turn_plan_progress import (  # journal is a fixture
    INSTANCE, SESSION, TURN, _Agent, journal,
)

SENDER_ROOT = "persona_chat_personainst_lead_aaaaaaaaaaaa"


@pytest.fixture
def named(monkeypatch):
    """Instances resolve to a name and a workspace without a seeded roster."""
    monkeypatch.setattr(RowContext, "_name", lambda self, instance: f"Name of {instance}" if instance else "")
    monkeypatch.setattr(RowContext, "_read_workspace", lambda self, handle: (f"ws-{handle}", "Launcher"))


def test_a_live_turn_says_who_asked_its_workspace_folder_and_steps(journal, named):
    agent = _Agent([
        {"id": "1", "content": "Read the failing test", "status": "completed"},
        {"id": "2", "content": "Fix the parser", "status": "in_progress"},
    ])
    with live_turns.live_turn(
        turn_id=TURN, session_id=SESSION, persona_instance_id=INSTANCE, agent=agent,
        workdir="/work/launcher", asked_by_marker=build_relay_sender_marker("lead", "personainst_lead"),
    ):
        [row] = [row for row in build_running_work()["rows"] if row["kind"] == KIND_CHAT_TURN]

    assert row["asked_by"] == {
        "kind": "agent", "persona_id": "lead", "persona_instance_id": "personainst_lead",
        "name": "Name of personainst_lead",
    }
    assert (row["workspace_id"], row["workspace_name"]) == (f"ws-{INSTANCE}", "Launcher")
    assert row["cwd"] == "/work/launcher"
    assert row["plan"]["items"] == [
        {"id": "1", "content": "Read the failing test", "status": "completed", "seconds": None},
        {"id": "2", "content": "Fix the parser", "status": "in_progress", "seconds": None},
    ]


def test_a_turn_with_no_relay_marker_was_asked_by_the_operator(journal, named):
    with live_turns.live_turn(turn_id=TURN, session_id=SESSION, persona_instance_id=INSTANCE, agent=_Agent()):
        [row] = [row for row in build_running_work()["rows"] if row["kind"] == KIND_CHAT_TURN]
    assert row["asked_by"] == {"kind": "operator"}
    assert row["cwd"] is None


def test_a_turn_read_outside_its_process_says_it_does_not_know_who_asked(journal, named):
    [row] = [row for row in build_running_work()["rows"] if row["kind"] == KIND_CHAT_TURN]
    assert (row["asked_by"], row["cwd"]) == (None, None)
    assert row["workspace_id"] == f"ws-{INSTANCE}"  # the instance's, read without the live turn


def test_an_agent_request_says_which_agent_asked_and_the_targets_workspace(tmp_path, monkeypatch, named):
    home = tmp_path / "bg-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setattr(lanes_chat, "_owner_of", lambda session, memo=None: ("lead", "personainst_lead"))
    dispatch_id = mint_dispatch_id()
    record_dispatch(
        dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, sender_persona_id="lead",
        target_persona="dev", target_instance_id="personainst_dev", ask="run the suite",
    )
    set_dispatch_owner(dispatch_id, owner_pid=424242, owner_started_at=None)

    rows, _source = DispatchLane(now=time.time(), accountant=None).collect()

    [row] = [row for row in rows if row["work_id"].endswith(dispatch_id)]
    assert row["asked_by"] == {
        "kind": "agent", "persona_id": "lead", "persona_instance_id": "personainst_lead",
        "name": "Name of personainst_lead",
    }
    assert (row["workspace_id"], row["workspace_name"], row["cwd"]) == ("ws-personainst_dev", "Launcher", None)


def test_a_builds_full_log_is_named_only_under_its_project(tmp_path):
    root = tmp_path / "project"
    (root / "build").mkdir(parents=True)
    inside = root / "build" / "flutter.log"
    outside = tmp_path / "elsewhere.log"

    assert readable_log_path({"project_root": str(root), "log_path": str(inside)}) == str(inside)
    assert readable_log_path({"project_root": str(root), "log_path": str(outside)}) == ""
    assert readable_log_path({"project_root": str(root), "log_path": "build/flutter.log"}) == ""

    facts = BuildFacts(source=SOURCE_ANNOUNCED, stable_id="job-1", project_root=str(root), log_path=str(inside))
    assert build_extra(facts, None)["log_path"] == str(inside)
