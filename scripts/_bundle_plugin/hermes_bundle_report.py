"""pytest plugin loaded by ``scripts/run_tests_bundled.py`` into each bundle process.

A bundle is ONE ``python -m pytest a.py b.py …`` process over up to N test
files. pytest's own summary line only totals the whole process, so the runner
cannot tell from it which member failed or how long each member took. This
plugin writes one JSON line per event to the path given by
``--hermes-bundle-events``:

* ``{"k": "start", "t": <epoch>}`` — session start (the shared start-up ends here);
* ``{"k": "collect", "f": <file>, "d": <s>, "err": <bool>}`` — one per test module;
* ``{"k": "test", "f": <file>, "c": <category>, "d": <s>, "w": <phase>}`` — one per
  runtest report, ``category`` being exactly what pytest's terminal summary files the
  report under (``passed`` / ``failed`` / ``skipped`` / ``error`` / ``xfailed``
  / ``xpassed``, or ``""`` for a passing setup/teardown phase), ``phase`` pytest's
  ``when`` (``setup`` / ``call`` / ``teardown``), plus ``"n"`` (the node id) on a
  failed or errored report or a phase of at least ``_NAMED_SECONDS``;
* ``{"k": "diag", "f": <file>, "spawn": {<kind>: [<n>, <s>]}, "wrapped": <s>, "sleep": <s>}``
  — once per file, when the run moves off it: the processes its tests started by
  program kind (``python`` / ``git`` / ``other``) with the seconds the main thread
  waited on them (``Popen.wait`` / ``communicate``), the seconds inside the callable
  ``--hermes-diag-wrap=<module>:<attr.path>`` names (wrapped on first sight of the
  module), and the main thread's ``time.sleep`` seconds. No profiler: two audit
  events, three method wraps;
* ``{"k": "end", "t": <epoch>, "rc": <int>}`` — session finish.

Lines are flushed as they are written, so a bundle killed by its timeout still
leaves a record of every member that finished before the kill — which is what
lets the runner re-run only the members that did not.

Generic on purpose (no fork paths): it is the half of the bundled runner that
would move with it into ``run_tests_parallel.py`` as a ``--bundle-size`` flag.
"""

from __future__ import annotations

import functools
import importlib
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from hermes_dep_trail import first_program, is_python

_OPTION = "--hermes-bundle-events"
_WRAP_OPTION = "--hermes-diag-wrap"
#: a phase at least this long carries its node id (the record's slowest tests)
_NAMED_SECONDS = 0.01


def pytest_addoption(parser):
    parser.addoption(
        _OPTION,
        dest="hermes_bundle_events",
        default=None,
        help="Write per-file bundle events (JSON lines) to this path.",
    )
    parser.addoption(
        _WRAP_OPTION, dest="hermes_diag_wrap", default=None,
        help="<module>:<attr.path> of a callable whose seconds the diag record counts.",
    )


def program_kind(args) -> str:
    """``python`` / ``git`` / ``other`` for a Popen's args (or an ``os.system`` command)."""

    first = first_program(args)  # the recorder's reader and judge: one owner (hermes_dep_trail)
    if is_python(first):
        return "python"
    return "git" if os.path.basename(first).lower() in ("git", "git.exe") else "other"


class _Probe:
    """Per-file spawns, waits, a wrapped callable's seconds and sleeps, attributed to
    the file the run is on. Waits and sleeps count on the main thread only."""

    def __init__(self, target: str | None) -> None:
        self.current = ""
        self.files: dict[str, dict] = {}
        self.active = True
        self._main = threading.get_ident()
        self._local = threading.local()
        self._target = target
        self._wrapped = False
        sys.addaudithook(self._audit)
        for name in ("wait", "communicate"):
            setattr(subprocess.Popen, name, self._timed_wait(getattr(subprocess.Popen, name)))
        time.sleep = self._timed(time.sleep, "sleep")

    def bucket(self) -> dict:
        found = self.files.get(self.current)
        if found is None:
            found = self.files[self.current] = {"spawn": {}, "wrapped": 0.0, "sleep": 0.0}
        return found

    def _audit(self, event: str, args: tuple) -> None:
        if not self.active or event not in ("subprocess.Popen", "os.system"):
            return
        try:
            kind = program_kind(args[1] if event == "subprocess.Popen" and args[1] else args[0])
            entry = self.bucket()["spawn"].setdefault(kind, [0, 0.0])
            entry[0] += 1
        except Exception:  # an audit hook must never raise into the code under test
            return

    def _timed_wait(self, method):
        probe = self

        @functools.wraps(method)
        def wrapper(popen, *args, **kwargs):
            if threading.get_ident() != probe._main or getattr(probe._local, "waiting", False):
                return method(popen, *args, **kwargs)
            probe._local.waiting = True
            started = time.perf_counter()
            try:
                return method(popen, *args, **kwargs)
            finally:
                probe._local.waiting = False
                if probe.active:
                    entry = probe.bucket()["spawn"].setdefault(program_kind(popen.args), [0, 0.0])
                    entry[1] += time.perf_counter() - started

        return wrapper

    def _timed(self, func, column: str):
        probe = self

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if threading.get_ident() != probe._main or getattr(probe._local, column, False):
                return func(*args, **kwargs)
            setattr(probe._local, column, True)
            started = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                setattr(probe._local, column, False)
                if probe.active:
                    probe.bucket()[column] += time.perf_counter() - started

        return wrapper

    def wrap_target(self) -> None:
        """Wrap ``--hermes-diag-wrap``'s callable once its module is imported."""

        if self._wrapped or not self._target:
            return
        module_name, _, path = self._target.partition(":")
        if module_name not in sys.modules:
            return
        self._wrapped = True
        try:
            owner = importlib.import_module(module_name)
            *parents, leaf = path.split(".")
            for name in parents:
                owner = getattr(owner, name)
            setattr(owner, leaf, self._timed(getattr(owner, leaf), "wrapped"))
        except (AttributeError, ImportError, ValueError):
            return

    def take(self, rel: str) -> dict | None:
        return self.files.pop(rel, None)


