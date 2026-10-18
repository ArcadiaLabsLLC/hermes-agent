"""The fork's completion-queue event types are ONE table every upstream drain reads.

A new fork event type is a row in ``tools/fork_completion_events.py``; the gateway drain keeps it
and both formatters render it without another upstream hunk.
"""

import queue

import pytest

from tools import fork_completion_events as fce


PLANTED = "planted_fork_event"


@pytest.fixture
def planted(monkeypatch):
    settled: list[dict] = []

    def settle(evt):
        settled.append(dict(evt))
        return True

    table = {**fce.FORK_COMPLETION_EVENTS, PLANTED: fce.ForkCompletionEvent(
        format=lambda evt: f"[IMPORTANT: planted {evt.get('job_id')}]", settle=settle)}
    monkeypatch.setattr(fce, "FORK_COMPLETION_EVENTS", table)
    return settled


def test_a_registered_type_survives_the_gateway_drain_with_no_gateway_edit(planted):
    from gateway.run import _drain_gateway_watch_events

    q: queue.Queue = queue.Queue()
    evt = {"type": PLANTED, "job_id": "j1"}
    q.put(evt)
    q.put({"type": "completion", "session_id": "proc_1"})

    assert _drain_gateway_watch_events(q) == [evt]


def test_both_formatters_render_a_registered_type(planted):
    from gateway.run import _format_gateway_process_notification
    from tools.process_registry_notifications import format_process_notification

    evt = {"type": PLANTED, "job_id": "j1"}
    assert _format_gateway_process_notification(evt) == "[IMPORTANT: planted j1]"
    assert format_process_notification(evt) == "[IMPORTANT: planted j1]"


def test_an_unregistered_type_is_left_to_upstream():
    assert not fce.is_fork_completion_event("completion")
    assert fce.format_fork_completion_event({"type": "completion"}) is None
    assert fce.settle_fork_completion_event({"type": "completion"}) is False
    assert fce.is_fork_completion_event("mcp_job_finished")
