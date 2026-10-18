"""A test's ``socketserver`` server shuts down in ~50 ms, not ~500 ms (suite speed, lane w2-speed-b).

``socketserver.BaseServer.shutdown()`` blocks until ``serve_forever`` next wakes from its selector,
and ``serve_forever``'s default ``poll_interval`` is 0.5 s: every stub HTTP server a test starts on a
thread costs ~0.45 s at exit (measured 2026-10-18 on ``tests/pm/_fixtures.py::threaded_server``:
0.497 s per exit at the default, 0.047 s at 0.05). 126 test files call ``serve_forever``; a handful
already pass their own short interval.

``poll_interval`` only decides how soon a running loop notices ``shutdown()``; requests are served
the moment they arrive at any value, so no assertion can read it. A caller that passes its own
interval keeps it. Installed process-wide at ``conftest_plugin`` import, like the registry fence.
"""

from __future__ import annotations

import socketserver

#: The default every test process's ``serve_forever`` uses; the chain contract pins it.
TEST_POLL_INTERVAL = 0.05


def install() -> None:
    """Give ``BaseServer.serve_forever`` the test default (idempotent)."""

    real = socketserver.BaseServer.serve_forever
    if getattr(real, "__wrapped__", None) is not None:
        return

    def serve_forever(self, poll_interval=TEST_POLL_INTERVAL):
        return real(self, poll_interval)

    serve_forever.__wrapped__ = real
    serve_forever.__doc__ = real.__doc__
    socketserver.BaseServer.serve_forever = serve_forever
