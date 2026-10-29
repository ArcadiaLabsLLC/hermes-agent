"""Slice P1 of launcher supervision: the play-session handback (row RT-PLAY-SESSION-HANDBACK).

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §2 and §3 decisions
16–18, §5's P1 cases. The records are G1's game files, written here directly; the ops are driven through
the serve's op table. Autouse conftest fixtures isolate the runtime root.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from agent_runtime import paths
from agent_runtime.launcher_supervision import play_sessions
from agent_runtime.launcher_supervision.game_watch import GameRecord, Outcome, _write_game_record
from hermes_cli.harness_parts.serve import handle_message
from hermes_cli.harness_parts.serve.manifest import ops_manifest

NOW = 1_800_000_000.0
DAY = 24 * 3600.0
WIRE_KEYS = {"session_id", "game_id", "ended_at", "last_seen_at", "exit_code", "outcome"}


def _record(session_id: str, *, received: float, outcome: str = Outcome.EXITED) -> GameRecord:
    record = GameRecord(session_id=session_id, game_id=f"game_{session_id}", mapping_id=None, title=None,
                        started_at=None, pid=4321, pid_create_time=None, executable="/games/x", install_dir=None,
                        received_epoch=received, last_seen_epoch=received + 30, outcome=outcome,
                        ended_epoch=received + 60 if outcome == Outcome.EXITED else None)
    _write_game_record(record)
    return record


def _on_disk() -> list[str]:
    return sorted(path.stem for path in paths.launcher_supervision_games_dir().glob("*.json"))


def _op(op: str, message: dict, *, transport: str = "stdio") -> list[dict]:
    frames: list[dict] = []
    handle_message.OP_HANDLERS[op](SimpleNamespace(), {"op": op, **message}, SimpleNamespace(emit=frames.append),
                                   SimpleNamespace(transport=transport))
    return frames


def test_pending_is_at_least_once_and_ack_deletes_only_the_named_ended_records(caplog):
    _record("s_a", received=NOW - 300)
    _record("s_b", received=NOW - 200, outcome=Outcome.LOST)
    _record("s_c", received=NOW - 100, outcome=Outcome.STILL_RUNNING)

    first = play_sessions.pending(NOW)
    assert play_sessions.pending(NOW) == first  # reading deletes nothing
    assert [row["session_id"] for row in first] == ["s_a", "s_b", "s_c"]
    assert all(set(row) == WIRE_KEYS for row in first)
    assert [row["outcome"] for row in first] == ["exited", "lost", "still_running"]
    assert first[1]["ended_at"] is None and first[0]["ended_at"] is not None

    caplog.set_level(logging.INFO, logger=play_sessions.__name__)
    assert play_sessions.ack(["s_a", "s_c", "no_such"]) == ["s_a"]
    assert _on_disk() == ["s_b", "s_c"]  # s_b was not named; s_c is the live watch's record
    assert "event=play_session_ack_kept_running session_id=s_c" in caplog.text


def test_the_65th_record_drops_the_oldest_ended_one_and_logs_it(caplog):
    _record("s_running_oldest", received=NOW - 10_000, outcome=Outcome.STILL_RUNNING)
    for n in range(play_sessions.MAX_RECORDS):
        _record(f"s_{n:03d}", received=NOW - 5_000 + n)
    caplog.set_level(logging.INFO, logger=play_sessions.__name__)

    assert play_sessions.prune(NOW) == ["s_000"]
    assert len(_on_disk()) == play_sessions.MAX_RECORDS
    assert "s_running_oldest" in _on_disk()  # a still-running record is the watch itself, never dropped
    assert "event=play_session_dropped_cap session_id=s_000" in caplog.text


def test_a_record_older_than_thirty_days_is_dropped_and_logged(caplog):
    _record("s_old", received=NOW - 31 * DAY)
    _record("s_new", received=NOW - 29 * DAY)
    caplog.set_level(logging.INFO, logger=play_sessions.__name__)
    assert [row["session_id"] for row in play_sessions.pending(NOW)] == ["s_new"]
    assert "event=play_session_dropped_age session_id=s_old" in caplog.text


def test_the_ops_answer_on_a_local_transport_and_are_never_a_devices():
    for op in ("play_sessions_pending", "play_sessions_ack"):
        assert op in ops_manifest(transport="stdio")["ops"]  # positive control
        assert op in ops_manifest(transport="socket")["ops"]
        assert op not in ops_manifest(transport="gateway")["ops"]
    _record("s_a", received=NOW)

    (refused,) = _op("play_sessions_ack", {"session_ids": ["s_a"]}, transport="gateway")
    assert refused["error"] == "op_not_available_on_gateway" and _on_disk() == ["s_a"]
    (refused,) = _op("play_sessions_pending", {}, transport="gateway")
    assert refused["error"] == "op_not_available_on_gateway"

    (answer,) = _op("play_sessions_pending", {"id": "p1"})
    assert answer["event"] == "play_sessions_pending_ok" and answer["id"] == "p1"
    assert [row["session_id"] for row in answer["sessions"]] == ["s_a"]
    (bad,) = _op("play_sessions_ack", {"session_ids": "s_a"})
    assert bad["error"] == "invalid_play_sessions_ack" and _on_disk() == ["s_a"]
    (acked,) = _op("play_sessions_ack", {"id": "a1", "session_ids": ["s_a"]})
    assert acked == {"id": "a1", "event": "play_sessions_ack_ok", "ok": True}
    assert _on_disk() == []
