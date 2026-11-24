"""A chat turn's preparation runs before the reads it set off (lane w1123q-replytimings, 2026-11-23).

Read live on the owner's serve: three Home turns' own work was 453-625 ms of CPU
(``send_prep_receipt own_cpu_ms``) and their accept -> ``request_sent`` took 8.1, 9.3 and 11.2 s;
the CPU went to the reads the new chat set off on the shared and read lanes (``top_threads``
``harness-serve_0:5000``, ``harness-serve-read_2:3203``). A shared- or read-lane job that would
start while a turn is between its accept and its ``request_sent`` now waits for that request to
leave, bounded by ``TURN_PREP_HOLD_MAX_S``; a job the turn submits itself is never held.

Killing mutation (recorded in the CHANGE commit): ``_hold_for_turn_prep`` returning at once ->
``test_a_read_waits_for_a_preparing_turn_to_send`` reddens (the read runs inside the window).
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from agent_runtime import idle_turn_keeper, turn_activity
from hermes_cli.harness_parts.serve import request_pool
from hermes_cli.harness_parts.serve.request_pool import RequestPool


class _Marks:
    """Stands in for a turn's ``TurnPhaseMarks`` in the keeper's window table (weak-referenceable)."""


@pytest.fixture
def pool():
    pool = RequestPool(2)
    yield pool
    pool.shutdown()


def _open_window():
    marks = _Marks()
    idle_turn_keeper.note_window_opened(marks)
    return marks


@pytest.mark.timeout(30)
def test_a_read_waits_for_a_preparing_turn_to_send(pool, caplog):
    marks = _open_window()
    sent_at: list[float] = []
    try:
        threading.Timer(0.4, lambda: (sent_at.append(time.monotonic()), idle_turn_keeper.note_window_closed(marks))).start()
        with caplog.at_level(logging.INFO, logger=request_pool.__name__):
            ran_at = pool.submit_read(time.monotonic, label="runtime.operator.conversation.read").result(timeout=10)
    finally:
        idle_turn_keeper.note_window_closed(marks)
    assert sent_at and ran_at >= sent_at[0], "the read ran while the turn was still preparing its request"
    held = [r.getMessage() for r in caplog.records if r.getMessage().startswith("lane_held_for_turn")]
    assert held and "lane=read" in held[0] and "label=runtime.operator.conversation.read" in held[0], held


@pytest.mark.timeout(30)
def test_the_hold_is_bounded(pool, monkeypatch):
    monkeypatch.setattr(request_pool, "TURN_PREP_HOLD_MAX_S", 0.3)
    marks = _open_window()
    try:
        started = time.monotonic()
        ran_at = pool.submit(time.monotonic, label="argv:x").result(timeout=10)
    finally:
        idle_turn_keeper.note_window_closed(marks)
    assert 0.25 <= ran_at - started < 3.0


@pytest.mark.timeout(30)
def test_a_job_the_turn_submits_itself_is_never_held(pool):
    marks = _open_window()
    try:
        with turn_activity.admitted_turn():
            started = time.monotonic()
            ran_at = pool.submit(time.monotonic, label="argv:own").result(timeout=10)
    finally:
        idle_turn_keeper.note_window_closed(marks)
    assert ran_at - started < 0.2


def test_with_no_turn_preparing_nothing_waits(pool, caplog):
    with caplog.at_level(logging.INFO, logger=request_pool.__name__):
        started = time.monotonic()
        ran_at = pool.submit_read(time.monotonic, label="x").result(timeout=10)
    assert ran_at - started < 0.2
    assert not [r for r in caplog.records if r.getMessage().startswith("lane_held_for_turn")]
