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
from hermes_dep_trail import _SESSION, CURRENT_FILE_ENV, AuditTrail, Bucket  # the pytest-free half

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
