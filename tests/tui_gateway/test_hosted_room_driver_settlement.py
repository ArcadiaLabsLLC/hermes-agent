"""Hosted-room driver settles only what it can prove (issue #125258, part 1).

Stop settlement on an unresolved stop, active-session deferral, the member error on the
terminal result, and per-task recovery-probe reconciliation. Helpers and the ``db`` fixture
come from ``test_hosted_room_driver_runtime``.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway import hosted_room_driver as state
from tui_gateway.hosted_room_driver import _find_terminal_receipt
from gateway import hosted_rooms
from tests.tui_gateway.test_hosted_room_driver_runtime import (
    BINDING,
    PROFILE,
    ROOM_ID,
    FakeSessionRPC,
    _admit,
    _identity,
    _runtime,
    _wait_for,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "state.db"
    hosted_rooms.create_room(
        path, room_id=ROOM_ID, name="Release room", members=[{"profile": PROFILE, "handle": PROFILE}],
        authority_gateway_id=BINDING.gateway_id, now=time.time())
    return path


@pytest.mark.parametrize(
    "stop_unresolved,expected",
    [(True, "stopping"), (False, "cancelled")],
)
def test_inactive_session_settles_stop_only_when_its_outcome_is_resolved(
    db: Path,
    stop_unresolved: bool,
    expected: str,
):
    """An inactive exact session is not, by itself, a Stop acknowledgement.

    The two rows are the same bytes with one field of one probe changed: a
    session that reports an unresolved stop cannot retire the cancellation, and
    the same session without that field can.
    """
    identity = _identity()
    _admit(db, identity)
    rpc = FakeSessionRPC(auto_complete=False)
    runtime = _runtime(db, rpc)
    lease = state.acquire_lease(
        db,
        room_id=ROOM_ID,
        gateway_id=BINDING.gateway_id,
        authority_epoch=BINDING.authority_epoch,
        process_generation=runtime.process_generation,
        ttl_seconds=5,
        clock=time.time,
    )
    runtime._leases[ROOM_ID] = lease
    attempt = state.start_task(
        db,
        identity,
        lease,
        expected_cancel_generation=0,
        clock=time.time,
    )
    rpc.add_session(active=False, task_id=identity.task_id)
    original_info = rpc.info

    def info(**kwargs):
        result = original_info(**kwargs)
        if stop_unresolved:
            result["stop_unresolved"] = True
        return result

    rpc.info = info
    state.begin_task_cancel(
        db,
        identity,
        cancel_id="cancel-unresolved",
        expected_cancel_generation=attempt.cancel_generation,
        clock=time.time,
    )

    result = runtime.cancel(identity, cancel_id="cancel-unresolved")

    assert result["status"] == expected
    assert state.get_task(db, identity)["status"] == expected


def test_request_reconciliation_reopens_only_the_named_task_s_recovery_probe(
    db: Path,
):
    """Fresh host evidence invalidates one exact negative observation.

    The probe count is the observable: while the attempt stays inspected the
    worker deliberately does NOT re-read it before its defer deadline, so a new
    probe can only come from the invalidation.
    """
    identity = _identity()
    now = [100.0]
    old_lease = state.acquire_lease(
        db,
        room_id=ROOM_ID,
        gateway_id=BINDING.gateway_id,
        authority_epoch=BINDING.authority_epoch,
        process_generation="old-process",
        ttl_seconds=1.0,
        clock=lambda: now[0],
    )
    _admit(db, identity)
    state.start_task(
        db,
        identity,
        old_lease,
        expected_cancel_generation=0,
        clock=lambda: now[0],
    )
    rpc = FakeSessionRPC(auto_complete=False)
    rpc.add_session(active=False, task_id=identity.task_id)
    now[0] += 2.0
    runtime = _runtime(db, rpc, clock=lambda: now[0])

    runtime.start()
    try:
        _wait_for(lambda: ROOM_ID in runtime.status()["blocked_rooms"])
        _wait_for(lambda: len([c for c in rpc.calls if c[0] == "info"]) >= 1)
        settled_probes = len([c for c in rpc.calls if c[0] == "info"])

        # Negative control: a different task in the same room reopens nothing.
        runtime.request_reconciliation(_identity("task-other"))
        time.sleep(0.3)  # health: allow HX013 -- negative control: no re-probe may happen in this window
        assert len([c for c in rpc.calls if c[0] == "info"]) == settled_probes

        runtime.request_reconciliation(identity)
        _wait_for(
            lambda: len([c for c in rpc.calls if c[0] == "info"]) > settled_probes
        )
    finally:
        assert runtime.stop(timeout=5.0)

    assert state.get_task(db, identity)["status"] == "indeterminate"


def test_provably_active_peer_session_is_never_deferred_past_the_deadline(db: Path):
    """Past the defer deadline an indeterminate attempt is deferred, unless the probe proves
    the session is still active: then the room stays blocked and the task stays indeterminate."""
    identity = _identity()
    now = [100.0]

    def clock():
        return now[0]

    old_lease = state.acquire_lease(
        db, room_id=ROOM_ID, gateway_id=BINDING.gateway_id,
        authority_epoch=BINDING.authority_epoch, process_generation="old-process",
        ttl_seconds=1, clock=clock)
    _admit(db, identity)
    state.start_task(db, identity, old_lease, expected_cancel_generation=0, clock=clock)
    now[0] = 102.0
    runtime = _runtime(db, FakeSessionRPC(), clock=clock, lease_ttl_seconds=30,
                       indeterminate_defer_seconds=5)
    recovery_lease = state.acquire_lease(
        db, room_id=ROOM_ID, gateway_id=BINDING.gateway_id,
        authority_epoch=BINDING.authority_epoch, process_generation=runtime.process_generation,
        ttl_seconds=30, clock=clock)
    state.recover_room(db, recovery_lease, clock=clock)
    runtime.transport_resolver = lambda _binding, _task: object()
    runtime._inspect_recovery_session = lambda _binding, _task: SimpleNamespace(
        terminal=None, active=True, status=None)

    assert runtime._reconcile_indeterminate(BINDING, recovery_lease) is True
    now[0] = 108.0  # past indeterminate_at + 5
    assert runtime._reconcile_indeterminate(BINDING, recovery_lease) is True
    assert state.get_task(db, identity)["status"] == "indeterminate"


def test_terminal_receipt_carries_the_member_error():
    identity = _identity()
    history = [{"role": "assistant", "task_id": identity.task_id, "execution_generation": 1,
                "status": "failed", "message_id": "m-1", "content": "", "error": "provider 401"}]
    receipt = _find_terminal_receipt(history, identity, 1)
    assert receipt is not None and receipt.result["error"] == "provider 401"
    history[0].pop("error")
    assert "error" not in _find_terminal_receipt(history, identity, 1).result
