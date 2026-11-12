"""The DETECTED build source: Flutter builds running under this machine's bound repo slots.

Plan ``docs/agent-runtime-harness/archive/build-running-work-2026-10-04.md`` §5 (owner calls 1,
7 and refinement 2). Runs in the serve process only (serve boot calls
:func:`enable_detection`), on the snapshot build cadence, and only while this machine binds at
least one slot.

The scan: processes filtered by executable name first (``dart``, ``flutter``), then the
cmdline through the Flutter argv parser, then the slot test on the cwd. A process whose cwd
cannot be read, or whose cwd is under no bound slot, is NOT a detected build — unprovable
scope is out of scope, by design. A candidate that is an agent-started or announced build, or
a DESCENDANT of one (``flutter.bat`` → ``dart.exe flutter_tools.snapshot``), is skipped.
Liveness is ``cpu``: the cumulative CPU time of the process AND its descendants across
consecutive scans; a build quiet for ``stall_seconds`` is ``stalled`` and is NEVER ended here
(owner call 1 — the operator ends it with Stop). The tree, not the process alone: the Dart SDK's
``dart.exe`` is a thin launcher that hands the work to a ``dartvm.exe`` child (which runs the
frontend server and MSBuild/CMake below it), so its own CPU never moves and every detected build
read ``stalled`` four minutes in, compiling or not (RT-BUILD-FLUTTER-RUN-READS-STALLED).

**A ``flutter run`` whose app is running is not a build.** Once a descendant's executable lives
under ``<project>/build/`` — the app the run built, which ``flutter run`` launched and now hosts
for hot reload — the session idles by design: neither building nor stalled, and Stop would close
the app in front of the operator. The scan names that app (``DetectedBuild.app``); the build lane
drops the row by design (RT-BUILD-FLUTTER-RUN-READS-STALLED). A web run has no app under
``build/``: ``-d chrome``/``-d edge`` hosts the browser it launched after compiling, and
``-d web-server`` counts once a browser is connected to it (:func:`_running_app`,
RT-BUILD-FLUTTER-RUN-WEB-LIVENESS).

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
import sys
import time
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Callable, Iterable

from agent_runtime.builds.flutter_argv import COMMAND_OTHER, COMMAND_RUN, recognize_argv
from agent_runtime.process_state import register_process_state
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
    DETECTED_SUB_REASONS,
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


def _reset_detection() -> None:
    global _ENABLED
    _ENABLED = False


register_process_state(__name__, _reset_detection, holds=("_ENABLED",))


@dataclass(frozen=True)
class Descendant:
    """One process below a candidate: its name, executable path and CPU seconds (None = refused)."""

    pid: int
    name: str
    exe: str | None
    cpu: float | None


@dataclass
class DetectedBuild:
    """One detected build, as the scan saw it.

    ``cpu`` is the tree's (the process plus every descendant read). ``app`` is the running app a
    ``flutter run`` launched (a descendant whose executable is under ``<project>/build/``), else None.
    """

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
    app: Descendant | None = None


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
        if self.reason and self.reason not in DETECTED_SUB_REASONS:
            # Only this module writes ``reason``, from the vocabulary's constants: a word
            # outside the tuple is a producer bug, reported as the lane's collector_failed.
            raise ValueError(f"detected sub reason {self.reason!r} is not a word of {DETECTED_SUB_REASONS}")
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
        tree = _process_fact(getattr(proc, "descendants", list))
        tree = tree if isinstance(tree, list) else []
        cpu = (float(cpu) if isinstance(cpu, (int, float)) else 0.0) + sum(d.cpu for d in tree if d.cpu is not None)
        self.scan.builds.append(DetectedBuild(int(proc.pid), _process_fact(proc.start), exe, [str(a) for a in argv], cwd, command,
                                              slot, cpu, parents,
                                              app=_running_app(command, tree, tcp=getattr(proc, "tcp", None), pid=proc.pid)))


#: ``flutter run -d <device>`` devices that run the app in a browser flutter_tools launches itself.
WEB_BROWSER_DEVICES = frozenset({"chrome", "edge"})
#: The ``-d web-server`` device: flutter_tools serves the app and launches nothing.
WEB_SERVER_DEVICE = "web-server"
#: Executable names of the browsers flutter_tools launches for a web device (Windows, Linux, macOS).
BROWSER_NAMES = frozenset({"chrome.exe", "msedge.exe", "chrome", "google-chrome", "google-chrome-stable",
                           "chromium", "chromium-browser", "msedge", "microsoft-edge", "google chrome",
                           "microsoft edge"})


def _running_app(command: Any, tree: list[Descendant], *, tcp: Callable[[], Any] | None = None,
                 pid: int | None = None) -> Descendant | None:
    """The app a ``flutter run`` is hosting, once it has one; None while it builds (or for a build).

    Only a ``run`` hosts an app; a ``build``'s descendants are its compilers and linkers, which
    live in the SDK and the toolchains, never in the output folder. A run's app is, by device:

    * desktop (and any run): a descendant whose executable is under ``<project>/build/``;
    * ``-d chrome`` / ``-d edge`` (or no ``-d``): a browser descendant — flutter_tools launches it
      only AFTER the first compile succeeded (``ResidentWebRunner.run``: compile, then
      ``startApp``), so a compiling run has none and still reads building, a hung one stalled;
    * ``-d web-server``: no app process exists, so the app is "a browser has it open": an
      ESTABLISHED connection a tree process ACCEPTED on a port it listens on. Until one connects,
      a served run is not told apart from a hung compile — both idle — and reads by CPU as before
      (RT-BUILD-FLUTTER-RUN-WEB-LIVENESS).
    """

    if getattr(command, "kind", "") != COMMAND_RUN:
        return None
    output = _comparable_path(os.path.join(str(command.project_dir), "build")) + os.sep
    app = next((d for d in tree if d.exe and _comparable_path(d.exe).startswith(output)), None)
    if app is not None:
        return app
    device = str(getattr(command, "target", "")).partition(":")[2]
    if device in WEB_BROWSER_DEVICES or device == "":
        return next((d for d in tree if d.name.lower() in BROWSER_NAMES), None)
    if device == WEB_SERVER_DEVICE and tcp is not None:
        return _browser_connected(tree, pid, _process_fact(tcp))
    return None


def _browser_connected(tree: list[Descendant], pid: int | None, table: Any) -> Descendant | None:
    """The web-server's session once a client is connected: an accepted connection in the run's tree.

    ``table`` rows are ``(pid, status, local port, remote port)`` for the machine's TCP sockets; a
    refused read (an exception class) is no evidence, so the run reads by CPU.
    """

    if not isinstance(table, list):
        return None
    names = {d.pid: d.name for d in tree}
    pids = set(names) | ({pid} if pid is not None else set())
    mine = [row for row in table if row[0] in pids]
    listening = {local for _pid, status, local, _remote in mine if status == "LISTEN"}
    for holder, status, local, _remote in mine:
        if status == "ESTABLISHED" and local in listening:
            return Descendant(holder, f"web server on port {local} (a browser is connected)", None, None)
    return None


def _comparable_path(path: Any) -> str:
    try:
        return os.path.normcase(os.path.realpath(str(path))).rstrip(os.sep)
    except (OSError, ValueError):
        return os.path.normcase(str(path)).rstrip(os.sep)


def _process_fact(reader: Callable[[], Any]) -> Any:
    """A process fact, or the exception class that refused it (AccessDenied, NoSuchProcess …)."""

    try:
        return reader()
    except Exception as exc:  # the CLASS is the evidence the index records
        return exc


def _consider_one(scanner: _Scanner, proc: Any, now: float) -> None:
    """One process; a read that escapes the fact guard skips THAT process, never the scan.

    An exception raised while WALKING the table (the table itself unreadable) still reaches
    :func:`scan`'s ``scan_failed`` arm: that is "I could not look". One process that exits or
    refuses mid-read is only an unknown (RT-BUILD-SCAN-FAILS-ON-OWNER-WINDOWS).
    """

    try:
        scanner.consider(proc)
    except Exception as exc:
        name = str(getattr(proc, "name", "") or "?")
        scanner.scan.unknowns.add(UNKNOWN_PROCESS_UNIDENTIFIED, f"{name}: unreadable ({type(exc).__name__})", now)


def _gate(census: Any) -> str:
    if not _ENABLED:
        return SUB_REASON_NOT_IN_PROCESS
    if census.declared == 0:
        return SUB_REASON_NO_SLOTS_DECLARED
    if not census.bound:
        return SUB_REASON_SLOTS_UNBOUND_HERE
    return ""


def warm_detection() -> None:
    """Pay the scan's ONE-TIME first-use costs, outside the budgeted walk.

    Measured 2026-11-12 on DESKTOP-QJ7DDV2 (16 logical CPUs): the first scan in a fresh process
    took 220–560 ms against the 50 ms budget, so its frame read ``scan_budget`` — not the walk
    (warm scans take 12–22 ms) but imports: ``gateway.status`` with ``hermes_cli.process_identity``
    (~300 ms, on the first candidate's start time), ``psutil`` (~36 ms) and the Toolhelp32 ctypes
    types (~13 ms). Each is a cached import after this, so the walk the budget times is the walk
    (RT-BUILD-SCAN-FIRST-PASS-OVER-BUDGET). Serve boot calls it on the build-sweep thread; ``scan``
    calls it again before its clock starts (a no-op once warm). A dependency that is missing is
    left for the walk to meet and report as ``scan_failed``.
    """

    try:
        import psutil  # noqa: F401  # the phone profile omits it

        from gateway.status import get_process_start_time
    except ImportError:
        return
    get_process_start_time(os.getpid())  # its own lazy imports, on a process that is surely there
    if sys.platform == "win32":
        _toolhelp_api()


def scan(*, now: float, census: Any, owned: set[int], table: Iterable[Any] | None = None,
         clock: Callable[[], float] = time.perf_counter, budget_ms: int = DETECT_BUDGET_MS) -> DetectScan:
    """Scan the process table for detected builds under ``census.bound``; never raises."""

    result = DetectScan(budget_ms=budget_ms)
    refusal = _gate(census)
    if refusal:
        result.status, result.reason = "unavailable", refusal
        return result
    if table is None:
        try:
            warm_detection()  # one-time imports: paid before the budget's clock starts, never inside it
        except Exception:  # noqa: S110 - the walk below meets the same failure and types it scan_failed
            pass
    scanner = _Scanner(result, now=now, bound=list(census.bound), owned=owned, clock=clock, budget_ms=budget_ms)
    try:
        if table is None:
            import psutil  # the phone profile omits it: ImportError is "I could not look", below

            table = psutil_table(psutil)
        for proc in table:
            _consider_one(scanner, proc, now)
            if scanner.over_budget():
                result.status, result.reason, result.builds = "unavailable", SUB_REASON_SCAN_BUDGET, []
                break
    except Exception as exc:  # "I could not look" is a typed sub-health
        result.status, result.reason, result.builds = "unavailable", SUB_REASON_SCAN_FAILED, []
        result.unknowns.add(UNKNOWN_PROCESS_UNIDENTIFIED, f"process table: {type(exc).__name__}", now)
    result.scan_ms = round((clock() - scanner.started) * 1000.0)
    return result


def restart_unknowns(build: DetectedBuild, *, now: float) -> UnknownsIndex:
    """What a Restart of ``build`` cannot reproduce — narrowed by the slot's declaration and fill."""

    from agent_runtime.workspace_slot_env import slot_fill
    from agent_runtime.workspace_slots import resolve_slot

    index = UnknownsIndex()
    resolved = resolve_slot(build.slot.workspace_id, build.slot.slot)
    declared = resolved.declaration if resolved else {}
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

    def descendants(self) -> list[Descendant]:
        return [_descendant(child, int(child.pid), None) for child in self._proc.children(recursive=True)]

    def tcp(self) -> list[tuple[int, str, int, int | None]]:
        """The machine's TCP sockets as ``(pid, status, local port, remote port)``; read only for a web-server run."""

        import psutil

        return _tcp_rows(psutil)


def _tcp_rows(psutil: Any) -> list[tuple[int, str, int, int | None]]:
    rows = []
    for conn in psutil.net_connections(kind="tcp"):
        if conn.pid is None or not conn.laddr:
            continue
        rows.append((int(conn.pid), str(conn.status), int(conn.laddr.port), int(conn.raddr.port) if conn.raddr else None))
    return rows


def _descendant(proc: Any, pid: int, name: str | None) -> Descendant:
    """One descendant's facts; a fact it refuses (gone, access denied) is None, never a raise."""

    if name is None:
        name = _process_fact(proc.name)
        name = name if isinstance(name, str) else ""
    exe = _process_fact(proc.exe)
    times = _process_fact(proc.cpu_times)
    cpu = float(times.user + times.system) if hasattr(times, "user") else None
    return Descendant(pid, name, exe if isinstance(exe, str) and exe else None, cpu)


class _SnapshotProcess(_PsutilProcess):
    """One row of a Windows process snapshot; ``psutil`` opens it only when a fact is read.

    Only a name-matched candidate ever reads a fact, so only candidates pay for an open (a pid
    gone by then is ``NoSuchProcess``, a refused fact). Its parent chain is read from the same
    snapshot, never through ``psutil.Process.parents()``, which names each ancestor the slow way.
    """

    def __init__(self, pid: int, name: str, snapshot: "WindowsSnapshot", psutil: Any) -> None:
        self.pid, self.name, self._snapshot, self._psutil, self._held = pid, name, snapshot, psutil, None

    @property
    def _proc(self) -> Any:  # type: ignore[override]
        if self._held is None:
            self._held = self._psutil.Process(self.pid)
        return self._held

    def parents(self) -> list[tuple[int, str]]:
        return self._snapshot.parents(self.pid, created=self._psutil_created)

    def tcp(self) -> list[tuple[int, str, int, int | None]]:
        return _tcp_rows(self._psutil)

    def _psutil_created(self, pid: int) -> float | None:
        try:
            return float(self._psutil.Process(pid).create_time())
        except Exception:  # gone or refused: the hop's age is unknown, so the walk stops there
            return None

    def descendants(self) -> list[Descendant]:
        opened: dict[int, Any] = {}

        def created(pid: int) -> float | None:
            try:
                if pid not in opened:
                    opened[pid] = self._psutil.Process(pid)
                return float(opened[pid].create_time())
            except Exception:  # gone or refused: not provably a descendant
                return None

        return [_descendant(opened[pid], pid, name) for pid, name in self._snapshot.descendants(self.pid, created=created)]


@dataclass
class WindowsSnapshot:
    """``pid -> (parent pid, executable name)`` for every process, from ONE Toolhelp32 snapshot."""

    rows: dict[int, tuple[int, str]]

    def parents(self, pid: int, *, created: Callable[[int], float | None]) -> list[tuple[int, str]]:
        """The ancestor chain, nearest first, the way ``psutil`` judges it.

        Windows keeps a dead parent's pid in the snapshot and reuses pids, so a "parent" created
        after its child is a recycled pid and ends the chain; so does an ancestor whose age
        cannot be read, or a loop.
        """

        chain: list[tuple[int, str]] = []
        seen, child = {pid}, pid
        child_created = created(pid)
        while True:
            ppid = self.rows.get(child, (0, ""))[0]
            if not ppid or ppid in seen or ppid not in self.rows:
                return chain
            parent_created = created(ppid)
            if parent_created is None or child_created is None or parent_created > child_created:
                return chain
            chain.append((ppid, self.rows[ppid][1]))
            seen.add(ppid)
            child, child_created = ppid, parent_created

    def descendants(self, pid: int, *, created: Callable[[int], float | None]) -> list[tuple[int, str]]:
        """Every process below ``pid``, breadth first, the way ``psutil`` judges a child.

        A row naming a parent but created BEFORE it is a recycled pid's orphan, not a child; one
        whose age cannot be read is not provably a child. Either is skipped with all below it.
        """

        children: dict[int, list[int]] = {}
        for child, (ppid, _name) in self.rows.items():
            children.setdefault(ppid, []).append(child)
        found: list[tuple[int, str]] = []
        seen, queue = {pid}, [(pid, created(pid))]
        while queue:
            parent, parent_created = queue.pop(0)
            if parent_created is None:
                continue
            for child in children.get(parent, ()):
                if child in seen:
                    continue
                child_created = created(child)
                if child_created is None or child_created < parent_created:
                    continue
                seen.add(child)
                found.append((child, self.rows[child][1]))
                queue.append((child, child_created))
        return found


def psutil_table(psutil: Any, *, snapshot: Callable[[], WindowsSnapshot] | None = None) -> Iterable[Any]:
    """The process table the scan walks; on Windows its names come from ONE OS snapshot.

    ``psutil``'s per-process ``name()`` on Windows resolves the full image path and converts
    its device form to a drive letter, every process: measured 2026-11-12 on a 16-core
    Windows box at ~5.6 ms a process (2.5 s for 440), so the 50 ms budget ran out after 5–23
    processes and EVERY scan read ``scan_budget`` (RT-BUILD-SCAN-FAILS-ON-OWNER-WINDOWS);
    ``parents()`` names each ancestor the same way (80–200 ms a candidate). One Toolhelp32
    snapshot names every process and its parent in ~20 ms; ``psutil`` then opens only the
    name-matched candidates.
    """

    if snapshot is None and sys.platform == "win32":
        snapshot = windows_snapshot
    if snapshot is None:
        return (_PsutilProcess(proc) for proc in psutil.process_iter(["pid", "name"]))
    taken = snapshot()
    return (_SnapshotProcess(pid, name, taken, psutil) for pid, (_ppid, name) in taken.rows.items())


@cache
def _toolhelp_api() -> tuple[Any, Any]:
    """kernel32 with the Toolhelp32 process walk typed, plus ``PROCESSENTRY32W``, built once."""

    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for walk in (kernel32.Process32FirstW, kernel32.Process32NextW):
        walk.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        walk.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32, PROCESSENTRY32W


def windows_snapshot() -> WindowsSnapshot:
    """Every process's parent pid and executable name, from one Toolhelp32 snapshot (Windows).

    Raises ``OSError`` when the snapshot cannot be taken — the table itself unreadable, which
    :func:`scan` reports as ``scan_failed``.
    """

    import ctypes

    kernel32, entry_type = _toolhelp_api()
    handle = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    rows: dict[int, tuple[int, str]] = {}
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry_type)
        found = kernel32.Process32FirstW(handle, ctypes.byref(entry))
        while found:
            rows[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), str(entry.szExeFile))
            found = kernel32.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(handle)
    return WindowsSnapshot(rows)
