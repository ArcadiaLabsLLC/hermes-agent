"""The ONE seeded home behind ``tests/fixtures/builds/build_rows.json`` (build plan §1, row H4).

The golden is WRITTEN by the producer from a seeded home, never typed:

    python -m tests.agent_runtime._build_rows_fixture --write

Seeds: a terminal checkpoint (agent-started builds, reclassified by the build lane), the
announced-build registry, a slot document + machine fill, and a FAKE process table for the
detected scan; identity, ownership and the bound slots are stubbed at the names the lanes
BIND, so the rows are deterministic. Paths are redacted to ``<root>`` with ``/``
separators. ``test_build_rows_fixture.py`` re-runs this and compares bytes; the launcher
mirrors the file into ``test/fixtures/harness_stream/build_rows.json``.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "builds" / "build_rows.json"
NOW = 1_759_590_720.0
#: pid -> the identity verdict the stubbed probe answers.
VERDICTS = {
    4101: "verified", 4102: "verified", 4103: "no_baseline", 4105: "verified",
    6001: "verified", 6006: "dead", 6008: "start_time_unreadable",
    5101: "verified",
}
OWNERS = {"sess_owned": ("dev", "personainst_dev_frontend")}


def _identity(pid: Any, _expected: Any) -> tuple[bool, bool, str]:
    verdict = VERDICTS.get(int(pid) if isinstance(pid, int) or str(pid).isdigit() else -1, "dead")
    return verdict != "dead", verdict == "verified", verdict


def _owner(session: Any, *, memo: Any = None) -> tuple[str, str]:
    return OWNERS.get(str(session or ""), ("", ""))


class _Session:
    def __init__(self, cwd: str, output: str, total: int) -> None:
        self.cwd, self.output_buffer, self.total_output_chars = cwd, output, total
        self._lock = threading.Lock()


def _checkpoint(root: Path) -> list[dict[str, Any]]:
    launcher, backend = root / "launcher", root / "scratch"
    return [
        {"session_id": "sess_build_live", "command": "flutter build windows --release", "cwd": str(launcher),
         "pid": 4101, "host_start_time": 1, "started_at": NOW - 90, "session_key": "sess_owned"},
        {"session_id": "sess_build_stalled", "command": f'cd "{backend}" && flutter build apk --debug', "cwd": str(root),
         "pid": 4102, "host_start_time": 1, "started_at": NOW - 600, "session_key": ""},
        {"session_id": "sess_build_unproven", "command": "fvm flutter run -d windows --profile", "cwd": str(launcher),
         "pid": 4103, "started_at": NOW - 30, "session_key": "sess_owned"},
        {"session_id": "sess_build_elsewhere", "command": "dart run tool/stagec_parity_build.dart", "cwd": str(launcher),
         "pid": 4105, "host_start_time": 1, "started_at": NOW - 45, "session_key": "sess_owned"},
        {"session_id": "sess_not_a_build", "command": "git status", "cwd": str(launcher),
         "pid": 4105, "host_start_time": 1, "started_at": NOW - 5, "session_key": "sess_owned"},
    ]


def _sessions(root: Path) -> dict[str, _Session]:
    return {
        "sess_build_live": _Session(str(root / "launcher"), "Resolving dependencies...\nBuilding Windows application...\n", 120),
        "sess_build_stalled": _Session(str(root), "Running Gradle task 'assembleDebug'...\n", 40),
    }


def _record(root: Path, job_id: str, **fields: Any) -> dict[str, Any]:
    from agent_runtime.builds.registry import new_record

    base = dict(
        job_id=job_id, toolchain="flutter", target="windows", mode="release", project_root=str(root / "launcher"),
        label="", started_by={"kind": "tool", "label": "launcher_qa"}, session_key="sess_owned",
        writer={"pid": 6001, "host_start_time": 1}, status="running", stage="compiling",
        stage_detail="Building Windows application...", started_at=NOW - 120, heartbeat_at=NOW - 5,
        controls={"stop": "request", "restart": "command"},
        restart={"argv": ["dart", "run", "tool/stagec_qa_mcp_server/bin/prebuild.dart"], "cwd": str(root / "launcher")},
        unknowns=[],
    )
    base.update(fields)
    return new_record(**base)


def _records(root: Path) -> list[dict[str, Any]]:
    finished = {"status": "finished", "finished_at": NOW - 10}
    return [
        _record(root, "qb-live", target="qa_isolated", build_pid=5101, build_host_start_time=1, expected_ms=330000,
                mcp_job={"server": "launcher_qa", "job_id": "qb-live"},
                unknowns=[{"kind": "output_unreadable", "evidence": "UnicodeDecodeError", "seen_at": NOW - 60}]),
        _record(root, "qb-succeeded", stage="done", outcome="succeeded", exit_code=0, mode="debug",
                artifact={"path": str(root / "launcher" / "build" / "app.exe"), "kind": "executable"}, **finished),
        _record(root, "qb-failed", stage="linking", outcome="failed", exit_code=1, mode="profile",
                unknowns=[{"kind": "artifact_unlocated", "evidence": "no 'Built' line", "seen_at": NOW - 11}], **finished),
        _record(root, "qb-stall-ended", stage="packaging", outcome="stalled", target="apk",
                artifact={"path": str(root / "launcher" / "build" / "app.apk"), "kind": "bundle"}, **finished),
        _record(root, "qb-stopped", stage="finishing", outcome="stopped", restart=None, mode="",
                artifact={"path": str(root / "launcher" / "build" / "linux" / "bundle"), "kind": "directory"}, **finished),
        _record(root, "qb-lost", stage="resolving", writer={"pid": 6006, "host_start_time": 1},
                artifact={"path": str(root / "launcher" / "build" / "notes.txt"), "kind": "other"}),
        _record(root, "qb-stalled", stage="preparing", heartbeat_at=NOW - 300, project_root=str(root / "elsewhere"),
                unknowns=[{"kind": "process_unidentified", "evidence": "dart.exe language-server", "seen_at": NOW - 7},
                          {"kind": "cwd_unreadable", "evidence": "AccessDenied", "seen_at": NOW - 7},
                          {"kind": "wrapper_unobserved", "evidence": "cmd.exe -> flutter.bat -> dart.exe", "seen_at": NOW - 7},
                          {"kind": "env_unobserved", "evidence": "PUB_CACHE, JAVA_HOME", "seen_at": NOW - 7},
                          {"kind": "path_unobserved", "evidence": "PATH", "seen_at": NOW - 7},
                          {"kind": "slot_unbound_here", "evidence": "backend: bound on mach_far", "seen_at": NOW - 7},
                          {"kind": "slot_probe_unknown", "evidence": "flutter --version: TimeoutExpired", "seen_at": NOW - 7},
                          {"kind": "toolchain_unrecognized", "evidence": "gradlew.bat", "seen_at": NOW - 7}]),
        _record(root, "qb-unproven", stage="unknown", toolchain="dart", writer={"pid": 6008, "host_start_time": 1},
                started_by={"kind": "operator", "label": "prebuild.dart by hand"}, session_key="sess_unknown",
                controls={"stop": "kill_tree", "restart": "none"}, restart=None),
        _record(root, "qb-queued", stage="queued", status="queued", heartbeat_at=NOW - 3000, target="qa_isolated",
                toolchain="unknown"),
        _record(root, "qb-stalling", heartbeat_at=NOW - 130, controls={"stop": "none", "restart": "command"}),
    ]


class _Proc:
    """A fake process-table entry with the scan's read interface; a fact may be an exception."""

    def __init__(self, pid: int, name: str, argv: Any, cwd: Any, *, start: int = 11, cpu: float = 1.0,
                 parents: list[tuple[int, str]] | None = None) -> None:
        self.pid, self.name, self._argv, self._cwd = pid, name, argv, cwd
        self._start, self._cpu, self._parents = start, cpu, parents or [(9000, "cmd.exe"), (8000, "explorer.exe")]

    @staticmethod
    def _fact(value: Any) -> Any:
        if isinstance(value, BaseException):
            raise value
        return value

    def cmdline(self) -> Any:
        return self._fact(self._argv)

    def cwd(self) -> Any:
        return self._fact(self._cwd)

    def start(self) -> int:
        return self._start

    def cpu(self) -> float:
        return self._cpu

    def parents(self) -> list[tuple[int, str]]:
        return list(self._parents)


