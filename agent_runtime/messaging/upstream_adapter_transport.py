"""TRIAL (RT-MESSAGING-UPSTREAM-ADAPTER-TRIAL) — an upstream platform adapter behind the fork's ``Transport``.

Throwaway code on a trial branch: nothing constructs this in the serve, nothing enables it. It answers
one question — can ``MessagingBridge`` sit on top of an UPSTREAM ``BasePlatformAdapter`` used as a plain
pipe, with no ``GatewayRunner`` and no upstream session — and the tests beside it are the answer.

The shape:

* the adapter is asyncio, the fork's transports are synchronous and thread-based, so the shim owns ONE
  event loop on its own thread and every outbound call is a coroutine handed to it;
* inbound, the adapter's one handler turns a ``MessageEvent`` into an ``InboundMessage``, hands it to the
  bridge OFF the loop (the bridge calls ``send`` back, which would deadlock on the loop thread) and
  returns ``None`` — "queued": the reply is sent later from the settle, so the base class's delivery
  ledger, media extraction and voice-reply steps never run;
* who may talk stays the bridge's (``OperatorStore``): the adapter's own sender gate is told yes, so a
  stranger still reaches the bridge and is refused and recorded there.

NOT covered (the row's handoff says so): approval cards (``send_card`` / ``edit`` / ``answer_callback``),
a real ``connect()``, and feeding the token from ``credentials.bot_token``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from .transport import Button, CallbackPress, InboundMessage, MessageRef, OnUpdate, SendResult

__layer__ = "lanes"
__all__ = ["TelegramUpstreamAdapterTransport", "UpstreamAdapterTransport", "update_id_of"]

logger = logging.getLogger(__name__)

_CALL_TIMEOUT_S = 30.0


def update_id_of(event: Any) -> int:
    """A stable integer for one platform message: the platform's own update id when the adapter carries
    one (Telegram), else a digest of (chat, thread, message id) — the same message re-delivered gives the
    same id, so the bridge's ``msg-<platform>-<update_id>`` converges on one queued entry."""

    native = getattr(event, "platform_update_id", None)
    if isinstance(native, int):
        return native
    source = event.source
    key = "\x00".join(str(part or "") for part in (source.chat_id, source.thread_id, event.message_id))
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:7], "big")


