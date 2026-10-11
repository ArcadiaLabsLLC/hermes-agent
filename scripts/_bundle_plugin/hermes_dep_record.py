"""pytest plugin: record what each test file of a process actually touched.

Loaded by ``scripts/run_tests_bundled.py`` beside ``hermes_bundle_report``
(``-p hermes_dep_record --hermes-gate-deps=<dir>``). One ``sys.addaudithook``
watches the process; every event is attributed to the test file that was being
collected or run when it fired. When the run moves off a file, and at session
finish, one JSON line per file goes to ``<dir>/deps-<pid>-<ns>.jsonl``::

    {"k": "deps", "f": <rel>, "paths": [...], "dirs": [...],
     "spawn_py": <n>, "spawn_other": <n>, "mods_add": [...]}

* ``paths`` — repo-relative files the file opened (``open`` / ``io.open_code``);
* ``dirs`` — repo-relative directories it listed (``os.listdir``, ``os.scandir``:
  ``glob``, ``os.walk``, ``Path.iterdir`` and the import system's own directory
  scans all go through these; ``"."`` is the repo root);
* ``spawn_py`` / ``spawn_other`` — processes it started, by whether the program
  is a Python interpreter (a Python child that inherits the environment records
  itself through ``sitecustomize``; anything else is a hole the cache closes by
  depending on the whole tree);
* ``mods_add`` — repo-rooted modules in ``sys.modules`` at the write that were
  not in an earlier line of this process file. CPython raises ``import`` only on
  first load, so a module an earlier member loaded is invisible to a later one;
  the reader therefore attributes to each line the UNION of ``mods_add`` up to
  and including it — a superset of what the file imported, never less.

Events before the first module is collected (conftest chain, plugins) are the
session's and are written into every line. Paths outside the repo root, and
under ``.git``, ``__pycache__``, ``.venv``, ``.pytest_cache`` or a tool cache,
are dropped. Generic on purpose (no fork path), like ``hermes_bundle_report``.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

_OPTION = "--hermes-gate-deps"
#: the file the process is running now; a ``sitecustomize`` child inherits it
CURRENT_FILE_ENV = "HERMES_GATE_CURRENT_FILE"
_DROP_PARTS = frozenset({".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
_PATH_EVENTS = frozenset({"open"})
_DIR_EVENTS = frozenset({"os.listdir", "os.scandir"})
_SPAWN_EVENTS = frozenset({"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile"})
_SESSION = ""


def pytest_addoption(parser):
    parser.addoption(_OPTION, dest="hermes_gate_deps", default=None, help="Write per-file dependency records here.")


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


def spawned_program(event: str, args: tuple) -> str:
    """The program a spawn event starts, as best the event says ("" unknown)."""

    if event == "subprocess.Popen":
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
    if event in ("os.exec", "os.posix_spawn"):
        return str(args[0])
    if event == "os.spawn":
        return str(args[1])
    return ""


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


class _DepRecorder:
    def __init__(self, directory: str, root: str) -> None:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"deps-{os.getpid()}-{time.time_ns()}.jsonl")
        self._handle = open(path, "a", encoding="utf-8")  # noqa: SIM115 — closed at unconfigure
        self._trail = AuditTrail(root)
        self._written_mods: set[str] = set()
        self._flushed: set[str] = set()
        self._running: str | None = None
        sys.addaudithook(self._trail.hook)

    def _flush(self, rel: str) -> None:
        trail = self._trail
        bucket = trail.buckets.pop(rel, None) or Bucket()
        session = trail.buckets[_SESSION]
        mods = trail.filter.modules()
        added = sorted(mods - self._written_mods)
        self._written_mods |= mods
        record = {
            "k": "deps",
            "f": rel,
            "paths": sorted(bucket.paths | session.paths | {rel}),
            "dirs": sorted(bucket.dirs | session.dirs),
            "spawn_py": bucket.spawn_py + session.spawn_py,
            "spawn_other": bucket.spawn_other + session.spawn_other,
            "mods_add": added,
        }
        self._handle.write(json.dumps(record) + "\n")
        self._handle.flush()
        self._flushed.add(rel)

    def _rel_of(self, node) -> str:
        """The repo-relative POSIX path of a collector's or item's file."""

        return self._trail.filter.rel(getattr(node, "path", None)) or str(node.nodeid).partition("::")[0]

    def pytest_collectstart(self, collector):
        if isinstance(collector, pytest.Module):
            self._trail.current = self._rel_of(collector)
            self._trail.bucket(self._trail.current)

    def pytest_collectreport(self, report):
        if str(report.nodeid).partition("::")[0].endswith(".py"):
            self._trail.current = _SESSION  # the module is collected: later events are the session's

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        rel = self._rel_of(item)
        if self._running is not None and self._running != rel:
            self._flush(self._running)
        self._running = rel
        self._trail.current = rel
        os.environ[CURRENT_FILE_ENV] = rel
        yield

    def pytest_sessionfinish(self, session, exitstatus):
        self._trail.active = False
        for rel in [name for name in self._trail.buckets if name != _SESSION]:
            self._flush(rel)
        os.environ.pop(CURRENT_FILE_ENV, None)

    def close(self) -> None:
        self._trail.active = False
        try:
            self._handle.close()
        except OSError:
            pass


def pytest_configure(config):
    directory = config.getoption("hermes_gate_deps")
    if not directory:
        return
    recorder = _DepRecorder(os.fspath(directory), str(config.rootpath))
    config.pluginmanager.register(recorder, "hermes_dep_recorder")
    config._hermes_dep_recorder = recorder  # type: ignore[attr-defined]


def pytest_unconfigure(config):
    recorder = getattr(config, "_hermes_dep_recorder", None)
    if recorder is not None:
        recorder.close()