class _Recorder:
    def __init__(self, path: str, config) -> None:
        self._handle = open(path, "a", encoding="utf-8")
        self._config = config
        self._collect_started: dict[str, float] = {}
        self._probe = _Probe(config.getoption("hermes_diag_wrap"))
        self._on = ""

    def _move_to(self, rel: str) -> None:
        """The probe now counts for ``rel``; the file it leaves gets its diag line."""

        self._probe.wrap_target()
        if rel == self._on:
            return
        self._flush_diag(self._on)
        self._on = self._probe.current = rel

    def _flush_diag(self, rel: str) -> None:
        found = self._probe.take(rel)
        if rel and found and (found["spawn"] or found["wrapped"] or found["sleep"]):
            self._write({"k": "diag", "f": rel, **found})

    def _write(self, record: dict) -> None:
        self._handle.write(json.dumps(record) + "\n")
        self._handle.flush()

    @staticmethod
    def _file_of(nodeid: str) -> str:
        return nodeid.split("::", 1)[0]

    def pytest_sessionstart(self, session):
        self._write({"k": "start", "t": time.time()})

    def pytest_collectstart(self, collector):
        if isinstance(collector, pytest.Module):
            self._collect_started[collector.nodeid] = time.perf_counter()
            self._move_to(self._file_of(collector.nodeid))

    def pytest_collectreport(self, report):
        started = self._collect_started.pop(report.nodeid, None)
        if started is None and not report.failed:
            return
        path = self._file_of(report.nodeid)
        if not path.endswith(".py"):
            return
        self._write(
            {
                "k": "collect",
                "f": path,
                "d": (time.perf_counter() - started) if started is not None else 0.0,
                "err": bool(report.failed),
            }
        )

    def pytest_runtest_logstart(self, nodeid, location):
        # Written BEFORE setup runs, so a process that dies in a fixture leaves this file as the
        # last record; ``pytest_runtest_logreport`` fires only for a phase that finished, which
        # blamed the previous member for a death in the next one's setup (2026-10-13).
        self._move_to(self._file_of(nodeid))
        self._write({"k": "begin", "f": self._file_of(nodeid)})

    def pytest_runtest_logreport(self, report):
        category, _letter, _word = self._config.hook.pytest_report_teststatus(
            report=report, config=self._config
        )
        record = {
            "k": "test",
            "f": self._file_of(report.nodeid),
            "c": category or "",
            "d": float(getattr(report, "duration", 0.0) or 0.0),
            "w": report.when,
        }
        if category in ("failed", "error") or record["d"] >= _NAMED_SECONDS:
            record["n"] = report.nodeid
        if report.when == "call":
            # tests/_downstream/body_patch_scope.py: (attrs, items, late_attrs, late_items, cwd, syspath)
            counts = dict(report.user_properties or ()).get("hermes_body_patches")
            bp = [int(counts[0]), int(counts[1]), int(counts[2]) + int(counts[3])] if counts else []
            if any(bp):
                record["bp"] = bp
        self._write(record)

    def pytest_sessionfinish(self, session, exitstatus):
        self._flush_diag(self._on)
        self._probe.active = False
        self._write({"k": "end", "t": time.time(), "rc": int(exitstatus)})

    def close(self) -> None:
        try:
            self._handle.close()
        except OSError:
            pass


def pytest_configure(config):
    path = config.getoption("hermes_bundle_events")
    if not path:
        return
    recorder = _Recorder(os.fspath(path), config)
    config.pluginmanager.register(recorder, "hermes_bundle_recorder")
    config._hermes_bundle_recorder = recorder  # type: ignore[attr-defined]


def pytest_unconfigure(config):
    recorder = getattr(config, "_hermes_bundle_recorder", None)
    if recorder is not None:
        recorder.close()
