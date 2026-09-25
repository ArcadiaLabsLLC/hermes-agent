"""Fork pin for ``tools/environments/local.py::_kill_process_windows`` (lane FORK-CODE).

Upstream's ``test_kill_process_uses_cached_pgid_if_wrapper_already_exited`` is
POSIX-only (an id-table skip on this host). The fork's old Windows half of that
test faked ``terminate_pid(pid, *, force)`` and went red once upstream's arm
started passing ``expected_start_time``: the fake raised ``TypeError``, the arm
fell back to ``proc.kill()`` and the fake saw ``[]``. The TEST was wrong; the
arm is right. This pins the arm directly — no host-OS faking.
"""

from types import SimpleNamespace

from tools.environments import local as local_mod


def _proc(pid=12345):
    killed = []
    proc = SimpleNamespace(
        pid=pid,
        kill=lambda: killed.append(pid),
        wait=lambda timeout=None: 0,
    )
    return proc, killed


def test_windows_arm_force_terminates_the_tree_behind_the_identity_guard(monkeypatch):
    calls = []

    def fake_terminate_pid(pid, *, force=False, expected_start_time=None):
        calls.append((pid, force, expected_start_time))

    monkeypatch.setattr("gateway.status.terminate_pid", fake_terminate_pid)
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: 777.0)
    proc, killed = _proc()

    local_mod._kill_process_windows(proc)

    assert calls == [(12345, True, 777.0)]
    assert killed == []


def test_windows_arm_falls_back_to_the_handle_when_the_guard_refuses(monkeypatch):
    """An exited wrapper has no start time; the guard refuses and the handle is killed."""

    def refusing_terminate_pid(pid, *, force=False, expected_start_time=None):
        raise OSError("refusing to force-kill without a process start-time guard")

    monkeypatch.setattr("gateway.status.terminate_pid", refusing_terminate_pid)
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: None)
    proc, killed = _proc()

    local_mod._kill_process_windows(proc)

    assert killed == [12345]
