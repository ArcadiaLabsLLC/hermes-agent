"""D1.08 S1 — one refusing params reader, three lanes, three envelopes.

``agent_runtime.param_readers`` owns the validation; each lane injects the
exception it has always raised, so its error envelope does not move. The lane
halves below pin that: realm's ``_Refused("invalid_request")`` (-32602 through
``handle_request``), chat-turn's ``ChatTurnInvalid("<key>_invalid")`` and the
console operations' ``ValueError(key)``.
"""

from __future__ import annotations

import pytest

from agent_runtime import serve_rpc
from agent_runtime.chat_turn import ChatTurnInvalid, normalize_chat_message
from agent_runtime.param_readers import read_flag, read_strings, read_text
from agent_runtime.serve_rpc import console_operations, realm
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS


class _Refusal(Exception):
    def __init__(self, key, sentence):
        super().__init__(sentence)
        self.key = key


# ── the readers ──────────────────────────────────────────────────────────────


def test_read_text_returns_stripped_none_or_blank_and_refuses_through_the_injected_constructor():
    assert read_text({"k": "  v "}, "k", refuse=_Refusal) == "v"
    assert read_text({}, "k", refuse=_Refusal) is None
    assert read_text({"k": None}, "k", refuse=_Refusal) is None
    assert read_text({"k": "   "}, "k", refuse=_Refusal) == ""
    with pytest.raises(_Refusal) as raised:
        read_text({"k": 3}, "k", refuse=_Refusal)
    assert (raised.value.key, str(raised.value)) == ("k", "k must be a string when sent")
    with pytest.raises(_Refusal, match="k must be 3 characters or fewer"):
        read_text({"k": "abcd"}, "k", refuse=_Refusal, limit=3)


def test_required_and_empty_ok_false_refuse_absent_and_blank():
    """Killing mutation: drop ``strict and not raw.strip()`` → a blank required or
    non-empty value passes, and this test plus the realm/console halves go red."""

    for params in ({}, {"k": ""}, {"k": "  "}):
        with pytest.raises(_Refusal, match="k must be a non-empty string"):
            read_text(params, "k", refuse=_Refusal, required=True)
    with pytest.raises(_Refusal, match="k must be a non-empty string"):
        read_text({"k": " "}, "k", refuse=_Refusal, empty_ok=False)
    assert read_text({}, "k", refuse=_Refusal, empty_ok=False) is None


def test_read_flag_and_read_strings():
    assert read_flag({}, "f", refuse=_Refusal) is False
    assert read_flag({"f": None}, "f", refuse=_Refusal, default=True) is True
    assert read_flag({"f": True}, "f", refuse=_Refusal) is True
    with pytest.raises(_Refusal, match="f must be a boolean when sent"):
        read_flag({"f": "yes"}, "f", refuse=_Refusal)
    assert read_strings({}, "s", refuse=_Refusal) is None
    assert read_strings({"s": ["a", "b"]}, "s", refuse=_Refusal) == ["a", "b"]
    for bad in ("a", ["a", 1]):
        with pytest.raises(_Refusal, match="s must be a list of strings"):
            read_strings({"s": bad}, "s", refuse=_Refusal)


# ── each lane keeps its envelope ─────────────────────────────────────────────


def _rpc(method, params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "p1", "method": method, "params": params})


def test_realm_refuses_invalid_request_with_its_sentence():
    missing = _rpc("runtime.realm.sync.status", {})["error"]
    assert (missing["code"], missing["data"]["reason"]) == (ERR_INVALID_PARAMS, "invalid_request")
    assert missing["message"] == "realm_id must be a non-empty string"
    blank = _rpc("runtime.realm.sync.status", {"realm_id": "  "})["error"]
    assert blank["data"]["reason"] == "invalid_request"
    with pytest.raises(realm._Refused) as raised:
        realm._param_text({"to": ""}, "to")  # optional, but a present value must be non-blank here
    assert raised.value.reason == "invalid_request"
    with pytest.raises(realm._Refused, match="dry_run must be a boolean"):
        realm._param_flag({"dry_run": "yes"}, "dry_run")
    with pytest.raises(realm._Refused, match="items must be a list of strings"):
        realm._param_strings({"items": "a"}, "items")


@pytest.mark.parametrize(
    "params, reason, message",
    [
        ({"title": 5}, "title_invalid", "invalid params: title must be a string when sent"),
        ({"title": "x" * 201}, "title_invalid", "invalid params: title must be 200 characters or fewer"),
        ({"new_session": "yes"}, "new_session_invalid", "invalid params: new_session must be a boolean when sent"),
        ({"persona_id": "  "}, "persona_id_required", "invalid params: persona_id must be a non-empty string"),
    ],
)
def test_chat_turn_refuses_with_its_reason_and_sentence(params, reason, message):
    base = {"turn_request_id": "t-1", "persona_id": "dev", "message": "hi"}
    with pytest.raises(ChatTurnInvalid) as raised:
        normalize_chat_message({**base, **params})
    assert (raised.value.reason, raised.value.message) == (reason, message)


def test_chat_turn_blank_optional_text_is_still_empty_not_refused():
    request = normalize_chat_message({"turn_request_id": "t-2", "persona_id": "dev", "message": "hi", "title": "  "})
    assert "--title" not in request.argv


def test_console_operations_raise_value_error_naming_the_key():
    with pytest.raises(ValueError, match="^model$"):
        console_operations._console_text({"model": 3}, "model")
    with pytest.raises(ValueError, match="^persona_id$"):
        console_operations._console_text({"persona_id": " "}, "persona_id", required=True)
    console_operations._console_text({"reason": ""}, "reason")  # optional blank: accepted, as before
    reply = console_operations.persona_model("c1", {"persona_id": 7})
    assert reply["error"]["code"] == ERR_INVALID_PARAMS
    assert reply["error"]["data"] == {"reason": "invalid_parameters", "field": "persona_id"}
