"""How FAST a running chat turn's own start and end reach the stream lane. Idle box only.

The loaded-suite file (``test_serve_gateway_chat_reply_lanes.py``) asserts WHAT the
lane carries for a running turn and waits on the turn's own hold; this file runs the
same turn against the three latency ceilings that file defines, unchanged. Listed on
``scripts/test_idle_box_files.txt`` (owner ruling 2026-10-10: timing budgets run only on
an idle box, serial, never inside a parallel gate), because each ceiling is a small
multiple of one core build, and a core build is CPU work: in three full suites at load
50-67 the start row arrived after the 6 s ceiling while the frame itself was right
(FH-CHAT-REPLY-LANES-START-FRAME-WAIT-RED-UNDER-LOAD, w1115c-h2).
"""

from __future__ import annotations

import pytest

from tests.agent_runtime.test_serve_gateway_chat_reply_lanes import (  # fixtures too: pytest finds them by name here
    _END_ROW_DEADLINE_SECONDS,
    _START_ROW_ACK_CEILING_SECONDS,
    _START_ROW_ELAPSED_CEILING_SECONDS,
    _assert_the_turn_published_its_own_start_and_end,
    _run_a_slow_turn,
    head_home,
    placed_agent,
    scripted_model,
    slow_scripted_model,
)
from tests.agent_runtime.test_serve_gateway_lane import gateway_on  # a fixture


@pytest.mark.timeout(300)
def test_a_running_turns_own_start_and_end_reach_the_lane_within_a_publish_interval(
    gateway_on, placed_agent, slow_scripted_model, capfd
):
    """Both publishes are PROMPT, and the numbers are the assertion.

    Nothing else moved this runtime's event log in either window, so these are
    the turn's own two appends and nobody else's. The turn holds for at most
    ``SLOW_TURN_SECONDS``, and the start is waited for within half of it.

    The start is bounded TWICE because the two bounds answer different
    questions. Off the clock: it arrived within half the dwell of the ack, so it
    cannot be the turn's end arriving. Off the ROW: the turn had been in flight
    for at most ``_START_ROW_ELAPSED_CEILING_SECONDS`` when the frame carrying it
    was built — that is one publish interval plus a core build plus the field's
    integer floor, measured from the write-ahead stamp rather than from the ack
    that precedes it by the whole session mint.
    """

    run = _run_a_slow_turn(
        placed_agent,
        slow_scripted_model,
        start_within=_START_ROW_ACK_CEILING_SECONDS,
        end_within=_END_ROW_DEADLINE_SECONDS,
    )
    _assert_the_turn_published_its_own_start_and_end(run)
    row = run["mid"]["running_work_chat_turn_rows"][-1]
    assert run["start_row_ms"] < _START_ROW_ACK_CEILING_SECONDS * 1000.0, run["start_row_ms"]
    assert row["elapsed_seconds"] <= _START_ROW_ELAPSED_CEILING_SECONDS, row
    assert run["end_row_ms"] < _END_ROW_DEADLINE_SECONDS * 1000.0, run["end_row_ms"]
