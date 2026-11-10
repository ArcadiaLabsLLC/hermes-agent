"""``python -m agent_runtime.provider_signin_warm`` — a sign-in child started before the press.

The cold child (``python -m hermes_cli.main harness auth login …``) spent 3.7–4.4 s in its
imports before the browser could open (RT-PROVIDER-SIGNIN-COLD-CHILD). This child pays that
cost ahead: it imports what the cold child imports plus the sign-in drivers, then blocks on
ONE stdin line ``{"provider", "flow", "profile"}`` and runs the same command
(``auth_login_command``) with the same NDJSON on stdout and a pasted code on stdin. It stays
a process so a cancelled sign-in is still killed whole (a thread cannot be). Unused, it exits
after :data:`IDLE_SECONDS`, or at once when its parent closes stdin.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import threading
from types import SimpleNamespace
from typing import TextIO

__layer__ = "stores"
__all__ = ["IDLE_SECONDS", "WARM_MODULES", "main"]

#: How long an unused warm child waits for a sign-in before it exits.
IDLE_SECONDS = 600.0

#: The cold child's entry module, then the drivers ``run_browser_login`` imports per provider.
WARM_MODULES = (
    "hermes_cli.main",
    "hermes_cli.auth_noninteractive",
    "hermes_cli.provider_browser_login",
    "hermes_cli.auth",
    "hermes_cli.auth_commands",
    "hermes_cli.auth_codex",
    "hermes_cli.auth_codex_browser",
    "hermes_cli.auth_xai",
    "hermes_cli.auth_minimax",
    "hermes_cli.auth_nous",
    "hermes_cli.anon_auth",
    "agent.anthropic_credentials",
)


def _warm() -> None:
    for name in WARM_MODULES:
        try:
            importlib.import_module(name)
        except Exception:  # a driver that cannot import fails its own sign-in, as cold
            pass


def main(stdin: TextIO | None = None, idle_seconds: float = IDLE_SECONDS) -> int:
    """Warm, wait for one request, run it; 0 with no request."""
    _warm()
    stdin = stdin or sys.stdin
    timer = threading.Timer(idle_seconds, os._exit, (0,))
    timer.daemon = True
    timer.start()
    try:
        line = stdin.readline()
    finally:
        timer.cancel()
    if not line.strip():
        return 0
    request = json.loads(line)
    from hermes_cli.auth_noninteractive import auth_login_command

    return auth_login_command(SimpleNamespace(provider=request.get("provider"), flow=request.get("flow"),
                                              profile=request.get("profile"), json=True))


if __name__ == "__main__":
    raise SystemExit(main())
