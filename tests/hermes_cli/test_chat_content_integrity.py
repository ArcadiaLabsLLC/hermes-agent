"""Accepted operator text and replies survive the real turn handler and stores."""
import json
from types import SimpleNamespace

import pytest

from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD, perform_chat_turn
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from hermes_cli.harness_parts.persona import chat_turn_message
from tests.hermes_cli.test_mission_chat_budget_payload import (
    _args, _seed, isolate_agent_runtime_root,  # noqa: F401
)


BODY = "  local function calculate()\n\treturn 10 * 8 / 200\nend\n\n" * 520 + "  TAIL\n"
REPLY = "Result\n    aligned detail\n\n" * 1200 + "REPLY TAIL"


def test_real_admission_and_handler_preserve_multiline_input(monkeypatch, capsys, isolate_agent_runtime_root):
    seen = []

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            seen.append((args, kwargs))
            return SimpleNamespace(final_response=REPLY, input_tokens=1, output_tokens=2,
                                   total_tokens=3, latency_ms=4, profile_timing={}, raw={})

    _seed(monkeypatch, Provider)
    requests = []
    outcome = perform_chat_turn(
        {"persona_id": "dev", "turn_request_id": "content-integrity", "message": BODY},
        verb=CHAT_MESSAGE_METHOD, spawn=lambda request_id, argv, turn_id: requests.append(argv),
    )
    assert outcome.refusal is None
    argv = requests[0]
    admitted = argv[argv.index("--message") + 1]
    assert admitted == BODY
    args = _args("content-integrity")
    args.message = admitted
    assert chat_turn_message._cmd_mission_chat_message(args) == 0
    assert seen[0][0][1].startswith(BODY)
    reply = json.loads(capsys.readouterr().out)
    assert reply["reply"] == REPLY
    journal = mission_chat_turn_record(session_id=args.session_id, client_message_id=args.client_message_id)
    assert journal["pending_user_message"] == BODY
    assert journal["stored_reply"] == REPLY


@pytest.mark.parametrize("body", ["x" * 64_001, "\n" * 64_001 + "tail"], ids=["text", "whitespace"])
def test_oversize_is_refused_before_worker_dispatch(body, isolate_agent_runtime_root):
    calls = []
    outcome = perform_chat_turn(
        {"persona_id": "dev", "turn_request_id": "oversize", "message": body},
        verb=CHAT_MESSAGE_METHOD, spawn=lambda request, *rest: calls.append(request),
    )
    assert outcome.refusal is not None
    assert outcome.refusal.data["reason"] == "message_invalid"
    assert not calls


def test_cli_oversize_is_refused_before_execution(monkeypatch, capsys, isolate_agent_runtime_root):
    class Provider:
        def __init__(self, *args, **kwargs):
            pytest.fail("Oversize text reached execution")

    _seed(monkeypatch, Provider)
    args = _args("cli-oversize")
    args.message = "x" * 64_001
    assert chat_turn_message._cmd_mission_chat_message(args) == 2
    refusal = json.loads(capsys.readouterr().out)
    assert refusal["reason"] == "message_invalid"
    assert "64000" in refusal["error"]
