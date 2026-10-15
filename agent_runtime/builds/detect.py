"""The DETECTED build source: Flutter builds running under this machine's bound repo slots.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §5 (owner calls 1,
7 and refinement 2). Runs in the serve process only (serve boot calls
:func:`enable_detection`), on the snapshot build cadence, and only while this machine binds at
least one slot.

The scan: processes filtered by executable name first (``dart``, ``flutter``), then the
cmdline through the Flutter argv parser, then the slot test on the cwd. A process whose cwd
cannot be read, or whose cwd is under no bound slot, is NOT a detected build — unprovable
scope is out of scope, by design. A candidate that is an agent-started or announced build, or
a DESCENDANT of one (``flutter.bat`` → ``dart.exe flutter_tools.snapshot``), is skipped.
Liveness is ``cpu``: the process's cumulative CPU time across consecutive scans; a build
quiet for ``stall_seconds`` is ``stalled`` and is NEVER ended here (owner call 1 — the
operator ends it with Stop).

**Index the unknowns.** A name-filtered process the parser cannot place is
``process_unidentified`` (exe + argv head; not shown as a build); a build-shaped cmdline whose
cwd cannot be read is ``cwd_unreadable``. Both go on the sub-health's own index. Every
detected ROW carries what a Restart cannot reproduce: ``env_unobserved`` (only the keys the
slot does not declare once a slot fill applies), ``wrapper_unobserved`` (the parent chain;
absent when the slot's ``tool_paths`` resolves the executable), ``path_unobserved`` (absent
when the slot declares ``path_prepend``).

**The ONE bound is the budget** (50 ms): over it, the sub-health is ``unavailable
scan_budget`` WITH the measured ``scan_ms``. There is no cap on slots — a machine that binds
eighty pays for eighty prefix compares per candidate, and ``scan_ms`` says so on every frame.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from agent_runtime.builds.flutter_argv import COMMAND_OTHER, recognize_argv
from agent_runtime.builds.unknowns import (
    UNKNOWN_CWD_UNREADABLE,
    UNKNOWN_ENV_UNOBSERVED,
    UNKNOWN_PATH_UNOBSERVED,
    UNKNOWN_PROCESS_UNIDENTIFIED,
    UNKNOWN_WRAPPER_UNOBSERVED,
    UnknownsIndex,
)
from agent_runtime.builds.vocabulary import (
    DETECT_BUDGET_MS,
    SUB_REASON_NO_SLOTS_DECLARED,
    SUB_REASON_NOT_IN_PROCESS,
    SUB_REASON_SCAN_BUDGET,
    SUB_REASON_SCAN_FAILED,
    SUB_REASON_SLOTS_UNBOUND_HERE,
)

__layer__ = "lanes"

#: Executable names the scan looks at first (cheap, before any cmdline read).
EXE_NAMES = frozenset({"dart", "dart.exe", "flutter", "flutter.bat", "flutter.exe"})
#: The environment a Flutter build reads that a detected process's env cannot be observed for.
TOOLCHAIN_ENV_KEYS = {"flutter": ("PATH", "PUB_CACHE", "FLUTTER_ROOT", "JAVA_HOME"),
                      "dart": ("PATH", "PUB_CACHE")}
_ARGV_HEAD = 3

_ENABLED = False


def enable_detection() -> None:
    """Serve boot: this process owns detection (a CLI snapshot reports ``not_in_process``)."""

    global _ENABLED
    _ENABLED = True


def detection_enabled() -> bool:
    return _ENABLED


@dataclass
class DetectedBuild:
    """One detected build, as the scan saw it."""

    pid: int
    start: Any
    exe: str
    argv: list[str]
    cwd: str
    command: Any
    slot: Any
    cpu: float
    parents: list[tuple[int, str]]
    unknowns: UnknownsIndex = field(default_factory=UnknownsIndex)


@dataclass
class DetectScan:
    """The scan's answer: builds, the sub-health (with its cost) and the sub-level unknowns."""

    builds: list[DetectedBuild] = field(default_factory=list)
    status: str = "ok"
    reason: str = ""
    scan_ms: int = 0
    processes_examined: int = 0
    candidates: int = 0
    budget_ms: int = DETECT_BUDGET_MS
    unknowns: UnknownsIndex = field(default_factory=UnknownsIndex)

    def sub(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "scan_ms": self.scan_ms,
                "processes_examined": self.processes_examined, "candidates": self.candidates,
                "budget_ms": self.budget_ms, "unknowns": self.unknowns.wire()}


