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
    result = detect.scan(now=1.0, census=census, owned=set(), table=table)
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
