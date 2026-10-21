"""RT-SEND-ORIGIN-KIND-TABLE (p10-messaging §3 M3): ``PersonaTurnExecutor.settled`` routes a settle by its
origin's KIND through one listener table, not by probing the origin's shape.

The send queue is the real one on this test's isolated home; the goal arms are recorded.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import chat_goal, paths
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.work_store import goal_turns
from agent_runtime.work_store.persona_turn import (
    ORIGIN_KIND_KEY, OriginKind, PersonaTurnExecutor, origin_kind,
)

ROOT = "persona_chat_root_kinds"


class _Instances:
    def get(self, instance_id):
        return SimpleNamespace(id=instance_id, persona_id="neko", runtime_root=str(paths.store_root()))


@pytest.fixture
def arms(monkeypatch):
    told: list[tuple[str, str]] = []
    monkeypatch.setattr(goal_turns, "after_chat_goal_turn",
                        lambda entry, payload, **_: told.append(("goal", entry.client_message_id)))
    executor = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, **_: ROOT, wake=lambda: None)
    executor.on_settle(lambda run, outcome: told.append(("work", run.request_id)))
    executor.register_origin_listener(OriginKind.MESSAGING,
                                      lambda entry, code, payload: told.append(("messaging", entry.client_message_id)))
    return executor, told


def _settle(executor, cmid, origin):
    args = {} if origin is None else {send_queue.ORIGIN_ARG: origin}
    entry, _, _ = send_queue.enqueue(ROOT, cmid, args)
    executor.settled(entry, 0, {"ok": True, "reply": "hi"})


def test_origin_kind_routes_by_table(arms):
    """Killing mutation: ``settled`` routes every non-``work`` origin to the goal arm (today's ladder) →
    the ``messaging`` settle reaches ``after_chat_goal_turn`` and not its listener → red."""
    executor, told = arms
    _settle(executor, "msg-telegram-1", {ORIGIN_KIND_KEY: "messaging", "messaging": {"platform": "telegram"}})
    assert told == [("messaging", "msg-telegram-1")]


def test_legacy_origins_keep_their_arms(arms):
    executor, told = arms
    _settle(executor, "work-rid-1", {"work": "rid-1", "rows": []})  # queued before ``kind`` existed
    _settle(executor, "schedule-f1", {"owner": None, "gateway": False, "schedule": "standup"})
    _settle(executor, "operator-1", None)
    _settle(executor, "odd-1", {ORIGIN_KIND_KEY: "carrier-pigeon"})
    assert told == [("work", "rid-1"), ("goal", "schedule-f1"), ("goal", "operator-1"), ("goal", "odd-1")]
    assert origin_kind({"work": "x"}) is OriginKind.WORK and origin_kind("junk") is OriginKind.GOAL


def test_an_unregistered_kind_falls_to_the_goal_arm(arms):
    executor, told = arms
    executor.unregister_origin_listener(OriginKind.MESSAGING)
    _settle(executor, "msg-telegram-2", {ORIGIN_KIND_KEY: "messaging"})
    assert told == [("goal", "msg-telegram-2")]


def test_a_bound_root_runs_the_goal_hook_and_still_tells_a_registered_kind(arms, monkeypatch):
    executor, told = arms
    monkeypatch.setattr(chat_goal, "binding", lambda root: SimpleNamespace(root_session_id=root))
    monkeypatch.setattr(goal_turns, "after_turn", lambda bound, entry, payload, **_: told.append(("bound", "")))
    _settle(executor, "msg-telegram-3", {ORIGIN_KIND_KEY: "messaging"})
    _settle(executor, "operator-2", None)
    assert told == [("bound", ""), ("messaging", "msg-telegram-3"), ("bound", "")]


def test_the_root_arms_cannot_be_replaced_and_a_failing_listener_is_contained(arms):
    executor, told = arms
    with pytest.raises(ValueError):
        executor.register_origin_listener(OriginKind.WORK, lambda *a: None)
    executor.register_origin_listener(OriginKind.MESSAGING, lambda *a: 1 / 0)
    _settle(executor, "msg-telegram-4", {ORIGIN_KIND_KEY: "messaging"})  # logged, never the runner's
    assert told == []


def test_a_work_start_names_its_kind():
    from tests.agent_runtime.work_store.test_persona_turn import _assignment, _executor

    executor, _ = _executor()
    run = executor.start(_assignment())
    assert send_queue.find("persona_chat_root_work", run.client_message_id).args[
        send_queue.ORIGIN_ARG][ORIGIN_KIND_KEY] == "work"


def test_schedule_cmid_unchanged(arms):
    """Killing mutation: ``queue_prompt`` passes another ``cmid_prefix`` (e.g. ``msg-``) → red: the
    scheduler's fire ids, its ``running_work`` rows and its idempotency are keyed on ``schedule-<id>``."""
    executor, _ = arms
    run = executor.queue_prompt("inst-1", "Stand-up?", request_id="fire-1", origin={"schedule": "standup"})
    assert run.client_message_id == "schedule-fire-1" and run.run_id == f"{ROOT}/schedule-fire-1"
    entry = send_queue.find(ROOT, "schedule-fire-1")
    assert entry.args["requested_by"] == "schedule:fire-1" and entry.args["message"] == "Stand-up?"
    again = executor.queue_inbound("inst-1", "Stand-up?", request_id="fire-1", origin={"schedule": "standup"},
                                   cmid_prefix="schedule-", requested_by="schedule:fire-1")
    assert again.replay is True and again.position == 1 and len(send_queue.entries(ROOT)) == 1
