"""Fork-owned test moved out of ``tests/tools/test_oneshot_completion_linger.py``.

A finished child is not delivered until its completion notification reaches the
queue. The ``registry`` fixture and ``_make_session`` are upstream's.
"""

from __future__ import annotations

import threading

from tests.tools.test_oneshot_completion_linger import (  # noqa: F401 — upstream names the moved test uses
    _make_session,
    registry,
)


def test_linger_waits_until_completion_notification_is_published(registry, monkeypatch):
    """A finished child is not delivered until its notification reaches the queue."""
    session = _make_session(exited=True)
    registry._running[session.id] = session
    publishing, release = threading.Event(), threading.Event()
    real_put = registry.completion_queue.put

    def delayed_put(event):
        publishing.set()
        if not release.wait(5):
            raise TimeoutError("test did not release notification publication")
        real_put(event)

    monkeypatch.setattr(registry.completion_queue, "put", delayed_put)
    thread = threading.Thread(target=registry._move_to_finished, args=(session,))
    thread.start()
    try:
        assert publishing.wait(5)
        result = registry.wait_for_pending_completions(timeout=0.05)
        assert result["waited"] == [session.id]
        assert result["timed_out"] == [session.id]
        assert not session._completion_event.is_set()
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert session._completion_event.is_set()
    assert registry.completion_queue.get_nowait()["session_id"] == session.id
