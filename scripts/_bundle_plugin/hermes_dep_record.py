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
  ``glob``, ``os.walk``, ``Path.iterdir`` and the import system's own directory
  scans all go through these; ``"."`` is the repo root);
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
        self._flushed: set[str] = set()
        self._running: str | None = None
        self._fixtures: dict[str, set[str]] = {}
        self._fx_unknown: set[str] = set()
        sys.addaudithook(self._trail.hook)
        # a Python child inherits these and records itself (sitecustomize, stage 1b)
        os.environ[CHILD_DIR_ENV] = directory
        os.environ[ROOT_ENV] = root

    def _point(self, rel: str) -> None:
        """Attribute what follows to ``rel`` ("" = the session), here and in any child."""

        self._trail.current = rel
        if rel:
            os.environ[CURRENT_FILE_ENV] = rel
        else:
            os.environ.pop(CURRENT_FILE_ENV, None)

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
            "own": sorted(bucket.paths),
        }
        if rel not in self._fx_unknown:
            record["fx"] = sorted(self._fixtures.pop(rel, ()))
        self._handle.write(json.dumps(record) + "\n")
        self._handle.flush()
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
        request = getattr(item, "_request", None)
        names = getattr(request, "fixturenames", None) if request else None
        if names is None:
            self._fx_unknown.add(rel)
        else:
            self._fixtures.setdefault(rel, set()).update(names)

    def pytest_sessionfinish(self, session, exitstatus):
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
