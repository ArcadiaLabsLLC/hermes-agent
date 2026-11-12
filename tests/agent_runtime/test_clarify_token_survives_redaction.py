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
