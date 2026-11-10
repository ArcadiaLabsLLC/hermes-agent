"""Fork-owned half of ``tests/tui_gateway/test_compute_host_pending_model_switch.py``.

Shared-provider correction 2026-09-29: on a compute-host (turn-isolation) session an IDLE
model pick returns the existing compute owner's receipt, so upstream's idle-defers test is
strict-xfailed by id (``tests/_downstream/id_markers/fork_marks.py``). A BUSY isolated turn
must still never be mutated: the pick is stashed and no second agent is built in the server.
"""

from __future__ import annotations

from tests.tui_gateway.test_compute_host_pending_model_switch import _session
from tui_gateway import server


def test_config_set_model_defers_on_busy_compute_host_session(monkeypatch):
    """A running isolated turn must not be mutated."""
    session = _session(_compute_host_active=True, running=True)
    server._sessions["sid-cfgset"] = session
    build_calls = []
    monkeypatch.setattr(server, "_start_agent_build", lambda *a, **k: build_calls.append(a))
    try:
        resp = server.handle_request(
            {"id": "1", "method": "config.set",
             "params": {"session_id": "sid-cfgset", "key": "model", "value": "anthropic/claude-sonnet-4.6"}})
        assert resp["result"].get("deferred") is True
        assert session["pending_model_switch"]["raw"] == "anthropic/claude-sonnet-4.6"
        # The broken path built a second agent inside the server process.
        assert build_calls == []
    finally:
        server._sessions.pop("sid-cfgset", None)
