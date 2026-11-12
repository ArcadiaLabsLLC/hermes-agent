"""The detected build source over a FAKE process table (plan ``build-running-work-2026-10-04.md`` §5, row H6).

Owner calls 1 and 7, refinement 2: only builds under a bound repo slot are shown; anything
the scan cannot classify is indexed WITH evidence and not shown; the ONE bound is the 50 ms
budget, breached ⇒ typed WITH the measured ms; no cap on slots, and the cost is on the frame.
"""

from __future__ import annotations

import pytest

from agent_runtime.builds import detect
from agent_runtime.builds.liveness import PROGRESS
from agent_runtime.workspace_slots import BoundSlot, SlotCensus
from tests.agent_runtime._build_rows_fixture import SNAPSHOT, _Proc

DART = "C:/flutter/bin/cache/dart-sdk/bin/dart.exe"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(detect, "_ENABLED", True)
    PROGRESS.clear()
    yield
    PROGRESS.clear()


def _build(pid, cwd, **kw):
    return _Proc(pid, "dart.exe", [DART, SNAPSHOT, "build", "windows", "--release"], str(cwd), **kw)


def _census(tmp_path, *names):
    slots = []
    for name in names:
        (tmp_path / name).mkdir(exist_ok=True)
        slots.append(BoundSlot("ws", name, tmp_path / name))
    return SlotCensus(len(slots), tuple(slots))


def test_only_a_build_under_a_bound_slot_is_detected(tmp_path):
    census = _census(tmp_path, "launcher")
    (tmp_path / "elsewhere").mkdir()
    result = detect.scan(now=1.0, census=census, owned=set(), table=[
        _build(1, tmp_path / "launcher" / "lib"), _build(2, tmp_path / "elsewhere")], clock=lambda: 0.0)
    assert [b.pid for b in result.builds] == [1]
    assert result.builds[0].slot.slot == "launcher" and result.builds[0].command.target == "windows"
    assert (result.processes_examined, result.candidates) == (2, 2)
    assert result.unknowns.wire() == []  # out-of-scope is by design, not an unknown


def test_what_the_scan_cannot_classify_is_indexed_and_not_shown(tmp_path):
    census = _census(tmp_path, "launcher")
    result = detect.scan(now=1.0, census=census, owned=set(), table=[
        _Proc(3, "dart.exe", ["C:/tools/weird-launcher.exe", "--go"], str(tmp_path / "launcher")),
        _Proc(4, "flutter.bat", PermissionError("denied"), str(tmp_path / "launcher")),
        _Proc(5, "dart.exe", [DART, SNAPSHOT, "build", "apk"], PermissionError("denied")),
        _Proc(6, "dart.exe", [DART, "language-server"], str(tmp_path / "launcher")),
    ], clock=lambda: 0.0)
    assert result.builds == []
    kinds = sorted((entry["kind"], entry["evidence"]) for entry in result.unknowns.wire())
    assert kinds == [
        ("cwd_unreadable", f"dart.exe {DART} {SNAPSHOT} build: PermissionError"),
        ("process_unidentified", "dart.exe C:/tools/weird-launcher.exe --go"),
        ("process_unidentified", "flutter.bat: cmdline unreadable (PermissionError)"),
    ]


def test_an_owned_pid_and_its_descendants_are_skipped(tmp_path):
    census = _census(tmp_path, "launcher")
    table = [_build(10, tmp_path / "launcher"), _build(11, tmp_path / "launcher", parents=[(10, "cmd.exe")]),
             _build(12, tmp_path / "launcher", parents=[(99, "cmd.exe")])]
    owned = detect.scan(now=1.0, census=census, owned={10}, table=table, clock=lambda: 0.0)
    assert [b.pid for b in owned.builds] == [12]


