"""A process-wide fake ``threading.Thread`` does not reach the stdlib's pipe readers here.

``tests._downstream.tui_gateway_conftest`` rides ``tests/tui_gateway/conftest.py`` and pins
``subprocess``'s ``Thread`` to the real class, so upstream's
``monkeypatch.setattr(server.threading, "Thread", _FakeThread)`` (which replaces
``threading.Thread`` everywhere) leaves ``Popen.communicate`` working on Windows, where it
reads each pipe on a thread.
"""

from __future__ import annotations

import subprocess
import sys
import threading

from tui_gateway import server


class _ImmediateThread:
    """The upstream shape that broke ``communicate``: runs ``target()`` with no args, no ``join``."""

    def __init__(self, target=None, **_kwargs):
        self._target = target

    def start(self):
        self._target()


def test_directory_half_is_registered_with_directory_scope(request):
    assert "_subprocess_keeps_real_threads" in request.fixturenames
    assert request.config.pluginmanager.get_plugin("tests._downstream.tui_gateway_conftest:hooks") is not None


def test_a_faked_server_thread_leaves_subprocess_pipes_readable(monkeypatch):
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    assert threading.Thread is _ImmediateThread  # the fake is process-wide, as upstream wrote it
    done = subprocess.run(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert (done.stdout.strip(), done.stderr.strip()) == ("out", "err")
