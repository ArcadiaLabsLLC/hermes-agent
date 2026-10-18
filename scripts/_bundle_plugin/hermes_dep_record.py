"""pytest plugin: record what each test file of a process actually touched.

Loaded by ``scripts/run_tests_bundled.py`` beside ``hermes_bundle_report``
(``-p hermes_dep_record --hermes-gate-deps=<dir>``). One ``sys.addaudithook``
watches the process; every event is attributed to the test file that was being
collected or run when it fired. When the run moves off a file, and at session
finish, one JSON line per file goes to ``<dir>/deps-<pid>-<ns>.jsonl``::

    {"k": "deps", "f": <rel>, "paths": [...], "dirs": [...],
     "spawn_py": <n>, "spawn_other": <n>, "mods_add": [...], "own": [...], "fx": [...]}

* ``paths`` — repo-relative files the file opened (``open`` / ``io.open_code``);
* ``dirs`` — repo-relative directories it listed (``os.listdir``, ``os.scandir``:
  ``glob``, ``os.walk`` and ``Path.iterdir`` go through these; ``"."`` is the repo root),
  never pytest's own collection walk (``hermes_dep_trail._listed_by_pytest_collection``);
* ``idirs`` — the directories the import system listed (``FileFinder``'s
  ``os.listdir``, its caller frame in ``importlib``): the cache keys each on only
  the entries whose stem matches a name the process tried to import, so a new
  file no import asked for misses no green;
* ``inames_add`` — the last dotted component of each module the process tried to
  import (the ``import`` audit event) not in an earlier line of this process
  file; the reader unions them over the whole process file;
* ``spawn_py`` / ``spawn_other`` — processes it started, by whether the program
  is a Python interpreter (a Python child that inherits the environment records
  itself through ``sitecustomize``; anything else is a hole the cache closes by
  depending on the whole tree);
* ``own`` — the part of ``paths`` the file opened itself (its collection and its
  tests), as opposed to the session's imports: the cache keys these by blob;
* ``fx`` — every fixture the file's tests set up (``request.fixturenames`` at
  teardown: the static closure, autouse included, plus ``getfixturevalue``);
  absent when an item had no fixture request (a non-Python item), so the cache
  keys every fixture module by blob for that file;
* ``mods_add`` — repo-rooted modules in ``sys.modules`` at the write that were
  not in an earlier line of this process file. CPython raises ``import`` only on
  first load, so a module an earlier member loaded is invisible to a later one;
  the reader therefore attributes to each line the UNION of ``mods_add`` up to
  and including it — a superset of what the file imported, never less;
* ``mods_own`` — the repo modules that entered ``sys.modules`` while THIS file was
  being collected or run (``sys.modules`` is swept at every change of file), apart
  from the session's and the earlier members': the file's own first loads;
* ``mods_ref`` — the repo modules the test module's namespace names (a module
  object, or the ``__module__`` of a class or function it holds) and their parent
  packages: a direct import an earlier member had already loaded, which fires no
  ``import`` event and adds nothing to ``mods_own``. ``--affected`` reads the two
  (``scripts/run_tests_bundled_affected.py``); the cache keys never do.

When a module finishes collecting, one ``{"k": "partial", ...}`` line (the same
fields bar ``own`` and ``fx``) records what the file reached so far: a process
killed mid-file (pytest-timeout's thread method, the runner's timeout) never
writes its ``deps`` line, and the gate keys such a known red by this one
(``scripts/run_tests_bundled_reds.py``). ``mods_add`` counts across both kinds.

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
import types

import pytest
from hermes_dep_trail import _SESSION, CHILD_DIR_ENV, CURRENT_FILE_ENV, ROOT_ENV, AuditTrail, Bucket

_OPTION = "--hermes-gate-deps"


def pytest_addoption(parser):
    parser.addoption(_OPTION, dest="hermes_gate_deps", default=None, help="Write per-file dependency records here.")


class _DepRecorder:
    def __init__(self, directory: str, root: str) -> None:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"deps-{os.getpid()}-{time.time_ns()}.jsonl")
        self._handle = open(path, "a", encoding="utf-8")  # noqa: SIM115 — closed at unconfigure
        self._trail = AuditTrail(root)
        self._written_mods: set[str] = set()
        self._written_names: set[str] = set()
        self._flushed: set[str] = set()
        self._running: str | None = None
        self._fixtures: dict[str, set[str]] = {}
        self._fx_unknown: set[str] = set()
        #: sys.modules entries already attributed (key → id of the module object: a module a test
        #: popped and imported again is a new load); each file's own first loads and its test module
        self._seen: dict[str, int] = {key: id(mod) for key, mod in list(sys.modules.items())}
        self._own_mods: dict[str, set[str]] = {}
        self._test_modules: dict[str, types.ModuleType] = {}
        sys.addaudithook(self._trail.hook)
        # a Python child inherits these and records itself (sitecustomize, stage 1b)
        os.environ[CHILD_DIR_ENV] = directory
        os.environ[ROOT_ENV] = root

    def _point(self, rel: str) -> None:
        """Attribute what follows to ``rel`` ("" = the session), here and in any child."""

        self._sweep()
        self._trail.current = rel
        if rel:
            os.environ[CURRENT_FILE_ENV] = rel
        else:
            os.environ.pop(CURRENT_FILE_ENV, None)

    def _sweep(self) -> None:
        """Attribute the modules loaded since the last sweep to the file current until now."""

        new = [(key, mod) for key, mod in list(sys.modules.items()) if self._seen.get(key) != id(mod)]
        if not new:
            return
        self._seen.update((key, id(mod)) for key, mod in new)
        if not self._trail.current:
            return  # the session's: every line carries those through ``mods_add``
        own = self._own_mods.setdefault(self._trail.current, set())
        for _, mod in new:
            rel = self._trail.filter.rel(getattr(mod, "__file__", None))
            if rel is not None:
                own.add(rel)

    def _refs(self, rel: str) -> list[str]:
        """The repo modules ``rel``'s test module names, and their parent packages."""

        module = self._test_modules.pop(rel, None)
        if module is None:
            return []
        names: set[str] = set()
        for value in list(vars(module).values()):
            if isinstance(value, types.ModuleType):
                names.add(getattr(value, "__name__", "") or "")
            elif isinstance(value, (type, types.FunctionType)):
                names.add(getattr(value, "__module__", "") or "")
        out: set[str] = set()
        for name in names:
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                found = self._trail.filter.rel(getattr(sys.modules.get(".".join(parts[:i])), "__file__", None))
                if found is not None and found != rel:
                    out.add(found)
        return sorted(out)

    def _record(self, kind: str, rel: str, bucket: Bucket) -> dict:
        session = self._trail.buckets[_SESSION]
        mods = self._trail.filter.modules()
        added = sorted(mods - self._written_mods)
        self._written_mods |= mods
        names = set(self._trail.import_names)
        names_added = sorted(names - self._written_names)
        self._written_names |= names
        return {
            "k": kind,
            "f": rel,
            "paths": sorted(bucket.paths | session.paths | {rel}),
            "dirs": sorted(bucket.dirs | session.dirs),
            "idirs": sorted(bucket.idirs | session.idirs),
            "spawn_py": bucket.spawn_py + session.spawn_py,
            "spawn_other": bucket.spawn_other + session.spawn_other,
            "mods_add": added,
            "inames_add": names_added,
        }

    def _write(self, record: dict) -> None:
        self._handle.write(json.dumps(record) + "\n")
        self._handle.flush()

    def _flush(self, rel: str) -> None:
        self._sweep()
        bucket = self._trail.buckets.pop(rel, None) or Bucket()
        record = self._record("deps", rel, bucket)
        record["own"] = sorted(bucket.paths)
        record["mods_own"] = sorted(self._own_mods.pop(rel, ()))
        record["mods_ref"] = self._refs(rel)
        if rel not in self._fx_unknown:
            record["fx"] = sorted(self._fixtures.pop(rel, ()))
        self._write(record)
        self._flushed.add(rel)

    def _rel_of(self, node) -> str:
        """The repo-relative POSIX path of a collector's or item's file."""

        return self._trail.filter.rel(getattr(node, "path", None)) or str(node.nodeid).partition("::")[0]

    def pytest_collectstart(self, collector):
        if isinstance(collector, pytest.Module):
            self._point(self._rel_of(collector))
            self._trail.bucket(self._trail.current)

    def pytest_collectreport(self, report):
        if str(report.nodeid).partition("::")[0].endswith(".py"):
            rel = self._trail.current
            if rel and "::" not in str(report.nodeid):  # the module itself: what a killed process keeps
                self._write(self._record("partial", rel, self._trail.buckets.get(rel) or Bucket()))
            self._point(_SESSION)  # the module is collected: later events are the session's

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        rel = self._rel_of(item)
        if self._running is not None and self._running != rel:
            self._flush(self._running)
        self._running = rel
        self._point(rel)
        yield

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        """The fixtures this item set up, read while its request is still alive."""

        rel = self._rel_of(item)
        module = getattr(item, "module", None)
        if isinstance(module, types.ModuleType):
            self._test_modules.setdefault(rel, module)
        request = getattr(item, "_request", None)
        names = getattr(request, "fixturenames", None) if request else None
        if names is None:
            self._fx_unknown.add(rel)
        else:
            self._fixtures.setdefault(rel, set()).update(names)

    def pytest_sessionfinish(self, session, exitstatus):
        self._sweep()
        self._trail.active = False
        for rel in [name for name in self._trail.buckets if name != _SESSION]:
            self._flush(rel)
        os.environ.pop(CURRENT_FILE_ENV, None)

    def close(self) -> None:
        self._trail.active = False
        for name in (CHILD_DIR_ENV, ROOT_ENV, CURRENT_FILE_ENV):
            os.environ.pop(name, None)
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
