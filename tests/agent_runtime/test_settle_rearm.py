"""Re-arming an undelivered chat-turn settle (D2.05 S1).

Plan ``docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md`` § D2.05:
re-arm is ``undelivered -> pending`` with ``attempts = 0`` and the SAME
``settle_id`` (one settle per turn; the launcher acks by ``client_message_id``),
counted on ``rearm_count``. The pusher needs no change: a re-armed record is due
under the pusher's own rule and goes on the next tick.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from agent_runtime import chat_turn_settles as settles
from agent_runtime import paths
from agent_runtime.chat_turn_settles import (
    STATE_ACKED,
    STATE_PENDING,
    STATE_UNDELIVERED,
    RearmResult,
    TurnOutcome,
    ack_settle,
    due_settles,
    note_push,
    read_settle,
    rearm_settle,
    record_settle,
    resolve_settle_id,
    settle_id_for,
    settles_listing,
)
from hermes_time import now
from tests.agent_runtime.test_serve_settle_push import _settled_frames, _wait
from tests.agent_runtime.test_serve_stream_lane_parity import _stdio_serve

CMID = "cm-rearm-1"
SESSION = "sess-rearm-1"


def _pending(cmid: str = CMID):
    return record_settle(
        client_message_id=cmid, session_id=SESSION, request_id="r1",
        exit_code=2, outcome=TurnOutcome(refusal_class="chat_turn_provider_refused"),
    )


def _undelivered_by_budget(cmid: str = CMID):
    record = _pending(cmid)
    moment = now()
    for step in range(settles.MAX_ATTEMPTS):
        record = note_push(record.settle_id, delivered_to=1, at=moment + timedelta(seconds=step * 60))
    assert record.state == STATE_UNDELIVERED
    assert record.undelivered_reason == settles.UNDELIVERED_RETRY_BUDGET
    return record


def test_a_rearmed_record_is_pending_due_and_survives_its_next_push():
    record = _undelivered_by_budget()
    result, rearmed = rearm_settle(record.settle_id)

    assert result is RearmResult.REARMED
    assert rearmed.settle_id == record.settle_id == settle_id_for(SESSION, CMID)
    assert rearmed.state == STATE_PENDING
    assert rearmed.attempts == 0
    assert rearmed.undelivered_reason is None
    assert rearmed.rearm_count == 1
    assert rearmed.rearmed_at and rearmed.next_attempt_at == rearmed.rearmed_at
    assert [r.settle_id for r in due_settles(now() + timedelta(seconds=1))] == [record.settle_id]
    # The pusher's first push of the re-armed record is attempt 1, not attempt 7:
    # a re-arm that kept the spent budget would be undelivered again right here.
    pushed = note_push(record.settle_id, delivered_to=1)
    assert pushed.state == STATE_PENDING and pushed.attempts == 1
    assert read_settle(record.settle_id).rearm_count == 1


def test_a_second_rearm_counts_and_keeps_the_one_record():
    record = _undelivered_by_budget()
    rearm_settle(record.settle_id)
    moment = now()
    for step in range(settles.MAX_ATTEMPTS):
        note_push(record.settle_id, delivered_to=1, at=moment + timedelta(seconds=step * 60))
    result, again = rearm_settle(record.settle_id)
    assert result is RearmResult.REARMED and again.rearm_count == 2
    assert [r.settle_id for r in settles.list_settles()] == [record.settle_id]


def test_an_acked_settle_is_refused_and_untouched():
    record = _undelivered_by_budget()
    assert ack_settle(record.settle_id) is True
    result, unchanged = rearm_settle(record.settle_id)
    assert result is RearmResult.ACKED
    assert unchanged.state == STATE_ACKED and unchanged.rearm_count == 0
    assert read_settle(record.settle_id).state == STATE_ACKED


def test_a_pending_settle_is_a_no_op_and_an_unknown_one_is_not_found():
    record = _pending()
    result, same = rearm_settle(record.settle_id)
    assert result is RearmResult.ALREADY_PENDING
    assert same == record
    assert rearm_settle("no-such-settle") == (RearmResult.NOT_FOUND, None)
    assert rearm_settle("") == (RearmResult.NOT_FOUND, None)


def test_a_rearmed_no_listener_settle_gets_a_fresh_hour():
    """The no-listener clock restarts at the re-arm; read off the old stamps it
    would be undelivered again on the first silent tick."""

    record = _pending()
    hour = settles.NO_LISTENER_SECONDS
    expired = note_push(record.settle_id, delivered_to=0, at=now() + timedelta(seconds=hour + 1))
    assert expired.undelivered_reason == settles.UNDELIVERED_NO_LISTENER
    rearm_at = now() + timedelta(seconds=hour + 60)
    result, _ = rearm_settle(record.settle_id, at=rearm_at)
    assert result is RearmResult.REARMED
    still = note_push(record.settle_id, delivered_to=0, at=rearm_at + timedelta(seconds=10))
    assert still.state == STATE_PENDING
    again = note_push(record.settle_id, delivered_to=0, at=rearm_at + timedelta(seconds=hour + 1))
    assert again.state == STATE_UNDELIVERED
    assert again.undelivered_reason == settles.UNDELIVERED_NO_LISTENER


def test_a_record_written_before_the_rearm_fields_reads_with_zero_and_none():
    record = _pending()
    path = paths.chat_turn_settle_path(record.settle_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("rearm_count", None)
    raw.pop("rearmed_at", None)
    path.write_text(json.dumps(raw), encoding="utf-8")
    read = read_settle(record.settle_id)
    assert read.rearm_count == 0 and read.rearmed_at is None


def test_the_listing_counts_every_state_and_filters_by_one():
    _undelivered_by_budget("cm-u")
    _pending("cm-p")
    acked = _pending("cm-a")
    ack_settle(acked.settle_id)

    listing = settles_listing()
    assert listing["counts"] == {"pending": 1, "undelivered": 1, "acked": 1}
    assert len(listing["settles"]) == 3
    only = settles_listing(state=STATE_UNDELIVERED)
    assert only["counts"] == listing["counts"]
    assert [row["client_message_id"] for row in only["settles"]] == ["cm-u"]
    row = only["settles"][0]
    assert row["undelivered_reason"] == settles.UNDELIVERED_RETRY_BUDGET
    assert row["rearm_count"] == 0 and row["state"] == STATE_UNDELIVERED
    with pytest.raises(ValueError):
        settles_listing(state="lost")


def test_both_addressings_resolve_to_the_one_settle_id():
    expected = settle_id_for(SESSION, CMID)
    assert resolve_settle_id(settle_id=f" {expected} ") == expected
    assert resolve_settle_id(client_message_id=CMID, session_id=SESSION) == expected
    assert resolve_settle_id(client_message_id=CMID) == settle_id_for(None, CMID)
    assert resolve_settle_id() is None
    assert resolve_settle_id(settle_id="  ", client_message_id=3) is None


def test_the_serve_pushes_a_rearmed_settle_on_its_next_tick(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.harness_parts.serve.settle_push.SETTLE_PUSH_TICK_SECONDS", 0.02
    )
    record = _undelivered_by_budget()
    with _stdio_serve() as (_pipe, sink):
        import time

        time.sleep(0.2)
        assert _settled_frames(sink) == [], "an undelivered settle was pushed"
        rearm_settle(record.settle_id)
        frame = _wait(lambda: _settled_frames(sink))[0]
    assert frame["settle_id"] == record.settle_id
    assert frame["client_message_id"] == CMID
    assert frame["attempt"] == 1


# ── the method lane (D2.05 S2) ──────────────────────────────────────────────


def _rpc(pipe, sink, rid, method, params):
    pipe.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    return _wait(lambda: [f for f in sink.frames() if f.get("id") == rid and "jsonrpc" in f])[0]


def test_list_and_rearm_round_trip_through_the_method_lane(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.harness_parts.serve.settle_push.SETTLE_PUSH_TICK_SECONDS", 0.02
    )
    record = _undelivered_by_budget()
    with _stdio_serve() as (pipe, sink):
        listed = _rpc(pipe, sink, "l1", "runtime.settles.list", {"state": "undelivered"})
        assert listed["result"]["counts"]["undelivered"] == 1
        assert [r["settle_id"] for r in listed["result"]["settles"]] == [record.settle_id]

        rearmed = _rpc(pipe, sink, "r1", "runtime.settles.rearm",
                       {"client_message_id": CMID, "session_id": SESSION})
        assert rearmed["result"]["rearmed"] is True
        assert rearmed["result"]["settle"]["rearm_count"] == 1
        frame = _wait(lambda: _settled_frames(sink))[0]
        assert frame["settle_id"] == record.settle_id and frame["attempt"] == 1

        again = _rpc(pipe, sink, "r2", "runtime.settles.rearm", {"settle_id": record.settle_id})
        assert again["result"]["rearmed"] is False  # pending now: a no-op
        missing = _rpc(pipe, sink, "r3", "runtime.settles.rearm", {"settle_id": "nope"})
        assert missing["error"]["data"]["reason"] == "settle_not_found"
        bare = _rpc(pipe, sink, "r4", "runtime.settles.rearm", {})
        assert bare["error"]["data"]["reason"] == "settle_ref_required"
        bad = _rpc(pipe, sink, "l2", "runtime.settles.list", {"state": "lost"})
        assert bad["error"]["data"]["reason"] == "state_invalid"
        ack_settle(record.settle_id)
        acked = _rpc(pipe, sink, "r5", "runtime.settles.rearm", {"settle_id": record.settle_id})
        assert acked["error"]["data"]["reason"] == "settle_acked"

