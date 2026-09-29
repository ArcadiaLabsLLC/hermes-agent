"""The 2026-09-26 wedged serve, reproduced on the real loop and socket lane.

Evidence: ``X:/wt/_holds/serve-wedge-0926/`` (README timeline, ``stacks.txt``).
Three defects, one incident:

1. A stdio serve whose parent died joined its worker pool BEFORE giving up the
   socket lane, the owner lock and the registry row, and the worker it joined —
   the stdio consumer's own standing ``harness stream`` — never returned. The
   dead runtime stayed the registered owner, listener open, for two hours.
2. A drain asked of that serve wrote its ``draining`` frame to the dead stdio
   pipe first; the write raised, after ``drain_state`` was latched and before
   the sidecar stamp and the monitor, so the runtime answered
   ``drain_in_progress`` for 115 minutes with ``deadline_holds=0``.
3. A serve that did NOT own the socket lane still ran the store-writing
   delivery drain beside the owner.

Each is driven through ``serve_loop`` with the real socket lane over the
isolated runtime root — the faithful harness the lane rule asks for: the lock
is the kernel's, the sidecar is read back from disk, and a second
``SocketOwnerLock`` taking the lane is the only proof of a release there is.
"""

from __future__ import annotations

import threading
import time

import pytest

from agent_runtime.request_control import request_cancelled
from agent_runtime.serve_socket import SocketOwnerLock, read_socket_owner
from hermes_cli.harness_parts import serve as serve_module
from tests.agent_runtime.test_serve_socket_lane import (  # type: ignore
    WAIT,
    _read_until,
    _serving_row,
    _Sink,
    _store_root,
    client,
    running_serve,
)


def _lane_is_free(timeout: float) -> bool:
    """True once another process-local lock can TAKE the lane (and gives it back)."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe = SocketOwnerLock(_store_root())
        if probe.acquire().acquired:
            probe.release()
            return True
        time.sleep(0.05)
    return False


# ── 1. EOF gives up the lane before it waits for a stuck worker ─────────────


def test_eof_releases_the_lane_and_row_while_a_worker_is_still_stuck(monkeypatch):
    """The owner lock and the registry row go BEFORE the join; the join is bounded.

    *Killing mutation:* move ``_close_socket_lane`` / ``_unregister_instance``
    in ``_end_without_drain`` back below ``_join_pool_within_exit_deadline`` —
    the lane is never free while the worker is stuck, as on 2026-09-26.
    """

    monkeypatch.setattr(serve_module.drain, "_DRAIN_EXIT_DEADLINE_SECONDS", 1.0)
    started, release = threading.Event(), threading.Event()
    exits: list[int] = []

    def _dispatch(argv):
        started.set()
        release.wait(WAIT)
        return 0

    try:
        with running_serve(dispatch=_dispatch, hard_exit=exits.append) as handle:
            handle.pipe.send({"id": "stuck-1", "argv": ["harness", "status"]})
            assert started.wait(WAIT)
            handle.pipe.close()  # the parent died: EOF on the protocol pipe

            assert _lane_is_free(10.0), "the lane stayed owned while one worker was stuck"
            from agent_runtime.serve_registry import list_serve_instances

            assert list_serve_instances(_store_root()) == []
            assert not release.is_set(), "the worker must still be stuck for this to mean anything"

            handle.thread.join(WAIT)
            assert not handle.thread.is_alive()
            assert exits == [serve_module.constants.DRAIN_TIMEOUT_EXIT_CODE]
            assert handle.code == serve_module.constants.DRAIN_TIMEOUT_EXIT_CODE
            shutdown = handle.sink.wait_for("shutdown")
            assert shutdown["stuck_request_ids"] == ["stuck-1"]
    finally:
        release.set()


def test_eof_cancels_the_stdio_consumers_standing_stream_and_exits_clean():
    """The incident's actual stuck shape: the stdio launcher's own ``harness stream``.

    *Killing mutation:* drop ``self._reclaim_stdio_streams()`` from
    ``_end_without_drain`` — the stream never ends, the join runs to its
    deadline, and the exit is 3 with the stream named stuck instead of 0.
    """

    exits: list[int] = []
    streaming = threading.Event()

    def _dispatch(argv):
        if argv[:2] == ["harness", "stream"]:
            streaming.set()
            deadline = time.monotonic() + WAIT
            while not request_cancelled() and time.monotonic() < deadline:
                time.sleep(0.02)
        return 0

    with running_serve(dispatch=_dispatch, hard_exit=exits.append) as handle:
        handle.pipe.send({"id": "stream-1", "argv": ["harness", "stream"]})
        assert streaming.wait(WAIT)
        handle.pipe.close()
        handle.thread.join(10.0)
        assert not handle.thread.is_alive(), "the serve joined its own consumer's stream forever"
        assert handle.code == 0
        assert exits == []
        assert "stuck_request_ids" not in handle.sink.wait_for("shutdown")


def test_eof_still_waits_for_a_chat_turn_past_the_deadline(monkeypatch):
    """Positive control on the bound: a chat turn HOLDS the join, as it holds a drain.

    Without it the bounded join would be a recycle of a recording turn by
    another name. *Killing mutation:* drop the ``held`` re-arm in
    ``_join_pool_within_exit_deadline`` — the turn is abandoned with exit 3.
    """

    monkeypatch.setattr(serve_module.drain, "_DRAIN_EXIT_DEADLINE_SECONDS", 0.2)
    started, release = threading.Event(), threading.Event()
    exits: list[int] = []

    def _dispatch(argv):
        started.set()
        release.wait(WAIT)
        return 0

    with running_serve(dispatch=_dispatch, hard_exit=exits.append) as handle:
        handle.pipe.send({"id": "turn-1", "argv": ["harness", "mission-chat", "message", "hi"]})
        assert started.wait(WAIT)
        handle.pipe.close()
        assert _lane_is_free(10.0)
        time.sleep(1.0)  # five deadlines
        assert exits == [] and handle.thread.is_alive(), "a chat turn was cut at the bound"
        release.set()
        handle.thread.join(WAIT)
        assert handle.code == 0 and exits == []


# ── 2. a drain on a serve whose stdio is dead ───────────────────────────────


class _DeadStdio(_Sink):
    """serve's stdout whose reader went away: Windows answers EINVAL, not EPIPE."""

    def __init__(self) -> None:
        super().__init__()
        self.dead = False

    def write(self, text: str) -> int:
        if self.dead:
            raise OSError(22, "Invalid argument")
        return super().write(text)


