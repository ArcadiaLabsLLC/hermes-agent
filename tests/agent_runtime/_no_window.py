"""The one spawn flag every test child carries: no console window on the operator's screen.

Owner 2026-10-15: during a landing gate a test-spawned ``python.exe`` serve opened a console
window on the desktop. A console child of a parent with no console of its own (an agent's
or a scheduler's pytest) gets a NEW visible console on win32; ``CREATE_NO_WINDOW`` gives it a
hidden console of its own instead. That console is NOT the parent's, so a test that signals
the child through the parent's console (``GenerateConsoleCtrlEvent`` to a
``CREATE_NEW_PROCESS_GROUP`` child) passes its own flags and skips ``no_window``.
``DETACHED_PROCESS`` already means "no console" and is never combined.
"""
from __future__ import annotations

import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)


def no_window(flags: int = 0) -> int:
    """``creationflags`` for a test child: ``flags`` plus ``CREATE_NO_WINDOW`` on win32 (0 elsewhere)."""

    if _DETACHED and flags & _DETACHED:
        return flags
    return flags | NO_WINDOW
