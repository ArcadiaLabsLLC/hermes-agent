"""Fork-owned (upstream ships no conftest here): a provider test leaves no log listener running.

The first import of ``hermes_cli.main`` in a process runs ``hermes_logging.setup_logging``, which
starts the async file-logging ``QueueListener`` thread (``_monitor``) writing into that test's
``HERMES_HOME``. ``test_missing_credentials_hints.py``'s readiness test is that first import, so
the thread outlived it (row FH-SEAL-LEFTOVER-THREADS-AND-CHILDREN, seen by the seal 2026-11-16).
A listener a test started is torn down with ``hermes_logging``'s own test-isolation helper, as
``tests/hermes_cli/test_web_server_listener_logging.py`` does.
"""

from __future__ import annotations

import pytest

import hermes_logging


@pytest.fixture(autouse=True)
def _stop_a_log_listener_the_test_started():
    before = hermes_logging._queue_listener
    yield
    if before is None and hermes_logging._queue_listener is not None:
        hermes_logging._reset_queued_handlers()
        hermes_logging._logging_initialized = False
