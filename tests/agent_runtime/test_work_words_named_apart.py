"""A Task is a board row; what is executing is "running now" (RT-WORK-WORD-MEANS-TASKS-AND-RUNNING-THINGS).

Owner 2026-11-12: "i think we are mixing up the backround tasks with process tasks in the backround" —
confirmed words: "Task" for a board item, "Running now" for what is executing. ``runtime.work.list`` is
board tasks while ``harness work list`` and ``runtime.work.{cancel,restart,background.promote}`` act on
running things; the method names stay (wire compatibility) and the fork-owned TEXT names the two apart.
Each row below reads one of those texts. Upstream tool descriptions are not touched.
"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from agent_runtime.serve_rpc import work as running_rpc
from agent_runtime.work import rpc as task_rpc
from agent_runtime.work.model import Reason, WorkRefused
from hermes_cli.harness_parts.parser.machine import add_work


def _work_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness")
    add_work(parser.add_subparsers(dest="command"))
    return parser


def test_harness_work_help_says_running_now_and_never_calls_it_background_work_or_tasks():
    """Killing mutation: the family help back to "Background work running right now" -> red."""

    family = " ".join(_work_parser().format_help().split())
    assert "What is running now" in family and "Board tasks are not listed here" in family
    assert "background work" not in family.lower()


def test_a_running_now_method_refuses_an_unknown_id_in_running_words(monkeypatch):
    """Killing mutation: the not_found message back to "No running work with that id." -> red."""

    monkeypatch.setattr("agent_runtime.running_work.find_work_row", lambda work_id: None)
    reply = running_rpc._runtime_work_cancel("r1", {"work_id": "RT-SOME-TASK"})
    assert reply["error"]["data"]["reason"] == "not_found"
    assert "running now" in reply["error"]["message"] and "task id is not" in reply["error"]["message"]


def test_a_task_method_refuses_in_task_words(monkeypatch):
    """Killing mutation: the refusal message back to "This work request could not be accepted." -> red."""

    def refuse(operation, params, caller):
        raise WorkRefused(Reason.INVALID, "no such row")

    monkeypatch.setattr(task_rpc, "execute", refuse)
    reply = task_rpc._work_reply("r2", "claim", {}, SimpleNamespace())
    assert reply["error"]["message"] == "This task request could not be accepted."


def test_a_promoted_calls_handle_says_it_is_neither_a_process_id_nor_a_task_id():
    """Killing mutation: drop the handle sentence from ``running_in_background`` -> red."""

    from tools import long_tool_calls

    message = json.loads(long_tool_calls.running_in_background(SimpleNamespace(handle="bg:abc", tool_name="terminal")))["message"]
    assert "not a process id and not a task id" in message
