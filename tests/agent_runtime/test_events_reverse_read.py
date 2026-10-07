"""``EventLog.for_session`` / ``for_task`` read each slice from its END.

The reverse chunked reader (``events._reversed_slice_lines``) must return exactly
what the whole-file ``reversed(read_text().splitlines())`` scan returned, for the
same arguments, across sealed + live slices — at every chunk size, so a chunk
boundary landing anywhere in a line (or inside a multi-byte character) is pinned.
"""

import json

import pytest

from hermes_time import now

from agent_runtime import event_rotation, events
from agent_runtime.events import EventLog
from agent_runtime.models import Event
from agent_runtime.serde import from_jsonable, to_jsonable

_CAP_ENV = "HERMES_EVENT_LOG_ROTATION_CAP_BYTES"


def _legacy_for_session(session_id, *, limit=50, since=None, types=None):
    """The pre-change ``EventLog._for_matching`` for a session, verbatim."""

    token = events._session_id_json_token(session_id)
    type_tokens = events._type_json_tokens(types)
    selected = []
    for sl in event_rotation.reversed_slices():
        if not sl.path.exists():
            continue
        for line in reversed(sl.path.read_text(encoding="utf-8").splitlines()):
            if token not in line:
                continue
            if type_tokens is not None and not any(t in line for t in type_tokens):
                continue
            evt = from_jsonable(Event, json.loads(line))
            if evt.session_id != session_id:
                continue
            if types is not None and evt.type not in types:
                continue
            if since is not None and evt.ts < since:
                continue
            selected.append(evt)
            if limit > 0 and len(selected) >= limit:
                return list(reversed(selected))
    return list(reversed(selected))


def _session_evt(i, session_id, *, kind="run.tool.started"):
    return Event(ts=now(), type=kind, task_id=None, run_id=f"r{i}", persona_id="base",
                 payload={"tool_name": f"tool-é-{i}" + "x" * (i % 7)}, session_id=session_id)


def _dump(rows):
    return [json.dumps(to_jsonable(row), ensure_ascii=False, sort_keys=True) for row in rows]


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 64, 1 << 20])
def test_reversed_slice_lines_matches_read_text_splitlines(tmp_path, monkeypatch, chunk):
    monkeypatch.setattr(events, "_REVERSE_READ_CHUNK_BYTES", chunk)
    body = (
        '{"a":"é"}\n'
        "\n"
        "plain\r\n"
        "lone\rcarriage\n"
        "sep inside\x85nel\n"
        "日本語の行\n"
        '{"torn":"no newli'
    )
    path = tmp_path / "slice.jsonl"
    path.write_bytes(body.encode("utf-8"))
    expected = list(reversed(path.read_text(encoding="utf-8").splitlines()))
    assert list(events._reversed_slice_lines(path)) == expected

    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    assert list(events._reversed_slice_lines(empty)) == []

    only_newlines = tmp_path / "nl.jsonl"
    only_newlines.write_bytes(b"\n\n\n")
    assert list(events._reversed_slice_lines(only_newlines)) == ["", "", ""]


@pytest.mark.parametrize("chunk", [1, 5, 97, 1 << 20])
def test_for_session_identical_to_legacy_across_sealed_and_live(isolate_agent_runtime_root, monkeypatch, chunk):
    monkeypatch.setenv(_CAP_ENV, "700")  # several events per sealed slice
    log = EventLog()
    for i in range(40):
        log.append(_session_evt(i, "chat_a" if i % 3 else "chat_b",
                                kind="run.tool.finished" if i % 4 == 0 else "run.tool.started"))
    assert event_rotation.slice_count() > 2
    monkeypatch.setattr(events, "_REVERSE_READ_CHUNK_BYTES", chunk)

    cases = [
        dict(session_id="chat_a"),
        dict(session_id="chat_a", limit=3),
        dict(session_id="chat_a", limit=0),
        dict(session_id="chat_b", limit=5, types={"run.tool.finished"}),
        dict(session_id="chat_absent"),
        dict(session_id="chat_absent", limit=0),
    ]
    for case in cases:
        sid = case.pop("session_id")
        new = log.for_session(sid, **case)
        old = _legacy_for_session(sid, **case)
        assert _dump(new) == _dump(old), (sid, case)
    assert [e.run_id for e in log.for_session("chat_a", limit=3)] == ["r35", "r37", "r38"]


