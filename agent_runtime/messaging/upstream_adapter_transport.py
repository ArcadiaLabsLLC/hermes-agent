"""An UPSTREAM platform adapter behind the fork's ``Transport`` (RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN).

Opt-in and off by default: ``serve_lane`` builds this only when the harness setting
``messaging_telegram_transport`` is ``upstream``; the fork's own ``telegram_api.TelegramTransport`` stays
the default. The adapter is used as a plain pipe — no ``GatewayRunner``, no upstream session — and
``MessagingBridge`` sits on top unchanged, so the persona system, the operator list, the bindings and the
approval cards are the fork's in both. Evidence:
``docs/agent-runtime-harness/evidence/upstream-adapter-as-transport-2026-11-14/SWITCH_AUDIT.md``.

The shape:

* the adapter is asyncio, the fork's transports are synchronous and thread-based, so the shim owns ONE
  event loop on its own thread and every outbound call is a coroutine handed to it;
* inbound, the adapter's one handler turns a ``MessageEvent`` into an ``InboundMessage``, hands it to the
  bridge OFF the loop (the bridge calls ``send`` back, which would deadlock on the loop thread) and
  returns ``None`` — "queued": the reply is sent later from the settle, so the base class's delivery
  ledger, media extraction and voice-reply steps never run;
* who may talk is the fork's (``is_allowed``), asked by the ADAPTER at intake: with no allowlist
  configured an upstream adapter passes every sender on and leaves the decision to a runner the fork
  does not start, having already fetched whatever media they sent. A stranger therefore never reaches
  the bridge, and ``on_refused`` is where the console's Allow list is fed.
* that intake is each adapter's OWN (RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM): Telegram asks
  ``_is_callback_user_authorized``, Discord ``_is_allowed_user`` and never the shared callback, Signal has
  no DM sender gate and fetches attachments before ``handle_message``. So the shared
  ``set_authorization_check`` is not a gate on its own: every platform's subclass puts ``_decide`` at its
  adapter's intake in :meth:`UpstreamAdapterTransport._install_intake_gate`, names the test that drives that
  intake with a stranger (``intake_gate_test``) and is listed in :data:`INTAKE_GATED`. The base class
  refuses to start with an ``is_allowed`` and no override, and the serve lane builds no platform that is
  not listed (both pinned by ``tests/agent_runtime/messaging/test_upstream_intake_gates.py``).

Five things a naive use of the Telegram adapter gets wrong, each fixed here and pinned by a test beside
``tests/agent_runtime/messaging/test_upstream_telegram_end_to_end.py``: a stranger's media fetched before
refusal; replies sent silently; upstream's slash-command menu pushed to the bot; the bot token logged at
INFO; message text logged at DEBUG.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import threading
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from .transport import Button, CallbackPress, InboundMessage, MessageRef, OnUpdate, SendResult

__layer__ = "lanes"
__all__ = ["INTAKE_GATED", "DiscordUpstreamAdapterTransport", "OnRefused", "SignalUpstreamAdapterTransport",
           "TelegramUpstreamAdapterTransport", "UpstreamAdapterTransport", "has_own_intake_gate", "update_id_of"]

logger = logging.getLogger(__name__)

_CALL_TIMEOUT_S = 30.0

#: ``(user_id, chat_id, display)`` of a sender the adapter refused at intake.
OnRefused = Callable[[str, str, str], None]


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
    """``Transport`` over one upstream adapter.

    ``connect=False`` leaves the platform connection to the caller (tests that never reach a network).
    ``is_allowed(user_id)`` / ``on_refused(user_id, chat_id, display)`` are the fork's sender gate; they
    run on the shim's loop thread, so ``scope`` (a context-manager factory, the serve lane's
    ``home_scope``) wraps them when the stores they read are per-home. ``is_allowed=None`` lets every
    sender through to the bridge, which then refuses — only for tests of the bridge itself."""

    #: ``Platform.value`` of the adapter a subclass gates; None on the generic base.
    platform: str | None = None
    #: The test file (repo-relative) that drives this adapter's OWN intake with a stranger and the operator.
    intake_gate_test: str | None = None

    def __init__(self, adapter: Any, *, connect: bool = True,
                 is_allowed: Callable[[str], bool] | None = None, on_refused: OnRefused | None = None,
                 scope: Callable[[], Any] | None = None) -> None:
        self.adapter = adapter
        self._connect = connect
        self._is_allowed = is_allowed
        self._on_refused = on_refused
        self._scope = scope or contextlib.nullcontext
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._on_update: OnUpdate | None = None

    # ── lifecycle ──

    def start(self, on_update: OnUpdate) -> None:
        if self._is_allowed is not None:
            # Before the loop exists: a transport that cannot gate its adapter starts nothing at all.
            self._install_intake_gate()
        self._on_update = on_update
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="messaging-upstream-adapter",
                                        daemon=True)
        self._thread.start()
        self.adapter.set_message_handler(self._handle)
        if self._is_allowed is None:
            self.adapter.set_authorization_check(lambda *_args, **_kwargs: True)
        else:
            # An allowlist must be CONFIGURED (even empty) for an adapter's intake gate to ask the
            # callback at all; with none it lets every sender through and leaves the decision to a runner.
            self.adapter.config.extra.setdefault("allow_from", [])
            self.adapter.set_authorization_check(self._gate)
        self._prepare()
        if self._connect:
            try:
                connected = self._call(self.adapter.connect())
            except Exception:
                self.stop()
                raise
            if connected is False:
                self.stop()
                raise RuntimeError("the upstream adapter did not connect")

    def _install_intake_gate(self) -> None:
        """Put :meth:`_decide` at the adapter's OWN intake, ahead of anything it fetches for a sender.

        The base has no adapter to read, so it refuses: the shared ``set_authorization_check`` callback is
        asked by some adapters and not by others, and an adapter that never asks it lets a stranger's media
        be fetched (Signal) or refuses the operator too (Discord)."""
        raise RuntimeError(f"{type(self).__name__} has no intake gate of its own for this adapter; "
                           "a platform's subclass must override _install_intake_gate")

    def _prepare(self) -> None:
        """Per-platform set-up that must be in place before ``connect()``."""

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
        if not loop.is_running():
            loop.close()
        self._loop = self._thread = None

    def _call(self, coro: Coroutine[Any, Any, Any]) -> Any:
        if self._loop is None:
            coro.close()
            raise RuntimeError("the transport is not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(_CALL_TIMEOUT_S)

    # ── the sender gate ──

    def _decide(self, user_id: Any, chat_id: Any = None, display: Any = None, *, report: bool = True) -> bool:
        """The fork's answer for one sender; a refusal is reported once here, unless ``report`` is False (a
        sender who did not address the agent: refused the same, but not listed). Fails CLOSED."""
        if self._is_allowed is None:
            return True
        user = str(user_id or "").strip()
        try:
            with self._scope():
                allowed = bool(user) and bool(self._is_allowed(user))
                if not allowed and report and user and self._on_refused is not None:
                    self._on_refused(user, str(chat_id or ""), str(display or ""))
        except Exception:
            logger.warning("the messaging sender gate failed; the sender is refused", exc_info=True)
            return False
        return allowed

    def _gate(self, user_id: Any, chat_type: Any = None, chat_id: Any = None, **_kwargs: Any) -> bool:
        return self._decide(user_id, chat_id)

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
        has seen it (a test's stand-in for a platform update arriving on a connected adapter)."""

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
            logger.warning("the upstream adapter refused a send: %s", getattr(result, "error_kind", None) or "error")
            return SendResult(())
        # A reply the adapter split: Telegram's adapter lists every part in ``raw_response["message_ids"]``;
        # others use ``continuation_message_ids`` with ``message_id`` the last part.
        raw = getattr(result, "raw_response", None)
        ids = list(raw.get("message_ids") or ()) if isinstance(raw, dict) else []
        if not ids:
            first = getattr(result, "message_id", None)
            ids = [first, *(i for i in getattr(result, "continuation_message_ids", ()) if i != first)]
        return SendResult(tuple(MessageRef(chat, str(i)) for i in ids if i))

    def typing(self, chat: str, thread: str | None = None) -> None:
        try:
            self._call(self.adapter.send_typing(chat, metadata={"thread_id": thread} if thread else None))
        except Exception:
            logger.debug("typing indicator failed", exc_info=True)

    def send_card(self, chat: str, text: str, buttons: Sequence[Button], thread: str | None = None) -> MessageRef:
        raise NotImplementedError("approval cards need the platform's own subclass")

    def edit(self, ref: MessageRef, text: str, buttons: Sequence[Button] | None = None) -> None:
        raise NotImplementedError("approval cards need the platform's own subclass")

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        raise NotImplementedError("approval cards need the platform's own subclass")


