"""Fork-owned half of ``tests/tui_gateway/conftest.py``: the stdlib's subprocess keeps its own threads.

Upstream's TUI server tests fake a thread with
``monkeypatch.setattr(server.threading, "Thread", _FakeThread)``. ``server.threading`` IS the
``threading`` module, so the fake replaces ``threading.Thread`` for the whole process. On
Windows ``subprocess.Popen.communicate`` reads each pipe on a ``threading.Thread``; any
subprocess the code under test runs while the fake is in place (a git probe, a version check)
gets the fake: ``TypeError: Popen._readerthread() missing 2 required positional arguments``
from an immediate-run fake, ``'_FakeThread' object has no attribute 'join'`` from a recording
one. POSIX ``communicate`` uses a selector and never saw it.

The fixture below gives ``subprocess`` a private view of ``threading`` whose ``Thread`` is the
real class, pinned for the test. The tests' fake still replaces ``Thread`` for the code under
test; only the stdlib's pipe readers are shielded. Attached by the root ``conftest.py`` when
pytest registers ``tests/tui_gateway/conftest.py`` (its fixtures keep that directory's scope).
"""

from __future__ import annotations

import subprocess
import threading
import types

import pytest


class _SubprocessThreading(types.ModuleType):
    """``threading`` as ``subprocess`` sees it: the real ``Thread``, every other name live."""

    def __init__(self, real_thread) -> None:
        super().__init__("threading")
        self.Thread = real_thread

    def __getattr__(self, name):
        return getattr(threading, name)


@pytest.fixture(autouse=True)
def _subprocess_keeps_real_threads(monkeypatch):
    """Pin ``subprocess``'s ``Thread`` to the real class for one test."""
    monkeypatch.setattr(subprocess, "threading", _SubprocessThreading(threading.Thread))
    yield