SNAPSHOT = r"C:/flutter/bin/cache/flutter_tools.snapshot"


def process_table(root: Path) -> list[_Proc]:
    dart = r"C:/flutter/bin/cache/dart-sdk/bin/dart.exe"
    return [
        _Proc(7001, "dart.exe", [dart, SNAPSHOT, "build", "windows", "--release"], str(root / "launcher"), cpu=12.5),
        _Proc(7002, "dart.exe", [dart, SNAPSHOT, "build", "apk", "--debug"], str(root / "backend" / "app"), cpu=3.0),
        _Proc(7003, "dart.exe", [dart, "language-server"], str(root / "launcher")),
        _Proc(7004, "flutter.bat", PermissionError("access denied"), str(root / "launcher")),
        _Proc(7005, "dart.exe", [dart, SNAPSHOT, "build", "windows"], PermissionError("access denied")),
        _Proc(7006, "python.exe", ["python", "-m", "http.server"], str(root / "launcher")),
        _Proc(7007, "dart.exe", [dart, SNAPSHOT, "build", "windows"], str(root / "elsewhere")),
        _Proc(7008, "dart.exe", [dart, SNAPSHOT, "build", "windows"], str(root / "launcher"), parents=[(4101, "cmd.exe")]),
        _Proc(7009, "dart.exe", [r"C:/tools/weird-launcher.exe", "--go"], str(root / "launcher")),
    ]


