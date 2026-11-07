"""``agent_chat_send`` checks a local target BEFORE accepting the send (``tools/agent_chat/addressing.py``).

RT-AGENT-CHAT-SEND-DISPLAY-NAME-ACCEPTED (found live 2026-11-06, Eternia w1106b-live-a): a display name
("QA Agent A") passed, dispatched, and only the background delivery refused ``unknown persona QA_Agent_A``.
"""

import json

import pytest
from hermes_cli.harness_parts.persona import chat_turn_message

from tools.agent_chat_tool import agent_chat_send

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


@pytest.fixture
def handled(monkeypatch):
    """The CLI lane's handler, faked: records the target it was handed."""

    seen: list[tuple[str, str | None]] = []

    def fake_handler(args):
        seen.append((args.persona_id, args.persona_instance_id))
        args.payload_sink({"ok": True, "reply": "ack"})
        return 0

    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", fake_handler)
    return seen


def test_a_display_name_is_resolved_to_its_instance_handle(handled):
    """Killing mutation: ``local_target`` returns None without resolving -> the handler gets "QA Agent"."""

    data = json.loads(agent_chat_send(persona_id="  qa   AGENT ", message="hi"))
    assert data["ok"] is True
    assert handled == [("personainst_qa", "personainst_qa")]


def test_an_unknown_name_is_refused_now_listing_the_addressable_handles(handled):
    """Killing mutation: drop the refusal (return ``persona_id, None``) -> it reaches the handler."""

    data = json.loads(agent_chat_send(persona_id="QA Agent A", message="hi", wait=False))
    assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona")
    handles = [row["handle"] for row in data["addressable"]]
    assert "personainst_qa" in handles and "personainst_qa" in data["error"]
    assert handled == []


def test_a_persona_id_and_an_instance_handle_pass_as_given(handled):
    assert json.loads(agent_chat_send(persona_id="dev", message="hi"))["ok"] is True
    assert json.loads(agent_chat_send(persona_id="personainst_dev", message="hi"))["ok"] is True
    assert handled == [("dev", None), ("personainst_dev", "personainst_dev")]
