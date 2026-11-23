"""A chat turn's durable record keeps where the turn ran (RT-FU-A-CHAT-TURNS-RECORD-KEEPS-WHERE-THE-TURN-RAN).

``persona_runtime`` puts the turn's ``MissionChatWorkdir.receipt()`` on ``result.raw``; the settle's native
commit carries it onto the turn record under ``mission_chat_workdir``, bounded by
``mission_chat_turns.records.safe_turn_workdir``. The receipt names an absolute local path, so it rides the
DISK record only: never the terminal frame, never a history row a Look or Run-chats device reads.

Driven through the real handler (``_cmd_mission_chat_message``) with a fake provider; the record is read off
disk. Killing mutations (reds seen 2026-11-22, lane w1122d-hmworkdir):

* M1 drop ``**self._workdir_block()`` from ``_commit_native``'s metadata
  -> test_the_turns_record_keeps_where_it_ran, test_the_read_projection_keeps_it_for_the_console
* M2 drop the ``safe_turn_workdir`` arm from ``_safe_journal_metadata``
  -> test_the_turns_record_keeps_where_it_ran, test_the_read_projection_keeps_it_for_the_console
* M3 ``safe_turn_workdir`` admits any ``source``
  -> test_a_receipt_naming_no_known_rung_is_not_kept
* M4 ``_safe_workdir_issue`` returns ``dict(row)``
  -> test_an_issue_keeps_its_typed_fields_and_drops_its_prose
* M5 ``_success_payload`` spreads ``**self._workdir_block()`` into the terminal frame
  -> test_the_terminal_frame_never_names_the_workdir
* M6 ``_workdir_block`` answers a block when the runner reported none
  (``{KEY: receipt or {"source": "process_cwd"}}``)
  -> test_a_turn_whose_runner_reported_no_receipt_records_no_block
* M7 ``curation`` copies the record's ``mission_chat_workdir`` onto the history row
  -> test_no_history_row_names_the_workdir
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime.mission_chat_turns.records import _safe_record, safe_turn_workdir
from agent_runtime.mission_chat_workdir import MissionChatWorkdir, MissionChatWorkdirIssue
from agent_runtime.mission_chat_workdir_words import (
    TURN_WORKDIR_KEY,
    WORKDIR_REASON_MISSING,
    WORKDIR_SOURCE_PERSONA_CONFIG,
    WORKDIR_SOURCE_USER_HOME,
)
from hermes_cli.harness_parts.persona import chat_turn_message

from tests.hermes_cli.test_mission_chat_budget_payload import (  # type: ignore
    _SESSION_ID,
    _TranscriptDB,
    _seed,
    isolate_agent_runtime_root,  # noqa: F401 - re-exported fixture
)
from tests.hermes_cli.test_mission_chat_turn_phases import _args, _record_on_disk  # type: ignore


def _receipt(home: str) -> dict:
    issue = MissionChatWorkdirIssue(
        requested="/nowhere/repo", source=WORKDIR_SOURCE_PERSONA_CONFIG, reason=WORKDIR_REASON_MISSING,
        config_key="agent_runtime.personas.dev.workdir", fell_back_to=WORKDIR_SOURCE_USER_HOME,
    )
    return MissionChatWorkdir(path=home, source=WORKDIR_SOURCE_USER_HOME, issues=(issue,)).receipt()


def _provider(raw: dict):
    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            ready = kwargs.get("agent_ready_callback")
            if ready is not None:
                ready(SimpleNamespace(id="fake-agent"))
            return SimpleNamespace(
                final_response="hello world", input_tokens=1, output_tokens=2, total_tokens=3,
                latency_ms=4, profile_timing={}, raw=dict(raw),
            )

    return _Provider


def _drive(monkeypatch, capsys, raw: dict, turn_id: str):
    _seed(monkeypatch, _provider(raw))
    db = _TranscriptDB()
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", lambda: db)
    assert chat_turn_message._cmd_mission_chat_message(_args(turn_id, stream=False)) == 0
    return capsys.readouterr().out, db


@pytest.fixture
def grounded_turn(monkeypatch, capsys, isolate_agent_runtime_root, tmp_path):  # noqa: F811
    home = str(tmp_path / "operator-home")
    out, db = _drive(monkeypatch, capsys, {TURN_WORKDIR_KEY: _receipt(home)}, "workdir_turn")
    return SimpleNamespace(home=home, frame=out, db=db,
                           record=_record_on_disk(isolate_agent_runtime_root, "workdir_turn"))


def test_the_turns_record_keeps_where_it_ran(grounded_turn):
    block = grounded_turn.record[TURN_WORKDIR_KEY]
    assert block["workdir"] == grounded_turn.home
    assert block["source"] == WORKDIR_SOURCE_USER_HOME
    assert block["grounded"] is True
    assert [(row["code"], row["source"], row["reason"], row["workdir"]) for row in block["issues"]] == [
        ("mission_chat_workdir_unresolved", WORKDIR_SOURCE_PERSONA_CONFIG, WORKDIR_REASON_MISSING, "/nowhere/repo"),
    ]


def test_the_read_projection_keeps_it_for_the_console(grounded_turn):
    """The console's own reads (``_safe_record``) see the receipt the disk holds."""

    safe = _safe_record(grounded_turn.record, client_message_id="workdir_turn")
    assert safe[TURN_WORKDIR_KEY]["workdir"] == grounded_turn.home


