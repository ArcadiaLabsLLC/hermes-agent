"""An agent request outlives its serve: re-adopted while its child runs, settled from its result file once it is gone.

Review w1118a.56 D12, rows ``RT-AGENT-REQUEST-STILL-RUNNING-WHEN-ITS-SERVE-RESTARTS-IS-PICKED-UP-AGAIN`` and
``RT-WINDOWS-STOP-AFTER-ITS-SUPERVISOR-ENDED-REACHES-WHAT-A-REQUEST-LEFT``:

* the child writes its answer to a per-request result file before stdout and survives a closed stdout;
* a request whose child is proved alive (pid plus start time) and whose supervising serve is proved
  gone is re-adopted by the next serve, which supervises it and records its REAL answer;
* a request a live serve still supervises is left alone;
* a request whose child is gone is settled from its result file, or ``unknown`` — never re-adopted;
* Windows: one named job per request with kill-on-close; the child holds its own handle by name and a
  re-adopting serve opens it by name (pinned against a faked kernel32; the Windows read is owed).

Real processes on POSIX for the re-adoption tests. Killing mutations: each test's docstring names one.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent_runtime import dispatch_store
from agent_runtime.dispatch_store import (
    dispatch_db_path,
    get_dispatch,
    mint_dispatch_id,
    record_dispatch,
    set_dispatch_owner,
)
from agent_runtime.dispatch_store import result_file
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import child as child_mod
from tools.agent_chat_dispatch import local as local_mod
from tools.agent_chat_dispatch import local_child
from tests._downstream.load_wait import wait_for

SENDER_ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"

#: A dispatch child stand-in: claims its env the way the real handler does, waits for a go file,
#: then writes its payload through the real result-file writer and exits.
_CHILD = r"""
import json, os, sys, time
from agent_runtime.dispatch_store.result_file import claim_dispatch_child_env, write_claimed_result
claim_dispatch_child_env()
go = sys.argv[1]
while not os.path.exists(go):
    time.sleep(0.05)
