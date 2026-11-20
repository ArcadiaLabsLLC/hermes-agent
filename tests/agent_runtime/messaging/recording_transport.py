"""A recording in-memory ``Transport`` for the bridge and approval-card tests — never a platform, never the network.

The bridge and the cards talk to :class:`~agent_runtime.messaging.transport.Transport` only, so their tests
need no Bot API: this fake queues updates (``push_message`` / ``push_press``), hands them to a handler on
``poll_once`` and records every outbound call as ``(method, payload)`` in ``calls``, named and shaped like the
Telegram Bot API call it stands for (``sendMessage``, ``editMessageText``, ``sendChatAction``,
``answerCallbackQuery``) so an assertion reads like the platform. ``sent`` is every ``sendMessage`` payload.
One ``send`` is one record: splitting a long reply is the platform adapter's job, pinned against the local Bot
API stand-in in ``test_upstream_telegram_end_to_end.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_runtime.messaging.transport import (Button, CallbackPress, InboundMessage, MessageRef, OnUpdate,
                                               SendResult, Update)


def _keyboard(buttons: Sequence[Button] | None) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": b.label, "callback_data": b.data}] for b in buttons or ()]}


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sent: list[dict[str, Any]] = []
        self.updates: list[Update] = []
        self._next_update = 1000
        self._next_message = 1

    # ── scripting ──

    def _take_update_id(self) -> int:
        self._next_update += 1
        return self._next_update - 1

    def _take_message_id(self) -> int:
        self._next_message += 1
        return self._next_message

    def push_message(self, text: str, *, chat_id: int = -1001, user_id: int = 42, thread_id: int | None = None,
                     first_name: str = "Max") -> int:
        update_id = self._take_update_id()
        self.updates.append(InboundMessage(
            update_id=update_id, chat_id=str(chat_id), thread_id=None if thread_id is None else str(thread_id),
            user_id=str(user_id), user_display=first_name, message_id=str(self._take_message_id()), text=text))
        return update_id

    def push_press(self, data: str, *, chat_id: int = -1001, user_id: int = 42, message_id: int = 7) -> int:
        update_id = self._take_update_id()
        self.updates.append(CallbackPress(
            update_id=update_id, callback_id=f"cb{update_id}", chat_id=str(chat_id), user_id=str(user_id),
            user_display="Max", message_id=str(message_id), data=data))
        return update_id

    def poll_once(self, on_update: OnUpdate) -> int:
        """Hand every queued update to ``on_update``, in order; returns how many there were."""
        batch, self.updates = self.updates, []
        for update in batch:
            on_update(update)
        return len(batch)

    def methods(self) -> list[str]:
        return [method for method, _payload in self.calls]

    # ── the Transport ──

    def start(self, on_update: OnUpdate) -> None:
        self.calls.append(("start", {}))

    def stop(self) -> None:
        self.calls.append(("stop", {}))

    def _record_send(self, payload: dict[str, Any]) -> MessageRef:
        self.calls.append(("sendMessage", payload))
        self.sent.append(payload)
        return MessageRef(payload["chat_id"], str(self._take_message_id()))

    def send(self, chat: str, text: str, thread: str | None = None, reply_to: str | None = None) -> SendResult:
        payload: dict[str, Any] = {"chat_id": chat, "text": text}
        if thread is not None:
            payload["message_thread_id"] = int(thread)
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": int(reply_to)}
        return SendResult((self._record_send(payload),))

    def send_card(self, chat: str, text: str, buttons: Sequence[Button], thread: str | None = None) -> MessageRef:
        payload: dict[str, Any] = {"chat_id": chat, "text": text, "reply_markup": _keyboard(buttons)}
        if thread is not None:
            payload["message_thread_id"] = int(thread)
        return self._record_send(payload)

    def edit(self, ref: MessageRef, text: str, buttons: Sequence[Button] | None = None) -> None:
        self.calls.append(("editMessageText", {"chat_id": ref.chat_id, "message_id": int(ref.message_id),
                                               "text": text, "reply_markup": _keyboard(buttons)}))

    def typing(self, chat: str, thread: str | None = None) -> None:
        self.calls.append(("sendChatAction", {"chat_id": chat, "action": "typing"}))

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.calls.append(("answerCallbackQuery", {"callback_query_id": callback_id, **({"text": text} if text else {})}))
