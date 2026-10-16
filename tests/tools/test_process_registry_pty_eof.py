"""close_stdin on a PTY session sends the platform's end-of-input."""

import time

import tools.process_registry as pr
from tools.process_registry import ProcessRegistry, ProcessSession


class _FakePty:
    def __init__(self):
        self.calls = []

    def write(self, data):
        self.calls.append(("write", data))

    def sendeof(self):
        self.calls.append(("sendeof",))


def _pty_session(registry):
    session = ProcessSession(id="proc_pty_eof", command="cat", task_id="t1", started_at=time.time())
    session._pty = _FakePty()
    registry._running[session.id] = session
    return session


def test_close_stdin_writes_ctrl_z_enter_on_windows(monkeypatch):
    monkeypatch.setattr(pr, "_IS_WINDOWS", True)
    registry = ProcessRegistry()
    session = _pty_session(registry)

    result = registry.close_stdin(session.id)

    assert result == {"status": "ok", "message": "EOF sent"}
    assert session._pty.calls == [("write", "\x1a\r\n")]


def test_close_stdin_sends_posix_eof_off_windows(monkeypatch):
    monkeypatch.setattr(pr, "_IS_WINDOWS", False)
    registry = ProcessRegistry()
    session = _pty_session(registry)

    result = registry.close_stdin(session.id)

    assert result == {"status": "ok", "message": "EOF sent"}
    assert session._pty.calls == [("sendeof",)]