def _head(exe: str, argv: list[str]) -> str:
    return " ".join([exe, *[str(a) for a in argv[:_ARGV_HEAD]]])


class _Scanner:
    """One pass over the process table."""

    def __init__(self, scan: DetectScan, *, now: float, bound: list[Any], owned: set[int],
                 clock: Callable[[], float], budget_ms: int) -> None:
        self.scan, self.now, self.bound, self.owned = scan, now, bound, owned
        self.clock, self.budget_ms = clock, budget_ms
        self.started = clock()
        # Every bound root normalised ONCE per scan; a candidate then costs one prefix
        # compare per bound slot (§5), never a filesystem call per slot.
        self.roots = sorted(((_comparable_path(slot.path), slot) for slot in bound), key=lambda item: -len(item[0]))

    def over_budget(self) -> bool:
        return (self.clock() - self.started) * 1000.0 > self.budget_ms

    def slot_for(self, cwd: str) -> Any:
        """The deepest bound slot ``cwd`` sits under (roots are sorted longest first)."""

        target = _comparable_path(cwd)
        return next((slot for root, slot in self.roots if target == root or target.startswith(root + os.sep)), None)

    def consider(self, proc: Any) -> None:
        self.scan.processes_examined += 1
        exe = str(getattr(proc, "name", "") or "").lower()
        if exe not in EXE_NAMES:
            return
        self.scan.candidates += 1
        argv = _process_fact(proc.cmdline)
        if not isinstance(argv, list) or not argv:
            self.scan.unknowns.add(UNKNOWN_PROCESS_UNIDENTIFIED, f"{exe}: cmdline unreadable ({type(argv).__name__})", self.now)
            return
        recognition = recognize_argv(argv, ".")
        if recognition.command is None:
            self.scan.unknowns.add(UNKNOWN_PROCESS_UNIDENTIFIED, _head(exe, argv), self.now)
            return
        if recognition.command.kind == COMMAND_OTHER:
            return  # classified: a Dart/Flutter process that is not a build (an analysis server, pub)
        cwd = _process_fact(proc.cwd)
        if not isinstance(cwd, str):
            self.scan.unknowns.add(UNKNOWN_CWD_UNREADABLE, f"{_head(exe, argv)}: {type(cwd).__name__}", self.now)
            return
        slot = self.slot_for(cwd)
        parents = _process_fact(proc.parents)
        parents = parents if isinstance(parents, list) else []
        if slot is None or proc.pid in self.owned or any(pid in self.owned for pid, _name in parents):
            return
        command = recognize_argv(argv, cwd).command
        cpu = _process_fact(proc.cpu)
        self.scan.builds.append(DetectedBuild(int(proc.pid), _process_fact(proc.start), exe, [str(a) for a in argv], cwd, command,
                                              slot, float(cpu) if isinstance(cpu, (int, float)) else 0.0, parents))


def _comparable_path(path: Any) -> str:
    try:
        return os.path.normcase(os.path.realpath(str(path))).rstrip(os.sep)
    except (OSError, ValueError):
        return os.path.normcase(str(path)).rstrip(os.sep)


def _process_fact(reader: Callable[[], Any]) -> Any:
    """A process fact, or the exception class that refused it (AccessDenied, NoSuchProcess …)."""

    try:
        return reader()
    except Exception as exc:  # noqa: BLE001 — the CLASS is the evidence the index records
        return exc


