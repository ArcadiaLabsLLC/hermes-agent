"""A messaging test's runtime-status write lands on disk and starts no writer thread (the folder's
``conftest.py::sync_runtime_status_writer``; RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING)."""

from __future__ import annotations

import threading

from gateway import status

THREAD = "gateway-runtime-status-writer"


def _writer_threads() -> set[threading.Thread]:
    return {thread for thread in threading.enumerate() if thread.name == THREAD}


def test_status_writes_leave_no_writer_thread(sync_runtime_status_writer):
    """``write_runtime_status`` and ``publish_runtime_status`` persist at once, as the upstream writer would, and no
    ``gateway-runtime-status-writer`` thread starts. KILLING MUTATION: drop the conftest fixture's ``setattr`` (the
    module's own writer back) -> a writer thread starts, red."""

    before = _writer_threads()
    assert status.write_runtime_status(gateway_state="running", reload_existing=True) is True
    generation = status.publish_runtime_status(gateway_state="stopped")
    assert sync_runtime_status_writer.settled(generation) is True
    assert status.flush_runtime_status() is True
    assert (status.read_runtime_status() or {}).get("gateway_state") == "stopped"
    assert _writer_threads() - before == set()