def test_a_budget_breach_is_typed_and_carries_the_measured_ms(tmp_path):
    census = _census(tmp_path, "launcher")
    ticks = iter(range(100))
    result = detect.scan(now=1.0, census=census, owned=set(), table=[_build(i, tmp_path / "launcher") for i in range(5)],
                         clock=lambda: next(ticks) * 0.04)
    sub = result.sub()
    assert (sub["status"], sub["reason"]) == ("unavailable", "scan_budget")
    assert sub["scan_ms"] > sub["budget_ms"] == 50
    assert result.builds == []


def test_eighty_bound_slots_are_still_correct_and_the_cost_is_reported(tmp_path):
    census = _census(tmp_path, *[f"s{i}" for i in range(80)])
    table = [_build(100 + i, tmp_path / f"s{i}" / "app") for i in range(0, 80, 8)]
    # A frozen clock: correctness at 80 slots is not a wall-clock race (under suite load the real
    # perf_counter crossed the 50 ms budget and returned scan_budget, FORK-BUILD-DETECT-CLOCK-FLAKE).
    result = detect.scan(now=1.0, census=census, owned=set(), table=table, clock=lambda: 0.0)
    assert sorted(b.slot.slot for b in result.builds) == sorted(f"s{i}" for i in range(0, 80, 8))
    sub = result.sub()
    assert sub["status"] == "ok" and sub["candidates"] == 10 and isinstance(sub["scan_ms"], int)


@pytest.mark.parametrize(
    ("census", "enabled", "reason"),
    [(SlotCensus(1, ()), False, "not_in_process"), (SlotCensus(0, ()), True, "no_slots_declared"),
     (SlotCensus(2, ()), True, "slots_unbound_here")],
)
def test_the_gate_says_why_it_did_not_look(monkeypatch, census, enabled, reason):
    monkeypatch.setattr(detect, "_ENABLED", enabled)
    sub = detect.scan(now=1.0, census=census, owned=set(), table=[]).sub()
    assert (sub["status"], sub["reason"]) == ("unavailable", reason)


def test_a_cpu_stalled_detected_build_is_marked_stalled_through_the_lane(tmp_path, monkeypatch):
    from agent_runtime.running_work import lanes_build

    census = _census(tmp_path, "launcher")
    monkeypatch.setattr(lanes_build, "_census", lambda: census)
    monkeypatch.setattr(lanes_build, "_head_home", lambda: (tmp_path / "home", "test"))
    monkeypatch.setattr(lanes_build, "_detect_table", [_build(7, tmp_path / "launcher", cpu=4.0)])
    first, _ = lanes_build.BuildLane(now=1000.0, accountant=None, frame_rows=[]).collect()
    later, _ = lanes_build.BuildLane(now=1000.0 + 300, accountant=None, frame_rows=[]).collect()
    assert (first[0]["liveness"], later[0]["liveness"], later[0]["status"]) == ("live", "stalled", "stalled")
    assert later[0]["seconds_since_progress"] == 300.0 and later[0]["progress_signal"] == "cpu"
    # Positive control: CPU that moved is progress.
    monkeypatch.setattr(lanes_build, "_detect_table", [_build(7, tmp_path / "launcher", cpu=9.0)])
    moved, _ = lanes_build.BuildLane(now=1000.0 + 600, accountant=None, frame_rows=[]).collect()
    assert moved[0]["liveness"] == "live"


# --- RT-BUILD-SCAN-FAILS-ON-OWNER-WINDOWS: one unreadable process, and the Windows table ----------


class _VanishingPid(_Proc):
    """A candidate whose pid read raises OUTSIDE the fact guard (the process went mid-read)."""

    @property
    def pid(self):
        raise ProcessLookupError("gone")

    @pid.setter
    def pid(self, _value):
        pass


def test_one_process_that_cannot_be_read_is_skipped_not_the_whole_scan(tmp_path):
    census = _census(tmp_path, "launcher")
    gone = _VanishingPid(0, "dart.exe", [DART, SNAPSHOT, "build", "windows"], str(tmp_path / "launcher"))
    result = detect.scan(now=1.0, census=census, owned=set(), table=[gone, _build(21, tmp_path / "launcher")],
                         clock=lambda: 0.0)
    assert (result.status, result.reason) == ("ok", "")
    assert [b.pid for b in result.builds] == [21]
    assert [(e["kind"], e["evidence"]) for e in result.unknowns.wire()] == [
        ("process_unidentified", "dart.exe: unreadable (ProcessLookupError)")]


