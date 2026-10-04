"""h-chatperf: a snapshot build does not contend with a live chat turn, and the
turn's ``builds_overlapped`` sees a build that is still running.

Two defects from the 2026-10-03 cold/warm pair, each pinned where it lives:

* ``builds_overlapped`` read 0 on warm turn ``15c73e0c`` while generation 6 was
  wrapped around its whole window: the ledger only learned of a build when it
  ENDED (after its core write-back), and the turn counts at ``stream_done``.
  An open build now counts.
* builds ran beside live turns. A LEADING build now waits while a turn is in
  a latency-critical window (its pre-admit span, each provider wait), pauses
  at its yield points while one is open, and both draw on one
  bounded budget; the hydrate (``accept_inflight``) and a build on a turn's own
  thread are exempt.

Named sabotage: drop ``open_starts`` from ``overlapping_builds`` -> the
in-flight row reds; make ``BuildYield.stand_aside`` return immediately -> the
wait rows red; drop the ``inside_admitted_turn`` guard -> the own-thread row
waits out its whole budget and reds on elapsed time.
"""

from __future__ import annotations

import threading
import time

import pytest

from agent_runtime import snapshot_build_ledger as ledger
from agent_runtime import snapshot_turn_yield as yielding
from agent_runtime import turn_activity
from agent_runtime.persona_chat_actor_prewarm import (
    _ConstructionSpan,
    overlapping_constructions,
    reset_construction_spans_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_ledgers():
    ledger.reset_for_tests()
    reset_construction_spans_for_tests()
    yield
    ledger.reset_for_tests()
    reset_construction_spans_for_tests()


def test_a_build_still_running_at_stream_done_counts_as_overlapping():
    started = time.monotonic()
    token = ledger.begin_build(started=started - 5.0)  # began before the turn
    assert ledger.overlapping_builds(start=started, end=started + 2.0) == 1
    assert ledger.builds_in_flight() == 1
    ledger.end_build(token, ended=started + 3.0)
    assert ledger.builds_in_flight() == 0
    assert ledger.overlapping_builds(start=started, end=started + 2.0) == 1


def test_a_build_that_starts_after_the_window_is_not_counted():
    """Positive control: an open build that began after the window end."""

    now = time.monotonic()
    ledger.begin_build(started=now + 10.0)
    assert ledger.overlapping_builds(start=now, end=now + 1.0) == 0


def test_a_construction_still_running_counts_as_overlapping():
    now = time.monotonic()
    with _ConstructionSpan():
        assert overlapping_constructions(start=now, end=now + 60.0) == 1
    assert overlapping_constructions(start=now, end=now + 60.0) == 1


class _Script:
    """A scripted clock + admitted count: the turn holds for ``hold_s``."""

    def __init__(self, hold_s: float):
        self.now = 0.0
        self.hold_s = hold_s
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds

    def admitted(self) -> int:
        return 1 if self.now < self.hold_s else 0


def test_stand_aside_waits_exactly_while_a_turn_is_admitted():
    script = _Script(hold_s=2.0)
    state = yielding.BuildYield(budget_ms=15_000, sleep=script.sleep, clock=script.clock, admitted=script.admitted)
    state.stand_aside()
    assert 2.0 <= script.now < 2.1
    assert state.pauses == 1 and not state.exhausted
    assert 2000 <= state.waited_ms < 2100


def test_stand_aside_is_free_when_no_turn_is_admitted():
    script = _Script(hold_s=0.0)
    state = yielding.BuildYield(sleep=script.sleep, clock=script.clock, admitted=script.admitted)
    state.stand_aside()
    assert script.sleeps == 0 and state.pauses == 0


def test_the_budget_is_shared_across_every_pause_of_one_build():
    script = _Script(hold_s=100.0)
    state = yielding.BuildYield(budget_ms=3_000, sleep=script.sleep, clock=script.clock, admitted=script.admitted)
    state.stand_aside()
    state.stand_aside()
    assert state.exhausted
    assert 3000 <= state.waited_ms < 3100, "the second pause must not get a fresh budget"


def test_a_yield_point_is_inert_outside_a_yielding_build(monkeypatch):
    monkeypatch.setattr(yielding, "_turns_admitted", lambda: 1)
    started = time.monotonic()
    yielding.snapshot_yield_point()
    assert time.monotonic() - started < 0.5


def _lead_with_turn(monkeypatch, *, accept_inflight: bool, hold_s: float = 0.4) -> float:
    """Lead a build while a real admitted turn holds for ``hold_s``; return the delay."""

    from agent_runtime.snapshot import build as build_mod

    started_at: list[float] = []
    monkeypatch.setattr(
        build_mod, "_lead_build_now",
        lambda decision, caller, generation, info: started_at.append(time.monotonic()) or {},
    )
    turn_in = threading.Event()
    release = threading.Event()

    def _turn():
        with turn_activity.admitted_turn():
            turn_in.set()
            release.wait(5)

    thread = threading.Thread(target=_turn, daemon=True)
    thread.start()
    turn_in.wait(5)
    threading.Timer(hold_s, release.set).start()
    began = time.monotonic()
    build_mod._lead_build(None, "hub", 1, None, accept_inflight=accept_inflight)
    thread.join(5)
    return started_at[0] - began


def test_a_leading_build_waits_for_the_admitted_turn(monkeypatch):
    assert _lead_with_turn(monkeypatch, accept_inflight=False) >= 0.3


def test_the_hydrate_does_not_wait(monkeypatch):
    """Positive control: the same live turn, an ``accept_inflight`` build."""

    assert _lead_with_turn(monkeypatch, accept_inflight=True) < 0.2


def test_a_build_on_the_turns_own_thread_never_waits_on_itself(monkeypatch):
    from agent_runtime.snapshot import build as build_mod

    monkeypatch.setattr(build_mod, "_lead_build_now", lambda *a: {})
    monkeypatch.setattr(yielding, "SNAPSHOT_TURN_YIELD_MAX_MS", 2_000)
    with turn_activity.admitted_turn():
        began = time.monotonic()
        build_mod._lead_build(None, "cli", 1, None)
        assert time.monotonic() - began < 0.5


def test_the_frame_build_stands_aside_at_section_boundaries(monkeypatch):
    from agent_runtime.snapshot import sections

    calls: list[str] = []
    monkeypatch.setattr(
        sections, "SECTIONS",
        (("a", lambda self: calls.append("a")), ("b", lambda self: calls.append("b"))),
    )
    monkeypatch.setattr(yielding, "snapshot_yield_point", lambda: calls.append("yield"))
    frame = object.__new__(sections.SnapshotFrameBuild)
    frame.data = {}
    sections.SnapshotFrameBuild.run(frame)
    assert calls == ["yield", "a", "yield", "b"]


def test_the_hot_window_is_the_pre_admit_span_and_each_provider_wait():
    """Only the latency-critical spans are hot, and none can leak past the turn.

    Between them the stream lane must still build: that is how a running turn's
    own start row reaches the board (``test_serve_gateway_chat_reply_lanes``).
    """

    from hermes_cli.harness_parts.persona.chat_turn_commit.run import _steer_hot_window

    def _marker(step):
        return {"type": "run.progress", "phase": "timing", "step": step}

    with turn_activity.admitted_turn() as window:
        assert turn_activity.hot_turn_windows() == 1, "the pre-admit span is hot from the anchor"
        window.close()  # write_ahead
        assert turn_activity.hot_turn_windows() == 0
        _steer_hot_window(window, _marker("conversation_request_assembled"))
        assert turn_activity.hot_turn_windows() == 1, "a provider wait is hot"
        _steer_hot_window(window, _marker("conversation_request_assembled"))
        assert turn_activity.hot_turn_windows() == 1, "idempotent: a retry does not double-count"
        _steer_hot_window(window, _marker("conversation_response_headers"))
        assert turn_activity.hot_turn_windows() == 1, "headers arrive long before the first token"
        _steer_hot_window(window, _marker("conversation_provider_returned"))
        assert turn_activity.hot_turn_windows() == 0, "the window closes when the provider call returns"
        _steer_hot_window(window, _marker("conversation_request_assembled"))
    assert turn_activity.hot_turn_windows() == 0, "a window left open is closed by the turn's exit"
