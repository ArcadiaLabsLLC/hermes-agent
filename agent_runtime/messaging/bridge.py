"""``MessagingBridge`` — a platform message becomes a QUEUED turn of a persona instance (p10-messaging §3 M3).

Plan ``docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md`` §2.3. The bridge owns no session:

* **inbound** (:meth:`MessagingBridge.inbound`, the transport's ``on_update``): an update from a platform
  user with no operator row is dropped with ONE ``messaging.refused`` receipt and no reply (fail closed);
  ``/persona <name>`` writes the chat's binding through the M1 service function (``rpc.execute``); an
  unbound chat is answered with the roster; a bound chat's text is queued on the instance's CURRENT chat
  root by ``PersonaTurnExecutor.queue_inbound`` — the busy-root send queue, never the door — idempotent by
  the platform's update id (cmid ``msg-<platform>-<update_id>``), so a re-delivered update converges.
* **reply** (:meth:`MessagingBridge.settled`, registered as the executor's ``messaging`` origin listener):
  the settle carries the reply; it is sent to the origin's chat and thread, chunked by the transport, or a
  one-line notice when the turn ended without one. Nothing is read from history.
* **presses** go to the approval cards (``approvals.ApprovalCards``, M4) when the bridge has them, and are
  otherwise answered and dropped; the cards' watched roots are refreshed at start, after a bind and on
  every inbound message (a root the launcher moved is picked up by the next message).

Receipts (``work_store.receipts.emit``): ``messaging.inbound | queued | replied | refused | bound`` — ids
and reasons only, never message text. Pinned by ``tests/agent_runtime/messaging/test_bridge_inbound.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .. import chat_root_send_queue as send_queue
from ..chat_turn_settles import outcome_from_payload
from ..work_store.persona_turn import ORIGIN_KIND_KEY, OriginKind, PersonaTurnExecutor, runs_here
from ..work_store.reasons import WorkRefused
from ..work_store.receipts import emit
from . import rpc
from .approvals import ApprovalCards
from .bindings import BindingStore
from .models import MessagingRefused, Platform, Reason
from .operators import OperatorStore
from .transport import CallbackPress, InboundMessage, Transport, Update

__layer__ = "lanes"
__all__ = ["PERSONA_COMMAND", "MessagingBridge", "messaging_origin"]

logger = logging.getLogger(__name__)

PERSONA_COMMAND = "/persona"
QUEUED_NOTICE = "Queued behind the current reply."
_ROSTER_MAX = 30


def messaging_origin(entry: send_queue.QueuedSend) -> dict[str, Any] | None:
    """The ``messaging`` block of a queued send's origin, or None for a send no platform sent."""

    origin = entry.args.get(send_queue.ORIGIN_ARG)
    block = origin.get(OriginKind.MESSAGING.value) if isinstance(origin, dict) else None
    return block if isinstance(block, dict) else None


def _root_busy(root: str) -> bool:
    """Whether a turn holds the root's lease right now (a zero-wait acquire, released at once)."""

    from ..persona_chat_continuity import PersonaChatBusyError, persona_chat_root_lease

    try:
        with persona_chat_root_lease(root, owner_id="messaging-probe", observer_kind="serve"):
            return False
    except PersonaChatBusyError:
        return True


def _instances() -> list[Any]:
    from ..persona_assignments.store import PersonaInstanceStore
    from ..states import WorkerSessionState

    return [i for i in PersonaInstanceStore().list_all()
            if runs_here(getattr(i, "runtime_root", "")) and i.state != WorkerSessionState.CLOSED]