def test_for_session_session_only_in_oldest_sealed_slice(isolate_agent_runtime_root, monkeypatch):
    monkeypatch.setenv(_CAP_ENV, "500")
    monkeypatch.setattr(events, "_REVERSE_READ_CHUNK_BYTES", 13)
    log = EventLog()
    log.append(_session_evt(0, "chat_old"))
    for i in range(1, 30):
        log.append(_session_evt(i, "chat_new"))
    assert event_rotation.slice_count() > 2
    rows = log.for_session("chat_old")
    assert [e.run_id for e in rows] == ["r0"]
    assert _dump(rows) == _dump(_legacy_for_session("chat_old"))


@pytest.mark.parametrize("chunk", [1, 11, 1 << 20])
def test_for_session_torn_final_line_on_live_slice(isolate_agent_runtime_root, monkeypatch, chunk):
    monkeypatch.setattr(events, "_REVERSE_READ_CHUNK_BYTES", chunk)
    log = EventLog()
    for i in range(6):
        log.append(_session_evt(i, "chat_t"))
    live = event_rotation.live_path()

    # A torn write that does not carry the session token: both readers skip it.
    with open(live, "ab") as handle:
        handle.write(b'{"ts":"2026-10-05T00:00:00","type":"run.tool.sta')
    assert _dump(log.for_session("chat_t", limit=2)) == _dump(_legacy_for_session("chat_t", limit=2))
    assert [e.run_id for e in log.for_session("chat_t", limit=2)] == ["r4", "r5"]

    # A torn write that DOES carry the token: both readers decode it and raise.
    with open(live, "ab") as handle:
        handle.write(b'\n{"session_id":"chat_t","type":"run.tool.sta')
    with pytest.raises(json.JSONDecodeError):
        _legacy_for_session("chat_t", limit=2)
    with pytest.raises(json.JSONDecodeError):
        log.for_session("chat_t", limit=2)


def test_for_session_does_not_read_past_the_limit(isolate_agent_runtime_root, monkeypatch):
    """The point of the change: a limit met in the tail never reaches the head."""

    monkeypatch.setattr(events, "_REVERSE_READ_CHUNK_BYTES", 256)
    log = EventLog()
    for i in range(200):
        log.append(_session_evt(i, "chat_hot"))
    live = event_rotation.live_path()
    # Undecodable bytes at the HEAD of the slice: the old whole-file read raised
    # on them; a tail scan that stops at the limit never reaches them.
    original = live.read_bytes()
    live.write_bytes(b"\xff\xfe junk\n" + original)
    with pytest.raises(UnicodeDecodeError):
        _legacy_for_session("chat_hot", limit=2)
    assert [e.run_id for e in log.for_session("chat_hot", limit=2)] == ["r198", "r199"]


def test_tail_is_chronological_across_slices_without_full_text_read(tmp_path, monkeypatch):
    rows = [_session_evt(i, "chat") for i in range(30)]
    paths = [tmp_path / "sealed.jsonl", tmp_path / "live.jsonl"]
    for path, part in zip(paths, (rows[:20], rows[20:])):
        path.write_text("\n".join(json.dumps(to_jsonable(row), ensure_ascii=False) for row in part) + "\n\n", encoding="utf-8")
    from types import SimpleNamespace
    monkeypatch.setattr(event_rotation, "reversed_slices", lambda: [SimpleNamespace(path=path) for path in reversed(paths)])
    from pathlib import Path
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("full text")))
    for count in (0, 1, 12, 35):
        assert _dump(EventLog().tail(count)) == _dump(rows[-count:] if count else [])