def test_the_terminal_frame_never_names_the_workdir(grounded_turn):
    frame = json.loads(grounded_turn.frame)
    assert frame["ok"] is True and frame["reply"] == "hello world"
    assert TURN_WORKDIR_KEY not in grounded_turn.frame
    assert grounded_turn.home not in grounded_turn.frame


def test_no_history_row_names_the_workdir(grounded_turn):
    from agent_runtime.persona_chat_history import persona_chat_session_messages

    # The native rows the real runtime writes (the fake provider writes none), keyed to the turn's record.
    grounded_turn.db.create_session(_SESSION_ID, "agent_runtime_persona_chat")
    grounded_turn.db.append_message(_SESSION_ID, "user", "please answer", platform_message_id="workdir_turn")
    grounded_turn.db.append_message(_SESSION_ID, "assistant", "hello world",
                                    platform_message_id="workdir_turn:assistant:1")
    page =persona_chat_session_messages(session_id=_SESSION_ID, session_db=grounded_turn.db)
    text = json.dumps(page, default=str)
    assert "hello world" in text, "the page carries the turn's reply row (else this test proves nothing)"
    assert TURN_WORKDIR_KEY not in text
    assert grounded_turn.home not in text


def test_a_turn_whose_runner_reported_no_receipt_records_no_block(
    monkeypatch, capsys, isolate_agent_runtime_root,  # noqa: F811
):
    _drive(monkeypatch, capsys, {}, "no_workdir_turn")
    record = _record_on_disk(isolate_agent_runtime_root, "no_workdir_turn")
    assert record["stored_reply"] == "hello world"
    assert TURN_WORKDIR_KEY not in record


def test_a_receipt_naming_no_known_rung_is_not_kept():
    assert safe_turn_workdir({"workdir": "/x", "source": "somewhere_else", "grounded": True, "issues": []}) is None
    assert safe_turn_workdir("not a receipt") is None


def test_an_issue_keeps_its_typed_fields_and_drops_its_prose():
    receipt = _receipt("/home/op")
    receipt["issues"].append({"code": "some_other_code", "source": WORKDIR_SOURCE_PERSONA_CONFIG,
                              "reason": WORKDIR_REASON_MISSING})
    receipt["issues"].append({**receipt["issues"][0], "reason": "free text the resolver never says"})
    block = safe_turn_workdir(receipt)
    assert len(block["issues"]) == 1
    (row,) = block["issues"]
    assert set(row) == {"code", "source", "reason", "workdir", "configured_via", "entry_point_lane"}
    assert "summary" not in row and "fix_hint" not in row
