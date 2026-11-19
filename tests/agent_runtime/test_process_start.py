"""RT-PHONE-TURN-RESERVATION-NEEDS-PROCESS-IDENTITY: a turn reservation records its owner without psutil."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace

import pytest

from agent_runtime import process_start

linux_only = pytest.mark.skipif(not os.path.exists("/proc/self/stat"), reason="reads /proc")


@pytest.fixture
def runtime_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_start, "_own", {})


@pytest.fixture(params=["unimportable", "stand_in"])
def no_psutil(request, monkeypatch):
    """The phone's two shapes: no psutil at all, and the fork's empty-table stand-in."""
    if request.param == "unimportable":
        monkeypatch.setitem(sys.modules, "psutil", None)  # ``import psutil`` raises ImportError
    else:
        from agent_runtime.psutil_stand_in import stand_in_modules

        monkeypatch.setitem(sys.modules, "psutil", stand_in_modules()["psutil"])
    return request.param


def _accept(key: str):
    from agent_runtime.chat_turn_reservations import reserve_chat_turn

    with reserve_chat_turn(turn_request_id=key, verb="message", session_scope="chat") as reservation:
        return reservation.mark_accepted({}, request_id=key)


@linux_only
def test_a_reservation_without_psutil_records_this_process(runtime_root, no_psutil):
    # Red under the old _process_started (None when psutil is missing or stood in): mark_accepted
    # raised accept_owner_unavailable, the refusal seen on the Android emulator.
    record = _accept("phone-turn")
    assert record.owner_pid == os.getpid()
    assert record.owner_started == process_start._proc_started(os.getpid())


@linux_only
def test_without_psutil_a_live_owner_stays_and_a_reused_pid_settles(runtime_root, no_psutil):
    from agent_runtime.chat_turn_reservations import (
        _write, read_chat_turn_receipt, repair_orphaned_chat_receipts,
    )

    _accept("live-turn")
    dead = _accept("dead-turn")
    _write(replace(dead, owner_started=dead.owner_started - 1000))
    # Red under the stand-in's NoSuchProcess read as death: the live turn settled too.
    assert repair_orphaned_chat_receipts() == ["chat"]
    assert read_chat_turn_receipt("dead-turn").exit_code == 130
    assert read_chat_turn_receipt("live-turn").state == "accepted"


@linux_only
def test_without_psutil_an_exited_owner_is_proven_gone(runtime_root, no_psutil):
    from agent_runtime.chat_turn_reservations import _owner_proven_dead

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    started = process_start.process_started(child.pid)
    child.wait()
    record = replace(_accept("gone-turn"), owner_pid=child.pid, owner_started=started)
    assert _owner_proven_dead(record)


def test_unreadable_owner_evidence_stays_unknown(runtime_root, monkeypatch):
    from agent_runtime.chat_turn_reservations import _owner_proven_dead

    record = _accept("unknown-turn")
    monkeypatch.setattr(process_start, "_read_started", lambda pid: None)
    assert not _owner_proven_dead(replace(record, owner_pid=os.getpid() + 1))


def test_own_identity_survives_no_platform_read(monkeypatch):
    monkeypatch.setattr(process_start, "_own", {})
    monkeypatch.setattr(process_start, "_read_started", lambda pid: None)
    first = process_start.process_started(os.getpid())
    assert isinstance(first, float)
    assert process_start.process_started(os.getpid()) == first


@linux_only
def test_the_proc_read_is_psutils_formula():
    psutil = pytest.importorskip("psutil")
    if not hasattr(psutil, "Process") or process_start._real_psutil() is None:
        pytest.skip("no real psutil")
    assert process_start._proc_started(os.getpid()) == pytest.approx(
        psutil.Process(os.getpid()).create_time(), abs=1e-6)


@linux_only
def test_a_denied_boot_time_still_names_one_incarnation(monkeypatch):
    # An Android app may be refused /proc/stat: the start is then boot-relative, and still stable.
    monkeypatch.setattr(process_start, "_boot_time", lambda: 0.0)
    once = process_start._proc_started(os.getpid())
    assert once == process_start._proc_started(os.getpid()) and 0 < once < 1e9


def test_the_stand_in_marker_is_the_one_its_module_sets():
    from agent_runtime.psutil_stand_in import STAND_IN_MARKER

    assert process_start._PSUTIL_STAND_IN_MARKER == STAND_IN_MARKER
