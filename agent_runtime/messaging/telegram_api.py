"""``TelegramTransport`` — the Bot API over ``httpx`` long polling (p10-messaging §2.2, §3 M2).

Six calls: ``getMe``, ``getUpdates``, ``sendMessage``, ``editMessageText``, ``sendChatAction``,
``answerCallbackQuery``. No ``python-telegram-bot``: one module, one daemon thread, no framework loop.
One poller per token is the serve's own root lock (one serve per root); a second poller anywhere is
Telegram's 409, which backs off rather than fights.

**Polling.** ``getUpdates(offset, timeout=30)``; the offset moves past every update the batch returned
once its handler has run (a handler that raises is logged by type and passed — the bridge is idempotent
by ``update_id`` and a poisoned update must not wedge the chat). Updates that are neither a text
message nor a button press advance the offset and reach nobody.

**Failures** are a table, :data:`BACKOFF`: ``Failure`` → (first delay, cap); the delay doubles per
consecutive failure, a 429's ``retry_after`` wins when it is longer, and ``UNAUTHORIZED`` (a revoked or
wrong token) stops the poller with a receipt instead of retrying forever.

**The token is in every URL** (``/bot<token>/<method>``), so it is kept off the log three ways: the
``httpx`` request log line passes :class:`_Redact` (installed on the ``httpx`` logger at construction),
a :class:`TelegramError` names the method and status only, and a network error is logged by its type.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any

import httpx

from ..work_store.receipts import emit
from .chunks import chunk, utf16_size
from .transport import Button, CallbackPress, InboundMessage, MessageRef, OnUpdate, SendResult, Update

__layer__ = "lanes"
__all__ = ["API_BASE", "BACKOFF", "MESSAGE_LIMIT", "Failure", "TelegramError", "TelegramTransport", "parse_update"]

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
MESSAGE_LIMIT = 4096
CALLBACK_DATA_LIMIT = 64
POLL_TIMEOUT_S = 30
REDACTED = "<redacted>"


class Failure(StrEnum):
    CONFLICT = "conflict"            # 409: another getUpdates poller holds this token
    RATE_LIMITED = "rate_limited"    # 429
    SERVER = "server"                # 5xx
    NETWORK = "network"              # no response at all
    UNAUTHORIZED = "unauthorized"    # 401 / 404: the token is wrong or revoked — fatal
    REFUSED = "refused"              # any other 4xx: this request was wrong, retrying it changes nothing


#: Failure -> (first delay s, cap s), doubled per consecutive failure. ``None``: stop polling.
BACKOFF: dict[Failure, tuple[float, float] | None] = {
    Failure.CONFLICT: (5.0, 60.0),
    Failure.RATE_LIMITED: (1.0, 60.0),
    Failure.SERVER: (1.0, 30.0),
    Failure.NETWORK: (1.0, 30.0),
    Failure.REFUSED: (5.0, 60.0),
    Failure.UNAUTHORIZED: None,
}


_STATUS_FAILURES: dict[int, Failure] = {
    401: Failure.UNAUTHORIZED, 404: Failure.UNAUTHORIZED, 409: Failure.CONFLICT, 429: Failure.RATE_LIMITED,
}


def _failure_of(status: int) -> Failure:
    return _STATUS_FAILURES.get(status) or (Failure.SERVER if status >= 500 else Failure.REFUSED)


class TelegramError(Exception):
    """A failed Bot API call. Its text is the method, the status and the failure — never a URL or body."""

    def __init__(self, method: str, failure: Failure, status: int = 0, retry_after: float | None = None) -> None:
        super().__init__(f"telegram {method}: {failure.value} ({status})")
        self.method, self.failure, self.status, self.retry_after = method, failure, status, retry_after


def backoff_delay(error: TelegramError, streak: int) -> float | None:
    """Seconds to wait before the next poll after ``streak`` consecutive failures (1-based); None stops."""
    row = BACKOFF[error.failure]
    if row is None:
        return None
    first, cap = row
    delay = min(cap, first * (2 ** max(0, streak - 1)))
    return max(delay, min(cap, error.retry_after or 0.0))


class _Redact(logging.Filter):
    """Rewrites any record carrying a registered token. One instance on the ``httpx`` logger."""

    def __init__(self) -> None:
        super().__init__()
        self.secrets: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            message = record.getMessage()
            redacted = message
            for secret in self.secrets:
                redacted = redacted.replace(secret, REDACTED)
            if redacted != message:
                record.msg, record.args = redacted, None
        return True


_REDACTOR = _Redact()
logging.getLogger("httpx").addFilter(_REDACTOR)


def _text_id(value: Any) -> str | None:
    return None if value is None else str(value)


def _display(user: Mapping[str, Any]) -> str:
    name = " ".join(str(user.get(k) or "").strip() for k in ("first_name", "last_name")).strip()
    return name or str(user.get("username") or user.get("id") or "")


def parse_update(raw: Mapping[str, Any]) -> Update | None:
    """A Bot API update as an :data:`Update`; anything but a text message or a button press is None."""
    update_id = int(raw["update_id"])
    message = raw.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("text"), str) and isinstance(message.get("from"), Mapping):
        return InboundMessage(update_id=update_id, chat_id=str(message["chat"]["id"]),
                              thread_id=_text_id(message.get("message_thread_id")),
                              user_id=str(message["from"]["id"]), user_display=_display(message["from"]),
                              message_id=str(message["message_id"]), text=message["text"])
    press = raw.get("callback_query")
    if isinstance(press, Mapping) and isinstance(press.get("message"), Mapping):
        return CallbackPress(update_id=update_id, callback_id=str(press["id"]),
                             chat_id=str(press["message"]["chat"]["id"]), user_id=str(press["from"]["id"]),
                             user_display=_display(press["from"]), message_id=str(press["message"]["message_id"]),
                             data=str(press.get("data") or ""))
    return None


def _keyboard(buttons: Sequence[Button]) -> dict[str, Any]:
    for button in buttons:
        if len(button.data.encode("utf-8")) > CALLBACK_DATA_LIMIT:
            raise ValueError(f"callback data over {CALLBACK_DATA_LIMIT} bytes")
    return {"inline_keyboard": [[{"text": b.label, "callback_data": b.data}] for b in buttons]}


class TelegramTransport:
    """The Telegram :class:`~agent_runtime.messaging.transport.Transport`. ``client`` is injected by tests
    (an ``httpx.MockTransport`` fake Bot API); production builds its own ``httpx.Client``."""

    def __init__(self, token: str, *, client: httpx.Client | None = None, api_base: str = API_BASE,
                 poll_timeout: int = POLL_TIMEOUT_S, wait: Callable[[float], bool] | None = None) -> None:
        if not token:
            raise ValueError("a bot token is required")
        self._token = token
        _REDACTOR.secrets.add(token)
        self._base = f"{api_base}/bot{token}"
        self._client = client or httpx.Client(timeout=httpx.Timeout(poll_timeout + 15.0, connect=10.0))
        self._poll_timeout = poll_timeout
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._thread: threading.Thread | None = None
        self.offset: int | None = None

    # ── the one call ──

    def _call(self, method: str, payload: Mapping[str, Any] | None = None, *, timeout: float | None = None) -> Any:
        try:
            response = self._client.post(f"{self._base}/{method}", json=dict(payload or {}),
                                         **({"timeout": timeout} if timeout is not None else {}))
        except httpx.HTTPError as exc:
            logger.warning("telegram %s: %s", method, type(exc).__name__)
            raise TelegramError(method, Failure.NETWORK) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200 and isinstance(body, Mapping) and body.get("ok") is True:
            return body.get("result")
        params = body.get("parameters") if isinstance(body, Mapping) else None
        retry_after = params.get("retry_after") if isinstance(params, Mapping) else None
        raise TelegramError(method, _failure_of(response.status_code), response.status_code,
                            float(retry_after) if isinstance(retry_after, (int, float)) else None)

    # ── inbound ──

    def get_me(self) -> dict[str, Any]:
        return dict(self._call("getMe") or {})

    def poll_once(self, on_update: OnUpdate) -> int:
        """One ``getUpdates``; every returned update reaches ``on_update`` (or nobody) and the offset moves
        past it. Returns how many updates the batch held."""
        payload: dict[str, Any] = {"timeout": self._poll_timeout, "allowed_updates": ["message", "callback_query"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        updates = self._call("getUpdates", payload, timeout=self._poll_timeout + 15.0) or []
        for raw in updates:
            update_id = int(raw["update_id"])
            try:
                update = parse_update(raw)
                if update is not None:
                    on_update(update)
            except Exception as exc:
                emit("messaging.transport.update_failed", platform="telegram", update_id=update_id,
                     error=type(exc).__name__)
            self.offset = update_id + 1
        return len(updates)

    def run(self, on_update: OnUpdate) -> None:
        """Poll until :meth:`stop`, backing off by :data:`BACKOFF`; returns on stop or a fatal failure."""
        streak = 0
        while not self._stop.is_set():
            try:
                self.poll_once(on_update)
            except TelegramError as error:
                streak += 1
                delay = backoff_delay(error, streak)
                emit("messaging.transport.poll_failed", platform="telegram", failure=error.failure.value,
                     status=error.status, streak=streak, delay_s=delay)
                if delay is None:
                    emit("messaging.transport.stopped", platform="telegram", reason=error.failure.value)
                    return
                if self._wait(delay):
                    return
            else:
                streak = 0

    def start(self, on_update: OnUpdate) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, args=(on_update,), name="messaging-telegram-poll",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(self._poll_timeout + 20.0 if timeout is None else timeout)

    # ── outbound ──

    def send(self, chat: str, text: str, thread: str | None = None, reply_to: str | None = None) -> SendResult:
        refs = []
        for piece in chunk(text, MESSAGE_LIMIT, size=utf16_size):
            payload: dict[str, Any] = {"chat_id": chat, "text": piece}
            if thread is not None:
                payload["message_thread_id"] = int(thread)
            if reply_to is not None and not refs:
                payload["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
            sent = self._call("sendMessage", payload)
            refs.append(MessageRef(str(sent["chat"]["id"]), str(sent["message_id"])))
        return SendResult(tuple(refs))

    def send_card(self, chat: str, text: str, buttons: Sequence[Button], thread: str | None = None) -> MessageRef:
        payload: dict[str, Any] = {"chat_id": chat, "text": text[:MESSAGE_LIMIT], "reply_markup": _keyboard(buttons)}
        if thread is not None:
            payload["message_thread_id"] = int(thread)
        sent = self._call("sendMessage", payload)
        return MessageRef(str(sent["chat"]["id"]), str(sent["message_id"]))

    def edit(self, ref: MessageRef, text: str, buttons: Sequence[Button] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": ref.chat_id, "message_id": int(ref.message_id), "text": text[:MESSAGE_LIMIT]}
        payload["reply_markup"] = _keyboard(buttons or ())
        self._call("editMessageText", payload)

    def typing(self, chat: str, thread: str | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat, "action": "typing"}
        if thread is not None:
            payload["message_thread_id"] = int(thread)
        self._call("sendChatAction", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, **({"text": text} if text else {})})
