"""The audit hook's half of the dependency recorder, without pytest.

``hermes_dep_record`` (the pytest plugin) and ``sitecustomize`` (a Python child
of a test, fast-gate §1 stage 1b) both attribute audit events through
:class:`AuditTrail`; this module imports nothing but the standard library, so a
child process pays no pytest import for it.
"""

from __future__ import annotations

import os
import sys

#: the file the process is running now; a ``sitecustomize`` child inherits it
CURRENT_FILE_ENV = "HERMES_GATE_CURRENT_FILE"
#: where a child writes its record, and the repo root it filters by (stage 1b)
CHILD_DIR_ENV = "HERMES_GATE_CHILD_EVENTS"
ROOT_ENV = "HERMES_GATE_ROOT"
_DROP_PARTS = frozenset({".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
_PATH_EVENTS = frozenset({"open"})
_DIR_EVENTS = frozenset({"os.listdir", "os.scandir"})
_SPAWN_EVENTS = frozenset({"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile"})
_SESSION = ""
#: Bound at import: a test that patches ``os.path.abspath`` process-wide (``ntpath`` is one module)
#: must never reach the recorder, whose ``rel`` runs inside pytest's own hooks, not only the audit
#: hook (``tests/tools/test_search_files_cpu_windows.py``, lane r-state 2026-10-18).
_abspath = os.path.abspath
_normcase = os.path.normcase
#: the import system's directory scan: ``FileFinder._fill_cache`` in ``importlib._bootstrap_external``
_IMPORT_LISTER = "_fill_cache"


def _listed_by_import_system() -> bool:
    """Whether the ``os.listdir`` being audited was called by the import system
    (``FileFinder._fill_cache``), read off the caller frames of the hook."""

    try:
        frame = sys._getframe(2)
    except ValueError:
        return False
    for _ in range(3):
        if frame is None:
            return False
        code = frame.f_code
        if code.co_name == _IMPORT_LISTER and "importlib" in code.co_filename:
            return True
        frame = frame.f_back
    return False


class PathFilter:
    """Absolute path → repo-relative POSIX path, or None when it is not the repo's."""

    def __init__(self, root: str) -> None:
        self._root = _normcase(_abspath(root))
        self._prefix = self._root.rstrip("\\/") + os.sep

    def rel(self, raw) -> str | None:
        if isinstance(raw, bytes):
            raw = os.fsdecode(raw)
        if not isinstance(raw, (str, os.PathLike)):
            return None
        try:
            full = _normcase(_abspath(os.fspath(raw)))
        except Exception:  # noqa: BLE001 — the recorder observes; it never fails the code it watches
            return None
        if not full.startswith(self._prefix):
            return None
        rel = full[len(self._prefix):].replace("\\", "/")
        if not rel or any(part in _DROP_PARTS for part in rel.split("/")):
            return None
        return rel

    def modules(self) -> set[str]:
        out: set[str] = set()
        for module in list(sys.modules.values()):
            rel = self.rel(getattr(module, "__file__", None))
            if rel is not None:
                out.add(rel)
        return out


def first_program(argv) -> str:
    """The program an argv (a sequence, or a command line) names first. Windows audits the
    command line: a quoted program may hold spaces (``"C:\Program Files\python.exe" -c``),
    so a quoted head is read to its closing quote, never split on spaces. The ONE reader:
    ``hermes_bundle_report.program_kind`` classifies through it too."""

    if isinstance(argv, (str, bytes)):
        text = os.fsdecode(argv).strip()
        if text.startswith('"'):
            return text[1:].partition('"')[0]
        return text.split()[0] if text.split() else ""
    try:
        first = list(argv)[0]
    except (TypeError, IndexError):
        return ""
    return os.fsdecode(first) if isinstance(first, bytes) else str(first)


def _popen_program(args: tuple) -> str:
    executable, argv = args[0], args[1]
    if executable:
        return os.fsdecode(executable) if isinstance(executable, bytes) else str(executable)
    return first_program(argv)


#: spawn audit event → the program it starts, read off the event's arguments
_PROGRAM_OF = {
    "subprocess.Popen": _popen_program,
    "os.exec": lambda args: str(args[0]),
    "os.posix_spawn": lambda args: str(args[0]),
    "os.spawn": lambda args: str(args[1]),
}


def spawned_program(event: str, args: tuple) -> str:
    """The program a spawn event starts, as best the event says ("" unknown:
    ``os.system`` and ``os.startfile`` go through a shell or the OS)."""

    read = _PROGRAM_OF.get(event)
    return read(args) if read is not None else ""


def is_python(program: str) -> bool:
    if not program:
        return False
    base = os.path.basename(program).lower()
    if base.startswith("python"):
        return True
    try:
        return _normcase(_abspath(program)) == _normcase(_abspath(sys.executable))
    except (OSError, ValueError):
        return False


class Bucket:
    __slots__ = ("paths", "dirs", "idirs", "spawn_py", "spawn_other")

    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.dirs: set[str] = set()
        #: directories the import system listed (keyed on the entries a tried module name matches)
        self.idirs: set[str] = set()
        self.spawn_py = 0
        self.spawn_other = 0


class AuditTrail:
    """The audit hook's state: one bucket per attributed file. Shared with
    ``sitecustomize`` (a child process records itself the same way)."""

    def __init__(self, root: str) -> None:
        self.filter = PathFilter(root)
        self.current = _SESSION
        self.buckets: dict[str, Bucket] = {_SESSION: Bucket()}
        #: the last dotted component of every module the process tried to import (``import`` event)
        self.import_names: set[str] = set()
        self.active = True

    def bucket(self, name: str) -> Bucket:
        found = self.buckets.get(name)
        if found is None:
            found = self.buckets[name] = Bucket()
        return found

    def hook(self, event: str, args: tuple) -> None:
        if not self.active:
            return
        try:
            if event in _PATH_EVENTS:
                rel = self.filter.rel(args[0])
                if rel is not None:
                    self.bucket(self.current).paths.add(rel)
            elif event in _DIR_EVENTS:
                target = args[0] if args and args[0] not in (None, "") else "."
                rel = self.filter.rel(target)
                if rel is None and _normcase(_abspath(os.fspath(target))) == self.filter._root:
                    rel = "."
                if rel is not None:
                    bucket = self.bucket(self.current)
                    if event == "os.listdir" and _listed_by_import_system():
                        bucket.idirs.add(rel)
                    else:
                        bucket.dirs.add(rel)
            elif event == "import":
                self.import_names.add(str(args[0]).rpartition(".")[2])
            elif event in _SPAWN_EVENTS:
                bucket = self.bucket(self.current)
                if is_python(spawned_program(event, args)):
                    bucket.spawn_py += 1
                else:
                    bucket.spawn_other += 1
        except Exception:  # noqa: BLE001 — an audit hook must never raise into the code under test
            return
