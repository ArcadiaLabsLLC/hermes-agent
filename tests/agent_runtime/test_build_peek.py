"""``work peek`` on a ``build:`` row reads the build's own output (runtime-queue row, 2026-10-04).

An agent build IS a background terminal process, so its peek is that session's buffer; an
announced build's peek is the writer-declared ``log_path`` tail — read only under the record's
``project_root`` — else the record's own ``tail``; a detected build has no output hermes can see.
"""

from __future__ import annotations

import threading
import types

import pytest

from agent_runtime.builds.registry import new_record, write_record
from agent_runtime.running_work import lanes_build, lanes_process, ownership, surface
from agent_runtime.running_work.vocabulary import PEEK_TAIL_LIMIT


@pytest.fixture
def head(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for module in (ownership, lanes_process, lanes_build):
        monkeypatch.setattr(module, "_head_home", lambda: (home, "test"))
    return home


def _serve_row(monkeypatch, row):
    monkeypatch.setattr(surface, "find_work_row", lambda work_id: row if work_id == row["work_id"] else None)


def _announced(head, tmp_path, monkeypatch, **fields):
    record = new_record(job_id="qb", started_at=1.0, project_root=str(tmp_path / "proj"), **fields)
    write_record(head / "builds", record)
    _serve_row(monkeypatch, {"work_id": "build:announced:qb", "kind": "build", "announcement": {"record": "qb.json"}})
    return surface.peek_work("build:announced:qb")


def test_an_agent_build_peeks_its_terminal_buffer(monkeypatch):
    session = types.SimpleNamespace(_lock=threading.Lock(), output_buffer="Resolving dependencies...\n\x1b[32mLinking\x1b[0m")
    registry = types.SimpleNamespace(process_registry=types.SimpleNamespace(get={"sess-b": session}.get))
    monkeypatch.setattr(surface, "_module", lambda name: registry if name == "tools.process_registry" else None)
    _serve_row(monkeypatch, {"work_id": "build:agent:sess-b", "kind": "build"})

    payload = surface.peek_work("build:agent:sess-b")

    assert (payload["tail_available"], payload["tail_source"]) == (True, "terminal_buffer")
    assert payload["tail"] == "Resolving dependencies... Linking"
    assert payload["consumed"] is False and "tail_reason" not in payload


def test_an_announced_build_peeks_the_log_tail_under_its_project(head, tmp_path, monkeypatch):
    log = tmp_path / "proj" / "build" / "qb" / "build.log"
    log.parent.mkdir(parents=True)
    log.write_text("x" * (PEEK_TAIL_LIMIT * 5) + "\nAPI_TOKEN=hunter2\nBuilding Windows application...", encoding="utf-8")

    payload = _announced(head, tmp_path, monkeypatch, log_path=str(log), tail="stale writer tail")

    assert (payload["tail_available"], payload["tail_source"], payload["truncated"]) == (True, "build_log", True)
    assert payload["tail"].endswith("API_TOKEN: [redacted] Building Windows application...")
    assert "hunter2" not in payload["tail"] and len(payload["tail"]) <= PEEK_TAIL_LIMIT


def test_a_log_path_outside_the_project_is_refused_not_read(head, tmp_path, monkeypatch):
    outside = tmp_path / "elsewhere.log"
    outside.write_text("not this build's", encoding="utf-8")

    payload = _announced(head, tmp_path, monkeypatch, log_path=str(outside), tail="writer tail")

    assert (payload["tail_available"], payload["tail_reason"]) == (False, "log_path_outside_project")
    assert payload["tail"] == ""


def test_an_unreadable_log_is_typed(head, tmp_path, monkeypatch):
    payload = _announced(head, tmp_path, monkeypatch, log_path=str(tmp_path / "proj" / "gone.log"))

    assert payload["tail_reason"] == "log_unreadable:FileNotFoundError"


def test_without_a_log_path_the_record_tail_answers(head, tmp_path, monkeypatch):
    payload = _announced(head, tmp_path, monkeypatch, tail="Compiling lib/main.dart")
    assert (payload["tail_source"], payload["tail"]) == ("record_tail", "Compiling lib/main.dart")

    silent = _announced(head, tmp_path, monkeypatch)
    assert (silent["tail_available"], silent["tail_reason"]) == (False, "no_log_path")


def test_a_detected_build_has_no_output_stream(monkeypatch):
    _serve_row(monkeypatch, {"work_id": "build:detected:7001-11", "kind": "build"})

    payload = surface.peek_work("build:detected:7001-11")

    assert (payload["tail_available"], payload["tail_reason"]) == (False, "no_output_stream")
