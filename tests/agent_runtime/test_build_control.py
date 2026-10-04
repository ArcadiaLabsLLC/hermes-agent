"""Stop and Restart for every build row (plan ``build-running-work-2026-10-04.md`` §7, row H8).

Each origin × each declared stop mode; a detected Restart takes no confirm (owner call 2) and,
under a bound slot, runs with the SLOT's environment — so the row it produces carries
``env_source: slot:<name>`` and fewer ``env_unobserved`` keys than the row it re-ran; the
``issued_at`` replay guard is the same at both doors (owner call 3).
"""

from __future__ import annotations

import json
import shlex
import types
from argparse import Namespace

import pytest

from agent_runtime import serve_rpc
from agent_runtime.builds import control
from agent_runtime.builds.registry import new_record, write_record
from agent_runtime.machine_roots import machine_roots_cache_clear, write_machine_roots
from agent_runtime.running_work import lanes_build, lanes_process, ownership
from agent_runtime.store import WorkspaceStore

STARTED = "2026-10-04T12:00:00+00:00"
DART = "C:/flutter/bin/cache/dart-sdk/bin/dart.exe"


def _row(source, stable, **extra):
    base = {"work_id": f"build:{source}:{stable}", "kind": "build", "source": source, "status": "running",
            "outcome": None, "started_at": STARTED, "controls": {"restart": "allowed", "restart_reason": ""}}
    base.update(extra)
    return base


class _Registry:
    def __init__(self, sessions=()):
        self.sessions = {sid: types.SimpleNamespace(id=sid) for sid in sessions}
        self.killed, self.spawned = [], []

    def get(self, sid):
        return self.sessions.get(sid)

    def kill_process(self, sid, **kwargs):
        self.killed.append((sid, kwargs))
        return {"status": "killed"}

    def spawn_local(self, command, **kwargs):
        self.spawned.append((command, kwargs))
        return types.SimpleNamespace(id="proc_restarted")


@pytest.fixture
def head(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for module in (ownership, lanes_process, lanes_build):
        monkeypatch.setattr(module, "_head_home", lambda: (home, "test"))
    return home


@pytest.fixture
def identity(monkeypatch):
    verdicts = {}
    monkeypatch.setattr(ownership, "_pid_identity", lambda pid, start: (True, verdicts.get(int(pid), True), "verified"))
    return verdicts


@pytest.fixture
def terminated(monkeypatch):
    from agent_runtime import _upstream_doors

    calls = []
    monkeypatch.setattr(_upstream_doors, "terminate_host_pid", lambda pid, start: calls.append((pid, start)))
    return calls


# ── stop: each origin × declared mode ─────────────────────────────────────────


def test_an_agent_build_stops_in_its_owning_process_only(monkeypatch):
    registry = _Registry(sessions=["sess"])
    monkeypatch.setattr(control, "_registry", lambda: registry)
    assert control.stop_build(_row("agent", "sess"))["status"] == "cancelled"
    assert registry.killed == [("sess", {"source": "harness.work_cancel", "consume_output": False})]
    refused = control.stop_build(_row("agent", "elsewhere"))
    assert (refused["code"], refused["detail"]) == ("cancel_unavailable", "owner_not_here")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("request", ("cancel_requested", "")), ("kill_tree", ("cancelled", "")), ("none", ("error", "cancel_refused"))],
)
def test_an_announced_build_stops_the_way_its_writer_declared(head, identity, terminated, mode, expected):
    write_record(head / "builds", new_record(job_id="qb", started_at=1.0, build_pid=4242, build_host_start_time=7,
                                             controls={"stop": mode, "restart": "none"}))
    result = control.stop_build(_row("announced", "qb", announcement={"record": "qb.json"}))
    assert (result["status"], result["code"]) == expected
    assert (head / "builds" / "qb.stop").is_file() is (mode == "request")
    assert terminated == ([(4242, 7)] if mode == "kill_tree" else [])


def test_a_kill_tree_on_a_recycled_pid_is_refused(head, identity, terminated):
    identity[4242] = False
    write_record(head / "builds", new_record(job_id="qb", started_at=1.0, build_pid=4242, build_host_start_time=7,
                                             controls={"stop": "kill_tree", "restart": "none"}))
    assert control.stop_build(_row("announced", "qb", announcement={"record": "qb.json"}))["code"] == "not_found"
    assert terminated == []


def test_a_detected_build_stops_only_while_its_slot_is_bound(monkeypatch, identity, terminated):
    bound = [types.SimpleNamespace(workspace_id="ws", slot="launcher")]
    monkeypatch.setattr("agent_runtime.workspace_slots.authorized_roots_bound_here", lambda: bound)
    row = _row("detected", "7001-11", workspace_id="ws", slot_id="launcher")
    assert control.stop_build(row)["status"] == "cancelled" and terminated == [(7001, 11)]
    bound.clear()
    refused = control.stop_build(row)
    assert (refused["code"], refused["detail"]) == ("cancel_refused", "slot_unbound")


# ── restart ──────────────────────────────────────────────────────────────────