class _FakePsutil:
    """``psutil`` as the Windows table uses it: ``Process(pid)`` only, every open recorded."""

    def __init__(self, procs, created):
        self.procs, self.created, self.opened = procs, created, []

    def Process(self, pid):  # noqa: N802 - psutil's name
        self.opened.append(pid)
        if pid not in self.created:
            raise ProcessLookupError(pid)
        fake = self.procs.get(pid)
        return type("P", (), {"create_time": lambda _s: self.created[pid], "cmdline": lambda _s: fake._argv,
                              "cwd": lambda _s: fake._cwd,
                              "cpu_times": lambda _s: type("T", (), {"user": 1.0, "system": 0.5})()})()

    def process_iter(self, _attrs):
        raise AssertionError("the Windows table never walks process_iter")


def test_on_windows_the_names_come_from_one_snapshot_and_only_candidates_are_opened(tmp_path, monkeypatch):
    census = _census(tmp_path, "launcher")
    build = _build(30, tmp_path / "launcher")
    snapshot = detect.WindowsSnapshot({4: (0, "System"), 20: (4, "cmd.exe"), 30: (20, "dart.exe"),
                                       40: (20, "svchost.exe"), 50: (20, "explorer.exe")})
    psutil = _FakePsutil({30: build}, {4: 1.0, 20: 2.0, 30: 3.0})
    monkeypatch.setattr(detect.sys, "platform", "win32")
    monkeypatch.setattr(detect, "windows_snapshot", lambda: snapshot)
    monkeypatch.setattr(detect._PsutilProcess, "start", lambda _self: 11)
    result = detect.scan(now=1.0, census=census, owned=set(), table=detect.psutil_table(psutil), clock=lambda: 0.0)
    assert [(b.pid, b.parents) for b in result.builds] == [(30, [(20, "cmd.exe"), (4, "System")])]
    assert result.processes_examined == 5 and result.candidates == 1
    assert set(psutil.opened) <= {30, 20, 4}  # never a non-candidate process's own open


def test_the_snapshot_parent_chain_stops_at_a_recycled_pid_a_loop_or_an_unknown_age():
    snapshot = detect.WindowsSnapshot({1: (0, "System"), 2: (1, "wininit.exe"), 3: (2, "cmd.exe"),
                                       4: (3, "dart.exe"), 7: (8, "a.exe"), 8: (7, "b.exe")})
    ages = {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 7: 7.0, 8: 6.0}
    assert snapshot.parents(4, created=ages.get) == [(3, "cmd.exe"), (2, "wininit.exe"), (1, "System")]
    assert snapshot.parents(4, created={**ages, 3: 5.0}.get) == []  # a parent younger than its child: recycled
    assert snapshot.parents(4, created={**ages, 2: None}.get) == [(3, "cmd.exe")]  # age unreadable: stop
    assert snapshot.parents(7, created={7: 7.0, 8: 6.0}.get) == [(8, "b.exe")]  # loop: 8 -> 7 is seen


@pytest.mark.skipif(detect.sys.platform != "win32", reason="the Toolhelp32 snapshot is Windows-only")
def test_the_real_windows_snapshot_names_this_process_and_its_parent():
    import os

    rows = detect.windows_snapshot().rows
    ppid, name = rows[os.getpid()]
    assert name.lower().startswith("python") and ppid == os.getppid()


# --- RT-BUILD-FLUTTER-RUN-READS-STALLED: the tree's CPU, and a run that hosts its app -----------


