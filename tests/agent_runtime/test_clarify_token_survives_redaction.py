"""RT-DISPATCH-DELIVERY-CLARIFY-TOKEN-MASKED: a clarify token reaches the asking agent whole.

Seen live 2026-11-12 (w1112b-lean): the background-dispatch delivery stored in the asker's thread
read ``clarify_token: clarif...7f38`` — upstream's secret redactor masks a ``…_token`` assignment
of 18+ characters — so the asker's answer on it did not resolve. The token is a lookup key
(``clarify_tickets``: "never a capability secret"). The persona-chat wire (the composed user row
the model is sent, and every native row stored) now shields that shape around the redactor, with
redaction ON; upstream's redactor itself is untouched. A real secret is still masked.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.dispatch_delivery.forge import _clarify_lines
from agent_runtime.persona_chat_continuity import safe_native_message
from agent_runtime.persona_chat_continuity.bounds import bound_composed_user_content
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore

TOKEN = PersonaChatClarifyTicketStore.new_token()


def _delivery_block() -> str:
    clarify = {"question": "Blue or green?", "choices": ["Blue", "Green"], "clarify_token": TOKEN}
    return "\n".join(_clarify_lines(clarify, "QA Agent A"))


def _says_the_token_whole(text: str) -> None:
    assert f"clarify_token: {TOKEN}" in text
    assert f"passing clarify_token={TOKEN}" in text


def test_the_delivery_turn_reaches_the_model_with_the_token_whole():
    _says_the_token_whole(bound_composed_user_content(_delivery_block()).text)


def test_the_delivery_turn_is_stored_with_the_token_whole():
    _says_the_token_whole(safe_native_message({"role": "user", "content": _delivery_block()})["content"])


def test_a_waited_sends_clarify_request_keeps_the_token_on_the_native_wire():
    result = json.dumps({"ok": True, "clarify_request": {"question": "Blue or green?", "clarify_token": TOKEN}})
    row = safe_native_message({"role": "tool", "tool_call_id": "call_1", "content": result})
    assert json.loads(row["content"])["clarify_request"]["clarify_token"] == TOKEN


def test_a_placeholder_shaped_string_already_in_the_text_is_left_alone():
    text = f"clarify_token: {TOKEN} and a literal ⟦00000⟧ ⟦ab120⟧"
    assert bound_composed_user_content(text).text == text


@pytest.mark.parametrize("secret", ["clarify-2f87bf3e7f38deadbeef", "ghp_abcdefghijklmnopqrstuvwxyz0123"])
def test_a_secret_under_a_token_key_is_still_masked(secret):
    assert secret not in bound_composed_user_content(f"clarify_token: {secret}").text
    row = safe_native_message({"role": "tool", "tool_call_id": "c", "content": json.dumps({"auth_token": secret})})
    assert secret not in row["content"]


# ---------------------------------------------------------------------------
# RT-DELIVERED-QUESTION-HIDDEN-IN-CONSOLE — the console's history read draws the question
# ---------------------------------------------------------------------------
# Seen live 2026-11-12 (w1112b-ctt-hm2, real model): the delivery carrying QA Agent A's question
# was drawn "Message hidden by redaction boundary." — the history read's secret check hid the whole
# row for its ``clarify_token: <ticket>`` line (whole, and in the cut form stored before b636d3b44b).


def _history_of(content: str):
    from agent_runtime.persona_chat_history.history_rows import _safe_recent_messages
    from agent_runtime.relay_policy import build_harness_delivery_marker
    from tests.agent_runtime.test_persona_chat_history_curation import FakeSessionDB

    db = FakeSessionDB([{
        "id": "m1", "role": "user", "content": content,
        "finish_reason": build_harness_delivery_marker(
            "dispatch-abc123", True, None, "persona_chat_personainst_qa_a", "QA Agent A"),
        "platform_message_id": "dispatch-delivery-dispatch-abc123",
        "created_at": "2026-11-12T00:00:00Z",
    }])
    rows, _status, _unread = _safe_recent_messages(db, session_id="persona_chat_personainst_base_abc123def456")
    return [row for row in rows if row.get("platform_message_id", row.get("id")) and "text" in row]


@pytest.mark.parametrize("ticket", [TOKEN, "clarif...7f38"], ids=["whole", "cut-before-b636d3b44b"])
def test_delivered_question_is_shown_in_history(ticket):
    """KILLING MUTATION: ``has_text_secret_assignment`` treats a ticket value as a secret
    (``return True`` in place of its ``continue``) -> the row reads "Message hidden by redaction
    boundary", red (run 2026-11-12)."""

    block = _delivery_block().replace(TOKEN, ticket)
    rows = _history_of(block)
    assert len(rows) == 1
    assert rows[0]["redaction_status"] == "safe"
    assert "Blue or green?" in rows[0]["text"] and f"clarify_token: {ticket}" in rows[0]["text"]


@pytest.mark.parametrize("secret_line", [
    "api_key=sk-abcdefghijklmnopqrstuvwx",
    f"clarify_token={TOKEN},password=hunter2hunter2",
], ids=["beside", "glued"])
def test_a_real_secret_in_a_delivered_question_still_hides_it(secret_line):
    rows = _history_of(_delivery_block() + "\n" + secret_line)
    assert len(rows) == 1
    assert rows[0]["redaction_status"] == "redacted"
    assert "Blue or green?" not in rows[0]["text"] and "hunter2" not in rows[0]["text"]
    assert "sk-abc" not in rows[0]["text"]


def test_the_conversation_lane_keeps_the_question_line_and_masks_a_secret_line():
    from agent_runtime.operator_channels.vocabulary import _safe_conversation_text

    text = _safe_conversation_text(_delivery_block() + "\nauth_token: ghp_abcdefghijklmnopqrstuvwxyz0123",
                                   limit=10_000)
    assert f"clarify_token: {TOKEN}" in text and "Blue or green?" in text
    assert "ghp_" not in text and "[redacted line — contained a secret]" in text
