"""``serve_loop`` — the entry point every caller and test drives.

It builds one :class:`~hermes_cli.harness_parts.serve.session.ServeSession` and
runs it; the loop's contract (transports, drain, service mode, the stdout
discipline) is the session's class docstring.
"""

from __future__ import annotations

from typing import Any, TextIO

from hermes_cli.harness_parts.serve.session import ServeSession

__layer__ = "lanes"

__all__ = ["serve_loop"]


def serve_loop(reader: TextIO, writer: TextIO, **options: Any) -> int:
    """Serve NDJSON frames from *reader* to *writer* until EOF, shutdown or drain.

    *options* are :class:`ServeSession`'s keyword arguments (pool size, the
    injected seams, ``socket_lane``, ``service``, …) with the same defaults.
    """

    return ServeSession(reader, writer, **options).run()
