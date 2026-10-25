"""J2 A2 (RT-J2-HOSTED-ROOM-LIMITS): the scheduled conclusion freezes its bounded input.

``hosted_room_limits._conclude`` builds the conclusion on upstream's ``_bounded_task_delta`` and
always carries ``input_context``, so the admitted task reconstructs after a late member message.
"""
from dataclasses import replace

from gateway import hosted_room_discussion as policy
from gateway import hosted_rooms
from tests.gateway.test_hosted_room_discussion import (
    GATEWAY_ID, LOCAL_PROFILES, ROOM_ID, _append_publication, _events, room_db,  # noqa: F401
)


def _user(db, key, text):
    return hosted_rooms.append_event(db, room_id=ROOM_ID, event_id=key, kind="message.user",
        actor={"kind": "user", "id": "operator"}, authority_gateway_id=GATEWAY_ID, authority_epoch=1,
        payload={"text": text, "thread_id": "thread-1"})


def test_the_conclusion_freezes_its_input_and_reconstructs_after_a_late_message(room_db):
    db, room = room_db
    limits = replace(policy.DEFAULT_LIMITS, conclusion_member_id="member-review", max_messages=1)
    _user(db, "ask", "Plan the release")
    first = policy.plan_next_task(room, _events(db), local_profiles=LOCAL_PROFILES, limits=limits).task
    plan = policy.plan_publication(room, _events(db), first, status="settled", result={"text": "Draft plan"},
                                   local_profiles=LOCAL_PROFILES, limits=limits)
    _append_publication(db, plan)

    decision = policy.plan_next_task(room, _events(db), local_profiles=LOCAL_PROFILES, limits=limits)
    assert (decision.status, decision.reason) == ("task", "conclusion_turn")
    conclusion = decision.task
    messages = [e["seq"] for e in _events(db) if e["kind"] in {"message.user", "message.member"}]
    assert conclusion.payload["input_context"] == {"watermark": 0, "event_seqs": messages}
    assert conclusion.seen_through_seq == messages[-1]

    _user(db, "late", "One more thing")  # a message after admission
    rebuilt = policy.reconstruct_task_plan(room, _events(db), {"identity": conclusion.identity,
        "payload": conclusion.payload}, local_profiles=LOCAL_PROFILES, limits=limits)
    assert rebuilt == conclusion
