"""Settle push (h-settle-push, 2026-10-10): every chat-turn settle reaches the launcher.

Contract: ``docs/agent-runtime-harness/planned/settle-push-2026-10-10.md``. The
owner ruling is that hermes pushes and verifies the push landed; the launcher
never polls. So each test here is about the PUSH side: the settle rides a channel
the stream producer cannot take down, it is re-sent until acked, an unacked one
ends in a typed undelivered record, and an ack (once or twice) retires it.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import timedelta

import pytest

from agent_runtime import chat_turn_settles as settles
from agent_runtime.chat_turn_settles import (
    STATE_ACKED,
    STATE_PENDING,
    STATE_UNDELIVERED,
    TurnOutcome,
    ack_settle,
    due_settles,
    note_push,
    read_settle,
    record_settle,
    settle_id_for,
)
from hermes_time import now
from tests.agent_runtime.test_serve_socket_lane import (
    WAIT,
    _read_until,
    client,
    running_serve,
)
from tests.agent_runtime.test_serve_stream_lane_parity import _stdio_serve

CMID = "cm-settle-1"
SESSION = "sess-settle-1"
TURN_ARGV = [
    "harness", "mission-chat", "message", "--session-id", SESSION,
    "--client-message-id", CMID, "--json", "hi",
]
REFUSAL = {
    "ok": False,
    "error_kind": "chat_provider_failed",
    "error": "the provider refused the turn",
    "next_expected": "check the provider key, then resend",
    "session_id": SESSION,
    "turn_id": "turn-77",
}


class _DeclaredProducerFailure(RuntimeError):
    code = "stream_store_unreadable"
    fix_hint = "repair the event log named in the service log"


def _raising_stream():
    def _factory():
        def _generate():
            yield {"type": "hydrate", "index": 0}
            raise _DeclaredProducerFailure("boom")

        return _generate()

    return _factory


def _refusing_turn(argv):
    sys.stdout.write(json.dumps(REFUSAL) + "\n")
    return 1


def _wait(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def _settled_frames(sink):
    return [frame for frame in sink.frames() if frame.get("event") == "turn_settled"]


# ── the push survives a raising stream producer ─────────────────────────────


def test_a_settle_reaches_a_socket_client_while_the_stream_producer_is_raising():
    with running_serve(dispatch=_refusing_turn, stream_source_factory=_raising_stream()) as handle:
        with client(handle, name="launcher") as (connection, _hello):
            connection.send({"op": "subscribe", "lane": "stream"})
            dropped = _read_until(connection, "subscription_dropped")
            # The drop frame carries what the producer's exception declared.
            assert dropped["reason"] == "producer_error:_DeclaredProducerFailure"
            assert dropped["refusal_class"] == "stream_store_unreadable"
            assert dropped["fix_hint"] == "repair the event log named in the service log"

            connection.send({"id": "turn-1", "argv": TURN_ARGV})
            exit_frame = _read_until(connection, "exit")
            assert exit_frame["code"] == 1
            # Durable BEFORE the exit frame.
            record = read_settle(settle_id_for(SESSION, CMID))
            assert record is not None and record.exit_code == 1

            settled = _read_until(connection, "turn_settled")
            assert settled["client_message_id"] == CMID
            assert settled["session_id"] == SESSION
            assert settled["turn_id"] == "turn-77"
            assert settled["exit_code"] == 1
            assert settled["refusal_class"] == "chat_provider_failed"
            assert settled["fix_hint"] == "check the provider key, then resend"
            assert settled["summary"] == "the provider refused the turn"
            assert settled["settle_id"] == settle_id_for(SESSION, CMID)

            connection.send({"op": "settle_ack", "settle_id": settled["settle_id"]})
            acked = _read_until(connection, "settle_acked")
            assert acked["retired"] is True
            assert read_settle(settled["settle_id"]).state == STATE_ACKED


def test_a_bare_producer_failure_keeps_the_historical_drop_shape():
    """Positive control for the drop keys: an exception that declares nothing adds nothing."""

    def _bare():
        def _generate():
            yield {"type": "hydrate", "index": 0}
            raise RuntimeError("boom")

        return _generate()

    with running_serve(stream_source_factory=lambda: _bare()) as handle:
        with client(handle, name="launcher") as (connection, _hello):
            connection.send({"op": "subscribe", "lane": "stream"})
            dropped = _read_until(connection, "subscription_dropped")
            assert dropped["reason"] == "producer_error:RuntimeError"
            assert "refusal_class" not in dropped and "fix_hint" not in dropped


# ── re-send, undelivered, ack, duplicate ack (through the serve) ────────────


def test_no_ack_is_re_sent_then_lands_in_the_undelivered_record(monkeypatch):
    monkeypatch.setattr(settles, "BACKOFF_BASE_SECONDS", 0.05)
    monkeypatch.setattr(settles, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(
        "hermes_cli.harness_parts.serve.settle_push.SETTLE_PUSH_TICK_SECONDS", 0.02
    )
    with _stdio_serve(dispatch=_refusing_turn) as (pipe, sink):
        pipe.send({"id": "turn-1", "argv": TURN_ARGV})
        record = _wait(
            lambda: (r := read_settle(settle_id_for(SESSION, CMID)))
            and r.state == STATE_UNDELIVERED and r
        )
        frames = _settled_frames(sink)
        assert [frame["attempt"] for frame in frames] == [1, 2, 3]
        assert record.attempts == 3
        assert record.undelivered_reason == settles.UNDELIVERED_RETRY_BUDGET
        _wait(lambda: "serve_settle_undelivered" in sink.text())
        time.sleep(0.2)
        assert len(_settled_frames(sink)) == 3  # nothing after the budget


def test_an_ack_retires_the_settle_and_a_duplicate_ack_is_harmless(monkeypatch):
    monkeypatch.setattr(settles, "BACKOFF_BASE_SECONDS", 0.05)
    monkeypatch.setattr(
        "hermes_cli.harness_parts.serve.settle_push.SETTLE_PUSH_TICK_SECONDS", 0.02
    )
    with _stdio_serve(dispatch=_refusing_turn) as (pipe, sink):
        pipe.send({"id": "turn-1", "argv": TURN_ARGV})
        first = _wait(lambda: _settled_frames(sink))[0]
        pipe.send({"op": "settle_ack", "id": "a1", "client_message_id": CMID, "session_id": SESSION})
        _wait(lambda: [f for f in sink.frames() if f.get("event") == "settle_acked" and f.get("id") == "a1"])
        pipe.send({"op": "settle_ack", "id": "a2", "settle_id": first["settle_id"]})
        acks = _wait(lambda: (rows := [f for f in sink.frames() if f.get("event") == "settle_acked"])
                     and len(rows) == 2 and rows)
        assert [ack["retired"] for ack in acks] == [True, False]
        record = read_settle(first["settle_id"])
        assert record.state == STATE_ACKED
        # A re-send can legitimately land before the first ack is read (the
        # backoff is 50 ms here), so count what was pushed BY the ack, then
        # prove nothing follows it across several backoff windows.
        pushed_before_ack = len(_settled_frames(sink))
        time.sleep(0.4)
        assert len(_settled_frames(sink)) == pushed_before_ack


def test_a_pending_settle_left_by_a_previous_serve_is_pushed_on_boot():
    record = record_settle(
        client_message_id=CMID, session_id=SESSION, request_id="old-rid",
        exit_code=1, outcome=TurnOutcome(refusal_class="chat_provider_failed"),
    )
    with _stdio_serve() as (_pipe, sink):
        frame = _wait(lambda: _settled_frames(sink))[0]
    assert frame["settle_id"] == record.settle_id
    assert frame["request_id"] == "old-rid"


def test_a_duplicate_refused_by_the_turn_claim_records_no_settle():
    gate = threading.Event()

    def _slow_turn(argv):
        gate.wait(WAIT)
        sys.stdout.write(json.dumps({"ok": True, "session_id": SESSION}) + "\n")
        return 0

    with _stdio_serve(dispatch=_slow_turn) as (pipe, sink):
        pipe.send({"id": "turn-1", "argv": TURN_ARGV})
        time.sleep(0.3)  # turn-1 holds the claim (the pool runs turns concurrently)
        pipe.send({"id": "turn-2", "argv": TURN_ARGV})
        _wait(lambda: [f for f in sink.frames() if f.get("id") == "turn-2" and f.get("event") == "exit"])
        assert read_settle(settle_id_for(SESSION, CMID)) is None
        gate.set()
        frame = _wait(lambda: _settled_frames(sink))[0]
    assert frame["request_id"] == "turn-1" and frame["exit_code"] == 0


# ── the outbox's own transitions ────────────────────────────────────────────


def _pending():
    return record_settle(
        client_message_id=CMID, session_id=SESSION, request_id="r1",
        exit_code=1, outcome=TurnOutcome(),
    )


def test_backoff_doubles_and_only_a_taken_frame_is_an_attempt():
    record = _pending()
    start = now()
    after_one = note_push(record.settle_id, delivered_to=1, at=start)
    assert after_one.attempts == 1 and after_one.state == STATE_PENDING
    assert due_settles(start + timedelta(seconds=1)) == []
    assert [r.settle_id for r in due_settles(start + timedelta(seconds=2.1))] == [record.settle_id]
    after_two = note_push(record.settle_id, delivered_to=1, at=start + timedelta(seconds=3))
    assert due_settles(start + timedelta(seconds=6)) == []
    assert due_settles(start + timedelta(seconds=7.1))
    nobody = note_push(record.settle_id, delivered_to=0, at=start + timedelta(seconds=8))
    assert nobody.attempts == after_two.attempts == 2


def test_no_listener_for_an_hour_is_undelivered_with_its_reason():
    record = _pending()
    later = now() + timedelta(seconds=settles.NO_LISTENER_SECONDS + 1)
    updated = note_push(record.settle_id, delivered_to=0, at=later)
    assert updated.state == STATE_UNDELIVERED
    assert updated.undelivered_reason == settles.UNDELIVERED_NO_LISTENER


def test_record_is_idempotent_on_session_and_client_message_id():
    first = _pending()
    again = record_settle(
        client_message_id=CMID, session_id=SESSION, request_id="r2",
        exit_code=0, outcome=TurnOutcome(),
    )
    assert again == first
    assert ack_settle(first.settle_id) is True
    assert ack_settle(first.settle_id) is False
    assert ack_settle("no-such-settle") is False


@pytest.mark.parametrize("refusal", sorted(settles.NON_TERMINAL_REFUSALS))
def test_a_duplicate_in_flight_answer_is_not_a_settle(refusal):
    assert record_settle(
        client_message_id=CMID, session_id=SESSION, request_id="r1",
        exit_code=2, outcome=TurnOutcome(refusal_class=refusal),
    ) is None


# ── the settle record is a new durable surface: no secret reaches it ────────

_LEAKED_KEY = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"


@pytest.mark.parametrize(
    "line",
    [
        {"ok": False, "error_kind": "chat_provider_failed",
         "error": f"invalid key {_LEAKED_KEY}",
         "next_expected": f"replace {_LEAKED_KEY} in .env"},
        {"kind": "error", "error": {"code": "provider_auth", "message": f"key {_LEAKED_KEY} rejected",
                                     "hint": f"rotate {_LEAKED_KEY}"}},
    ],
)
def test_summary_and_fix_hint_are_redacted_before_they_are_recorded(line):
    outcome = settles.outcome_from_result_lines([json.dumps(line)])
    # Positive control: the line DID carry text into both fields.
    assert outcome.summary and outcome.fix_hint
    assert _LEAKED_KEY not in outcome.summary
    assert _LEAKED_KEY not in outcome.fix_hint
