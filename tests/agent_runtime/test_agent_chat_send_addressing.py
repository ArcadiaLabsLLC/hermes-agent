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


def test_an_invented_profile_handle_is_refused_now_not_in_the_background(handled):
    """RT-AGENT-CHAT-SEND-ACCEPTS-AN-AGENT-WITH-NO-PROFILE (seen live 2026-11-15): Base's send to the
    invented ``personainst_profile_charsheet`` answered ``dispatched: true`` and failed later "Hermes
    profile 'charsheet' does not exist". Killing mutation: ``_unreachable_handle`` returns None -> the
    send reaches the handler."""

    for target in ("personainst_profile_charsheet", "@personainst_profile_charsheet"):  # the second, seen live
        data = json.loads(agent_chat_send(persona_id=target, message="hi", wait=False))
        assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona"), target
        assert "'charsheet' does not exist" in data["error"]
        assert "personainst_qa" in [row["handle"] for row in data["addressable"]]
    assert handled == []


def test_a_stored_profile_backed_instance_whose_profile_is_gone_is_refused(handled, monkeypatch):
    """The roster's own rule (``roster_reach.profile_missing``), asked at admission."""
    from agent_runtime import roster_reach
    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
    from agent_runtime.persona_assignments import PersonaInstanceStore

    PersonaInstanceStore().ensure_for_personas(list(ensure_persisted_personas(load_agent_runtime_config())))
    monkeypatch.setattr(roster_reach, "profile_missing", lambda instance: "gone")
    data = json.loads(agent_chat_send(persona_id="personainst_dev", message="hi"))
    assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona")
    assert "'gone' does not exist" in data["error"]
    assert handled == []


def test_an_invented_handle_is_refused_when_the_sender_has_no_teammates(handled, monkeypatch):
    """Seen live 2026-11-15 (w1115e-h4): Base, alone on its roster, still had its send to
    ``personainst_profile_charsheet`` accepted — an empty roster deferred the handle to the handler.
    Killing mutation: defer a handle again when the roster is empty -> it reaches the handler."""
    from tools.agent_chat import addressing

    real = addressing._addressable
    monkeypatch.setattr(addressing, "_addressable", lambda session: (*real(session)[:2], []))
    data = json.loads(agent_chat_send(persona_id="personainst_profile_charsheet", message="hi", wait=False))
    assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona")
    assert "none are addressable" in data["error"]
    assert handled == []
