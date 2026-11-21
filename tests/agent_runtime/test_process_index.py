"""D1.09 S1 — hermes children the Launcher's sweep can name: the chokepoint and its spawn site.

``agent_runtime.process_index`` is the one writer of hermes' entries in the
Launcher's machine-wide process index. The byte format is pinned against
``tests/fixtures/process_index/`` -- a byte copy of the Launcher's
``test/fixtures/process_index/`` (launcher 7c88e35fc0), which the Launcher's
``mission_process_index_qa_fixture_test.dart`` decodes with its reader and
re-encodes to the same bytes. ``started_at_ticks`` is the serve register's
unit, which the Launcher's ``missionServeObservedStart`` compares: centiseconds
since the epoch off Linux (``round(psutil create_time * 100)``).

Killing mutations: ``process_start_ticks`` answers seconds instead of
centiseconds -> the unit test reds; ``to_json_text`` drops the key order or the
compact separators -> the fixture compare reds. The one spawn site left, the
conversation worker, is pinned by ``test_process_index_native_peer.py`` (the
dispatch and sign-in children retired 2026-11-21: both run inside the serve).

The autouse ``_isolate_launcher_process_index`` fixture
(``tests/_downstream/conftest_plugin.py``) points ``index_directory`` at a
per-test tmp dir; the operator's real index is never touched.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

from agent_runtime import paths, process_index

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "process_index"
_KEYS = ["pid", "started_at_ticks", "store_root", "purpose", "recorded_by_pid"]


def _entry_file(pid: int) -> Path:
    return process_index.index_directory() / f"{pid}.json"


def test_the_bytes_are_the_launchers_fixture_bytes(monkeypatch):
    monkeypatch.setattr(process_index.os, "getpid", lambda: 777)
    process_index.record_child(
        4242, purpose="qa_launcher", started_at_ticks=179099109522,
        store_root=r"C:\Users\qa\AppData\Local\EterniaLauncher\stagec-smoke-local\hermes\agent-runtime",
    )
    monkeypatch.setattr(process_index.os, "getpid", lambda: 5151)
    monkeypatch.setattr(process_index, "process_start_ticks", lambda pid: None)
    process_index.record_child(5151, purpose="qa_mcp_server", store_root="")

    for name in ("4242.json", "5151.json"):
        assert _entry_file(int(name[:4])).read_bytes() == (_FIXTURES / name).read_bytes(), name


def test_a_hermes_child_entry_is_the_launchers_hermes_child_fixture_bytes(monkeypatch):
    """The ``hermes_child`` purpose pinned both ways: a byte copy of the Launcher's
    ``test/fixtures/process_index_hermes_child/6161.json``, which the Launcher's
    reader decodes. Killing mutation: ``PURPOSE_HERMES_CHILD`` respelled -> red."""
    monkeypatch.setattr(process_index.os, "getpid", lambda: 4321)
    process_index.record_child(
        6161, started_at_ticks=179099112233,
        store_root=r"C:\Users\qa\AppData\Local\hermes\agent-runtime",
    )
    fixture = _FIXTURES.parent / "process_index_hermes_child" / "6161.json"
    assert _entry_file(6161).read_bytes() == fixture.read_bytes()


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="Linux stamps /proc clock ticks, not centiseconds")
def test_started_at_ticks_is_centiseconds_since_the_epoch():
    import psutil

    entry = process_index.record_child(os.getpid())

    assert entry is not None and entry.started_at_ticks is not None
    expected = round(psutil.Process(os.getpid()).create_time() * 100)
    assert abs(entry.started_at_ticks - expected) <= 1, (entry.started_at_ticks, expected)


def test_a_record_names_this_store_and_a_forget_removes_only_its_own_identity(monkeypatch):
    entry = process_index.record_child(os.getpid())
    stored = json.loads(_entry_file(os.getpid()).read_text(encoding="utf-8"))
    assert list(stored) == _KEYS
    assert stored["purpose"] == "hermes_child"
    assert stored["store_root"] == str(paths.store_root())
    assert stored["recorded_by_pid"] == os.getpid()
    assert stored["started_at_ticks"] == entry.started_at_ticks

    # Another writer took the pid since: its entry survives our forget.
    _entry_file(os.getpid()).write_text(json.dumps({**stored, "started_at_ticks": 1}), encoding="utf-8")
    assert process_index.forget_child(os.getpid()) is False
    assert _entry_file(os.getpid()).exists()

    process_index.record_child(os.getpid())
    assert process_index.forget_child(os.getpid()) is True
    assert not _entry_file(os.getpid()).exists()
    assert process_index.forget_child(os.getpid()) is False, "a pid this process did not record is never removed"


def test_no_directory_writes_nothing_and_raises_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(process_index, "index_directory", lambda: None)
    assert process_index.record_child(os.getpid()) is None

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(process_index, "index_directory", lambda: blocker)
    assert process_index.record_child(os.getpid()) is None
    assert process_index.forget_child(os.getpid()) is False


def test_the_directory_follows_the_launchers_rule():
    resolve = process_index.resolve_index_directory
    assert resolve({"LOCALAPPDATA": r"C:\Users\op\AppData\Local", "HOME": "/h"}) == (
        Path(r"C:\Users\op\AppData\Local") / "EterniaLauncher" / "process_index")
    assert resolve({"LOCALAPPDATA": "  ", "HOME": "/home/op"}) == Path("/home/op") / ".eternia_launcher" / "process_index"
    assert resolve({}) is None
