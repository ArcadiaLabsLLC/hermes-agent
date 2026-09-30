"""The local dispatch leg's child process: ``tools.agent_chat_dispatch.local._spawn_child``'s spawn.

A sibling module so the supervisor pool carries no process spawn where none may start:
``local._spawn_child`` imports this only when ``conversations.subprocess_worker`` is on,
and the bundled phone profile switches it off. Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

__layer__ = "lanes"
__all__ = ["spawn_child"]


def spawn_child(argv: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Start the child: both streams piped, stdin closed, hidden on Windows."""

    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        # Never inherit the parent's stdin: in serve that is the launcher's
        # request pipe, and a child reading from it would steal requests.
        "stdin": subprocess.DEVNULL,
        "env": env,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name == "nt":
        try:
            from hermes_cli._subprocess_compat import windows_hide_flags

            popen_kwargs["creationflags"] = windows_hide_flags()
        except Exception:
            pass
    return subprocess.Popen(argv, **popen_kwargs)