def _seed_slots(root: Path) -> None:
    from agent_runtime.workspace_slot_env import set_slot_fill
    from agent_runtime.workspace_slots import write_document

    write_document("ws_team", {"schema_version": 1, "workspace_id": "ws_team", "issued_at": "2026-10-04T12:00:00+00:00",
                               "machines": {}, "slots": {
        "launcher": {"repo": {"clone_url": "https://x/launcher.git", "default_branch": "main"},
                     "toolchain": {"kind": "flutter", "tools": [], "env_keys": [{"key": "FLUTTER_ROOT", "required": True}],
                                   "dotenv": None},
                     "context": {"role": "", "files": ["AGENTS.md"]}, "recipe": {"revision": 0, "steps": []},
                     "issued_at": "2026-10-04T12:00:00+00:00", "removed_at": None},
        "backend": {"repo": {"clone_url": "https://x/backend.git", "default_branch": "main"}, "toolchain": {},
                    "context": {"role": "", "files": ["AGENTS.md"]}, "recipe": {"revision": 0, "steps": []},
                    "issued_at": "2026-10-04T12:00:00+00:00", "removed_at": None}}})
    set_slot_fill("ws_team", "launcher", env={"FLUTTER_ROOT": "C:/flutter"}, path_prepend=["C:/flutter/bin"],
                  tool_paths={"flutter": "C:/flutter/bin/flutter.bat"})


def _redact(value: Any, root: Path) -> Any:
    text = json.dumps(value, sort_keys=True)
    for spelling in {str(root), str(root).replace("\\", "/")}:
        text = text.replace(json.dumps(spelling)[1:-1], "<root>")
    return json.loads(text.replace("\\\\", "/"))


@contextmanager
def _seeded(root: Path) -> Iterator[None]:
    from agent_runtime.builds import detect
    from agent_runtime.builds.liveness import PROGRESS
    from agent_runtime.builds.registry import write_record
    from agent_runtime.running_work import lanes_build, lanes_process
    from agent_runtime.workspace_slots import BoundSlot, SlotCensus

    home = root / "home"
    for name in ("launcher", "backend", "elsewhere"):
        (root / name).mkdir(parents=True, exist_ok=True)
    _seed_slots(root)
    home.mkdir(parents=True, exist_ok=True)
    (home / "processes.json").write_text(json.dumps(_checkpoint(root)), encoding="utf-8")
    for record in _records(root):
        write_record(home / "builds", record)
    sessions = _sessions(root)
    PROGRESS.clear()
    PROGRESS.observe(("agent", "sess_build_stalled"), 40, NOW - 300)
    PROGRESS.observe(("detected", 7002, 11), 3.0, NOW - 300)
    census = SlotCensus(2, (BoundSlot("ws_team", "launcher", root / "launcher"),
                            BoundSlot("ws_team", "backend", root / "backend")))
    patches = [
        (lanes_process, "_head_home", lambda: (home, "test_home")),
        (lanes_process, "_pid_identity", _identity),
        (lanes_process, "_owner_of", _owner),
        (lanes_build, "_head_home", lambda: (home, "test_home")),
        (lanes_build, "_pid_identity", _identity),
        (lanes_build, "_owner_of", _owner),
        (lanes_build, "_census", lambda: census),
        (lanes_build, "_registry_session", lambda _registry, sid: sessions.get(sid)),
        (lanes_build, "_detect_table", process_table(root)),
        (lanes_build, "_detect_clock", lambda: 0.0),
        (detect, "_ENABLED", True),
    ]
    with ExitStack() as stack:
        for module, name, value in patches:
            held = getattr(module, name)
            setattr(module, name, value)
            stack.callback(setattr, module, name, held)
        stack.callback(PROGRESS.clear)
        yield