write_claimed_result({"capability_id": "x", "ok": True, "reply": "the real answer", "session_id": "persona_chat_t"})
"""


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setattr(local_mod, "READOPT_POLL_SECONDS", 0.05)
    # The cancel watch is the existing lane's (pinned in test_dispatch_cancel_elsewhere); Stop is driven directly here.
    monkeypatch.setattr(local_mod, "ensure_cancel_watch", lambda: None)
    yield home
    for dispatch_id in list(agent_chat_dispatch.supervised_dispatch_ids()):
        agent_chat_dispatch._forget_supervised(dispatch_id)


@pytest.fixture
def children():
    procs: list[subprocess.Popen] = []
    yield procs
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=30)
    return proc.pid


def _set_supervisor(dispatch_id: str, pid: int | None, started: int | None) -> None:
    with sqlite3.connect(dispatch_db_path()) as conn:
        conn.execute(
            "UPDATE mission_chat_dispatches SET supervisor_pid=?, supervisor_started_at=? WHERE dispatch_id=?",
            (pid, started, dispatch_id),
        )


def _request() -> str:
    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="dev", ask="x")
    return dispatch_id


def _start_child(dispatch_id, tmp_path, children):
    """A real child started the way a dispatch starts one, its row stamped, its serve then 'gone'."""

    go = tmp_path / f"go-{dispatch_id}"
    env = dict(os.environ)
    env[result_file.RESULT_FILE_ENV] = str(result_file.dispatch_result_path(dispatch_id))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    proc = local_child.spawn_child([sys.executable, "-c", _CHILD, str(go)], env)
    proc.stdout.close()  # the serve that read it is gone
    proc.stderr.close()
    children.append(proc)
    started = child_mod._child_identity(proc.pid)
    assert set_dispatch_owner(dispatch_id, owner_pid=proc.pid, owner_started_at=started, owner_group=proc.pid)
    child_mod.release_child_group(proc.pid)  # this process is the NEW serve: it holds nothing yet
    _set_supervisor(dispatch_id, _dead_pid(), 12345)
    return proc, go


def _wait_state(dispatch_id, seconds=20.0):
    def settled():
        row = get_dispatch(dispatch_id)
        return row if row["state"] != dispatch_store.STATE_RUNNING else None

    return wait_for(settled, seconds, interval=0.05, what=f"dispatch {dispatch_id} to settle")


# --------------------------------------------------------------------------- the child side


def test_the_child_writes_its_answer_before_stdout_and_survives_a_closed_stdout(store_home, monkeypatch):
    """Mutations: ``_mission_chat_emit`` drops ``write_claimed_result`` -> no file, red;
    ``claim_dispatch_child`` drops ``tolerate_closed_streams`` -> BrokenPipeError, red."""

    from hermes_cli.harness_parts.persona import chat_events

    class _ClosedPipe:
        def write(self, text):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            raise BrokenPipeError(32, "Broken pipe")

    path = result_file.dispatch_result_path("dsp_child_side")
    monkeypatch.setattr(result_file, "_claimed_result_path", None)
    monkeypatch.setenv(result_file.RESULT_FILE_ENV, str(path))
    monkeypatch.setattr(sys, "stdout", _ClosedPipe())
    monkeypatch.setattr(sys, "stderr", sys.stderr)

    chat_events.claim_dispatch_child()
    assert result_file.RESULT_FILE_ENV not in os.environ  # nothing the turn starts inherits it
    payload = {"capability_id": "x", "ok": True, "reply": "written first"}
    chat_events._mission_chat_emit(SimpleNamespace(json=True, stream=False), payload)

    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_a_process_that_is_not_a_dispatch_child_writes_no_result_file(store_home, monkeypatch, capsys):
    from hermes_cli.harness_parts.persona import chat_events

    monkeypatch.setattr(result_file, "_claimed_result_path", None)
    monkeypatch.delenv(result_file.RESULT_FILE_ENV, raising=False)
    chat_events.claim_dispatch_child()
    chat_events._mission_chat_emit(SimpleNamespace(json=True, stream=False), {"capability_id": "x", "ok": True})

    assert not (dispatch_db_path().parent / "dispatch_results").exists()
    assert '"capability_id"' in capsys.readouterr().out


# --------------------------------------------------------------------------- re-adoption (POSIX, real processes)

posix_only = pytest.mark.skipif(os.name != "posix", reason="real processes; the Windows job half is faked below")


@posix_only
def test_a_request_still_running_when_its_serve_restarts_is_re_adopted_and_its_real_answer_lands(
    store_home, tmp_path, children
):
    """Mutations: ``readopt_live_dispatches`` skips every row -> not adopted, red;
    ``_settle_local`` reads stdout only (no result file) -> settled ``unknown``, red."""

    dispatch_id = _request()
    proc, go = _start_child(dispatch_id, tmp_path, children)

    assert local_mod.readopt_live_dispatches() == [dispatch_id]

    assert dispatch_id in agent_chat_dispatch.supervised_dispatch_ids()
    row = get_dispatch(dispatch_id)
    assert row["state"] == dispatch_store.STATE_RUNNING
    assert row["supervisor_pid"] == os.getpid()
    # The orphan sweep in this serve now leaves it to its supervisor.
    assert dispatch_store.restore_undelivered_dispatches()["restored"] == 0
    go.write_text("go", encoding="utf-8")

    row = _wait_state(dispatch_id)
    assert row["state"] == dispatch_store.STATE_COMPLETED
    assert row["result"]["reply"] == "the real answer"
    # Discarded right after the record, on the supervisor's thread.
    wait_for(lambda: not result_file.dispatch_result_path(dispatch_id).exists(), 10, interval=0.05,
             what="the result file to be discarded")


@posix_only
def test_the_drains_orphan_sweep_re_adopts_before_it_settles(store_home, tmp_path, children):
    """Mutation: ``sweep_orphaned_dispatches`` drops its ``readopt_live_dispatches`` call -> red."""

    from agent_runtime.dispatch_delivery.drain import sweep_orphaned_dispatches

    dispatch_id = _request()
    proc, go = _start_child(dispatch_id, tmp_path, children)

    assert sweep_orphaned_dispatches() == 0

    assert dispatch_id in agent_chat_dispatch.supervised_dispatch_ids()
    go.write_text("go", encoding="utf-8")
    assert _wait_state(dispatch_id)["result"]["reply"] == "the real answer"


@posix_only
def test_stop_on_a_re_adopted_request_ends_its_child(store_home, tmp_path, children):
    """Mutation: ``_supervise_readopted`` settles with ``cancel_reason=None`` -> ``unknown``, red."""

    dispatch_id = _request()
    proc, _go = _start_child(dispatch_id, tmp_path, children)
    assert local_mod.readopt_live_dispatches() == [dispatch_id]

    answer = agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")

    assert answer["outcome"] == "stopping"
    row = _wait_state(dispatch_id)
    assert row["state"] == dispatch_store.STATE_CANCELLED
    proc.wait(timeout=10)


@posix_only
def test_a_request_a_live_serve_still_supervises_is_not_re_adopted(store_home, tmp_path, children):
    """Mutation: the re-adoption drops ``supervisor_provably_gone`` -> adopted beside its live supervisor, red."""

    dispatch_id = _request()
    proc, go = _start_child(dispatch_id, tmp_path, children)
    _set_supervisor(dispatch_id, os.getpid(), child_mod._child_identity(os.getpid()))  # a live serve holds it

    assert local_mod.readopt_live_dispatches() == []
    assert dispatch_id not in agent_chat_dispatch.supervised_dispatch_ids()
    go.write_text("go", encoding="utf-8")
    proc.wait(timeout=20)


@posix_only
def test_a_row_without_a_supervisor_stamp_is_not_re_adopted(store_home, tmp_path, children):
    dispatch_id = _request()
    proc, go = _start_child(dispatch_id, tmp_path, children)
    _set_supervisor(dispatch_id, None, None)  # written before the column

    assert local_mod.readopt_live_dispatches() == []
    go.write_text("go", encoding="utf-8")
    proc.wait(timeout=20)


@posix_only
def test_a_request_whose_child_is_gone_is_settled_from_its_result_file_and_never_re_adopted(
    store_home, tmp_path, children
):
    """Mutations: the re-adoption drops ``owner_provably_alive`` -> a dead child adopted, red;
    ``settle_if_orphaned`` ignores the result file -> settled ``unknown``, red."""

    dispatch_id = _request()
    proc, go = _start_child(dispatch_id, tmp_path, children)
    go.write_text("go", encoding="utf-8")
    proc.wait(timeout=20)

    assert local_mod.readopt_live_dispatches() == []
    assert dispatch_store.restore_undelivered_dispatches()["restored"] == 1

    row = get_dispatch(dispatch_id)
    assert row["state"] == dispatch_store.STATE_COMPLETED
    assert row["result"]["reply"] == "the real answer"
    assert not result_file.dispatch_result_path(dispatch_id).exists()


@posix_only
def test_a_request_whose_child_is_gone_without_an_answer_is_settled_unknown(store_home, tmp_path, children):
    dispatch_id = _request()
    proc, _go = _start_child(dispatch_id, tmp_path, children)
    proc.kill()
    proc.wait(timeout=10)

    assert local_mod.readopt_live_dispatches() == []
    assert dispatch_store.restore_undelivered_dispatches()["restored"] == 1
    assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_UNKNOWN


@posix_only
def test_the_supervisor_records_the_result_file_when_stdout_lost_the_answer(store_home, monkeypatch):
    """The live supervisor's own settle reads the file too. Mutation: ``_settle_local`` stdout only -> red."""

    dispatch_id = _request()
    result_file.dispatch_result_path(dispatch_id).parent.mkdir(parents=True, exist_ok=True)
    result_file.dispatch_result_path(dispatch_id).write_text(
        json.dumps({"capability_id": "x", "ok": True, "reply": "from the file"}), encoding="utf-8"
    )

    local_mod._settle_local(dispatch_id, 60.0, 0, "", "", "")

    row = get_dispatch(dispatch_id)
    assert row["state"] == dispatch_store.STATE_COMPLETED
    assert row["result"]["reply"] == "from the file"