def test_a_drain_on_a_dead_stdio_stamps_leaving_and_still_ends():
    """The sidecar says ``draining_at`` (read back from disk) and the drain terminates.

    *Killing mutation:* put ``self.frames.emit(draining_frame)`` back in front
    of ``mark_draining`` in ``_request_drain`` — the write raises, no stamp, no
    monitor, and the socket client never reads a terminal frame.
    """

    stdout = _DeadStdio()
    started, release = threading.Event(), threading.Event()
    exits: list[int] = []

    def _dispatch(argv):
        started.set()
        release.wait(WAIT)
        return 0

    try:
        with running_serve(
            sink=stdout,
            dispatch=_dispatch,
            drain_socket_minimum_deadline_seconds=0.2,
            drain_poll_interval_seconds=0.01,
            hard_exit=exits.append,
        ) as handle:
            with client(handle, name="launcher") as (connection, _reply):
                connection.send({"id": "stuck-1", "argv": ["harness", "status"]})
                assert started.wait(WAIT)
                stdout.dead = True
                connection.send({"op": "drain", "force": True, "deadline_seconds": 0.2})
                assert _read_until(connection, "draining")
                sidecar = read_socket_owner(_store_root())
                assert isinstance((sidecar or {}).get("draining_at"), str), sidecar
                terminal = _read_until(connection, "drain_timeout")
                assert terminal["terminal"] is True
            deadline = time.monotonic() + WAIT
            while not exits and time.monotonic() < deadline:
                time.sleep(0.02)
            assert exits == [serve_module.constants.DRAIN_TIMEOUT_EXIT_CODE]
    finally:
        release.set()


