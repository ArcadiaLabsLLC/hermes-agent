"""A local HTTP stand-in for the Telegram Bot API (audit of RT-MESSAGING-NEXT-APPS-REUSE-UPSTREAM-CONNECTORS).

Unlike ``fake_bot_api.py`` (an ``httpx.MockTransport`` for the fork's own transport), this is a real
socket on 127.0.0.1, because the UPSTREAM adapter talks through python-telegram-bot's own HTTP client and
only takes a ``base_url``. It serves ``/bot<token>/<method>``: ``getMe``, ``getUpdates`` (returns what
:meth:`FakeTelegram.push_message` queued, honouring ``offset``), ``sendMessage`` (records and answers a
message) and answers every other method ``true`` while recording it. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import threading
import time
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

BOT_ID = 1234567890
BOT_USERNAME = "trial_audit_bot"
#: The smallest valid PNG (1x1), served for every file download.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c626001000000"
    "ffff03000006000557bfabd40000000049454e44ae426082")


def _decode(value: str):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _params(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    body = handler.rfile.read(length) if length else b""
    kind = (handler.headers.get("Content-Type") or "").lower()
    if not body:
        return {}
    if "application/json" in kind:
        return json.loads(body.decode("utf-8"))
    if "multipart/form-data" in kind:
        message = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: " + handler.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
        return {part.get_param("name", header="content-disposition"): _decode(part.get_content())
                for part in message.iter_parts()}
    return {key: _decode(values[-1]) for key, values in parse_qs(body.decode("utf-8")).items()}


class FakeTelegram:
    """The server and everything it saw. ``calls`` is every (method, params) in arrival order."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.calls: list[tuple[str, dict]] = []
        self.sent: list[dict] = []
        self._updates: list[dict] = []
        self._next_update = 1000
        self._next_message = 500
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # keep pytest output quiet
                return

            def _answer(self, payload: dict, status: int = 200) -> None:
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):  # noqa: N802 - http.server's name
                prefix = f"/bot{fake.token}/"
                if self.path.endswith(".png"):  # a file download, whatever root the client built for it
                    with fake._lock:
                        fake.calls.append(("<download>", {"path": self.path.replace(fake.token, "<token>")}))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(PNG)))
                    self.end_headers()
                    self.wfile.write(PNG)
                    return
                if not self.path.startswith(prefix):
                    self._answer({"ok": False, "error_code": 401, "description": "Unauthorized"}, 401)
                    return
                method = self.path[len(prefix):].split("?")[0]
                params = _params(self)
                self._answer({"ok": True, "result": fake.handle(method, params)})

            do_GET = do_POST  # noqa: N815

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="fake-telegram", daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/bot"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # ── what the test drives ──

    def push_message(self, text: str, *, user_id: int = 42, first_name: str = "Max", chat_id: int | None = None,
                     chat_type: str = "private", thread_id: int | None = None) -> dict:
        with self._lock:
            update_id, self._next_update = self._next_update, self._next_update + 1
            message_id, self._next_message = self._next_message, self._next_message + 1
            chat = {"id": chat_id if chat_id is not None else user_id, "type": chat_type}
            if chat_type == "private":
                chat["first_name"] = first_name
            else:
                chat["title"] = "Trial group"
                chat["is_forum"] = thread_id is not None
            message = {"message_id": message_id, "date": int(time.time()), "chat": chat, "text": text,
                       "from": {"id": user_id, "is_bot": False, "first_name": first_name}}
            if thread_id is not None:
                message["message_thread_id"] = thread_id
                message["is_topic_message"] = True
            if text.startswith("/"):
                message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
            update = {"update_id": update_id, "message": message}
            self._updates.append(update)
            return update

    def push_press(self, data: str, *, message_id: int, user_id: int = 42, first_name: str = "Max",
                   chat_id: int | None = None) -> dict:
        """An inline-keyboard button press on a message the bot sent."""
        with self._lock:
            update_id, self._next_update = self._next_update, self._next_update + 1
            chat = {"id": chat_id if chat_id is not None else user_id, "type": "private", "first_name": first_name}
            update = {"update_id": update_id, "callback_query": {
                "id": f"cb-{update_id}", "chat_instance": "audit", "data": data,
                "from": {"id": user_id, "is_bot": False, "first_name": first_name},
                "message": {"message_id": message_id, "date": int(time.time()), "chat": chat, "text": "card",
                            "from": {"id": BOT_ID, "is_bot": True, "first_name": "Trial Audit",
                                     "username": BOT_USERNAME}}}}
            self._updates.append(update)
            return update

    def push_photo(self, caption: str = "", *, user_id: int = 42, first_name: str = "Max") -> dict:
        update = self.push_message(caption, user_id=user_id, first_name=first_name)
        message = update["message"]
        message["caption"] = message.pop("text")
        message.pop("entities", None)
        message["photo"] = [{"file_id": "photo-1", "file_unique_id": "u-photo-1", "width": 1, "height": 1,
                             "file_size": len(PNG)}]
        return update

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]

    # ── the Bot API ──

    def handle(self, method: str, params: dict):
        with self._lock:
            self.calls.append((method, params))
        if method == "getMe":
            return {"id": BOT_ID, "is_bot": True, "first_name": "Trial Audit", "username": BOT_USERNAME,
                    "can_join_groups": True, "can_read_all_group_messages": False,
                    "supports_inline_queries": False}
        if method == "getUpdates":
            offset = int(params.get("offset") or 0)
            deadline = time.monotonic() + min(float(params.get("timeout") or 0), 0.2)
            while True:
                with self._lock:
                    self._updates = [u for u in self._updates if u["update_id"] >= offset]
                    ready = list(self._updates)
                if ready or time.monotonic() >= deadline:
                    return ready
                time.sleep(0.02)
        if method == "sendMessage":
            with self._lock:
                message_id, self._next_message = self._next_message, self._next_message + 1
                self.sent.append(dict(params))
            return {"message_id": message_id, "date": int(time.time()), "text": str(params.get("text") or ""),
                    "chat": {"id": int(params.get("chat_id") or 0), "type": "private"},
                    "from": {"id": BOT_ID, "is_bot": True, "first_name": "Trial Audit", "username": BOT_USERNAME}}
        if method == "editMessageText":
            return {"message_id": int(params.get("message_id") or 0), "date": int(time.time()),
                    "text": str(params.get("text") or ""), "chat": {"id": int(params.get("chat_id") or 0), "type": "private"}}
        if method == "getFile":
            return {"file_id": str(params.get("file_id")), "file_unique_id": "u-photo-1", "file_size": len(PNG),
                    "file_path": "photos/photo-1.png"}
        if method in {"getMyCommands", "getChatAdministrators"}:
            return []
        if method == "getWebhookInfo":
            return {"url": "", "has_custom_certificate": False, "pending_update_count": 0}
        return True
