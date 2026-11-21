"""RT-STOP-REACHES-WHAT-AN-AGENT-REQUEST-STARTED-AFTER-ITS-PROCESS-ENDS (review w1118a.55 D10).

An agent request's child leads its own process group (``local_child.spawn_child``), so what it
started and left behind — a build whose shell already returned — is ended by Stop, by the
budget kill and by the supervisor's settle, even after the child itself has exited. The
tree-kill alone walked a LIVE parent's descendants only (``_terminate_host_pid`` refuses a dead
pid), so such a survivor was reached on no platform. Real processes, Linux.

Killing mutations (reds recorded in the commit body):
* ``child._kill_child`` drops its ``end_child_group`` call -> the Stop-after-exit test red;
* ``_group_is_the_childs`` drops the start-time comparison -> the recycled-leader test red;
* ``delivery.settle_if_orphaned`` drops ``_end_left_group`` -> the supervisor-gone Stop test red;
* ``local._run_child_once`` drops the settle's ``end_child_group`` -> the settle test red.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys

import psutil
import pytest

from agent_runtime import dispatch_store
from agent_runtime.dispatch_store import get_dispatch, mint_dispatch_id, record_dispatch, set_dispatch_owner
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import child as child_mod
from tools.agent_chat_dispatch.local_child import spawn_child
from tests._downstream.load_wait import wait_for

pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="POSIX process groups; the Windows Job Object half is on the owed Windows checks"),
    pytest.mark.timeout(120),
    # Real signals, only ever to processes these tests started; a grandchild re-parented
    # after its parent exited is outside the test's subtree by construction.
    pytest.mark.live_system_guard_bypass,
]

SENDER_ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"

#: The child: starts a grandchild in its own group (as a build's shell would), one in a
#: session of its own (as a registered background process is), writes their pids, prints a
#: payload and exits without waiting for either.
_CHILD = r"""
import json, subprocess, sys
left = subprocess.Popen(["sleep", "300"])
own = subprocess.Popen(["sleep", "300"], start_new_session=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
with open(sys.argv[1], "w") as handle:
    json.dump({"left": left.pid, "own": own.pid}, handle)
print(json.dumps({"capability_id": "x", "ok": True, "reply": "done"}), flush=True)
"""


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    yield home
    for dispatch_id in list(agent_chat_dispatch.supervised_dispatch_ids()):
        agent_chat_dispatch._forget_supervised(dispatch_id)


@pytest.fixture
def strays():
    """Pids a test started; whatever is left is killed at teardown."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)  # windows-footgun: ok — POSIX-only test (skipped elsewhere)
        except OSError:
            pass


def _gone(pid: int, seconds: float = 8.0) -> bool:
    """True once ``pid`` has exited (or is a zombie); a load-scaled wait that fails naming the pid."""
    return wait_for(lambda: not _alive(pid), seconds, interval=0.05, what=f"pid {pid} to exit")


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _pids(path) -> dict[str, int]:
    def written() -> dict[str, int] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    return wait_for(written, 20, interval=0.05, what="the child to write its grandchildren's pids")


def _spawn_and_exit(tmp_path, strays):
    """A real child spawned the way a dispatch is, left to exit: (proc, started_at, pids)."""
    pid_file = tmp_path / "pids.json"
    proc = spawn_child([sys.executable, "-c", _CHILD, str(pid_file)], dict(os.environ))
    started_at = child_mod._child_identity(proc.pid)
    proc.wait(timeout=30)  # not communicate(): the grandchild left behind holds the pipes open
    proc.stdout.close()
    proc.stderr.close()
    pids = _pids(pid_file)
    strays.extend(pids.values())
    return proc, started_at, pids


def test_stop_ends_what_the_child_left_after_it_exited(tmp_path, strays):
    proc, started_at, pids = _spawn_and_exit(tmp_path, strays)
    try:
        assert _alive(pids["left"]), "the grandchild should outlive its parent until Stop"

        child_mod._kill_child(proc.pid, started_at)

        assert _gone(pids["left"])
        # A process in a session of its own is not the group's: it stops from Running now.
        assert _alive(pids["own"])
    finally:
        child_mod.release_child_group(proc.pid)


def test_a_live_leader_with_another_start_time_is_a_stranger_and_is_left(tmp_path, strays):
    proc = spawn_child([sys.executable, "-c", "import time; time.sleep(300)"], dict(os.environ))
    strays.append(proc.pid)
    try:
        started_at = child_mod._child_identity(proc.pid)
        assert started_at is not None

        assert child_mod.end_child_group(proc.pid, started_at + 1) is False

        assert _alive(proc.pid)
    finally:
        proc.kill()
        proc.wait(timeout=10)
        child_mod.release_child_group(proc.pid)


def test_a_stop_after_the_supervisor_is_gone_ends_what_the_child_left(store_home, tmp_path, strays):
    """D9's live shape: the supervising process ended first, then the child; a Stop from a
    process that supervises nothing settles the row AND ends the group the row names."""
    proc, started_at, pids = _spawn_and_exit(tmp_path, strays)
    try:
        dispatch_id = mint_dispatch_id()
        record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
        assert set_dispatch_owner(
            dispatch_id, owner_pid=proc.pid, owner_started_at=started_at, owner_group=proc.pid
        )
        # Nothing here supervises it, and its owner is provably gone.
        assert dispatch_id not in agent_chat_dispatch.supervised_dispatch_ids()

        answer = agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")

        assert answer["outcome"] == "settled"
        assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_UNKNOWN
        assert _gone(pids["left"])
        assert _alive(pids["own"])
    finally:
        child_mod.release_child_group(proc.pid)


def test_the_supervisors_settle_ends_what_the_child_left(store_home, tmp_path, strays, monkeypatch):
    pid_file = tmp_path / "pids.json"
    monkeypatch.setattr(
        agent_chat_dispatch.local, "build_dispatch_argv",
        lambda spec, deadline_epoch: [sys.executable, "-c", _CHILD, str(pid_file)],
    )
    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
    agent_chat_dispatch._mark_supervised(dispatch_id)

    agent_chat_dispatch._run_dispatch(dispatch_id, {"persona_id": "dev", "message": "x", "max_seconds": 60})

    pids = _pids(pid_file)
    strays.extend(pids.values())
    row = get_dispatch(dispatch_id)
    assert row["state"] == dispatch_store.STATE_COMPLETED
    assert row["owner_group"] == row["owner_pid"]
    assert _gone(pids["left"])
    assert _alive(pids["own"])
    assert child_mod.child_group(row["owner_pid"]) is None  # released with the settle


def test_a_serve_that_never_dispatched_still_answers_stop_on_an_ended_request(
    store_home, tmp_path, strays, monkeypatch
):
    """Seen live 2026-11-20: a serve restarted after the request's supervisor ended had never
    imported the dispatch lane, and Running now's Stop answered ``not_owned_here``."""
    from agent_runtime.running_work import surface

    proc, started_at, pids = _spawn_and_exit(tmp_path, strays)
    try:
        dispatch_id = mint_dispatch_id()
        record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
        set_dispatch_owner(dispatch_id, owner_pid=proc.pid, owner_started_at=started_at, owner_group=proc.pid)
        real = surface._module
        monkeypatch.setattr(
            surface, "_module", lambda name: None if name == "tools.agent_chat_dispatch" else real(name)
        )

        answer = surface.cancel_work(f"dispatch:{dispatch_id}", reason="operator_stop")

        assert (answer["status"], answer.get("outcome")) == ("ok", "settled")
        assert _gone(pids["left"])
    finally:
        child_mod.release_child_group(proc.pid)