class TelegramUpstreamAdapterTransport(UpstreamAdapterTransport):
    """Upstream's Telegram adapter, with what the generic shim cannot do.

    **Approval cards.** Upstream's own approval buttons (``ea:<choice>:<id>``) resolve against UPSTREAM's
    approval registry and session keys, so they cannot carry the fork's cards. This goes one level down,
    to the python-telegram-bot ``Bot`` the adapter holds: cards are plain inline keyboards, and a press
    whose data carries the fork's prefix is taken by a handler registered AHEAD of the adapter's own
    (group -1) and stopped there, so the adapter never answers it. The handler rides the adapter's
    ``_register_handlers``, which the adapter calls again when it rebuilds its application on a
    connect retry — so a rebuilt application still has it.

    **The sender gate with a name.** The adapter's ``set_authorization_check`` callback gets ids only.
    The adapter also consults an instance-level ``_is_callback_user_authorized`` for both messages and
    button presses, and passes the sender's display name to it — that is what feeds the console's Allow
    list a name, as the fork's own transport does.

    **The log.** python-telegram-bot's HTTP client logs every request URL at INFO on the ``httpx`` logger
    — the URL carries the bot token — and its own loggers print whole updates and sends, message text
    included, at DEBUG. The token goes to the redactor the fork's own transport uses and the library's
    loggers are held at INFO.

    **The command menu.** The adapter pushes UPSTREAM's slash-command menu to the bot after connect, with
    no switch for it; those commands live in the runner the fork does not start.

    The last three are overrides of PRIVATE adapter attributes; each has a test that goes red if an
    upstream release renames what it overrides."""

    platform = "telegram"
    intake_gate_test = "tests/agent_runtime/messaging/test_upstream_telegram_stranger_gate.py"

    def __init__(self, adapter: Any, *, press_prefix: str, **kwargs: Any) -> None:
        super().__init__(adapter, **kwargs)
        self._press_prefix = press_prefix
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

    def _prepare(self) -> None:
        adapter = self.adapter

        async def _no_upstream_menu() -> None:
            return None

        adapter._register_command_menu = _no_upstream_menu
        register_core = adapter._register_handlers

        def register(app: Any) -> None:
            from telegram.ext import CallbackQueryHandler

            app.add_handler(CallbackQueryHandler(self._on_press, pattern=f"^{self._press_prefix}:"), group=-1)
            register_core(app)

        adapter._register_handlers = register

    def _install_intake_gate(self) -> None:
        self.adapter._is_callback_user_authorized = self._named_gate

    def _named_gate(self, user_id: Any, *, chat_id: Any = None, chat_type: Any = None, thread_id: Any = None,
                    user_name: Any = None, **_kwargs: Any) -> bool:
        return self._decide(user_id, chat_id, user_name)

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


