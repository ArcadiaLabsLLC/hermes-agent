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
from collections.abc import Coroutine, Sequence
from typing import Any

from .transport import Button, InboundMessage, MessageRef, OnUpdate, SendResult

__layer__ = "lanes"
__all__ = ["UpstreamAdapterTransport", "update_id_of"]

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

    def __init__(self, adapter: Any, *, connect: bool = True) -> None:
        self.adapter = adapter
        self._connect = connect
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
        self.adapter.set_authorization_check(lambda *_args, **_kwargs: True)
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
        metadata = {"thread_id": thread} if thread else None
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
