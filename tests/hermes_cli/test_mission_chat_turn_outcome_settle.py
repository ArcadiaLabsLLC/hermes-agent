"""The settle point persists what a turn left behind on its terminal record
(``RT-TURN-LEFT-BEHIND-RECORD`` S3, plan ``planned/p10-turn-2026-10-19.md`` §1.5 test 6).

Drives the real ``mission-chat message`` handler over the turn-phases fixture; the
durable record is the subject. Killing mutation: remove the ``turn_outcome`` line
from ``mission_chat_turns.records._safe_journal_metadata`` -> the block is absent.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from hermes_cli.harness_parts.persona import chat_turn_message

from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from tests.hermes_cli.test_mission_chat_turn_phases import (  # type: ignore
    _SESSION_ID,
    _args,
    _record_on_disk,
    isolate_agent_runtime_root,  # noqa: F401  (re-exported fixture)
)
from tests.hermes_cli.test_mission_chat_budget_payload import _seed  # type: ignore

_BLOCK = {
    "schema": 1,
    "tests": [{"command": "pytest -q", "exit_code": 1, "verdict": "failed"}],
    "commits": [{"command": "git commit -m x", "sha": "abc1234", "pushed": True}],
    "files": [{"path": "a.py", "op": "patch"}],
    "truncated": False,
}


def _provider(turn_outcome):
    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            return SimpleNamespace(
                final_response="done", input_tokens=1, output_tokens=2, total_tokens=3,
                latency_ms=4, profile_timing={}, raw={}, turn_outcome=turn_outcome,
            )

    return _Provider


def _settle(monkeypatch, capsys, root, turn_id, turn_outcome):
    _seed(monkeypatch, _provider(turn_outcome))
    code = chat_turn_message._cmd_mission_chat_message(_args(turn_id, stream=False))
    out = capsys.readouterr().out
    assert code == 0, out
    return out, _record_on_disk(root, turn_id)


def test_settle_persists_the_block_and_logs_the_receipt(
    monkeypatch, capsys, caplog, isolate_agent_runtime_root,  # noqa: F811
):
    caplog.set_level(logging.INFO)
    out, record = _settle(monkeypatch, capsys, isolate_agent_runtime_root, "outcome_ok", dict(_BLOCK))
    assert record["turn_outcome"] == _BLOCK
    read = mission_chat_turn_record(session_id=_SESSION_ID, client_message_id="outcome_ok")
    assert read["turn_outcome"] == _BLOCK
    assert "turn_outcome" not in out  # a log receipt, never a key on the terminal frame
    receipts = [r.getMessage() for r in caplog.records if r.getMessage().startswith("turn_outcome ")]
    assert len(receipts) == 1
    assert receipts[0].endswith("tests=1 failed=1 commits=1 pushed=1 files=1 truncated=False")


def test_a_turn_that_folded_nothing_has_no_block(
    monkeypatch, capsys, caplog, isolate_agent_runtime_root,  # noqa: F811
):
    caplog.set_level(logging.INFO)
    _out, record = _settle(monkeypatch, capsys, isolate_agent_runtime_root, "outcome_none", None)
    assert "turn_outcome" not in record
    assert not [r for r in caplog.records if r.getMessage().startswith("turn_outcome ")]
