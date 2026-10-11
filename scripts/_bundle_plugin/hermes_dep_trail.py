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


class PathFilter:
    """Absolute path → repo-relative POSIX path, or None when it is not the repo's."""

    def __init__(self, root: str) -> None:
        self._root = os.path.normcase(os.path.abspath(root))
        self._prefix = self._root.rstrip("\\/") + os.sep

    def rel(self, raw) -> str | None:
        if isinstance(raw, bytes):
            raw = os.fsdecode(raw)
        if not isinstance(raw, (str, os.PathLike)):
            return None
        try:
            full = os.path.normcase(os.path.abspath(os.fspath(raw)))
        except (OSError, ValueError):
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


def _popen_program(args: tuple) -> str:
    executable, argv = args[0], args[1]
    if executable:
        return os.fsdecode(executable) if isinstance(executable, bytes) else str(executable)
    if isinstance(argv, (str, bytes)):
        text = os.fsdecode(argv) if isinstance(argv, bytes) else argv
        return text.split()[0].strip('"') if text.split() else ""
    try:
        first = list(argv)[0]
    except (TypeError, IndexError):
        return ""
    return os.fsdecode(first) if isinstance(first, bytes) else str(first)


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
        return os.path.normcase(os.path.abspath(program)) == os.path.normcase(os.path.abspath(sys.executable))
    except (OSError, ValueError):
        return False


class Bucket:
    __slots__ = ("paths", "dirs", "spawn_py", "spawn_other")

    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.dirs: set[str] = set()
        self.spawn_py = 0
        self.spawn_other = 0


class AuditTrail:
    """The audit hook's state: one bucket per attributed file. Shared with
    ``sitecustomize`` (a child process records itself the same way)."""

    def __init__(self, root: str) -> None:
        self.filter = PathFilter(root)
        self.current = _SESSION
        self.buckets: dict[str, Bucket] = {_SESSION: Bucket()}
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
                if rel is None and os.path.normcase(os.path.abspath(os.fspath(target))) == self.filter._root:
                    rel = "."
                if rel is not None:
                    self.bucket(self.current).dirs.add(rel)
            elif event in _SPAWN_EVENTS:
                bucket = self.bucket(self.current)
                if is_python(spawned_program(event, args)):
                    bucket.spawn_py += 1
                else:
                    bucket.spawn_other += 1
        except Exception:  # noqa: BLE001 — an audit hook must never raise into the code under test
            return
