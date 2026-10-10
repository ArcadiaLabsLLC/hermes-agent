"""D1.09 S1 — hermes children the Launcher's sweep can name: the chokepoint and two spawn sites.

``agent_runtime.process_index`` is the one writer of hermes' entries in the
Launcher's machine-wide process index. The byte format is pinned against
``tests/fixtures/process_index/`` -- a byte copy of the Launcher's
``test/fixtures/process_index/`` (launcher 7c88e35fc0), which the Launcher's
``mission_process_index_qa_fixture_test.dart`` decodes with its reader and
re-encodes to the same bytes. ``started_at_ticks`` is the serve register's
unit, which the Launcher's ``missionServeObservedStart`` compares: centiseconds
since the epoch off Linux (``round(psutil create_time * 100)``).

Killing mutations: ``process_start_ticks`` answers seconds instead of
centiseconds -> the unit test reds; ``record_child`` stops being called at the
dispatch spawn -> the dispatch test reds; ``to_json_text`` drops the key order
or the compact separators -> the fixture compare reds.

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


class _FakeProc:
    def __init__(self, pid: int, seen: list):
        self.pid = pid
        self.stdout = io.StringIO(json.dumps({"ok": True, "reply": "done", "session_id": "s"}))
        self.stderr = io.StringIO("")
        self.returncode = 0
        self._seen = seen

    def wait(self, timeout=None):
        self._seen.append(_entry_file(self.pid).exists())
        return self.returncode


def test_a_dispatch_child_is_named_while_it_runs_and_forgotten_once_settled(tmp_path, monkeypatch):
    from agent_runtime.dispatch_store import get_dispatch, mint_dispatch_id, record_dispatch
    from tools import agent_chat_dispatch
    import tools.agent_chat_dispatch.local_child  # noqa: F401 - the spawn patched below

    home = tmp_path / "bg-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    seen: list[bool] = []
    proc = _FakeProc(os.getpid(), seen)
    monkeypatch.setattr(agent_chat_dispatch.local_child.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(agent_chat_dispatch.local, "_child_identity", lambda pid: 777)
    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id="persona_chat_x", target_persona="dev", ask="go")

    agent_chat_dispatch._run_dispatch(dispatch_id, {"persona_id": "dev", "message": "go", "max_seconds": 1.0})

    assert get_dispatch(dispatch_id)["state"] == "completed"
    assert seen == [True], "the entry must exist while the supervisor waits on the child"
    assert not _entry_file(os.getpid()).exists(), "a settled dispatch leaves no entry"


def test_a_sign_in_child_is_named_while_it_runs_and_forgotten_when_it_ends():
    from agent_runtime.provider_signin_child import _PopenChild

    child = _PopenChild([sys.executable, "-c", "print('ready')"], dict(os.environ))
    pid = child._proc.pid
    stored = json.loads(_entry_file(pid).read_text(encoding="utf-8"))
    assert stored["pid"] == pid and stored["purpose"] == "hermes_child"

    assert [line.strip() for line in child.lines()] == ["ready"]
    assert not _entry_file(pid).exists()

    killed = _PopenChild([sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ))
    assert _entry_file(killed._proc.pid).exists()
    killed.terminate()
    killed._proc.wait(timeout=10)
    assert not _entry_file(killed._proc.pid).exists()
