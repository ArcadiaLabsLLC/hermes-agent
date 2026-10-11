"""An MCP server's job-finished wake (``tools/mcp_job_wake.py``) survives the gateway's queue drain.

The gateway drain keeps the event types it injects and discards the rest as "handled by the
per-process watcher"; an ``mcp_job_finished`` wake has no per-process watcher, so it must be
kept and rendered like a watch event, not eaten.
"""

import queue

from gateway.run import _drain_gateway_watch_events, _format_gateway_process_notification


def _wake() -> dict:
    return {
        "type": "mcp_job_finished", "server": "launcher_qa", "job_id": "job-7", "outcome": "ready",
        "job_kind": "qa_build", "session_key": "agent:main:telegram:dm:42", "platform": "telegram",
        "chat_id": "42",
    }


def test_gateway_drain_keeps_an_mcp_job_wake_for_injection():
    q: queue.Queue = queue.Queue()
    wake = _wake()
    completion = {"type": "completion", "session_id": "proc_1"}
    q.put(wake)
    q.put(completion)

    retained = _drain_gateway_watch_events(q)

    assert retained == [wake]
    assert q.empty()  # a process completion stays the per-process watcher's; the wake is not requeued either


def test_gateway_formats_an_mcp_job_wake():
    text = _format_gateway_process_notification(_wake())

    assert text is not None
    assert "QA build ready, job job-7" in text
