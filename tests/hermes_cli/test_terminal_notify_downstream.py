"""``write_tty`` never opens ``/dev/tty`` on Windows (L4.04): the path is a FILE under the drive root there."""

from __future__ import annotations

import io

from hermes_cli import terminal_notify


def _capture(monkeypatch, os_name):
    opened: list[str] = []

    def _spy_open(path, *args, **kwargs):
        opened.append(str(path))
        return io.StringIO()

    stdout = io.StringIO()
    monkeypatch.setattr(terminal_notify, "open", _spy_open, raising=False)
    monkeypatch.setattr(terminal_notify.sys, "stdout", stdout)
    monkeypatch.setattr(terminal_notify.os, "name", os_name)
    terminal_notify.write_tty("\x07")
    monkeypatch.undo()
    return opened, stdout.getvalue()


def test_windows_writes_to_stdout_and_never_opens_dev_tty(monkeypatch):
    opened, written = _capture(monkeypatch, "nt")
    assert opened == []
    assert written == "\x07"


def test_posix_still_prefers_dev_tty(monkeypatch):
    opened, written = _capture(monkeypatch, "posix")
    assert opened == ["/dev/tty"]
    assert written == ""
