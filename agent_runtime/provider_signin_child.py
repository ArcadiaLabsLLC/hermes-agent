"""The sign-in child: ``hermes harness auth login --json`` as a process.

A sibling module so the sign-in sessions carry no process spawn where none may start:
``provider_signin.spawn_login_child`` imports this only when ``auth.subprocess_signin``
selects it (:func:`agent_runtime.provider_signin.select_login_runner`), and the bundled
phone profile, which runs the same sign-in in process, switches this module off.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Iterable

__layer__ = "stores"
__all__ = ["spawn_login_child"]


class _PopenChild:
    """The default :class:`LoginChild`: native sign-in in a hidden child."""

    def __init__(self, argv: list[str], env: dict[str, str]) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )

    def lines(self) -> Iterable[str]:
        assert self._proc.stdout is not None
        yield from self._proc.stdout
        self._proc.wait()

    def write_line(self, text: str) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(text + "\n")
        self._proc.stdin.flush()

    def terminate(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()


def spawn_login_child(provider: str, flow: str, profile: str | None) -> _PopenChild:
    """Start ``hermes harness auth login <provider> --json --flow <flow>`` under this home."""
    from hermes_constants import get_hermes_home

    argv = [sys.executable, "-m", "hermes_cli.main", "harness", "auth", "login", provider, "--json", "--flow", flow]
    if profile:
        argv += ["--profile", profile]
    env = {**os.environ, "HERMES_HOME": str(get_hermes_home())}
    return _PopenChild(argv, env)