_SIGNAL_INTAKE_TEST = "tests/agent_runtime/messaging/test_upstream_signal_and_discord_intake_gates.py"


class SignalUpstreamAdapterTransport(UpstreamAdapterTransport):
    """Upstream's Signal adapter: the fork's operator list asked before an envelope is handled.

    Read in ``plugins/platforms/signal/adapter.py::SignalAdapter._handle_envelope``: a direct message has no
    sender gate there (DM auth is the runner's), and ``_collect_attachments`` fetches every attachment over
    signal-cli's ``getAttachment`` BEFORE ``handle_message`` — the shared callback is asked only after. The
    override wraps the adapter's ``_handle_envelope`` and refuses a stranger's message envelope before the
    adapter reads it. Passed through untouched, as the adapter itself handles them: an envelope with no
    message (receipts, typing: nothing to fetch, nothing reaches the bridge), one with no sender, the
    account's own echo, and a ``syncMessage`` — sent from the account's OWN linked devices ("Note to Self"),
    not by a stranger; the adapter's unwrap of it consumes an echo timestamp, so it must run once, there.
    No approval cards yet (the generic ``NotImplementedError``s stand)."""

    platform = "signal"
    intake_gate_test = _SIGNAL_INTAKE_TEST

    def _install_intake_gate(self) -> None:
        adapter = self.adapter
        handle = adapter._handle_envelope

        async def gated(envelope: dict) -> None:
            if self._refuses_envelope(envelope):
                return None
            return await handle(envelope)

        adapter._handle_envelope = gated

    def _refuses_envelope(self, envelope: Any) -> bool:
        data = envelope.get("envelope", envelope) if isinstance(envelope, dict) else None
        if not isinstance(data, dict) or "syncMessage" in data:
            return False
        message = data.get("dataMessage") or (data.get("editMessage") or {}).get("dataMessage")
        sender = data.get("sourceNumber") or data.get("sourceUuid") or data.get("source")
        if not isinstance(message, dict) or not sender:
            return False
        if sender == getattr(self.adapter, "_account_normalized", None):
            return False
        group = (message.get("groupInfo") or {}).get("groupId")
        return not self._decide(sender, f"group:{group}" if group else sender, data.get("sourceName") or "")


