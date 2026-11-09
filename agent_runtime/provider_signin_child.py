"""The sign-in child: ``hermes harness auth login --json`` as a process.

A sibling module so the sign-in sessions carry no process spawn where none may start:
``provider_signin.spawn_login_child`` imports this only when ``auth.subprocess_signin``
selects it (:func:`agent_runtime.provider_signin.select_login_runner`), and the bundled
phone profile, which runs the same sign-in in process, switches this module off.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import Iterable, Optional

from agent_runtime import process_index

__layer__ = "stores"
__all__ = ["prewarm_login_child", "spawn_login_child"]


class _PopenChild:
    """The default :class:`LoginChild`: native sign-in in a hidden child."""

    def __init__(self, argv: list[str], env: dict[str, str], home: str = "") -> None:
        self.home = home
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )
        # A hard serve exit can leave it running: the Launcher's sweep must name it (D1.09).
        process_index.record_child(getattr(self._proc, "pid", None))

    def alive(self) -> bool:
        return self._proc.poll() is None

    def lines(self) -> Iterable[str]:
        assert self._proc.stdout is not None
        yield from self._proc.stdout
        self._proc.wait()
        process_index.forget_child(getattr(self._proc, "pid", None))

    def write_line(self, text: str) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(text + "\n")
        self._proc.stdin.flush()

    def terminate(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        process_index.forget_child(getattr(self._proc, "pid", None))


_WARM_LOCK = threading.Lock()
_WARM: Optional[_PopenChild] = None


def _same_home(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _child_env(home: str) -> dict[str, str]:
    return {**os.environ, "HERMES_HOME": home}


def prewarm_login_child() -> bool:
    """Start one warm sign-in child for this home (RT-PROVIDER-SIGNIN-COLD-CHILD); True when one started.

    One at a time: a live warm child for the same home is kept, one for another home is
    discarded. It is recorded in ``process_index`` like the cold child.
    """
    from hermes_constants import get_hermes_home

    global _WARM
    home = str(get_hermes_home())
    with _WARM_LOCK:
        if _WARM is not None and _WARM.alive() and _same_home(_WARM.home, home):
            return False
        if _WARM is not None:
            _WARM.terminate()
        _WARM = _PopenChild([sys.executable, "-m", "agent_runtime.provider_signin_warm"], _child_env(home), home)
        return True


def _take_warm(target_home: str) -> Optional[_PopenChild]:
    """The warm child, if one is alive for ``target_home``; any other is discarded. Single use."""
    global _WARM
    with _WARM_LOCK:
        warm, _WARM = _WARM, None
    if warm is None:
        return None
    if warm.alive() and _same_home(warm.home, target_home):
        return warm
    warm.terminate()
    return None


def spawn_login_child(provider: str, flow: str, profile: str | None) -> _PopenChild:
    """Run ``hermes harness auth login <provider> --json --flow <flow>`` under this home.

    A warm child for the sign-in's home takes the request; otherwise a cold child starts.
    """
    from hermes_cli.auth_noninteractive import resolve_target_home
    from hermes_constants import get_hermes_home

    warm = _take_warm(resolve_target_home(profile)[0])
    if warm is not None:
        try:
            warm.write_line(json.dumps({"provider": provider, "flow": flow, "profile": profile}))
            return warm
        except OSError:  # it died between the check and the write: start cold
            warm.terminate()
    argv = [sys.executable, "-m", "hermes_cli.main", "harness", "auth", "login", provider, "--json", "--flow", flow]
    if profile:
        argv += ["--profile", profile]
    home = str(get_hermes_home())
    return _PopenChild(argv, _child_env(home), home)