def test_a_fresh_child_never_reads_an_earlier_childs_answer(store_home):
    """Mutation: ``_dispatch_child_environment`` drops the discard -> the stale file survives, red."""

    dispatch_id = _request()
    path = result_file.dispatch_result_path(dispatch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"capability_id": "x", "ok": False, "error_kind": "chat_busy"}), encoding="utf-8")

    env = local_mod._dispatch_child_environment(dispatch_id, {"persona_id": "dev"})

    assert env[result_file.RESULT_FILE_ENV] == str(path)
    assert not path.exists()


# --------------------------------------------------------------------------- Windows job (faked kernel32)


class _FakeKernel32:
    """Records the job calls; handles are small ints."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.flags: int | None = None
        self.info_class: int | None = None
        self._next = 100

    def _handle(self):
        self._next += 1
        return self._next

    def CreateJobObjectW(self, attrs, name):
        self.calls.append(("CreateJobObjectW", name))
        return self._handle()

    def OpenJobObjectW(self, access, inherit, name):
        self.calls.append(("OpenJobObjectW", access, bool(inherit), name))
        return self._handle()

    def SetInformationJobObject(self, job, info_class, info, size):
        import ctypes

        _basic, extended = local_child._job_structs()
        self.info_class = info_class
        self.flags = ctypes.cast(info, ctypes.POINTER(extended)).contents.BasicLimitInformation.LimitFlags
        self.calls.append(("SetInformationJobObject", job, info_class, size))
        return 1

    def AssignProcessToJobObject(self, job, handle):
        self.calls.append(("AssignProcessToJobObject", job, handle))
        return 1

    def TerminateJobObject(self, job, code):
        self.calls.append(("TerminateJobObject", job))
        return 1

    def CloseHandle(self, handle):
        self.calls.append(("CloseHandle", handle))
        return 1


@pytest.fixture
def kernel32(monkeypatch):
    fake = _FakeKernel32()
    monkeypatch.setattr(local_child, "_job_kernel32", lambda: fake)
    return fake


def test_each_request_gets_a_named_job_that_ends_its_processes_on_its_last_close(kernel32):
    """Mutation: ``_create_job`` drops the KILL_ON_JOB_CLOSE flag -> red; creates it unnamed -> red."""

    name = result_file.dispatch_job_name("dsp_abc")
    assert name == "Local\\hermes-dispatch-dsp_abc"

    job = local_child._create_job(name)

    assert job is not None
    assert ("CreateJobObjectW", name) in kernel32.calls
    assert kernel32.info_class == 9  # JobObjectExtendedLimitInformation
    assert kernel32.flags == local_child.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x2000


def test_the_child_holds_its_own_non_inheritable_handle_by_name(kernel32, monkeypatch):
    """Mutation: ``claim_dispatch_child`` never calls ``hold_job_by_name`` -> no handle, red."""

    from hermes_cli.harness_parts.persona import chat_events

    monkeypatch.setattr(local_child, "_HELD_JOB", None)
    monkeypatch.setattr(result_file, "_claimed_result_path", None)
    monkeypatch.setattr(result_file, "tolerate_closed_streams", lambda: None)
    monkeypatch.setenv(result_file.RESULT_FILE_ENV, "unused.json")
    monkeypatch.setenv(result_file.JOB_NAME_ENV, "Local\\hermes-dispatch-dsp_held")
    monkeypatch.setattr(os, "name", "nt")

    chat_events.claim_dispatch_child()

    monkeypatch.setattr(os, "name", "posix")
    assert ("OpenJobObjectW", local_child.JOB_OBJECT_QUERY, False, "Local\\hermes-dispatch-dsp_held") in kernel32.calls
    assert local_child._HELD_JOB is not None
    assert result_file.JOB_NAME_ENV not in os.environ


def test_on_windows_the_child_is_told_its_jobs_name(store_home, monkeypatch):
    """Mutation: ``_dispatch_child_environment`` drops the job name -> red."""

    dispatch_id = _request()
    env = local_mod._dispatch_child_environment(dispatch_id, {"persona_id": "dev"}, windows=True)
    assert env[result_file.JOB_NAME_ENV] == f"Local\\hermes-dispatch-{dispatch_id}"


def test_a_re_adopting_serve_opens_the_job_by_name_and_its_settle_ends_what_the_request_left(
    store_home, kernel32, monkeypatch
):
    """Mutation: ``_supervise_readopted`` never opens the job by name -> no TerminateJobObject, red."""

    dispatch_id = _request()
    row = {"dispatch_id": dispatch_id, "owner_pid": 424242, "owner_started_at": 1, "owner_group": None}
    from agent_runtime.dispatch_store import delivery as store_delivery

    monkeypatch.setattr(store_delivery, "owner_provably_gone", lambda identity: True)
    # child.py's group end and release take their Windows arm (the job) for this call only.
    monkeypatch.setattr(child_mod, "os", SimpleNamespace(name="nt"))
    agent_chat_dispatch._mark_supervised(dispatch_id)
    local_mod._supervise_readopted(dispatch_id, row, windows=True)

    opened = [c for c in kernel32.calls if c[0] == "OpenJobObjectW"]
    assert opened and opened[0][3] == f"Local\\hermes-dispatch-{dispatch_id}"
    assert opened[0][1] == local_child.JOB_OBJECT_TERMINATE | local_child.JOB_OBJECT_QUERY
    handle = kernel32._next
    assert ("TerminateJobObject", handle) in kernel32.calls
    assert ("CloseHandle", handle) in kernel32.calls
    assert get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_UNKNOWN
    assert dispatch_id not in agent_chat_dispatch.supervised_dispatch_ids()
