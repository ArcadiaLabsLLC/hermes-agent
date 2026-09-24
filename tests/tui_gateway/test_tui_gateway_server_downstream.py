"""Fork-owned tests moved out of ``tests/tui_gateway/test_tui_gateway_server.py`` (lane CARRY).

Same names, same bodies. The upstream file keeps the fork's in-place carries its
ledger row names (HERMES_BACKGROUND_AGENT_TURNS replaces upstream's delivery).
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
