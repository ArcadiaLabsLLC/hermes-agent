"""The messaging tests write gateway runtime status without the upstream writer's thread.

``gateway/status.py`` keeps one module-level ``_RuntimeStatusWriter`` whose first ``submit`` starts the daemon
thread ``gateway-runtime-status-writer``; its loop has no stop, so any test here whose path writes runtime status
(the Telegram adapter's connect, the stand-in live check) left that thread for the test seal to report
(RT-TELEGRAM-STAND-IN-TESTS-LEAVE-THE-GATEWAY-STATUS-THREAD-RUNNING, review w1118a.51 D12). The fork route: a
writer that persists at once, through the module's own ``_merge_over_on_disk`` and ``_write_json_file``, so the
status file is written as upstream writes it and no thread starts. No edit to ``gateway/status.py``.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from gateway import status


class SyncStatusWriter:
    """``_RuntimeStatusWriter``'s surface (``submit`` / ``wait`` / ``flush`` / ``settled``), written in the
    caller's thread. Callers already serialise on ``status._runtime_status_state_lock``."""

    def __init__(self) -> None:
        self._submitted = 0
        self._successful = 0
        self._last_error: BaseException | None = None

    def submit(self, path: Path, payload: dict[str, Any]) -> int:
        self._submitted += 1
        try:
            status._write_json_file(path, status._merge_over_on_disk(path, copy.deepcopy(payload)))
        except Exception as exc:  # the upstream writer records it and the next write retries
            self._last_error = exc
        else:
            self._successful, self._last_error = self._submitted, None
        return self._submitted

    def settled(self, generation: int) -> bool | None:
        if self._successful >= generation:
            return True
        return False if generation <= self._submitted else None

    def wait(self, generation: int, timeout: float | None = None) -> bool:
        state = self.settled(generation)
        if not state and timeout is None and self._last_error is not None:
            raise self._last_error
        return bool(state)

    def flush(self, timeout: float = 2.0) -> bool:
        return self._submitted == 0 or self.wait(self._submitted, timeout=timeout)


@pytest.fixture(autouse=True)
def sync_runtime_status_writer(monkeypatch: pytest.MonkeyPatch) -> SyncStatusWriter:
    """Every messaging test writes runtime status through :class:`SyncStatusWriter`. KILLING MUTATION: drop this
    fixture and ``test_live_telegram_check_on_the_stand_in.py`` leaves ``gateway-runtime-status-writer`` running
    (the seal's ``leftover`` line, and ``test_status_writes_leave_no_writer_thread``, red)."""

    writer = SyncStatusWriter()
    monkeypatch.setattr(status, "_runtime_status_writer", writer)
    return writer


@pytest.fixture(autouse=True)
def stop_the_build_sweep():
    """A serve these tests boot starts ``agent_runtime.builds.sweep``'s ``build-sweep`` thread, a process-lifetime
    daemon with no stop of its own (a serve process ends with it). Each test here ends the one it started: set the
    module's ``_STOP``, join the thread, and reset both for the next boot
    (RT-MESSAGING-TESTS-LEAVE-SERVE-AND-SIGNAL-THREADS-RUNNING, review w1118a.52 D13). No edit to the sweep.
    KILLING MUTATION: drop this fixture and
    ``test_serve_lane.py::test_a_service_serve_runs_the_lane_and_a_socket_drain_stops_it`` leaves ``build-sweep``
    running (the seal's ``leftover`` line; red once the folder is sealed)."""

    from agent_runtime.builds import sweep

    before = sweep._THREAD
    yield
    thread = sweep._THREAD
    if thread is None or thread is before or not thread.is_alive():
        return
    sweep._STOP.set()
    thread.join(5)
    sweep._STOP.clear()
    sweep._THREAD = None