class _TreeProc(_Proc):
    """A candidate with descendants (``dart.exe`` → ``dartvm.exe`` → frontend server, the app …)."""

    def __init__(self, *args, tree=(), **kw):
        super().__init__(*args, **kw)
        self.tree = list(tree)

    def descendants(self):
        return list(self.tree)


def _run(pid, root, *, cpu=0.03, tree=()):
    return _TreeProc(pid, "dart.exe", [DART, SNAPSHOT, "run", "-d", "windows"], str(root), cpu=cpu, tree=tree)


def _vm(cpu):
    return detect.Descendant(41, "dartvm.exe", "C:/flutter/bin/cache/dart-sdk/bin/dartvm.exe", cpu)


def _app(root):
    return detect.Descendant(42, "eternia_launcher.exe", str(root / "build" / "windows" / "x64" / "runner" / "Debug"
                                                             / "eternia_launcher.exe"), 500.0)


def _lane_rows(monkeypatch, tmp_path, census, table, now, accountant=None):
    from agent_runtime.running_work import lanes_build

    monkeypatch.setattr(lanes_build, "_census", lambda: census)
    monkeypatch.setattr(lanes_build, "_head_home", lambda: (tmp_path / "home", "test"))
    monkeypatch.setattr(lanes_build, "_detect_table", table)
    rows, _source = lanes_build.BuildLane(now=now, accountant=accountant, frame_rows=[]).collect()
    return rows


def test_a_flutter_run_hosting_its_built_app_is_not_a_build_and_offers_no_stop(tmp_path, monkeypatch):
    # The owner's own `flutter run -d windows`: the wrapper's CPU never moves, its app runs below it.
    from agent_runtime.projection_accountant import ProjectionAccountant

    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    run = _run(8, root, tree=[_vm(9.0), _app(root)])
    scanned = detect.scan(now=1.0, census=census, owned=set(), table=[run], clock=lambda: 0.0)
    assert scanned.builds[0].app.pid == 42
    accountant = ProjectionAccountant("running_work")
    first = _lane_rows(monkeypatch, tmp_path, census, [run], 1000.0, accountant)
    later = _lane_rows(monkeypatch, tmp_path, census, [run], 1000.0 + 600)
    assert first == [] and later == []  # never a row, so never "stalled" and never a Stop to press
    summary = accountant.summary()
    assert "build_app_running" in summary["by_design"]


def test_a_flutter_run_still_compiling_reads_building_by_its_trees_cpu(tmp_path, monkeypatch):
    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    first = _lane_rows(monkeypatch, tmp_path, census, [_run(8, root, tree=[_vm(5.0)])], 1000.0)
    later = _lane_rows(monkeypatch, tmp_path, census, [_run(8, root, tree=[_vm(60.0)])], 1000.0 + 300)
    assert (first[0]["status"], later[0]["status"], later[0]["liveness"]) == ("running", "running", "live")
    assert later[0]["controls"]["stop"] == "allowed"  # a build, not an app: Stop stays offered


def test_a_hung_compile_still_reads_stalled(tmp_path, monkeypatch):
    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    hung = [_run(8, root, tree=[_vm(5.0)])]
    _lane_rows(monkeypatch, tmp_path, census, hung, 1000.0)
    later = _lane_rows(monkeypatch, tmp_path, census, hung, 1000.0 + 300)
    assert (later[0]["status"], later[0]["seconds_since_progress"]) == ("stalled", 300.0)


def test_only_a_run_hosts_an_app_and_only_from_its_build_folder(tmp_path):
    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    build = _TreeProc(9, "dart.exe", [DART, SNAPSHOT, "build", "windows"], str(root), tree=[_app(root)])
    elsewhere = detect.Descendant(43, "chrome.exe", "C:/Program Files/Google/Chrome/chrome.exe", 3.0)
    refused = detect.Descendant(44, "eternia_launcher.exe", None, None)
    scanned = detect.scan(now=1.0, census=census, owned=set(), clock=lambda: 0.0,
                          table=[build, _run(10, root, tree=[elsewhere, refused])])
    assert [(b.pid, b.app) for b in scanned.builds] == [(9, None), (10, None)]
    assert scanned.builds[1].cpu == pytest.approx(3.03)  # a refused CPU read adds nothing