class DiscordUpstreamAdapterTransport(UpstreamAdapterTransport):
    """Upstream's Discord adapter: the fork's operator list IS its user gate.

    Read in ``plugins/platforms/discord/adapter.py``: every ingress — ``_discord_message_admission`` (before
    ``_handle_message`` and its attachment download), slash commands, reactions, voice — asks
    ``_is_allowed_user``, never the shared callback; with no ``DISCORD_ALLOWED_*`` it refuses everyone, the
    operator included, and the fork never hears of the refusal. The override replaces that method on the
    instance with :meth:`_decide`, so the operator is admitted, a stranger is refused (and listed) at the same
    place, and upstream's pairing, wildcard and role grants do not widen the fork's list. Upstream's other
    admission rules (bots, mentions in shared channels) still run after it. No approval cards yet.

    **Only who addressed the agent is listed** (RT-MESSAGING-ONE-SENDER-GATE, closing
    RT-MESSAGING-DISCORD-GATE-LISTS-EVERY-GUILD-SENDER-AS-REFUSED). The adapter asks ``_is_allowed_user`` for
    EVERY message, reaction and voice event on a shared server, before its mention rules, so a gate that
    listed each refusal would put the whole server on the console's Allow list. Every stranger is still
    refused there; one is LISTED only for a DM, or a server message that @mentions the bot or sits in a
    thread the bot joined. The message being admitted is read by wrapping ``_discord_message_admission``
    (synchronous, on the adapter's one loop thread); reactions and voice carry no message and list nobody."""

    platform = "discord"
    intake_gate_test = _SIGNAL_INTAKE_TEST

    def _install_intake_gate(self) -> None:
        adapter = self.adapter
        adapter._is_allowed_user = self._user_gate
        admit = adapter._discord_message_admission
        self._admitting: Any = None

        def admission(message: Any, *, claim: bool) -> tuple[bool, bool]:
            self._admitting = message
            try:
                return admit(message, claim=claim)
            finally:
                self._admitting = None

        adapter._discord_message_admission = admission

    def _addressed(self, message: Any) -> bool:
        """A server message aimed at the bot: an @mention, or a thread the bot joined."""
        if message is None:
            return False
        adapter = self.adapter
        try:
            if adapter._self_is_explicitly_mentioned(message):
                return True
            return bool(adapter._in_bot_thread(message))
        except Exception:  # the adapter's helpers read discord.py types; unreadable means not addressed
            return False

    def _user_gate(self, user_id: Any, author: Any = None, *, guild: Any = None, is_dm: bool = False,
                   channel_ids: Any = None, **_kwargs: Any) -> bool:
        display = getattr(author, "display_name", None) or getattr(author, "name", None) or ""
        chat = sorted(str(c) for c in channel_ids)[0] if channel_ids else ""
        report = bool(is_dm) or self._addressed(self._admitting)
        return self._decide(user_id, chat, display, report=report)


def has_own_intake_gate(cls: type) -> bool:
    """True when ``cls`` overrides the base's refusing :meth:`~UpstreamAdapterTransport._install_intake_gate`
    and names the test that drives its adapter's intake."""
    return (isinstance(cls, type) and issubclass(cls, UpstreamAdapterTransport)
            and cls._install_intake_gate is not UpstreamAdapterTransport._install_intake_gate
            and bool(cls.platform) and bool(cls.intake_gate_test))


#: ``Platform.value`` -> the transport whose adapter intake carries the fork's gate. The serve lane wires in
#: an upstream adapter only for a platform listed here.
INTAKE_GATED: dict[str, type[UpstreamAdapterTransport]] = {
    cls.platform: cls for cls in (TelegramUpstreamAdapterTransport, SignalUpstreamAdapterTransport,
                                  DiscordUpstreamAdapterTransport) if cls.platform}
