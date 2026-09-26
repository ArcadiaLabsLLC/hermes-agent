"""A watcher notification is sent as a reply to the watcher's own message."""

import asyncio

from gateway.run_notifications import GatewayNotificationsMixin


class _Adapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


class _Runner:
    def __init__(self, adapter):
        self.adapter = adapter

    def _build_process_event_source(self, watcher):
        return None

    def _resolve_injection_adapter(self, platform_name, source):
        return self.adapter


def _send(watcher):
    adapter = _Adapter()
    asyncio.run(GatewayNotificationsMixin._send_watcher_message(
        _Runner(adapter), "telegram", "chat-1", None, "process finished", watcher))
    assert len(adapter.sent) == 1
    return adapter.sent[0]


def test_watcher_message_replies_to_the_originating_message():
    chat_id, text, kwargs = _send({"message_id": "m-42", "session_key": "k"})
    assert (chat_id, text) == ("chat-1", "process finished")
    assert kwargs.get("reply_to") == "m-42"


def test_watcher_without_a_message_id_sends_unthreaded():
    """Positive control: no originating message, no reply target."""
    _chat_id, _text, kwargs = _send({"session_key": "k"})
    assert kwargs.get("reply_to") is None