def test_a_drain_whose_monitor_never_runs_is_ended_by_the_deadline_watchdog(monkeypatch):
    """Past the deadline with zero holds is a hard exit, through the one terminal path.

    *Killing mutation:* do not start ``_drain_deadline_watchdog`` in
    ``_request_drain`` — the drain sits in ``drain_in_progress`` forever, the
    2026-09-26 shape (``deadline_holds=0`` after 115 minutes).
    """

    monkeypatch.setattr(serve_module.drain, "_DRAIN_EXIT_DEADLINE_SECONDS", 0.3)
    monkeypatch.setattr(
        serve_module.drain.DrainLane, "_drain_monitor", lambda self, state: None
    )
    started, release = threading.Event(), threading.Event()
    exits: list[int] = []

    def _dispatch(argv):
        started.set()
        release.wait(WAIT)
        return 0

    try:
        with running_serve(
            dispatch=_dispatch,
            drain_socket_minimum_deadline_seconds=0.2,
            hard_exit=exits.append,
        ) as handle:
            with client(handle, name="launcher") as (connection, _reply):
                connection.send({"id": "stuck-1", "argv": ["harness", "status"]})
                assert started.wait(WAIT)
                connection.send({"op": "drain", "force": True, "deadline_seconds": 0.2})
                assert _read_until(connection, "draining")
                terminal = _read_until(connection, "drain_timeout")
                assert terminal["monitor_stalled"] is True
                assert terminal["deadline_holds"] == 0
                assert terminal["stuck_request_ids"] == ["conn-1:stuck-1"]
            assert _lane_is_free(10.0)
            deadline = time.monotonic() + WAIT
            while not exits and time.monotonic() < deadline:
                time.sleep(0.02)
            assert exits == [serve_module.constants.DRAIN_TIMEOUT_EXIT_CODE]
    finally:
        release.set()


# ── 3. only the socket owner runs the store-writing delivery drain ──────────


@pytest.fixture
def delivery_starts(monkeypatch):
    import agent_runtime.dispatch_delivery as dispatch_delivery

    calls: list[int] = []
    monkeypatch.setattr(
        dispatch_delivery, "start_delivery_drain", lambda **kwargs: calls.append(1)
    )
    return calls


def test_a_serve_that_lost_the_lane_runs_no_delivery_drain(delivery_starts):
    """*Killing mutation:* drop the ``_another_serve_owns_this_root`` gate — 1 start."""

    root = _store_root()
    incumbent = SocketOwnerLock(root)
    assert incumbent.acquire().acquired is True
    incumbent.publish_owner({"pid": 4242, "port": 61000, "boot_id": "incumbent"})
    _serving_row(root, 4242)
    try:
        with running_serve() as handle:
            assert handle.ready["socket"]["outcome"] == "lock_held_by"
            skipped = [
                row for row in handle.sink.frames()
                if row.get("event") == "stderr" and "dispatch_delivery_drain_skipped" in (row.get("line") or "")
            ]
            assert delivery_starts == []
            assert skipped, "the skip must be on the service log, not silent"
    finally:
        incumbent.release()


def test_the_owner_still_runs_the_delivery_drain(delivery_starts):
    """Positive control: the same capture sees the owner's start."""

    with running_serve() as handle:
        assert handle.ready["socket"]["outcome"] == "listening"
        assert delivery_starts == [1]


def test_a_shutdown_order_with_a_stuck_worker_is_bounded_too(monkeypatch):
    """A ``shutdown`` ORDER keeps its order (join, then teardown) but not its hang.

    *Killing mutation:* make ``_join_pool_within_exit_deadline`` an unbounded
    ``self.pool.shutdown(wait=True)`` — the serve never returns and the lane
    stays owned.
    """

    monkeypatch.setattr(serve_module.drain, "_DRAIN_EXIT_DEADLINE_SECONDS", 0.5)
    started, release = threading.Event(), threading.Event()
    exits: list[int] = []

    def _dispatch(argv):
        started.set()
        release.wait(WAIT)
        return 0

    try:
        with running_serve(dispatch=_dispatch, hard_exit=exits.append) as handle:
            handle.pipe.send({"id": "stuck-1", "argv": ["harness", "status"]})
            assert started.wait(WAIT)
            handle.pipe.send({"op": "shutdown"})
            handle.thread.join(10.0)
            assert not handle.thread.is_alive(), "a shutdown order joined a stuck worker forever"
            assert exits == [serve_module.constants.DRAIN_TIMEOUT_EXIT_CODE]
            assert _lane_is_free(5.0)
            assert handle.sink.wait_for("shutdown")["stuck_request_ids"] == ["stuck-1"]
    finally:
        release.set()