def test_the_snapshot_descendants_skip_a_recycled_pid_and_an_unknown_age():
    snapshot = detect.WindowsSnapshot({10: (1, "dart.exe"), 11: (10, "dartvm.exe"), 12: (11, "app.exe"),
                                       13: (10, "old.exe"), 14: (11, "ghost.exe"), 15: (14, "below.exe")})
    ages = {10: 10.0, 11: 11.0, 12: 12.0, 13: 5.0, 14: None, 15: 15.0}
    assert snapshot.descendants(10, created=ages.get) == [(11, "dartvm.exe"), (12, "app.exe")]


# --- RT-BUILD-SCAN-FIRST-PASS-OVER-BUDGET: one-time imports are paid before the budget's clock ------


def test_the_first_scans_one_time_imports_are_paid_before_the_budget_clock(tmp_path, monkeypatch):
    # A fresh process's first scan imported gateway.status (~300 ms) on its first candidate and read
    # scan_budget; the warm-up runs before the clock starts, so the budget times only the walk.
    census = _census(tmp_path, "launcher")
    now = [0.0]
    warmed = []

    def slow_imports():
        warmed.append(now[0])
        now[0] += 0.3  # the measured first-use cost

    monkeypatch.setattr(detect, "warm_detection", slow_imports)
    monkeypatch.setattr(detect, "psutil_table", lambda _psutil: [_build(1, tmp_path / "launcher")])
    result = detect.scan(now=1.0, census=census, owned=set(), clock=lambda: now[0])
    assert warmed == [0.0]
    assert (result.status, result.reason, result.scan_ms) == ("ok", "", 0)
    assert [b.pid for b in result.builds] == [1]
    # A walk that is slow ITSELF still breaches: the warm-up hides nothing it does not pay for.
    monkeypatch.setattr(detect, "psutil_table", lambda _psutil: [_build(i, tmp_path / "launcher") for i in range(5)])
    slow = iter(range(100))
    breached = detect.scan(now=1.0, census=census, owned=set(), clock=lambda: next(slow) * 0.04)
    assert (breached.status, breached.reason) == ("unavailable", "scan_budget")


def test_an_injected_table_never_warms_and_the_serve_sweep_warms_before_its_first_tick(tmp_path, monkeypatch):
    import threading

    from agent_runtime.builds import sweep

    calls = []
    monkeypatch.setattr(detect, "warm_detection", lambda: calls.append("warm"))
    detect.scan(now=1.0, census=_census(tmp_path, "launcher"), owned=set(), table=[], clock=lambda: 0.0)
    assert calls == []
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(sweep, "_STOP", stop)
    sweep._loop(type("S", (), {"tick": lambda _self: calls.append("tick")})())
    assert calls == ["warm"]


def test_the_real_warm_up_runs_and_a_second_one_is_cheap():
    import time

    detect.warm_detection()
    started = time.perf_counter()
    detect.warm_detection()
    assert (time.perf_counter() - started) * 1000.0 < detect.DETECT_BUDGET_MS


# --- RT-BUILD-FLUTTER-RUN-WEB-LIVENESS: a web run's app is its browser, or a browser connected to it --


def _web(pid, root, device, *, tree=(), tcp=None):
    proc = _TreeProc(pid, "dart.exe", [DART, SNAPSHOT, "run", "-d", device], str(root), cpu=0.03, tree=tree)
    if tcp is not None:
        proc.tcp = lambda: tcp() if callable(tcp) else list(tcp)
    return proc


def _chrome(pid=45):
    return detect.Descendant(pid, "chrome.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe", 2.0)


