"""Per-message audience is durable policy, not a separate room or parser."""
from dataclasses import replace

import pytest

from gateway import hosted_room_discussion as policy
from gateway import hosted_rooms
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
from tests.gateway.test_hosted_room_discussion import (
    GATEWAY_ID, LOCAL_PROFILES, ROOM_ID, _append_activity, _append_publication,
    _events, room_db as room_db,
)


def append(db, key, text, response=None):
    payload = {"text": text, "thread_id": "thread-1"}
    if response is not None:
        payload["response"] = response
    return hosted_rooms.append_event(db, room_id=ROOM_ID, event_id=key,
        kind="message.user", actor={"kind": "user", "id": "operator"},
        authority_gateway_id=GATEWAY_ID, authority_epoch=1, payload=payload)


def next_step(db, room, **kwargs):
    return policy.plan_next_task(room, _events(db), local_profiles=LOCAL_PROFILES, **kwargs)


def publish(db, room, task, text="Answer", status="settled", **kwargs):
    result = {"text": text} if status == "settled" else {"error": "Unavailable"}
    plan = policy.plan_publication(room, _events(db), task, status=status,
        result=result, local_profiles=LOCAL_PROFILES, **kwargs)
    _append_publication(db, plan)


def test_compare_freezes_public_context_then_discussion_sees_all_answers(room_db):
    db, room = room_db
    event = append(db, "compare", "Find options", {"mode": "compare", "members": []})
    admitted = next_step(db, room).ready_tasks
    assert len(admitted) == 3
    assert len({task.seen_through_seq for task in admitted}) == 1
    tasks = []
    for number in range(3):
        task = next_step(db, room).task
        assert task is not None
        assert task.seen_through_seq == event["seq"]
        assert "Candidate " not in task.payload["prompt"]
        assert "independent answer" in task.payload["prompt"]
        tasks.append(task)
        assert task == admitted[number]
        publish(db, room, task, f"Candidate {number}: @{LOCAL_PROFILES[(number + 1) % 3]}")
    assert len({task.member.member_id for task in tasks}) == 3
    decision = next_step(db, room)
    assert (decision.status, decision.reason) == ("settled", "comparison_finished")
    _append_activity(db, event_id="finish", discussion_event_id="compare", thread_id="thread-1")
    append(db, "continue", "Develop candidate 2 together")
    resumed = next_step(db, room).task
    assert resumed is not None
    for number in range(3):
        assert f"Candidate {number}" in resumed.payload["prompt"]
    assert "independent answer" not in resumed.payload["prompt"]
    checkpoint = HostedRoomPolicyCheckpoint(db)
    state = hosted_rooms.room_state(db, room_id=ROOM_ID)
    checkpoint.sync(room_id=ROOM_ID, latest_seq=state["latest_seq"])
    snapshot = checkpoint.snapshot(room_id=ROOM_ID, latest_seq=state["latest_seq"])
    restored = policy.plan_next_task(room, snapshot.events, local_profiles=LOCAL_PROFILES,
        initial_watermarks=snapshot.watermarks)
    assert restored.task == resumed


def test_explicit_reply_does_not_expand_peer_mentions_or_schedule_synthesis(room_db):
    db, room = room_db
    limits = replace(policy.DEFAULT_LIMITS, conclusion_member_id="member-review")
    append(db, "reply", "Ask @review about it", {"mode": "reply", "members": ["member-build"]})
    task = next_step(db, room, limits=limits).task
    assert task.member.member_id == "member-build"
    publish(db, room, task, "@review please follow up", limits=limits)
    decision = next_step(db, room, limits=limits)
    assert (decision.status, decision.reason) == ("settled", "reply_finished")


def test_compare_failure_does_not_poison_other_participants(room_db):
    db, room = room_db
    append(db, "compare", "Find options", {"mode": "compare", "members": []})
    first = next_step(db, room).task
    publish(db, room, first, status="failed")
    second = next_step(db, room).task
    assert second.member != first.member
    publish(db, room, second)
    third = next_step(db, room).task
    publish(db, room, third)
    assert next_step(db, room).status == "settled"


@pytest.mark.parametrize("budget", [2, 3])
def test_compare_keeps_the_host_budget_and_reports_full_completion(room_db, budget):
    db, room = room_db
    limits = replace(policy.DEFAULT_LIMITS, max_messages=budget)
    append(db, "compare", "Find options", {"mode": "compare", "members": []})
    tasks = next_step(db, room, limits=limits).ready_tasks
    assert len(tasks) == budget
    for task in tasks:
        publish(db, room, task, limits=limits)
    decision = next_step(db, room, limits=limits)
    assert decision.task is None
    assert decision.reason == ("comparison_finished" if budget == 3 else "max_messages")


def test_compare_task_reconstruction_and_stop_keep_exact_identity(room_db):
    db, room = room_db
    append(db, "compare", "Find options", {"mode": "compare", "members": []})
    task = next_step(db, room).task
    reconstructed = policy.reconstruct_task_plan(room, _events(db),
        {"identity": task.identity, "payload": task.payload}, local_profiles=LOCAL_PROFILES)
    assert reconstructed == task
    assert next_step(db, room).task == task
    hosted_rooms.request_room_stop(db, room_id=ROOM_ID, cancel_id="stop",
        expected_gateway_id=GATEWAY_ID, expected_epoch=1)
    assert next_step(db, room).status == "idle"


@pytest.mark.parametrize("response", [
    {"mode": "guess", "members": []}, {"mode": "reply", "members": []},
    {"mode": "compare", "members": ["member-build", "member-build"]},
    {"mode": "compare", "members": ["foreign"]},
    {"mode": "compare", "members": "member-build"},
    {"mode": "compare", "members": [], "secret": True},
])
def test_invalid_audience_is_never_replaced_with_everyone(room_db, response):
    db, room = room_db
    append(db, "invalid", "Hello", response)
    with pytest.raises(policy.DiscussionValidationError):
        next_step(db, room)


def test_removed_recipient_is_not_silently_replaced(room_db):
    db, room = room_db
    append(db, "reply", "Hello", {"mode": "reply", "members": ["member-build"]})
    decision = next_step(db, room, active_member_ids=["member-research", "member-review"])
    assert decision.status == "settled"
    assert decision.task is None
