"""Path and handle clocks must be stable individually, not equal to each other."""

import json
import os
from types import SimpleNamespace

import pytest

from tools import file_tools_read_tracking as tracking
from tools.file_tools import clear_file_ops_cache
from tools.registry import registry


def _different_handle_clock(monkeypatch, *, drift=False):
    real_fstat = os.fstat
    calls = 0

    def fstat(fd):
        nonlocal calls
        stamp = real_fstat(fd)
        calls += 1
        fields = ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        values = {name: getattr(stamp, name) for name in fields}
        values["st_ctime_ns"] += 1_000_000_000 + (calls if drift else 0)
        return SimpleNamespace(**values)

    monkeypatch.setattr(tracking.os, "fstat", fstat)


def test_distinct_stable_handle_clock_preserves_read_write_guard(tmp_path, monkeypatch):
    _different_handle_clock(monkeypatch)
    path = tmp_path / "file.txt"
    path.write_text("original\n", encoding="utf-8")
    task = "distinct-handle-clock"

    def call(name, **args):
        return json.loads(registry.dispatch(name, {"path": str(path), **args}, task_id=task))

    try:
        assert "error" not in call("read_file")
        assert "error" not in call("write_file", content="replaced\n")
        stamp = path.stat()
        path.write_text("external\n", encoding="utf-8")  # same byte count
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert call("write_file", content="clobbered\n").get("stale_write_blocked")
        assert path.read_text(encoding="utf-8") == "external\n"
        assert "error" not in call("read_file")
        assert "error" not in call("write_file", content="merged\n")
        assert path.read_text(encoding="utf-8") == "merged\n"
    finally:
        clear_file_ops_cache(task)


@pytest.mark.parametrize("change", ["handle_clock", "path_replacement"])
def test_snapshot_refuses_changes_during_hashing(tmp_path, monkeypatch, change):
    path = tmp_path / "file.txt"
    path.write_bytes(b"original")
    if change == "handle_clock":
        _different_handle_clock(monkeypatch, drift=True)
    else:
        replacement = tmp_path / "replacement.txt"
        replacement.write_bytes(b"external")
        original_digest = tracking.hashlib.file_digest

        def replace_after_hash(stream, algorithm):
            digest = original_digest(stream, algorithm)
            os.replace(replacement, path)
            return digest

        monkeypatch.setattr(tracking.hashlib, "file_digest", replace_after_hash)
    assert tracking._file_version(str(path)) is None