def test_a_chrome_run_is_an_app_session_once_its_browser_is_up_and_building_until_then(tmp_path, monkeypatch):
    from agent_runtime.projection_accountant import ProjectionAccountant

    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    compiling = _lane_rows(monkeypatch, tmp_path, census, [_web(8, root, "chrome", tree=[_vm(5.0)])], 1000.0)
    moved = _lane_rows(monkeypatch, tmp_path, census, [_web(8, root, "chrome", tree=[_vm(60.0)])], 1000.0 + 300)
    assert (compiling[0]["status"], moved[0]["status"]) == ("running", "running")
    accountant = ProjectionAccountant("running_work")
    running = [_web(8, root, "chrome", tree=[_vm(60.0), _chrome()])]
    assert _lane_rows(monkeypatch, tmp_path, census, running, 1000.0 + 600, accountant) == []
    assert _lane_rows(monkeypatch, tmp_path, census, running, 1000.0 + 1200) == []
    assert "build_app_running" in accountant.summary()["by_design"]
    edge = detect.scan(now=1.0, census=census, owned=set(), clock=lambda: 0.0, table=[
        _web(9, root, "edge", tree=[detect.Descendant(46, "msedge.exe", "C:/Edge/msedge.exe", 1.0)])])
    assert edge.builds[0].app.pid == 46


def test_a_hung_web_compile_still_reads_stalled(tmp_path, monkeypatch):
    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    for device, tcp in (("chrome", None), ("web-server", [(41, "LISTEN", 8080, None)])):
        PROGRESS.clear()
        hung = [_web(8, root, device, tree=[_vm(5.0)], tcp=tcp)]
        _lane_rows(monkeypatch, tmp_path, census, hung, 1000.0)
        later = _lane_rows(monkeypatch, tmp_path, census, hung, 1000.0 + 300)
        assert (device, later[0]["status"]) == (device, "stalled")


def test_a_web_server_run_is_an_app_session_once_a_browser_is_connected_to_it(tmp_path, monkeypatch):
    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    served = [(41, "LISTEN", 8080, None), (41, "ESTABLISHED", 8080, 51234), (999, "ESTABLISHED", 51234, 8080)]
    rows = _lane_rows(monkeypatch, tmp_path, census, [_web(8, root, "web-server", tree=[_vm(5.0)], tcp=served)], 1000.0)
    assert rows == []
    scanned = detect.scan(now=1.0, census=census, owned=set(), clock=lambda: 0.0,
                          table=[_web(8, root, "web-server", tree=[_vm(5.0)], tcp=served)])
    assert (scanned.builds[0].app.pid, scanned.builds[0].app.name) == (41, "web server on port 8080 (a browser is connected)")


@pytest.mark.parametrize(
    "tcp",
    [
        [(41, "LISTEN", 8080, None)],  # served, nobody connected yet: not told from a hang
        [(41, "LISTEN", 8080, None), (41, "ESTABLISHED", 50000, 443)],  # an OUTBOUND connection (pub, a CDN)
        [(41, "ESTABLISHED", 8080, 51234), (77, "LISTEN", 8080, None)],  # the listener is not the run's
        lambda: (_ for _ in ()).throw(PermissionError("denied")),  # the TCP table refused
    ],
    ids=["listening-only", "outbound-only", "foreign-listener", "refused"],
)
def test_a_web_server_run_without_a_connected_browser_is_not_an_app(tmp_path, tcp):
    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    scanned = detect.scan(now=1.0, census=census, owned=set(), clock=lambda: 0.0,
                          table=[_web(8, root, "web-server", tree=[_vm(5.0)], tcp=tcp)])
    assert scanned.builds[0].app is None


def test_a_browser_below_a_desktop_or_web_server_run_is_not_its_app(tmp_path):
    census = _census(tmp_path, "launcher")
    root = tmp_path / "launcher"
    scanned = detect.scan(now=1.0, census=census, owned=set(), clock=lambda: 0.0, table=[
        _web(8, root, "windows", tree=[_vm(5.0), _chrome()]), _web(9, root, "web-server", tree=[_chrome(47)], tcp=[])])
    assert [b.app for b in scanned.builds] == [None, None]