class MessagingBridge:
    """One platform's inbound → queued turn → reply loop over one :class:`Transport`."""

    def __init__(self, transport: Transport, turns: PersonaTurnExecutor, *, platform: Platform = Platform.TELEGRAM,
                 bindings: BindingStore | None = None, operators: OperatorStore | None = None,
                 roster: Callable[[], list[Any]] = _instances, root_busy: Callable[[str], bool] = _root_busy,
                 approvals: ApprovalCards | None = None) -> None:
        self.transport = transport
        self.turns = turns
        self.platform = platform
        self.bindings = bindings or BindingStore()
        self.operators = operators or OperatorStore()
        self._roster = roster
        self._root_busy = root_busy
        #: The approval cards' press handler (M4); None answers and drops a press.
        self.on_press: Callable[[CallbackPress], None] | None = None
        #: Told after a platform-side ``/persona`` wrote a binding (M4 re-registers its notifiers).
        self.on_bind: list[Callable[[], None]] = []
        self.approvals = approvals
        if approvals is not None:
            self.on_press = approvals.on_callback
            self.on_bind.append(approvals.refresh)

    # ── lifecycle (the serve lane, M5, calls these) ──

    def start(self, on_update: Callable[[Update], None] | None = None) -> None:
        """Register the reply listener, watch the bound roots, start polling. ``on_update`` replaces
        :meth:`inbound` as the transport's callback (the serve lane wraps it in its home and its drain gate)."""
        self.turns.register_origin_listener(OriginKind.MESSAGING, self.settled)
        if self.approvals is not None:
            self.approvals.refresh()
        self.transport.start(on_update or self.inbound)

    def stop(self) -> None:
        self.transport.stop()
        self.turns.unregister_origin_listener(OriginKind.MESSAGING)
        if self.approvals is not None:
            self.approvals.close()

    # ── inbound ──

    def inbound(self, update: Update) -> None:
        """The transport's ``on_update``: one message or one button press. Never raises into the poller."""

        try:
            if isinstance(update, CallbackPress):
                self._press(update)
            elif isinstance(update, InboundMessage):
                self._message(update)
        except Exception:
            logger.warning("messaging update %s failed", getattr(update, "update_id", "?"), exc_info=True)

    def _refuse(self, update: Update, reason: Reason | str) -> None:
        emit("messaging.refused", platform=self.platform.value, update_id=update.update_id,
             chat_id=update.chat_id, user_id=update.user_id, reason=str(getattr(reason, "value", reason)))

    def _press(self, press: CallbackPress) -> None:
        if self.on_press is not None:
            self.on_press(press)
            return
        self.transport.answer_callback(press.callback_id, "")

    def _message(self, msg: InboundMessage) -> None:
        emit("messaging.inbound", platform=self.platform.value, update_id=msg.update_id, chat_id=msg.chat_id,
             thread_id=msg.thread_id, user_id=msg.user_id, message_id=msg.message_id)
        if not self.operators.is_allowed(self.platform, msg.user_id):
            self._refuse(msg, Reason.UNKNOWN_OPERATOR)
            return
        if self.approvals is not None:
            self.approvals.refresh()
        command, _sep, rest = msg.text.strip().partition(" ")
        if command.split("@", 1)[0].lower() == PERSONA_COMMAND:
            self.persona_command(msg, rest.strip())
            return
        binding = self.bindings.get(self.platform, msg.chat_id, msg.thread_id)
        if binding is None:
            self.roster_reply(msg)
            return
        origin = {"owner": None, "gateway": False, ORIGIN_KIND_KEY: OriginKind.MESSAGING.value,
                  OriginKind.MESSAGING.value: {"platform": self.platform.value, "chat_id": msg.chat_id,
                                               "thread_id": msg.thread_id, "user_id": msg.user_id,
                                               "message_id": msg.message_id, "update_id": msg.update_id}}
        try:
            queued = self.turns.queue_inbound(
                binding.persona_instance_id, msg.text, request_id=f"{self.platform.value}-{msg.update_id}",
                origin=origin, cmid_prefix="msg-", requested_by=f"messaging:{self.platform.value}:{msg.user_id}")
        except WorkRefused as refused:
            self._refuse(msg, refused.reason)
            self.transport.send(msg.chat_id, f"Not queued: {refused.reason.value}.", msg.thread_id, msg.message_id)
            return
        run = queued.run
        emit("messaging.queued", platform=self.platform.value, update_id=msg.update_id, run_id=run.run_id,
             persona_instance_id=binding.persona_instance_id, position=queued.position, replay=queued.replay)
        if queued.replay:
            return
        self.transport.typing(msg.chat_id, msg.thread_id)
        entry = send_queue.find(run.root_session_id, run.client_message_id)
        held = entry is not None and entry.state == send_queue.STATE_QUEUED and (
            queued.position > 1 or self._root_busy(run.root_session_id))
        if held:
            self.transport.send(msg.chat_id, QUEUED_NOTICE, msg.thread_id, msg.message_id)

    def roster_reply(self, msg: InboundMessage, lead: str = "This chat is not bound to a persona yet.") -> None:
        names = [f"- {getattr(i, 'display_name', '') or i.persona_id} ({i.id})" for i in self._roster()]
        body = "\n".join(names[:_ROSTER_MAX]) if names else "(no persona instance on this runtime)"
        self.transport.send(msg.chat_id, f"{lead}\nSend {PERSONA_COMMAND} <name> with one of:\n{body}",
                            msg.thread_id, msg.message_id)

    def persona_command(self, msg: InboundMessage, name: str) -> None:
        """``/persona <name>``: bind this chat (and thread) to the one instance the name picks."""

        wanted = name.strip().lower()
        picked = [i for i in self._roster() if wanted and wanted in {
            str(getattr(i, "display_name", "") or "").lower(), str(i.id).lower(), str(i.persona_id).lower()}]
        if len(picked) != 1:
            if wanted:
                self._refuse(msg, Reason.UNKNOWN_PERSONA)
            self.roster_reply(msg, f"No single persona is named {name!r}." if wanted else "Name a persona.")
            return
        instance = picked[0]
        try:
            rpc.execute("binding.set", {"platform": self.platform.value, "chat_id": msg.chat_id,
                                        "thread_id": msg.thread_id, "persona_instance_id": instance.id},
                        by=f"messaging:{self.platform.value}:{msg.user_id}")
        except MessagingRefused as refused:
            self._refuse(msg, refused.reason)
            self.roster_reply(msg, "That persona could not be bound.")
            return
        emit("messaging.bound", platform=self.platform.value, chat_id=msg.chat_id, thread_id=msg.thread_id,
             persona_instance_id=instance.id, user_id=msg.user_id)
        for listener in list(self.on_bind):
            listener()
        label = getattr(instance, "display_name", "") or instance.persona_id
        self.transport.send(msg.chat_id, f"This chat now talks to {label}.", msg.thread_id, msg.message_id)

    # ── reply ──

    def settled(self, entry: send_queue.QueuedSend, exit_code: int, payload: dict | None) -> None:
        """The executor's ``messaging`` listener: send the settle's reply back where the message came from."""

        block = messaging_origin(entry)
        if block is None or block.get("platform") != self.platform.value:
            return
        reply = str((payload or {}).get("reply") or "")
        refusal = outcome_from_payload(payload).refusal_class
        if not reply.strip():
            reply = f"(no reply: the turn ended {refusal or f'with exit {exit_code}'})"
        sent = self.transport.send(str(block["chat_id"]), reply, block.get("thread_id"), block.get("message_id"))
        emit("messaging.replied", platform=self.platform.value, update_id=block.get("update_id"),
             run_id=f"{entry.root_session_id}/{entry.client_message_id}", messages=len(sent.refs),
             refusal_class=refusal)