def _gate(census: Any) -> str:
    if not _ENABLED:
        return SUB_REASON_NOT_IN_PROCESS
    if census.declared == 0:
        return SUB_REASON_NO_SLOTS_DECLARED
    if not census.bound:
        return SUB_REASON_SLOTS_UNBOUND_HERE
    return ""


def scan(*, now: float, census: Any, owned: set[int], table: Iterable[Any] | None = None,
         clock: Callable[[], float] = time.perf_counter, budget_ms: int = DETECT_BUDGET_MS) -> DetectScan:
    """Scan the process table for detected builds under ``census.bound``; never raises."""

    result = DetectScan(budget_ms=budget_ms)
    refusal = _gate(census)
    if refusal:
        result.status, result.reason = "unavailable", refusal
        return result
    scanner = _Scanner(result, now=now, bound=list(census.bound), owned=owned, clock=clock, budget_ms=budget_ms)
    try:
        for proc in (table if table is not None else psutil_table()):
            scanner.consider(proc)
            if scanner.over_budget():
                result.status, result.reason, result.builds = "unavailable", SUB_REASON_SCAN_BUDGET, []
                break
    except Exception as exc:  # noqa: BLE001 — "I could not look" is a typed sub-health
        result.status, result.reason, result.builds = "unavailable", SUB_REASON_SCAN_FAILED, []
        result.unknowns.add(UNKNOWN_PROCESS_UNIDENTIFIED, f"process table: {type(exc).__name__}", now)
    result.scan_ms = int(round((clock() - scanner.started) * 1000.0))
    return result


def restart_unknowns(build: DetectedBuild, *, now: float) -> UnknownsIndex:
    """What a Restart of ``build`` cannot reproduce — narrowed by the slot's declaration and fill."""

    from agent_runtime.workspace_slot_env import slot_fill
    from agent_runtime.workspace_slots import live_slots, load_document

    index = UnknownsIndex()
    declared = live_slots(load_document(build.slot.workspace_id)).get(build.slot.slot) or {}
    fill = slot_fill(build.slot.workspace_id, build.slot.slot)
    toolchain = declared.get("toolchain") or {}
    keys = set(TOOLCHAIN_ENV_KEYS.get(getattr(build.command, "toolchain", ""), TOOLCHAIN_ENV_KEYS["flutter"]))
    if fill is not None:
        keys -= {row.get("key") for row in toolchain.get("env_keys") or []}
        keys -= {row.get("key") for row in (toolchain.get("dotenv") or {}).get("keys") or []}
        keys -= set(fill.env)
        if fill.path_prepend:
            keys.discard("PATH")
    if keys:
        index.add(UNKNOWN_ENV_UNOBSERVED, ", ".join(sorted(keys)), now)
    if fill is None or not fill.tool_paths:
        chain = " → ".join(name for _pid, name in reversed(build.parents)) or "(no parent seen)"
        index.add(UNKNOWN_WRAPPER_UNOBSERVED, f"{chain} → {build.exe}", now)
    if fill is None or not fill.path_prepend:
        index.add(UNKNOWN_PATH_UNOBSERVED, "PATH of the observed process", now)
    return index


class _PsutilProcess:
    """One ``psutil`` process behind the scan's read interface (facts read lazily, in order)."""

    def __init__(self, proc: Any) -> None:
        self._proc = proc
        self.pid = proc.info.get("pid")
        self.name = proc.info.get("name") or ""

    def cmdline(self) -> list[str]:
        return list(self._proc.cmdline())

    def cwd(self) -> str:
        return str(self._proc.cwd())

    def start(self) -> Any:
        from gateway.status import get_process_start_time

        return get_process_start_time(int(self.pid))

    def cpu(self) -> float:
        times = self._proc.cpu_times()
        return float(times.user + times.system)

    def parents(self) -> list[tuple[int, str]]:
        return [(parent.pid, parent.name()) for parent in self._proc.parents()]


def psutil_table() -> Iterable[Any]:
    import psutil

    return (_PsutilProcess(proc) for proc in psutil.process_iter(["pid", "name"]))
