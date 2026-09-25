"""The coercion owners (program rule 15): ``serde.safe_text`` / ``safe_block`` /
``safe_int`` / ``positive_int`` and ``clock.elapsed_ms``.

Lane H2 folded the mission-chat stream's private copies (``_safe_stream_text``,
``_safe_stream_block``, ``_safe_exit_code_value``, ``_elapsed_ms``,
``_positive_int_or_zero``) and ``mission_chat_turns._safe_block_text`` into
these. No test pinned the copies' contracts — a whitespace-collapsing
``safe_block`` passed every stream test — so the owners are pinned here.
"""

from __future__ import annotations

import time

from agent_runtime import clock, serde


def test_safe_text_is_one_bounded_line_or_none():
    assert serde.safe_text("  a\n\tb\x00c  ", limit=80) == "a b c"
    assert serde.safe_text("abcdef", limit=3) == "abc"
    assert serde.safe_text("   ", limit=10) is None
    assert serde.safe_text(None, limit=10) is None


def test_safe_block_keeps_lines_and_marks_a_cut():
    block = "key: 1\r\nother: 2\rlast\x00x"
    assert serde.safe_block(block, limit=100) == "key: 1\nother: 2\nlast x"
    assert serde.safe_block("abcdef", limit=3) == "abc\n…(rest truncated)…"
    assert serde.safe_block("  \n ", limit=10) is None


def test_safe_int_coerces_or_answers_none():
    assert serde.safe_int("7") == 7
    assert serde.safe_int(-2) == -2
    assert serde.safe_int("x") is None
    assert serde.safe_int(None) is None
    assert serde.safe_int(float("inf")) is None


def test_positive_int_floors_at_its_default():
    assert serde.positive_int("5") == 5
    assert serde.positive_int(0) is None
    assert serde.positive_int(-3, default=0) == 0
    assert serde.positive_int("nope", default=0) == 0


def test_elapsed_ms_is_non_negative_or_none():
    assert clock.elapsed_ms(time.monotonic() + 60) == 0
    assert clock.elapsed_ms(time.monotonic() - 1.5) >= 1500
    assert clock.elapsed_ms("not a stamp") is None
    assert clock.elapsed_ms(None) is None


def test_non_negative_int_keeps_zero_and_refuses_negatives():
    """Lane R2 folded ``prompt_observability._safe_int`` and
    ``mission_chat_turns._safe_int`` (both: int >= 0, else None) into this."""

    assert serde.non_negative_int("7") == 7
    assert serde.non_negative_int(0) == 0
    assert serde.non_negative_int(-1) is None
    assert serde.non_negative_int("x") is None
    assert serde.non_negative_int(None) is None


def test_strict_int_refuses_bool():
    """Lane R2 folded ``persona_chat_history._safe_trace_int`` (a trace's
    ``exit_code`` / ``duration_ms``: ``True`` is not exit code 1) into this."""

    assert serde.strict_int(True) is None
    assert serde.strict_int(False) is None
    assert serde.strict_int("3") == 3
    assert serde.strict_int(-2) == -2
    assert serde.strict_int("x") is None
