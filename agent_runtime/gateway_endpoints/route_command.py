"""The routing-table spawn of :mod:`agent_runtime.gateway_endpoints.routes` (R-D8).

A sibling module so ``routes`` — its parsers and ``default_route_address`` — carries no
process spawn: ``routes.run_route_command`` imports this lazily and reads a missing
module as "the table did not answer", and the bundled phone profile switches it off.
"""

from __future__ import annotations

from typing import Any

from .routes import _ROUTE_COMMAND_TIMEOUT_SECONDS

__layer__ = "stores"
__all__ = ["run_route_command"]


def run_route_command(argv: list[str]) -> str | None:
    """One routing-table command's stdout, or ``None``. Never raises (``routes.run_route_command``)."""

    import subprocess
    import sys

    extra: dict[str, Any] = {}
    if sys.platform == "win32":
        # ``route.exe`` is a console program and this CLI is routinely spawned
        # by a windowless launcher process; without this the operator would see
        # a console blink every time the sheet refreshes.
        flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if flag:
            extra["creationflags"] = flag
    try:
        completed = subprocess.run(
            argv,
            # This CLI is spoken to over stdio by a launcher (see
            # ``CALLER_STDIO_OWNER``), so a child that inherited stdin could eat
            # a frame addressed to us. ``route``/``ip``/``ifconfig`` read none.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_ROUTE_COMMAND_TIMEOUT_SECONDS,
            check=False,
            **extra,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout or ""
