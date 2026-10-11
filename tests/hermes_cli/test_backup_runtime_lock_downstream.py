"""Full backups skip the live serve's socket lock (L8.12): a held lock is unreadable on Windows."""

from __future__ import annotations

from pathlib import Path

from agent_runtime.paths import SOCKET_LOCK_FILENAME
from hermes_cli import backup


def test_the_serve_socket_lock_is_excluded_wherever_it_sits():
    assert backup._should_exclude(Path("agent-runtime") / SOCKET_LOCK_FILENAME)
    assert backup._should_exclude(Path("profiles") / "alice" / "agent-runtime" / SOCKET_LOCK_FILENAME)


def test_other_lock_named_files_are_still_backed_up():
    assert not backup._should_exclude(Path("agent-runtime") / "serve_socket.owner.json")
    assert not backup._should_exclude(Path("project") / "uv.lock")
