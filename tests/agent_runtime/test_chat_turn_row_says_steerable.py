"""``RT-CHAT-TURN-ROW-SAYS-WHETHER-IT-TAKES-A-STEER``: the running ``chat_turn`` row says ``steerable``.

Since 7df8385a42 a Work turn takes an operator steer and a forged delivery turn refuses one, but nothing the
app reads said which a running turn is: the ``running_work`` row of a wave lane's Work turn and of a helper's
result turn carried the same keys (seen live 2026-11-12, Eternia lane w1112b-turn6). The row now carries
``steerable`` — true exactly while the steer watcher is up for THAT turn — read through
``mission_chat_steer.steer_taking_turn``, the one read ``submit_mission_chat_steer`` accepts or refuses on.

Whole turns (``held_model_turn``): each kind of turn runs through its real door, is held at the model, and the
row is read from ``build_running_work`` (what the snapshot section and the ``running_work`` frame serve) beside
a steer sent through ``submit_mission_chat_steer``.

Killing mutations (reds recorded in the commit body):
* ``turn_row`` writes ``steerable: False`` always → the Work, until-done and operator tests red;
* ``turn_takes_steer`` drops the "is it THIS turn" comparison → the stale-turn test red;
* ``submit_mission_chat_steer``'s admission keeps a read of its own that ignores the record's state
  (``_read_json(...) is None``) → the agreement test red (a refused steer left in the inbox, where the
  root's next watcher would take it; the wait loop's second read alone still answers ``no_active_turn``);
* ``steer_taking_turn`` ignores a dead pid → the agreement test's dead-pid case red.
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from agent_runtime import chat_goal, mission_chat_steer, paths
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner
from agent_runtime.dispatch_delivery.forge import forge_delivery_turn
from agent_runtime.mission_chat_door import run_mission_chat_turn
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.running_work import build_running_work
from agent_runtime.running_work.vocabulary import KIND_CHAT_TURN
from agent_runtime.work_store.persona_turn import _turn_args
from hermes_cli.harness_parts.persona.chat_turn_commit import run as turn_run
from tests.agent_runtime.held_model_turn import Running
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, placed_agent, qa_persona,
)
from tests.agent_runtime.test_work_turn_takes_a_steer import chat, chat_head, model  # fixtures: a chat, a held model

pytestmark = pytest.mark.timeout(180)


def _rows(root: str) -> list[dict]:
    return [row for row in build_running_work()["rows"]
            if row["kind"] == KIND_CHAT_TURN and row["owner"]["session_id"] == root]


def _steer(root: str, steer_id: str = "steer-1") -> dict:
    return submit_mission_chat_steer(runtime_root=paths.store_root(), session_id=root,
                                     message="Look at the logs too.", client_message_id=steer_id,
                                     timeout_seconds=20)


def _queued(instance: str, root: str, cmid: str, requested_by: str) -> Running:
    """A turn the runtime starts: queued on the root and run by the send runner, as Work, schedules and
    platform messages are (``work_store/persona_turn.py``: ``stream=False``)."""

    args = _turn_args(PersonaInstanceStore().get(instance), root, cmid, "Tidy the meadow.", requested_by)
    entry, _position, _replay = send_queue.enqueue(root, cmid, send_queue.persistable_args(args))
    return Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy()))


def _accepted(ack: dict) -> bool:
    return ack.get("ok") is True and ack.get("execution_state") == "accepted"


def _refused_no_turn(ack: dict) -> bool:
    return ack.get("ok") is not True and ack.get("error_kind") == "no_active_turn"


def test_a_wave_lanes_work_turn_says_steerable_and_takes_the_steer(chat, model):
    instance, root = chat
    turn = _queued(instance, root, "work-BATCH-Q44PM7:L1", "work:BATCH-Q44PM7:L1")
    assert model.entered.wait(60), "the Work turn never reached the model"

    [row] = _rows(root)
    ack = _steer(root)

    assert row["steerable"] is True and "work_request" not in row, row
    assert _accepted(ack), ack
    model.release.set()
    turn.join(60)
    # The turn is over: no row, and a steer is refused.
    assert _rows(root) == []
    assert _refused_no_turn(_steer(root, "steer-2"))


def test_an_until_done_pass_says_steerable_and_takes_the_steer(chat, model):
    instance, root = chat
    cmid = "work-ws_x:repo:RT-A:2026-11-12:a0dccc"
    chat_goal.bind(chat_goal.GoalBinding(root, "run-1", (), {}, cmid, turns=0))
    turn = _queued(instance, root, cmid, "work:ws_x:repo:RT-A:2026-11-12:a0dccc")
    assert model.entered.wait(60), "the pass never reached the model"

    [row] = _rows(root)
    ack = _steer(root)

    assert row["steerable"] is True and row["work_request"] == "run-1", row
    assert _accepted(ack), ack
    model.release.set()
    turn.join(60)


def test_an_operators_streaming_send_says_steerable_and_takes_the_steer(chat, model):
    instance, root = chat
    args = _turn_args(PersonaInstanceStore().get(instance), root, "agent-chat-send-1", "Hello.", "gateway_device")
    args.stream = True
    turn = Running(lambda: run_mission_chat_turn(args))
    assert model.entered.wait(60), "the operator's turn never reached the model"

    [row] = _rows(root)
    ack = _steer(root)

    assert row["steerable"] is True, row
    assert _accepted(ack), ack
    model.release.set()
    turn.join(60)


def test_a_forged_helper_result_turn_says_not_steerable_and_refuses_the_steer(chat, model):
    instance, root = chat
    turn = Running(lambda: forge_delivery_turn(
        root_session_id=root, persona_id=PERSONA, persona_instance_id=instance,
        message="[Background task finished] the helper's result: done.",
        client_message_id="bg-completion-async_delegation_7f3a"))
    assert model.entered.wait(60), "the forged turn never reached the model"

    [row] = _rows(root)
    ack = _steer(root)

    assert row["steerable"] is False, row
    assert _refused_no_turn(ack), ack
    model.release.set()
    turn.join(60)


@pytest.mark.parametrize(("cmid", "requested_by"), [
    ("schedule-sched_7:2026-11-12T09:00", "schedule:sched_7:2026-11-12T09:00"),
    ("msg-telegram:42:9001", "messaging:telegram:42"),
])
def test_a_schedule_fire_and_a_platform_message_say_not_steerable_and_refuse_the_steer(chat, model, cmid, requested_by):
    instance, root = chat
    turn = _queued(instance, root, cmid, requested_by)
    assert model.entered.wait(60), "the turn never reached the model"

    [row] = _rows(root)
    ack = _steer(root)

    assert row["steerable"] is False, row
    assert _refused_no_turn(ack), ack
    model.release.set()
    turn.join(60)


def test_steerable_flips_with_the_watchers_life(chat, model, monkeypatch):
    """False while the turn is written ahead and its agent is still being built; true once the watcher is up;
    false again when the watcher closes — and at each instant the steer door gives the same answer."""

    instance, root = chat
    at_gate, open_gate = threading.Event(), threading.Event()
    real_start = turn_run.start_active_mission_chat_turn

    def _held_start(**kwargs):
        at_gate.set()
        assert open_gate.wait(60)
        return real_start(**kwargs)

    monkeypatch.setattr(turn_run, "start_active_mission_chat_turn", _held_start)
    turn = _queued(instance, root, "work-BATCH-JXEHAC:L1", "work:BATCH-JXEHAC:L1")
    assert at_gate.wait(60), "the turn never got as far as starting its steer watcher"

    [before] = _rows(root)
    assert before["steerable"] is False, before
    assert _refused_no_turn(_steer(root, "steer-before"))

    open_gate.set()
    assert model.entered.wait(60), "the Work turn never reached the model"
    [during] = _rows(root)
    assert during["steerable"] is True, during
    assert _accepted(_steer(root, "steer-during"))

    model.release.set()
    turn.join(60)
    assert _rows(root) == []
    assert mission_chat_steer.turn_takes_steer(
        runtime_root=paths.store_root(), session_id=root, client_message_id="work-BATCH-JXEHAC:L1") is False
    assert _refused_no_turn(_steer(root, "steer-after"))


def _write_ahead(root: str, cmid: str) -> None:
    persist_mission_chat_turn(session_id=root, client_message_id=cmid, turn_id=cmid, elements=None,
                              state="executing", write_ahead=True,
                              metadata={"persona_instance_id": "personainst_neko", "root_chat_session_id": root})


def _dead_pid() -> int:
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


@pytest.mark.parametrize("active", [
    None,
    {"execution_state": "completed", "client_message_id": "turn-1"},
    {"execution_state": "active", "client_message_id": "turn-1", "pid": "dead"},
    {"execution_state": "active", "client_message_id": "turn-1", "pid": "mine"},
    {"execution_state": "active", "client_message_id": "turn-1"},
])
def test_the_row_and_the_steer_door_never_disagree(isolate_agent_runtime_root, active):
    """Every state the steer watcher's record can be in: the row says ``steerable`` exactly when the door
    would not refuse ``no_active_turn``. (No watcher thread runs here, so an admitted steer times out waiting
    for its ack — admitted is what is read.)"""

    root = "chat-sess-agree"
    _write_ahead(root, "turn-1")
    if active is not None:
        record = dict(active)
        if "pid" in record:
            record["pid"] = os.getpid() if record["pid"] == "mine" else _dead_pid()
        path = mission_chat_steer._active_path(paths.store_root(), root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")

    [row] = _rows(root)
    ack = submit_mission_chat_steer(runtime_root=paths.store_root(), session_id=root, message="Hi.",
                                    client_message_id="steer-1", timeout_seconds=0.1)

    assert row["steerable"] is (not _refused_no_turn(ack)), (row["steerable"], ack)
    # A refused steer left nothing behind for the root's NEXT watcher to pick up as its own.
    inbox = mission_chat_steer._request_path(paths.store_root(), root, "steer-1")
    assert inbox.exists() is row["steerable"]
    assert row["steerable"] is (active is not None and active["execution_state"] == "active"
                                and active.get("pid") != "dead")


def test_a_stale_turns_row_is_not_steerable_while_the_roots_live_turn_is(isolate_agent_runtime_root):
    """A crashed turn's record still in flight beside the root's live one: the steer goes to the live turn,
    so only that turn's row says it takes one."""

    root = "chat-sess-stale"
    _write_ahead(root, "turn-crashed")
    _write_ahead(root, "turn-live")
    path = mission_chat_steer._active_path(paths.store_root(), root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"execution_state": "active", "client_message_id": "turn-live",
                                "pid": os.getpid()}), encoding="utf-8")

    said = {row["work_id"]: row["steerable"] for row in _rows(root)}

    assert said == {"chat_turn:turn-crashed": False, "chat_turn:turn-live": True}
