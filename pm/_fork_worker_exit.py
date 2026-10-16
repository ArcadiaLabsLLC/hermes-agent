"""Fork-owned: let a PM worker that already returned its result exit slowly (L7.32).

Ledger row ``pm/client.py``: ``_request`` calls :func:`wait_for_slow_exit` once the result is in,
before upstream's 5 s exit wait. A worker whose EXIT is slow under load (the 5 s ran out on
2026-10-09: ``source-update completion failed: ... timed out after 5 seconds``) must not fail a
completed request; the 5 s wait then returns at once. PR candidate: a received result with a slow
exit should not fail the request.
"""

from __future__ import annotations

import subprocess

__all__ = ["RESULT_EXIT_GRACE_SECONDS", "wait_for_slow_exit"]

#: How long a worker that already returned its result may take to exit.
RESULT_EXIT_GRACE_SECONDS = 60


def wait_for_slow_exit(process: subprocess.Popen) -> None:
    """Wait up to :data:`RESULT_EXIT_GRACE_SECONDS` for ``process``; a timeout is not an error."""
    try:
        process.wait(timeout=RESULT_EXIT_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
