"""FORK-TEST-PREWARM-ISOLATION-UNPINNED: a prewarm never builds an in-process agent for a
compute-host session.

`tui_gateway.server._schedule_agent_build` returns lazy for a session whose turns run on the
compute host (turn isolation on, no in-process agent yet). A prewarm there would build an
AIAgent in-process, and `_session_uses_compute_host` (agent is None) would then route the
turn in-process: isolation lost. Native conversations return lazy earlier
(`source: eternia_intelligence`), so the native round trip no longer exercises this arm; this
unit pins it with a session that is NOT an intelligence session.
"""

import contextlib
import threading
import types

import pytest

from tui_gateway import server


class _RecordingTimer:
    started: list = []

    def __init__(self, delay, fn):
        self.fn = fn
        self.daemon = False

    def start(self):
        _RecordingTimer.started.append(self.fn)


@pytest.fixture
def harness(monkeypatch):
    _RecordingTimer.started = []
    monkeypatch.setattr(server, "threading", types.SimpleNamespace(Timer=_RecordingTimer))
    monkeypatch.setattr(server, "_session_profile_runtime_scope", lambda *a, **k: contextlib.nullcontext())
    built: list[str] = []
    monkeypatch.setattr(server, "_start_agent_build", lambda sid, session: built.append(sid))

    def with_isolation(enabled: bool) -> dict:
        monkeypatch.setattr(server, "_load_dashboard_process_isolation_config",
                            lambda: {"turn_isolation": enabled})
        session = {"source": "tui", "agent": None, "agent_ready": threading.Event()}
        monkeypatch.setitem(server._sessions, "sid-prewarm", session)
        return session

    return with_isolation, built


def test_a_compute_host_session_is_left_lazy_and_never_prewarmed(harness):
    with_isolation, built = harness
    session = with_isolation(True)

    server._schedule_agent_build("sid-prewarm")

    assert session.get("lazy") is True
    assert _RecordingTimer.started == [] and built == []


def test_without_turn_isolation_the_same_session_prewarms(harness):
    """Positive control: the arm above is the compute-host check, not a session that never builds."""
    with_isolation, built = harness
    session = with_isolation(False)

    server._schedule_agent_build("sid-prewarm")

    assert "lazy" not in session
    assert len(_RecordingTimer.started) == 1
    _RecordingTimer.started[0]()
    assert built == ["sid-prewarm"]
