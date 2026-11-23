"""``persona_chat`` times three projections; one receipt says which one paid (w1122f-agentlist).

After the history curation cuts of 2026-11-22 the owner's steady ``persona_chat`` still
read 1,090 ms, with nothing saying whether the history, the trace or the operator
channels paid it. Like ``snapshot_agents_readiness`` (``test_agents_readiness_attribution``)
the split is a LOG line beside ``snapshot_build_core``, never parity keys, and the gate
injects a known delay into ONE part on a controlled clock and requires the others not
to carry it.
"""

from __future__ import annotations

import logging
import re
import time
from types import SimpleNamespace

import pytest

from agent_runtime import snapshot as snapshot_module
from agent_runtime.snapshot import build_snapshot

_INJECTED_DELAY_SECONDS = 0.25
_INJECTED_DELAY_MS = _INJECTED_DELAY_SECONDS * 1000
_RECEIPT = re.compile(r"snapshot_persona_chat history_ms=(\d+) trace_ms=(\d+) channels_ms=(\d+) pid=(\d+)")


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _build_and_split(mp) -> tuple[int, int, int]:
    handler = _ListHandler()
    logger = logging.getLogger(snapshot_module.__name__)
    previous = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        build_snapshot()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    matches = [_RECEIPT.fullmatch(r.getMessage()) for r in handler.records
               if r.getMessage().startswith("snapshot_persona_chat ")]
    assert len(matches) == 1 and matches[0] is not None, [r.getMessage() for r in handler.records]
    return int(matches[0].group(1)), int(matches[0].group(2)), int(matches[0].group(3))


def _controlled_clock(mp) -> list[float]:
    clock = [0.0]
    fake = SimpleNamespace(**{**vars(time), "perf_counter": lambda: clock[0]})
    for module in (snapshot_module.build_log, snapshot_module.envelope, snapshot_module.sections,
                   snapshot_module.summaries):
        mp.setattr(module, "time", fake)
    return clock


def test_a_slow_trace_lands_on_the_trace_number(isolate_agent_runtime_root):
    """MUTATION (red recorded 2026-11-22): time the trace under ``history_ms`` in
    ``SnapshotFrameBuild.persona_chat`` -> history carries the delay and trace reads 0."""

    real = snapshot_module.sections.persona_chat_trace_summary
    with pytest.MonkeyPatch.context() as mp:
        clock = _controlled_clock(mp)

        def slow(**kwargs):
            clock[0] += _INJECTED_DELAY_SECONDS
            return real(**kwargs)

        mp.setattr(snapshot_module.sections, "persona_chat_trace_summary", slow)
        history, trace, channels = _build_and_split(mp)

    assert trace >= _INJECTED_DELAY_MS * 0.8, (history, trace, channels)
    assert history < _INJECTED_DELAY_MS * 0.5 and channels < _INJECTED_DELAY_MS * 0.5, (history, trace, channels)


def test_a_slow_history_lands_on_the_history_number(isolate_agent_runtime_root):
    """MUTATION (red recorded 2026-11-22): drop the ``history_ms`` span -> history reads 0."""

    real = snapshot_module.sections.persona_chat_frame_history
    with pytest.MonkeyPatch.context() as mp:
        clock = _controlled_clock(mp)

        def slow(**kwargs):
            clock[0] += _INJECTED_DELAY_SECONDS
            return real(**kwargs)

        mp.setattr(snapshot_module.sections, "persona_chat_frame_history", slow)
        history, trace, channels = _build_and_split(mp)

    assert history >= _INJECTED_DELAY_MS * 0.8, (history, trace, channels)
    assert trace < _INJECTED_DELAY_MS * 0.5 and channels < _INJECTED_DELAY_MS * 0.5, (history, trace, channels)


def test_the_split_stays_off_the_wire(isolate_agent_runtime_root):
    sections = build_snapshot()["parity"]["sections_ms"]

    assert isinstance(sections["persona_chat"], int)
    assert [key for key in sections if key.startswith("persona_chat_")] == []