@pytest.fixture
def slot(tmp_path):
    from agent_runtime.workspace_slot_env import set_slot_fill
    from agent_runtime.workspace_slots import declare

    machine_roots_cache_clear()
    workspace = WorkspaceStore().create(name="Builds").id
    checkout = tmp_path / "launcher"
    checkout.mkdir()
    write_machine_roots({"launcher": str(checkout)}, dry_run=False)
    declare(workspace, [{"name": "launcher", "repo": {"clone_url": "https://x/launcher.git"},
                         "toolchain": {"env_keys": [{"key": "FLUTTER_ROOT"}]}}], issued_at=STARTED, machine="m")
    set_slot_fill(workspace, "launcher", env={"FLUTTER_ROOT": "C:/flutter"}, path_prepend=["C:/flutter/bin"],
                  tool_paths={"dart": "C:/fill/dart.exe"})
    return workspace, checkout


def test_a_detected_restart_runs_with_the_slot_environment_and_says_so(head, identity, terminated, slot, monkeypatch):
    workspace, checkout = slot
    registry = _Registry()
    original = _row("detected", "7001-11", workspace_id=workspace, slot_id="launcher",
                    restart={"argv": [DART, "flutter_tools.snapshot", "build", "windows"], "cwd": str(checkout)},
                    unknowns=[{"kind": "env_unobserved", "evidence": "FLUTTER_ROOT, JAVA_HOME, PATH, PUB_CACHE"}])
    result = control.restart_build(original, registry=registry)
    assert result["status"] == "restarted" and result["env_source"] == "slot:launcher"
    assert terminated == [(7001, 11)]  # stopped first: it was running
    [(command, kwargs)] = registry.spawned
    assert shlex.split(command)[0] == "C:/fill/dart.exe"  # argv[0] through the slot's tool_paths
    assert kwargs["env_vars"]["FLUTTER_ROOT"] == "C:/flutter" and kwargs["env_vars"]["PATH"].startswith("C:/flutter/bin")
    # The row the restart produces: the new terminal session, reclassified, stamped from the marks file.
    (head / "processes.json").write_text(json.dumps([{"session_id": "proc_restarted", "command": command,
                                                      "cwd": str(checkout), "pid": 9, "host_start_time": 1,
                                                      "started_at": 1.0, "session_key": ""}]), encoding="utf-8")
    monkeypatch.setattr(lanes_process, "_pid_identity", lambda pid, start: (True, True, "verified"))
    frame, _ = lanes_process.TerminalLane(now=2.0, accountant=None).collect()
    lanes_build.BuildLane(now=2.0, accountant=None, frame_rows=frame).collect()
    [new] = [row for row in frame if row["work_id"] == "build:agent:proc_restarted"]
    assert (new["restart_of"], new["env_source"], new["started_by"]["kind"]) == (original["work_id"], "slot:launcher", "operator")
    env_unobserved = lambda row: [u for u in row["unknowns"] if u["kind"] == "env_unobserved"]  # noqa: E731
    assert len(env_unobserved(new)) < len(env_unobserved(original))


def test_a_restart_without_an_argv_or_off_its_slot_is_refused_typed(monkeypatch):
    assert control.restart_build(_row("announced", "qb"))["detail"] == "argv_unknown"
    monkeypatch.setattr("agent_runtime.workspace_slots.authorized_roots_bound_here", lambda: [])
    off = _row("detected", "1-1", workspace_id="ws", slot_id="gone", restart={"argv": [DART], "cwd": "C:/x"})
    assert control.restart_build(off)["detail"] == "slot_unbound"


# ── the doors: methods, argv, replay guard, tiers ────────────────────────────


def _call(method, params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def test_the_detected_restart_method_takes_no_confirm_and_both_doors_share_the_replay_guard(monkeypatch):
    from agent_runtime import running_work
    from hermes_cli.harness_parts import work_commands

    row = _row("detected", "5-5", restart={"argv": [DART], "cwd": "C:/x"}, status="completed", outcome="succeeded")
    monkeypatch.setattr(running_work, "find_work_row", lambda work_id: row if work_id == row["work_id"] else None)
    monkeypatch.setattr(control, "restart_build", lambda r: {"status": "restarted", "work_id": r["work_id"]})
    fresh = _call("runtime.work.restart", {"work_id": row["work_id"], "issued_at": "2026-10-04T13:00:00+00:00"})
    assert fresh["result"]["status"] == "restarted"  # no confirm parameter exists or is needed
    stale = {"work_id": row["work_id"], "issued_at": "2026-10-04T11:00:00+00:00"}
    assert _call("runtime.work.restart", stale)["error"]["data"]["reason"] == "stale_revision"
    assert _call("runtime.work.cancel", stale)["error"]["data"]["reason"] == "stale_revision"
    argv = Namespace(work_id=row["work_id"], issued_at=stale["issued_at"], json=True, output="json")
    assert work_commands._cmd_work_restart(argv) == 4


def test_both_methods_are_console_tier():
    tiers = serve_rpc.manifest()["tiers"]
    assert tiers["runtime.work.cancel"] == tiers["runtime.work.restart"] == "console"