def produce(root: Path) -> dict[str, Any]:
    """Seed ``root`` and build the rows through the REAL lanes: terminal, then build."""

    from agent_runtime.running_work.lanes_build import BuildLane
    from agent_runtime.running_work.lanes_process import TerminalLane

    with _seeded(root):
        frame, _terminal_source = TerminalLane(now=NOW, accountant=None).collect()
        announced, source = BuildLane(now=NOW, accountant=None, frame_rows=frame).collect()
    rows = [row for row in frame if row["kind"] == "build"] + announced
    payload = {"rows": sorted(rows, key=lambda row: row["work_id"]), "sources": {"build": source},
               "source_variants": _source_variants(root)}
    return _redact(payload, root)


def _source_variants(root: Path) -> dict[str, Any]:
    """``sources.build`` in the states one frame cannot show at once: each sub reason, named."""

    from agent_runtime.running_work import lanes_build
    from agent_runtime.running_work.lanes_build import BuildLane

    unreadable = root / "unreadable_home"
    unreadable.mkdir(exist_ok=True)
    (unreadable / "builds").write_text("a file where the registry directory belongs", encoding="utf-8")
    held = lanes_build._head_home
    lanes_build._head_home = lambda: (unreadable, "test_home")
    try:
        _rows, registry_unreadable = BuildLane(now=NOW, accountant=None, frame_rows=[]).collect()
    finally:
        lanes_build._head_home = held
    return {"registry_unreadable": registry_unreadable, "detected": _detected_variants(root)}


def _detected_variants(root: Path) -> dict[str, Any]:
    """The detected sub-health in each state the gate and the scan can end in."""

    from agent_runtime.builds import detect
    from agent_runtime.workspace_slots import BoundSlot, SlotCensus

    bound = SlotCensus(1, (BoundSlot("ws_team", "launcher", root / "launcher"),))
    ticks = iter(range(0, 10_000, 1))

    def failing():
        raise OSError("process table unreadable")
        yield  # pragma: no cover

    held = detect._ENABLED
    try:
        detect._ENABLED = False
        not_in_process = detect.scan(now=NOW, census=bound, owned=set(), table=[]).sub()
        detect._ENABLED = True
        return {
            "not_in_process": not_in_process,
            "no_slots_declared": detect.scan(now=NOW, census=SlotCensus(0, ()), owned=set(), table=[]).sub(),
            "slots_unbound_here": detect.scan(now=NOW, census=SlotCensus(3, ()), owned=set(), table=[]).sub(),
            "scan_budget": detect.scan(now=NOW, census=bound, owned=set(), table=process_table(root),
                                       clock=lambda: next(ticks) * 0.03).sub(),
            "scan_failed": detect.scan(now=NOW, census=bound, owned=set(), table=failing(), clock=lambda: 0.0).sub(),
        }
    finally:
        detect._ENABLED = held


def render(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    import os

    with tempfile.TemporaryDirectory(prefix="hermes-build-rows-", ignore_cleanup_errors=True) as temp:
        # The same isolation the conftest gives a test: no read of this machine's hermes root.
        for name, sub in (("HERMES_HOME", "hermes"), ("HERMES_AGENT_RUNTIME_ROOT", "runtime")):
            (Path(temp) / sub).mkdir()
            os.environ[name] = str(Path(temp) / sub)
        os.environ.pop("HERMES_HEAD_HOME", None)
        live = render(produce(Path(temp) / "seed"))
    if argv[:1] == ["--write"]:
        FIXTURE_PATH.write_text(live, encoding="utf-8", newline="\n")
        print(f"wrote {FIXTURE_PATH.name}")
        return 0
    same = FIXTURE_PATH.is_file() and FIXTURE_PATH.read_text(encoding="utf-8") == live
    print("up to date" if same else "stale: run `python -m tests.agent_runtime._build_rows_fixture --write`")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
