"""pytest plugin loaded by ``scripts/run_tests_bundled.py`` into each bundle process.

A bundle is ONE ``python -m pytest a.py b.py …`` process over up to N test
files. pytest's own summary line only totals the whole process, so the runner
cannot tell from it which member failed or how long each member took. This
plugin writes one JSON line per event to the path given by
``--hermes-bundle-events``:

* ``{"k": "start", "t": <epoch>}`` — session start (the shared start-up ends here);
* ``{"k": "collect", "f": <file>, "d": <s>, "err": <bool>}`` — one per test module;
* ``{"k": "test", "f": <file>, "c": <category>, "d": <s>}`` — one per runtest
  report, ``category`` being exactly what pytest's terminal summary files the
  report under (``passed`` / ``failed`` / ``skipped`` / ``error`` / ``xfailed``
  / ``xpassed``, or ``""`` for a passing setup/teardown phase), plus ``"n"``
  (the node id) on a failed or errored report;
* ``{"k": "end", "t": <epoch>, "rc": <int>}`` — session finish.

Lines are flushed as they are written, so a bundle killed by its timeout still
leaves a record of every member that finished before the kill — which is what
lets the runner re-run only the members that did not.

Generic on purpose (no fork paths): it is the half of the bundled runner that
would move with it into ``run_tests_parallel.py`` as a ``--bundle-size`` flag.
"""

from __future__ import annotations

import json
import os
import time

import pytest

_OPTION = "--hermes-bundle-events"


def pytest_addoption(parser):
    parser.addoption(
        _OPTION,
        dest="hermes_bundle_events",
        default=None,
        help="Write per-file bundle events (JSON lines) to this path.",
    )


class _Recorder:
    def __init__(self, path: str, config) -> None:
        self._handle = open(path, "a", encoding="utf-8")  # noqa: SIM115 — closed at unconfigure
        self._config = config
        self._collect_started: dict[str, float] = {}

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

    def pytest_runtest_logreport(self, report):
        category, _letter, _word = self._config.hook.pytest_report_teststatus(
            report=report, config=self._config
        )
        record = {
            "k": "test",
            "f": self._file_of(report.nodeid),
            "c": category or "",
            "d": float(getattr(report, "duration", 0.0) or 0.0),
        }
        if category in ("failed", "error"):
            record["n"] = report.nodeid
        self._write(record)

    def pytest_sessionfinish(self, session, exitstatus):
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
