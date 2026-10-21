"""p10-messaging M2: ``TelegramTransport`` against the recorded fake Bot API — never the network."""

from __future__ import annotations

import logging
import threading

import httpx
import pytest

from agent_runtime.messaging import telegram_api
from agent_runtime.messaging.chunks import chunk, utf16_size
from agent_runtime.messaging.telegram_api import Failure, TelegramError, TelegramTransport
from agent_runtime.messaging.transport import Button, CallbackPress, InboundMessage, MessageRef, Transport
from tests.agent_runtime.messaging.fake_bot_api import API_BASE, FakeBotApi

TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
SECRET = TOKEN.split(":", 1)[1]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The real transport refuses: a test that reached past the fake fails loudly."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("a messaging test reached the network")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def api():
    return FakeBotApi(TOKEN)


def _transport(api, token=TOKEN, delays=None):
    record = delays if delays is not None else []
    return TelegramTransport(token, client=api.client(), api_base=API_BASE,
                             wait=lambda seconds: record.append(seconds) or False)


def _receipts(caplog, kind):
    return [r.getMessage() for r in caplog.records
            if r.name == "agent_runtime.work_store.receipts" and f'"kind": "{kind}"' in r.getMessage()]


def test_it_is_a_transport(api):
    assert isinstance(_transport(api), Transport)


def test_offset_advances_past_handled(api):
    """Killing mutation: ``poll_once`` stops writing ``self.offset`` → the second poll re-delivers → red."""
    first = api.push_message("hello")
    second = api.push_message("again", thread_id=9)
    transport, seen = _transport(api), []
    assert transport.poll_once(seen.append) == 2
    assert [u.update_id for u in seen] == [first, second] and transport.offset == second + 1
    assert seen[0] == InboundMessage(first, "-1001", None, "42", "Max", seen[0].message_id, "hello")
    assert seen[1].thread_id == "9"
    assert transport.poll_once(seen.append) == 0 and len(seen) == 2
    assert api.calls[-1] == ("getUpdates", {"timeout": 30, "allowed_updates": ["message", "callback_query"],
                                            "offset": second + 1})


def test_a_raising_handler_or_a_foreign_update_never_wedges_the_chat(api, caplog):
    caplog.set_level(logging.INFO)
    poisoned = api.push_message("boom")
    edited = api.push_raw({"edited_message": {"message_id": 1, "text": "x", "chat": {"id": 1}}})
    press = api.push_press("ap:abc:once")
    transport, seen = _transport(api), []

    def handle(update):
        if update.update_id == poisoned:
            raise RuntimeError("store unavailable")
        seen.append(update)

    transport.poll_once(handle)
    assert transport.offset == press + 1 and edited < press
    assert seen == [CallbackPress(press, f"cb{press}", "-1001", "42", "Max", "7", "ap:abc:once")]
    (failed,) = _receipts(caplog, "messaging.transport.update_failed")
    assert '"error": "RuntimeError"' in failed and str(poisoned) in failed


def test_conflict_backs_off(api, caplog):
    """Killing mutation: ``BACKOFF[Failure.CONFLICT]`` = ``(0.0, 0.0)`` (a 409 retried hot) → red."""
    caplog.set_level(logging.INFO)
    api.fail("getUpdates", 409, times=3)
    api.push_message("after the other poller left")
    delays: list[float] = []
    transport = _transport(api, delays=delays)
    transport.run(lambda update: transport.stop())
    assert delays == [5.0, 10.0, 20.0]
    assert len(_receipts(caplog, "messaging.transport.poll_failed")) == 3


def test_rate_limit_honours_retry_after_and_a_dropped_connection_backs_off(api):
    api.fail("getUpdates", 429, retry_after=7)
    api.drop("getUpdates", times=2)
    api.push_message("hi")
    delays: list[float] = []
    transport = _transport(api, delays=delays)
    transport.run(lambda update: transport.stop())
    assert delays == [7.0, 2.0, 4.0]


def test_a_wrong_token_stops_the_poller_instead_of_retrying(api, caplog):
    caplog.set_level(logging.INFO)
    delays: list[float] = []
    transport = _transport(api, token="987654321:AAWrongTokenWrongTokenWrong", delays=delays)
    transport.run(lambda update: pytest.fail("no update reaches a wrong token"))
    assert delays == [] and api.methods() == ["getUpdates"]
    assert '"reason": "unauthorized"' in _receipts(caplog, "messaging.transport.stopped")[0]


