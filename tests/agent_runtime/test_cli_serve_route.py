"""CLI-to-serve route S1: one relay loop, one typed outcome, one fallback rule.

Plan: ``docs/agent-runtime-harness/planned/cli-serve-route-2026-10-15.md`` S1. Every case
runs against a real serve socket lane on a thread of this process
(``test_serve_socket_lane.running_serve``), whose dispatch is a spy.

Kill-mutation: make ``RelayOutcome.runs_locally`` answer ``True`` for every non-served
outcome under ``FallbackPolicy.WRITE`` (the per-caller "any failure, run it here" habit
this module retires). The live-serve-failed-mid-request case then lets the write run
locally, and reds.
"""

from __future__ import annotations

import io

import pytest

from agent_runtime.serve_socket import cli_route
from agent_runtime.serve_socket.cli_route import FallbackPolicy, RelayKind, relay_argv
from tests.agent_runtime.test_serve_socket_lane import running_serve


@pytest.fixture
def not_the_serve(monkeypatch):
    # The serve under test is a thread of THIS process, so its target row carries this
    # pid; the self-dial guard would (correctly) refuse it.
    monkeypatch.setattr(cli_route, "_this_pid", lambda: -1)


def _spy(code: int = 0, *, lines: tuple[str, ...] = ("one", "two")):
    calls: list[list[str]] = []

    def dispatch(argv):
        calls.append(list(argv))
        for line in lines:
            print(line)
        return code

    return dispatch, calls


def test_a_write_runs_in_the_live_serve_and_returns_its_code(not_the_serve):
    dispatch, calls = _spy(code=3)
    with running_serve(dispatch=dispatch):
        outcome = relay_argv(["harness", "serve", "settles"], client="test-route")
    assert outcome.kind is RelayKind.SERVED, outcome
    assert outcome.code == 3
    assert outcome.lines == ("one", "two")
    assert calls == [["harness", "serve", "settles"]]
    assert outcome.runs_locally(FallbackPolicy.WRITE) is False


def test_lines_stream_to_a_sink_when_one_is_given(not_the_serve):
    dispatch, _ = _spy()
    out = io.StringIO()
    with running_serve(dispatch=dispatch):
        outcome = relay_argv(["harness", "serve", "settles"], client="test-route",
                             sink=lambda line: out.write(line + "\n"), read_lap_seconds=5.0)
    assert outcome.kind is RelayKind.SERVED
    assert outcome.lines == ()
    assert out.getvalue() == "one\ntwo\n"


def test_with_no_live_serve_a_write_may_run_locally():
    """Positive control for the write rule's one local arm."""

    outcome = relay_argv(["harness", "serve", "settles"], client="test-route")
    assert outcome.kind is RelayKind.NO_SERVE
    assert outcome.reason == "no_live_serve_socket"
    assert outcome.runs_locally(FallbackPolicy.WRITE) is True
    assert outcome.runs_locally(FallbackPolicy.READ) is True


def test_a_live_serve_that_failed_mid_request_refuses_the_write(not_the_serve):
    def failing(argv):
        raise SystemExit(2)  # the serve's parser refused the argv: an ``error`` frame

    with running_serve(dispatch=failing):
        outcome = relay_argv(["harness", "serve", "settles"], client="test-route")
    assert outcome.kind is RelayKind.REFUSED, outcome
    assert outcome.reason
    assert outcome.runs_locally(FallbackPolicy.WRITE) is False
    assert outcome.runs_locally(FallbackPolicy.TURN_HANDOFF) is False
    assert outcome.runs_locally(FallbackPolicy.READ) is True


def test_a_rejected_hello_is_unreached_and_a_write_still_refuses(not_the_serve, monkeypatch):
    dispatch, calls = _spy()
    # The serve reads the same token module, so a wrong token would be wrong on both
    # sides; refuse at the client's hello instead.
    monkeypatch.setattr("agent_runtime.serve_socket.client.ServeSocketClient.hello",
                        lambda self, **kwargs: {"event": "hello_rejected", "reason": "bad_proof"})
    with running_serve(dispatch=dispatch):
        outcome = relay_argv(["harness", "serve", "settles"], client="test-route")
    assert outcome.kind is RelayKind.UNREACHED, outcome
    assert calls == []
    assert outcome.runs_locally(FallbackPolicy.WRITE) is False
    assert outcome.runs_locally(FallbackPolicy.TURN_HANDOFF) is True


def test_this_process_being_the_serve_is_no_serve():
    dispatch, calls = _spy()
    with running_serve(dispatch=dispatch):
        outcome = relay_argv(["harness", "serve", "settles"], client="test-route")
    assert outcome.kind is RelayKind.NO_SERVE
    assert outcome.reason == "this_process_is_the_serve"
    assert calls == []
