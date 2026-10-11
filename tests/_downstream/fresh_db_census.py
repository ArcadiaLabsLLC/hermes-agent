"""Fresh-SessionDB census (design sweep D3.11, suite-speed Stage 4F).

A ``SessionDB`` writer-opened on a path that does not exist yet runs the whole
schema and FTS script: 0.8-1.0 s on the workstation, against ~0.02 s to copy a
finished file (``tests/agent_runtime/_session_db_template.py``). Which test
files pay that, and how often, is a RUN fact, not a reading: production paths
open stores the test never names. This plugin writes it down.

``HERMES_TEST_COUNT_FRESH_DBS=1`` registers it (``conftest_plugin`` does, at
configure; the bundled runner sets the variable, so the landing gate pays the
census). It wraps ``hermes_state.SessionDB.__init__`` once ``hermes_state`` is
imported, and counts, per test FILE, the writer opens of a path that did not
exist when the open began, with the seconds spent inside them. A READ open is
never counted, and neither is a writer open of an existing file (the template
fixture's copy lands first, so a seeded open reads as not-fresh). At session
end it appends one JSON line per file that ran a test to
``<rootdir>/.pytest_cache/hermes_fresh_dbs.jsonl`` (git-ignored, the home of
``hermes_bundled_runs.jsonl``): ``{file, fresh_dbs, fresh_seconds, seconds}``,
``seconds`` being the file's setup+call+teardown wall in this process.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ENV = "HERMES_TEST_COUNT_FRESH_DBS"
RECEIPT = Path(".pytest_cache") / "hermes_fresh_dbs.jsonl"

_lock = threading.Lock()
_current: dict[str, str | None] = {"file": None}
_files: dict[str, dict[str, float]] = {}
_installed: dict[str, object] = {}


def enabled(environ=os.environ) -> bool:
    return (environ.get(ENV) or "").strip() not in ("", "0")


def _row(file: str) -> dict[str, float]:
    return _files.setdefault(file, {"fresh_dbs": 0, "fresh_seconds": 0.0, "seconds": 0.0})


def _open_args(args: tuple, kwargs: dict) -> tuple[object, bool]:
    db_path = args[0] if args else kwargs.get("db_path")
    read_only = args[1] if len(args) > 1 else kwargs.get("read_only", False)
    return db_path, bool(read_only)


def install() -> bool:
    """Wrap ``SessionDB.__init__`` if ``hermes_state`` is imported; idempotent."""

    module = sys.modules.get("hermes_state")
    if module is None or _installed.get("module") is module:
        return False
    original = module.SessionDB.__init__

    def counted_init(self, *args, **kwargs):
        db_path, read_only = _open_args(args, kwargs)
        fresh = False
        if not read_only:
            try:
                target = Path(db_path) if db_path else Path(module._default_db_path())
                fresh = not target.exists()
            except Exception:  # the census never decides an open
                fresh = False
        started = time.perf_counter()
        try:
            original(self, *args, **kwargs)
        finally:
            if fresh:
                with _lock:
                    row = _row(_current["file"] or "<outside a test>")
                    row["fresh_dbs"] += 1
                    row["fresh_seconds"] += time.perf_counter() - started

    module.SessionDB.__init__ = counted_init
    _installed["module"] = module
    return True


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    install()
    file = item.nodeid.split("::", 1)[0]
    _current["file"] = file
    started = time.perf_counter()
    try:
        return (yield)
    finally:
        with _lock:
            _row(file)["seconds"] += time.perf_counter() - started


def write_receipt(rootdir: Path) -> Path | None:
    with _lock:
        rows = [
            {
                "file": file,
                "fresh_dbs": int(row["fresh_dbs"]),
                "fresh_seconds": round(row["fresh_seconds"], 3),
                "seconds": round(row["seconds"], 3),
            }
            for file, row in sorted(_files.items())
        ]
    if not rows:
        return None
    path = Path(rootdir) / RECEIPT
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        return None
    return path


def pytest_sessionfinish(session, exitstatus):
    write_receipt(session.config.rootpath)