def test_chunks_at_platform_limit(api):
    """Killing mutation: ``send`` posts ``text`` whole (no ``chunk``) → the 4,097-char reply is one call → red."""
    transport = _transport(api)
    result = transport.send("-1001", "a" * 4097, thread="9", reply_to="5")
    assert [len(m["text"]) for m in api.sent] == [4096, 1] and len(result.refs) == 2
    assert api.sent[0]["reply_parameters"]["message_id"] == 5 and "reply_parameters" not in api.sent[1]
    assert {m["message_thread_id"] for m in api.sent} == {9}
    api.sent.clear()
    transport.send("-1001", "\N{GRINNING FACE}" * 2049)  # 4,098 UTF-16 units: Telegram's measure
    assert [utf16_size(m["text"]) for m in api.sent] == [4096, 2]


def test_chunk_cuts_at_the_best_break_in_the_windows_back_half():
    # A paragraph break in the back half beats a later line break; a lone front-half break is a last resort.
    assert chunk("aaaa\nbbbbbbbbbbbbbb\n\ncc dd\nee", 25) == ["aaaa\nbbbbbbbbbbbbbb", "cc dd\nee"]
    text = "para one.\n\nline two\nword " + "x" * 30
    assert chunk(text, 25) == ["para one.\n\nline two", "word", "x" * 25, "x" * 5]
    assert chunk("   ", 10) == [] and chunk("short", 10) == ["short"]
    assert "".join(chunk("ab" * 50, 7)) == "ab" * 50


def test_card_edit_typing_and_answer(api):
    transport = _transport(api)
    ref = transport.send_card("-1001", "Run `rm -rf build`?", [Button("Once", "ap:a1:once"), Button("Deny", "ap:a1:deny")])
    assert api.calls[-1][1]["reply_markup"] == {"inline_keyboard": [[{"text": "Once", "callback_data": "ap:a1:once"}],
                                                                     [{"text": "Deny", "callback_data": "ap:a1:deny"}]]}
    transport.edit(ref, "approved (once) by Max")
    assert api.calls[-1] == ("editMessageText", {"chat_id": "-1001", "message_id": int(ref.message_id),
                                                 "text": "approved (once) by Max", "reply_markup": {"inline_keyboard": []}})
    transport.typing("-1001", thread="9")
    transport.answer_callback("cb1", "not allowed")
    assert api.methods()[-2:] == ["sendChatAction", "answerCallbackQuery"]
    assert api.calls[-1][1] == {"callback_query_id": "cb1", "text": "not allowed"}
    with pytest.raises(ValueError):
        transport.send_card("-1001", "x", [Button("Once", "ap:" + "z" * 64)])
    assert isinstance(ref, MessageRef)


def test_token_redacted_in_receipts(api, caplog):
    """Killing mutation: ``TelegramTransport.__init__`` stops registering the token with ``_REDACTOR`` →
    httpx's own ``HTTP Request: POST …/bot<token>/getMe`` line carries it → red. Every call kind, a
    failure, a dropped connection and a stop are logged in the window read here."""
    caplog.set_level(logging.DEBUG)
    transport = _transport(api)
    transport.get_me()
    transport.send("-1001", "hello")
    api.fail("getUpdates", 409)
    api.drop("getUpdates")
    api.fail("getUpdates", 401)
    transport.run(lambda update: None)
    with pytest.raises(TelegramError) as raised:
        api.fail("sendMessage", 400)
        transport.send("-1001", "x")
    assert raised.value.failure is Failure.REFUSED and SECRET not in str(raised.value)
    messages = [r.getMessage() for r in caplog.records]
    assert any("HTTP Request: POST" in m for m in messages), "httpx's request line was not captured"
    assert any("messaging.transport.stopped" in m for m in messages)
    assert [m for m in messages if SECRET in m] == []


def test_start_and_stop_run_the_poller_on_its_own_thread(api):
    got = threading.Event()
    api.push_message("hi")
    transport = _transport(api)
    transport.start(lambda update: got.set())
    try:
        assert got.wait(10)
    finally:
        transport.stop(timeout=10)
    assert not transport._thread.is_alive()
