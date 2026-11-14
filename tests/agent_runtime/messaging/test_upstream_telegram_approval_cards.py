"""AUDIT: the fork's approval cards over the upstream Telegram adapter, end to end over HTTP.

A card is sent, a button on it is pressed, the press reaches the bridge's ``on_press`` as the fork's own
``CallbackPress``, and the card is answered and edited — all through ``TelegramUpstreamAdapterTransport``
on a connected upstream adapter with no ``GatewayRunner``. The card logic itself
(``approvals.ApprovalCards``) is not re-tested here: it only ever sees the ``Transport`` protocol.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent_runtime.messaging.approvals import CALLBACK_PREFIX
from agent_runtime.messaging.transport import Button, CallbackPress, Transport
from agent_runtime.messaging.upstream_adapter_transport import TelegramUpstreamAdapterTransport
from tests.agent_runtime.messaging.fake_bot_api_server import FakeTelegram
from tests.agent_runtime.messaging.test_upstream_telegram_end_to_end import GATE_ENV, TOKEN, _wait


@pytest.fixture
def rig(monkeypatch):
    from gateway.config import PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter

    for name in GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERMES_TELEGRAM_DISABLE_FALLBACK_IPS", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    server = FakeTelegram(TOKEN)
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token=TOKEN, typing_indicator=False,
                                             extra={"base_url": server.base_url}))
    transport = TelegramUpstreamAdapterTransport(adapter, press_prefix=CALLBACK_PREFIX, connect=True)
    assert isinstance(transport, Transport)
    updates = []
    transport.start(updates.append)
    try:
        yield SimpleNamespace(server=server, transport=transport, updates=updates)
    finally:
        transport.stop()
        server.close()


def _presses(rig):
    return [u for u in rig.updates if isinstance(u, CallbackPress)]


def test_a_card_is_sent_pressed_answered_and_edited(rig):
    """Killing mutation: ``_on_press`` does not raise ``ApplicationHandlerStop`` → the adapter's own callback
    handler also answers the press → two ``answerCallbackQuery`` → red."""
    buttons = [Button("Allow once", f"{CALLBACK_PREFIX}:appr-1:once"), Button("Deny", f"{CALLBACK_PREFIX}:appr-1:deny")]
    ref = rig.transport.send_card("42", "Run `ls`?", buttons, None)
    [card] = rig.server.sent
    keyboard = card["reply_markup"]["inline_keyboard"]
    assert [[b["text"], b["callback_data"]] for row in keyboard for b in row] == [
        ["Allow once", f"{CALLBACK_PREFIX}:appr-1:once"], ["Deny", f"{CALLBACK_PREFIX}:appr-1:deny"]]
    assert card["text"] == "Run `ls`?" and "parse_mode" not in card  # the card's text is sent as written

    rig.server.push_press(f"{CALLBACK_PREFIX}:appr-1:once", message_id=int(ref.message_id))
    [press] = _wait(lambda: _presses(rig), what="the press to reach the bridge")
    assert press.data == f"{CALLBACK_PREFIX}:appr-1:once" and press.user_id == "42" and press.chat_id == "42"
    assert press.message_id == ref.message_id and press.user_display == "Max"

    time.sleep(1.0)  # room for the adapter's own handler to answer, if it wrongly saw the press
    assert "answerCallbackQuery" not in rig.server.methods()
    rig.transport.answer_callback(press.callback_id, "Allowed once")
    answers = [p for m, p in rig.server.calls if m == "answerCallbackQuery"]
    assert answers == [{"callback_query_id": press.callback_id, "text": "Allowed once"}]

    rig.transport.edit(ref, "Allowed once by Max", None)
    [edit] = [p for m, p in rig.server.calls if m == "editMessageText"]
    assert str(edit["chat_id"]) == "42" and str(edit["message_id"]) == ref.message_id
    assert edit["text"] == "Allowed once by Max" and not (edit.get("reply_markup") or {}).get("inline_keyboard")


def test_a_press_that_is_not_the_forks_stays_the_adapters(rig):
    """Upstream's own buttons (a stale picker, say) are not swallowed: the adapter acknowledges them itself."""
    rig.server.push_press("mp:some-upstream-picker", message_id=501)
    _wait(lambda: "answerCallbackQuery" in rig.server.methods(), what="the adapter to acknowledge its own press")
    assert _presses(rig) == []
