"""Fork-owned tests moved out of ``tests/tui_gateway/test_tui_gateway_server.py`` (lane CARRY).

The fork's ``tui_gateway.session_notifications._tui_background_agent_turns_enabled``
makes completion delivery status-only by default; upstream's poller tests run
the agent-turn lane with ``background_agent_turns_on`` applied by id from
``tests/_downstream/id_markers.py``, and the default's own assertions are here.
"""

import threading
from tui_gateway import server

from tests.tui_gateway.test_tui_gateway_server import (  # noqa: F401 — upstream names the moved tests use
    _ImmediateThread,
    _neuter_agent_prewarm_timer,
    _reap_leaked_notification_pollers,
    _session,
)


def test_notification_poller_legacy_agent_turn_env_opt_in(monkeypatch):
    """Explicit opt-in preserves the old completion→agent-turn behavior."""
    from tools.process_registry import process_registry

    turns = []
    emitted = []

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None, **_kwargs
        ):
            turns.append(prompt)
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target
        def start(self):
            self._target()

    sess = _session(agent=_Agent())
    server._sessions["sid_poll_legacy"] = sess
    monkeypatch.setenv("HERMES_BACKGROUND_AGENT_TURNS", "true")
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: emitted.append(a))
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()
    process_registry._completion_consumed.discard("proc_poller_legacy")

    process_registry.completion_queue.put({
        "type": "completion",
        "session_id": "proc_poller_legacy",
        "command": "echo hello",
        "exit_code": 0,
        "output": "hello",
    })
    stop = threading.Event()
    stop.set()

    try:
        server._notification_poller_loop(stop, "sid_poll_legacy", sess)
        assert len(turns) == 1
        assert "[IMPORTANT: Background process proc_poller_legacy completed" in turns[0]
    finally:
        server._sessions.pop("sid_poll_legacy", None)
        while not process_registry.completion_queue.empty():
            process_registry.completion_queue.get_nowait()


def test_tui_background_agent_turns_can_be_enabled_by_config(monkeypatch):
    monkeypatch.delenv("HERMES_BACKGROUND_AGENT_TURNS", raising=False)
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"display": {"background_process_agent_turns": True}},
    )

    assert server._tui_background_agent_turns_enabled() is True


def test_notification_poller_delivers_status_only_by_default(monkeypatch):
    """Poller surfaces completion as status only; agent turns are legacy opt-in."""
    import queue as _queue_mod

    from tools.process_registry import process_registry

    turns = []
    emitted = []

    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, stream_callback=None, **_kwargs):
            turns.append(prompt)
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, **_thread_options):
            self._target = target
        def start(self):
            self._target()

    sess = _session(agent=_Agent())
    server._sessions["sid_poll"] = sess
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: emitted.append(a))
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    # Isolate the completion queue for the duration of this test. The poller
    # reads process_registry.completion_queue by attribute at runtime; the
    # event below carries no session_key, so any *other* poller (a leaked
    # daemon thread from another test, or a concurrent one in the same xdist
    # worker) is allowed to dequeue and dispatch it to its own session — whose
    # agent may be a fixture double without run_conversation. A fresh Queue
    # here fully isolates this test; monkeypatch restores the original on
    # teardown. (Same pattern as test_notification_poller_requeues_when_busy.)
    isolated_queue: _queue_mod.Queue = _queue_mod.Queue()
    monkeypatch.setattr(process_registry, "completion_queue", isolated_queue)
    process_registry._completion_consumed.discard("proc_poller_test")

    stop = threading.Event()

    # Put event on queue, then immediately signal stop so the poller
    # runs exactly one iteration.
    isolated_queue.put({
        "type": "completion",
        "session_id": "proc_poller_test",
        "command": "echo hello OPENAI_API_KEY=sk-testsecret1234567890",
        "exit_code": 0,
        "output": "hello\nOPENAI_API_KEY=sk-outputsecret1234567890",
    })
    stop.set()

    try:
        server._notification_poller_loop(stop, "sid_poll", sess)

        # Should have emitted a status.update with kind=process
        status_calls = [a for a in emitted if a[0] == "status.update"]
        assert len(status_calls) >= 1
        assert status_calls[0][2]["kind"] == "process"
        status_text = status_calls[0][2]["text"]
        assert "Background Process Finished:" in status_text
        assert "sk-testsecret" not in status_text
        assert "sk-outputsecret" not in status_text

        # Should not trigger an agent turn unless legacy opt-in is enabled.
        assert len(turns) == 0
    finally:
        server._sessions.pop("sid_poll", None)
        while not process_registry.completion_queue.empty():
            process_registry.completion_queue.get_nowait()
def test_notification_poller_status_only_when_busy_by_default(monkeypatch):
    """When the agent is busy, default status-only notifications do not requeue."""
    import queue as _queue_mod

    from tools.process_registry import process_registry

    emitted = []

    sess = _session(running=True)  # agent is busy
    server._sessions["sid_busy"] = sess
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: emitted.append(a))

    # Isolate the completion queue for the duration of this test. The poller
    # reads process_registry.completion_queue by attribute at runtime, so a
    # fresh Queue here means no concurrently-running test in the same xdist
    # worker can put/get on the shared singleton mid-run and drain the event
    # we expect to be requeued. monkeypatch restores the original on teardown.
    isolated_queue: _queue_mod.Queue = _queue_mod.Queue()
    monkeypatch.setattr(process_registry, "completion_queue", isolated_queue)
    process_registry._completion_consumed.discard("proc_busy_test")

    evt = {
        "type": "completion",
        "session_id": "proc_busy_test",
        "command": "make build",
        "exit_code": 0,
        "output": "ok",
    }
    isolated_queue.put(evt)

    stop = threading.Event()
    stop.set()

    try:
        server._notification_poller_loop(stop, "sid_busy", sess)

        # Status update was emitted (user sees it)
        status_calls = [a for a in emitted if a[0] == "status.update"]
        assert len(status_calls) == 1

        # Event is consumed after the status-only update; no synthetic agent turn
        # should be queued ahead of a human message unless legacy opt-in is set.
        assert isolated_queue.empty()
    finally:
        server._sessions.pop("sid_busy", None)
        while not process_registry.completion_queue.empty():
            process_registry.completion_queue.get_nowait()
