"""A recorded fake of the Telegram Bot API — an ``httpx.MockTransport`` handler, never the network.

Shapes follow the Bot API's own replies (``{"ok": true, "result": …}`` / ``{"ok": false, "error_code": …,
"description": …, "parameters": {"retry_after": …}}``). The fake keeps the state a test reads back:

* ``calls`` — every ``(method, payload)`` in order (``getUpdates`` included, with its ``offset``);
* ``push_message`` / ``push_press`` / ``push_raw`` — updates queued for ``getUpdates``, served from the
  requested ``offset`` on, as Telegram serves them (an update below the offset is confirmed and gone);
* ``fail(method, status, times=1, retry_after=None)`` — the next ``times`` calls of ``method`` answer
  ``status``; ``drop(method, times)`` raises a connection error instead (no response at all);
* ``sent`` — the messages ``sendMessage`` accepted (a text over 4,096 UTF-16 units is a 400, as live).

A request with any token but ``token`` is a 401, as live.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any

import httpx

API_BASE = "https://api.telegram.test"


class FakeBotApi:
    def __init__(self, token: str) -> None:
        self.token = token
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sent: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self._failures: dict[str, deque] = defaultdict(deque)
        self._next_update = 1000
        self._next_message = 1

    # ── scripting ──

    def push_raw(self, update: dict[str, Any]) -> int:
        update_id = self._next_update
        self._next_update += 1
        self.updates.append({"update_id": update_id, **update})
        return update_id

    def push_message(self, text: str, *, chat_id: int = -1001, user_id: int = 42, thread_id: int | None = None,
                     first_name: str = "Max") -> int:
        message: dict[str, Any] = {"message_id": self._take_message_id(), "date": 0, "text": text,
                                   "chat": {"id": chat_id, "type": "supergroup"},
                                   "from": {"id": user_id, "is_bot": False, "first_name": first_name}}
        if thread_id is not None:
            message["message_thread_id"] = thread_id
        return self.push_raw({"message": message})

    def push_press(self, data: str, *, chat_id: int = -1001, user_id: int = 42, message_id: int = 7) -> int:
        return self.push_raw({"callback_query": {
            "id": f"cb{self._next_update}", "data": data, "from": {"id": user_id, "is_bot": False, "first_name": "Max"},
            "message": {"message_id": message_id, "date": 0, "chat": {"id": chat_id, "type": "private"}}}})

    def fail(self, method: str, status: int, times: int = 1, retry_after: int | None = None) -> None:
        self._failures[method].extend([(status, retry_after)] * times)

    def drop(self, method: str, times: int = 1) -> None:
        self._failures[method].extend([("drop", None)] * times)

    def methods(self) -> list[str]:
        return [method for method, _payload in self.calls]

    # ── the wire ──

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        prefix, _, method = request.url.path.lstrip("/").partition("/")
        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if prefix != f"bot{self.token}":
            return self._error(401, "Unauthorized")
        if self._failures[method]:
            status, retry_after = self._failures[method].popleft()
            if status == "drop":
                raise httpx.ConnectError("connection refused", request=request)
            return self._error(status, "scripted failure", retry_after)
        return getattr(self, "_" + method)(payload)

    @staticmethod
    def _ok(result: Any) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": result})

    @staticmethod
    def _error(status: int, description: str, retry_after: int | None = None) -> httpx.Response:
        body: dict[str, Any] = {"ok": False, "error_code": status, "description": description}
        if retry_after is not None:
            body["parameters"] = {"retry_after": retry_after}
        return httpx.Response(status, json=body)

    def _take_message_id(self) -> int:
        self._next_message += 1
        return self._next_message

    def _getMe(self, _payload):
        return self._ok({"id": int(self.token.split(":")[0]), "is_bot": True, "first_name": "Hermes",
                         "username": "hermes_test_bot"})

    def _getUpdates(self, payload):
        offset = int(payload.get("offset") or 0)
        self.updates = [u for u in self.updates if u["update_id"] >= offset]
        return self._ok(list(self.updates))

    def _sendMessage(self, payload):
        if len(payload["text"].encode("utf-16-le")) // 2 > 4096:
            return self._error(400, "Bad Request: message is too long")
        message = {"message_id": self._take_message_id(), "date": 0, "text": payload["text"],
                   "chat": {"id": int(payload["chat_id"]), "type": "private"}}
        self.sent.append(payload)
        return self._ok(message)

    def _editMessageText(self, payload):
        return self._ok({"message_id": payload["message_id"], "date": 0, "text": payload["text"],
                         "chat": {"id": int(payload["chat_id"]), "type": "private"}})

    def _sendChatAction(self, _payload):
        return self._ok(True)

    def _answerCallbackQuery(self, _payload):
        return self._ok(True)