class UpstreamAdapterTransport:
    """``Transport`` over one upstream adapter. ``connect=False`` leaves the platform connection to the
    caller (the tests, which never reach a network)."""

    def __init__(self, adapter: Any, *, connect: bool = True,
                 is_allowed: Callable[[str], bool] | None = None,
                 on_refused: Callable[[str, str], None] | None = None) -> None:
        """``is_allowed(user_id)`` makes the ADAPTER refuse a stranger at intake, before it downloads or
        transcribes anything they sent (audit 2026-11-14: with no allowlist configured the Telegram
        adapter passes every sender to the handler, having already fetched their media). The stranger
        then never reaches the bridge, so ``on_refused(user_id, chat_id)`` is where the console's Allow
        list is fed. ``None`` keeps the trial's behaviour: everyone reaches the bridge, which refuses."""
        self.adapter = adapter
        self._connect = connect
        self._is_allowed = is_allowed
        self._on_refused = on_refused
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._on_update: OnUpdate | None = None

    # ── lifecycle ──

    def start(self, on_update: OnUpdate) -> None:
        self._on_update = on_update
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="messaging-upstream-adapter",
                                        daemon=True)
        self._thread.start()
        self.adapter.set_message_handler(self._handle)
        if self._is_allowed is None:
            self.adapter.set_authorization_check(lambda *_args, **_kwargs: True)
        else:
            # An allowlist must be CONFIGURED (even empty) for the adapter's intake gate to ask the
            # callback at all; with none it lets every sender through and leaves the decision to a runner.
            self.adapter.config.extra.setdefault("allow_from", [])
            self.adapter.set_authorization_check(self._gate)
        if hasattr(self.adapter, "_register_command_menu"):
            # Telegram: the adapter pushes UPSTREAM's slash-command menu to the bot after connect, and has
            # no switch for it. Those commands live in the runner the fork does not start, so the menu
            # would advertise commands that do nothing here. An instance override, not a config key.
            async def _no_upstream_menu() -> None:
                return None
            self.adapter._register_command_menu = _no_upstream_menu
        if self._connect:
            self._call(self.adapter.connect())

    def stop(self) -> None:
        loop, thread = self._loop, self._thread
        if loop is None:
            return
        try:
            if self._connect:
                self._call(self.adapter.disconnect())
            self._call(self.adapter.cancel_background_tasks())
        except Exception:
            logger.warning("the upstream adapter did not stop cleanly", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        loop.close()
        self._loop = self._thread = None

    def _gate(self, user_id: Any, chat_type: Any = None, chat_id: Any = None, **_kwargs: Any) -> bool:
        allowed = bool(self._is_allowed(str(user_id))) if self._is_allowed is not None else True
        if not allowed and self._on_refused is not None:
            try:
                self._on_refused(str(user_id), str(chat_id or ""))
            except Exception:
                logger.debug("recording a refused sender failed", exc_info=True)
        return allowed

    def _call(self, coro: Coroutine[Any, Any, Any]) -> Any:
        if self._loop is None:
            coro.close()
            raise RuntimeError("the transport is not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(_CALL_TIMEOUT_S)

    # ── inbound: the adapter's ONE handler ──

    async def _handle(self, event: Any) -> None:
        source = event.source
        message = InboundMessage(
            update_id=update_id_of(event), chat_id=str(source.chat_id),
            thread_id=str(source.thread_id) if source.thread_id else None, user_id=str(source.user_id or ""),
            user_display=str(source.user_name or ""), message_id=str(event.message_id or ""),
            text=str(event.text or ""))
        if self._on_update is not None:
            await asyncio.to_thread(self._on_update, message)
        return None  # queued: the settle sends the reply through ``send``

    def deliver(self, event: Any) -> None:
        """Hand one ``MessageEvent`` to the adapter's real ``handle_message`` and wait until the bridge
        has seen it (the tests' stand-in for a platform update arriving on a connected adapter)."""

        async def run() -> None:
            await self.adapter.handle_message(event)
            pending = [t for t in list(getattr(self.adapter, "_background_tasks", ())) if not t.done()]
            pending += [t for t in list(getattr(self.adapter, "_session_tasks", {}).values()) if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        self._call(run())

    # ── outbound ──

    def send(self, chat: str, text: str, thread: str | None = None, reply_to: str | None = None) -> SendResult:
        """One ``adapter.send``; the adapter splits a long text at its own platform limit."""

        if not text.strip():
            return SendResult(())
        # ``notify``: the Telegram adapter sends silently (disable_notification) unless a reply says it is
        # user-visible — the base class marks that itself on a RETURNED reply, which this shim never uses.
        metadata = {"notify": True, **({"thread_id": thread} if thread else {})}
        result = self._call(self.adapter.send(chat, text, reply_to=reply_to, metadata=metadata))
        if not getattr(result, "success", False):
            logger.warning("the upstream adapter refused a send: %s", getattr(result, "error", None))
            return SendResult(())
        ids = [*getattr(result, "continuation_message_ids", ()), getattr(result, "message_id", None)]
        return SendResult(tuple(MessageRef(chat, str(i)) for i in ids if i))

    def typing(self, chat: str, thread: str | None = None) -> None:
        try:
            self._call(self.adapter.send_typing(chat, metadata={"thread_id": thread} if thread else None))
        except Exception:
            logger.debug("typing indicator failed", exc_info=True)

    def send_card(self, chat: str, text: str, buttons: Sequence[Button], thread: str | None = None) -> MessageRef:
        raise NotImplementedError("trial: approval cards over an upstream adapter are not covered")

    def edit(self, ref: MessageRef, text: str, buttons: Sequence[Button] | None = None) -> None:
        raise NotImplementedError("trial: approval cards over an upstream adapter are not covered")

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        raise NotImplementedError("trial: approval cards over an upstream adapter are not covered")


class TelegramUpstreamAdapterTransport(UpstreamAdapterTransport):
    """The Telegram half the generic shim cannot do: the fork's approval cards.

    Upstream's own approval buttons (``ea:<choice>:<id>``) resolve against UPSTREAM's approval registry and
    session keys, so they cannot carry the fork's cards. This goes one level down instead, to the
    python-telegram-bot ``Bot`` the adapter already holds: cards are plain inline keyboards, and a press
    whose data carries the fork's prefix is taken by a handler registered AHEAD of the adapter's own
    (group -1) and stopped there, so the adapter never answers it. Per-platform code — every other
    adapter needs its own equivalent.

    Audit caveat: the handler is added once, after ``connect()``. The adapter rebuilds its PTB application
    on a transient-init retry; a real build registers through upstream's plugin handler factory
    (``BasePlatformAdapter._wire_plugin_handlers``), which the adapter re-runs on a rebuild."""

    def __init__(self, adapter: Any, *, press_prefix: str, **kwargs: Any) -> None:
        super().__init__(adapter, **kwargs)
        self._press_prefix = press_prefix
        # Audit 2026-11-14: python-telegram-bot's HTTP client logs every request URL at INFO on the
        # ``httpx`` logger — and the URL carries the bot token — and its own loggers print whole updates
        # and sends, message text included, at DEBUG. The fork's rule is that neither reaches a log:
        # the token goes to the redactor the fork's own transport uses, and the library's loggers are
        # held at INFO.
        from .telegram_api import _REDACTOR

        token = str(getattr(getattr(adapter, "config", None), "token", "") or "")
        if token:
            _REDACTOR.secrets.add(token)
            _REDACTOR.secrets.add(token.split(":", 1)[-1])
        for name in ("telegram", "telegram.ext", "telegram.ext.ExtBot", "telegram.ext.Application",
                     "telegram.ext.Updater", "telegram.Bot"):
            library_logger = logging.getLogger(name)
            if library_logger.level < logging.INFO:  # NOTSET (0) inherits, and the root may go to DEBUG
                library_logger.setLevel(logging.INFO)

    def start(self, on_update: OnUpdate) -> None:
        super().start(on_update)
        from telegram.ext import CallbackQueryHandler

        app = getattr(self.adapter, "_app", None)
        if app is not None:
            app.add_handler(CallbackQueryHandler(self._on_press, pattern=f"^{self._press_prefix}:"), group=-1)

    async def _on_press(self, update: Any, _context: Any) -> None:
        from telegram.ext import ApplicationHandlerStop

        query = update.callback_query
        user = query.from_user
        message = query.message
        press = CallbackPress(
            update_id=int(update.update_id), callback_id=str(query.id),
            chat_id=str(message.chat_id) if message is not None else "", user_id=str(user.id),
            user_display=str(user.full_name or user.username or user.id),
            message_id=str(message.message_id) if message is not None else "", data=str(query.data or ""))
        if self._on_update is not None:
            await asyncio.to_thread(self._on_update, press)
        raise ApplicationHandlerStop  # the adapter's own callback handler must not see the fork's press

    @staticmethod
    def _keyboard(buttons: Sequence[Button] | None) -> Any:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup([[InlineKeyboardButton(b.label, callback_data=b.data)] for b in buttons or ()])

    def send_card(self, chat: str, text: str, buttons: Sequence[Button], thread: str | None = None) -> MessageRef:
        sent = self._call(self.adapter._bot.send_message(
            chat_id=int(chat), text=text[:4096], reply_markup=self._keyboard(buttons),
            message_thread_id=int(thread) if thread is not None else None))
        return MessageRef(str(sent.chat_id), str(sent.message_id))

    def edit(self, ref: MessageRef, text: str, buttons: Sequence[Button] | None = None) -> None:
        self._call(self.adapter._bot.edit_message_text(
            chat_id=int(ref.chat_id), message_id=int(ref.message_id), text=text[:4096],
            reply_markup=self._keyboard(buttons)))

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._call(self.adapter._bot.answer_callback_query(callback_id, text=text or None))
