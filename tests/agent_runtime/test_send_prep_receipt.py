"""h-prereq-window: one ``send_prep_receipt`` per turn splits anchor -> request_sent into its marks."""

from __future__ import annotations

import logging

from agent_runtime.mission_chat_phases import PHASE_ORDER, TurnPhaseMarks
from agent_runtime.send_prep_receipt import prep_segments, send_prep_line


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_a_skipped_mark_folds_into_the_next_and_marks_after_request_sent_are_left_out():
    marks = {"request_received": 0, "context_built": 100, "agent_ready": 160, "client_built": 400,
             "request_sent": 430, "response_headers": 900}

    assert prep_segments(marks, PHASE_ORDER) == {
        "context_built": 100, "agent_ready": 60, "client_built": 240, "request_sent": 30,
    }
    line = send_prep_line(marks, PHASE_ORDER, turn="m-1", anchored_at="t", cpu_ms=12.7, title_threads=1)
    assert line.startswith("send_prep_receipt turn=m-1 anchored_at=t total_ms=430 cpu_ms=12 title_threads=1 "
                           "largest=client_built ")
    assert "response_headers" not in line


def test_request_sent_logs_one_receipt_keyed_on_the_turn(caplog):
    clock = _Clock()
    marks = TurnPhaseMarks(monotonic=clock, wall_now=lambda: "2026-10-06T21:05:00Z")
    marks.receipt_turn = "m-7"
    with caplog.at_level(logging.INFO, logger="agent_runtime.send_prep_receipt"):
        clock.now += 0.2
        marks.mark("agent_ready")
        clock.now += 0.3
        marks.mark("request_sent")
        clock.now += 0.1
        marks.mark("request_sent")  # first mark wins: no second line

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("send_prep_receipt ")]
    assert len(lines) == 1
    assert " turn=m-7 anchored_at=2026-10-06T21:05:00Z total_ms=500 " in lines[0]
    assert lines[0].endswith("agent_ready_ms=200 request_sent_ms=300")
