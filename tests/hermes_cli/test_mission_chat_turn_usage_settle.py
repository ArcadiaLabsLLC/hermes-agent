"""The settle point persists a turn's provider tokens, and the audit verb reads them back
(``RT-TURN-RECORD-USAGE``, ``RT-TURN-AUDIT-ENTRY``).

Drives the real ``mission-chat message`` handler over the turn-phases fixture; the durable
record and the ``mission-chat audit`` read of it are the subjects.

Killing mutations (recorded in the landing commit):
* drop the ``provider_usage`` admission from ``mission_chat_turns.records._safe_journal_metadata``
  -> the block is absent from the record;
* drop the ``provider_usage`` line from ``chat_turn_commit/settle.py``'s projected metadata
  -> the block is absent from the record.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from hermes_cli.harness_parts.persona import chat_tickets_commands, chat_turn_message

from tests.hermes_cli.test_mission_chat_turn_phases import (  # type: ignore
    _SESSION_ID,
    _args,
    _record_on_disk,
    isolate_agent_runtime_root,  # (re-exported fixture)
)
from tests.hermes_cli.test_mission_chat_budget_payload import _seed  # type: ignore

_LEDGER = [
    {"call_index": 1, "prompt_tokens": 900, "input_tokens": 100, "output_tokens": 20,
     "cache_read_tokens": 800, "cache_write_tokens": 0, "reasoning_tokens": 0},
    {"call_index": 2, "prompt_tokens": 950, "input_tokens": 50, "output_tokens": 30,
     "cache_read_tokens": 900, "cache_write_tokens": 0, "reasoning_tokens": 0},
]


def _provider():
    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            return SimpleNamespace(
                final_response="done", provider="anthropic", model="claude-test", api_calls=2,
                input_tokens=150, output_tokens=50, total_tokens=1900, cache_read_tokens=1700,
                cache_write_tokens=0, reasoning_tokens=0, usage_ledger=list(_LEDGER),
                latency_ms=4, profile_timing={}, raw={}, turn_outcome=None,
            )

    return _Provider


def test_settle_persists_provider_usage_and_the_audit_reads_it(
    monkeypatch, capsys, isolate_agent_runtime_root,
):
    _seed(monkeypatch, _provider())
    code = chat_turn_message._cmd_mission_chat_message(_args("usage_ok", stream=False))
    assert code == 0, capsys.readouterr().out
    capsys.readouterr()

    usage = _record_on_disk(isolate_agent_runtime_root, "usage_ok")["provider_usage"]
    assert usage["model"] == "claude-test" and usage["provider"] == "anthropic"
    assert (usage["api_calls"], usage["input_tokens"], usage["output_tokens"]) == (2, 150, 50)
    assert usage["cache_read_tokens"] == 1700
    assert [call["prompt_tokens"] for call in usage["calls"]] == [900, 950]

    args = SimpleNamespace(persona_instance_id=None, session_id=_SESSION_ID, turn_id=None, limit=5, json=True)
    assert chat_tickets_commands._cmd_mission_chat_audit(args) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["ok"] is True and audit["namespace"]["kind"] == "base"
    [turn] = [row for row in audit["turns"] if row["client_message_id"] == "usage_ok"]
    assert turn["usage"]["calls"] == usage["calls"]
    assert turn["cost"] is not None and "status" in turn["cost"]
