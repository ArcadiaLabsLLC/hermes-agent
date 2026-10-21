"""Approval cards — an exec approval on any bound root reaches the operator on the platform (p10-messaging §3 M4).

Plan ``docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md`` §2.5. Owner RULED 2026-10-19: cards
for EVERY bound root — a platform turn, a launcher turn while the operator walked away, a scheduled fire.

* :meth:`ApprovalCards.refresh` registers :meth:`ApprovalCards.on_pending` as the approval notifier
  (``session_controls.register_approval_notifier``) of every root a binding points at — the bound
  instance's CURRENT chat root — and unregisters the roots no binding reaches any more. The bridge calls it
  at start, after a ``/persona`` bind and on every inbound message.
* :meth:`ApprovalCards.on_pending` (upstream's notify, in the agent thread) sends one card per chat bound
  to that root: upstream's wording (``gateway/platforms/base_exec_approval.py``: header, the command, the
  reason, the deadline line) and one button per choice the resolver accepts, labelled by
  ``ea_action_labels``, ``callback_data = "ap:<approval_id>:<choice>"``. Upstream's settle hook
  (``tools.approval.register_gateway_settle``) edits the card when the wait ends elsewhere: timed out,
  answered from the launcher, withdrawn.
* :meth:`ApprovalCards.on_callback` (a press): a user with no operator row is answered "not allowed" and
  dropped with a receipt; otherwise the press resolves through
  ``operator_session_controls.respond_operator_approval`` — the function the launcher's
  ``runtime.operator.conversation.approval.respond`` calls, so there is ONE resolve path — and the card
  is edited to who answered what, or to the timed-out notice on ``approval_expired``.

Follows the tree where the plan said "four choices": ``respond_operator_approval`` accepts
``session_controls.APPROVAL_CHOICES`` (once, deny) and nothing else, so the card offers those, in upstream's
order and words. Pinned by ``tests/agent_runtime/messaging/test_approval_cards.py``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import operator_session_controls, session_controls
from ..work_store.persona_turn import PersonaTurnExecutor
from ..work_store.receipts import emit
from .bindings import BindingStore
from .models import Platform, Reason
from .operators import OperatorStore
from .transport import Button, CallbackPress, MessageRef, Transport

__layer__ = "lanes"
__all__ = ["CALLBACK_PREFIX", "ApprovalCards", "card_choices", "card_text"]

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "ap"
#: What upstream's settle hook says -> the line the card is edited to (``timeout`` is upstream's own notice).
_ENDED_ELSEWHERE = {"resolved": "Answered from another surface.", "session_closed": "Withdrawn: the turn ended.",
                    "interrupted": "Withdrawn: the turn was interrupted."}


def card_choices() -> list[tuple[str, str]]:
    """``(choice, label)`` in upstream's order, for every choice the operator resolver accepts."""

    from gateway.platforms.base_exec_approval import ea_action_labels

    labels = ea_action_labels()
    return [(choice, label) for choice, label in labels.items() if choice in session_controls.APPROVAL_CHOICES]


def card_text(data: dict[str, Any]) -> str:
    from gateway.platforms.base_exec_approval import (
        approval_timeout_seconds, ea_default_reason_text, ea_header_text, ea_reason_label_text,
        format_approval_deadline_line,
    )

    reason = str(data.get("description") or "").strip() or ea_default_reason_text()
    return (f"{ea_header_text()}\n\n```\n{data.get('command') or ''}\n```\n"
            f"{ea_reason_label_text()}: {reason}\n\n{format_approval_deadline_line(approval_timeout_seconds())}")


def _timed_out_text() -> str:
    from gateway.platforms.base_exec_approval import approval_timeout_seconds, format_approval_timed_out_notice

    return format_approval_timed_out_notice(approval_timeout_seconds())


def _identity(root: str, instance_id: str) -> dict[str, Any]:
    """The exact-owner reference ``respond_operator_approval`` checks, unscoped (the runtime's own console)."""

    from .. import paths
    from ..gateway_identity import read_install_identity
    from ..persona_assignments import PersonaInstanceStore
    from ..workspace_scope import effective_workspace_id

    instance = PersonaInstanceStore().get(instance_id)
    return {"install_id": read_install_identity(paths.store_root()).install_id,
            "workspace_id": effective_workspace_id(instance, active_workspace_id=None),
            "persona_id": instance.persona_id, "persona_instance_id": instance.id, "session_id": root}


@dataclass
class _Card:
    root: str
    instance_id: str
    refs: list[MessageRef] = field(default_factory=list)
    done: bool = False


class ApprovalCards:
    def __init__(self, transport: Transport, turns: PersonaTurnExecutor, *, platform: Platform = Platform.TELEGRAM,
                 bindings: BindingStore | None = None, operators: OperatorStore | None = None,
                 identity: Callable[[str, str], dict[str, Any]] = _identity) -> None:
        self.transport = transport
        self.turns = turns
        self.platform = platform
        self.bindings = bindings or BindingStore()
        self.operators = operators or OperatorStore()
        self._identity = identity
        self._lock = threading.Lock()
        self._roots: dict[str, tuple[str, list[tuple[str, str | None]]]] = {}  # root -> (instance, chats)
        self._notifiers: dict[str, Callable[[dict], None]] = {}
        self._cards: dict[str, _Card] = {}

    # ── which roots are watched ──

    def refresh(self) -> set[str]:
        """Register a notifier for every root a binding reaches; drop the rest. Returns the watched roots."""

        roots: dict[str, tuple[str, list[tuple[str, str | None]]]] = {}
        for binding in self.bindings.list(self.platform):
            root = self.turns.current_root(binding.persona_instance_id)
            if root:
                roots.setdefault(root, (binding.persona_instance_id, []))[1].append((binding.chat_id, binding.thread_id))
        with self._lock:
            gone = set(self._notifiers) - set(roots)
            self._roots = roots
            for root in gone:
                session_controls.unregister_approval_notifier(root, self._notifiers.pop(root))
            for root in roots:
                if root not in self._notifiers:
                    self._notifiers[root] = lambda data, root=root: self.on_pending(root, data)
                    session_controls.register_approval_notifier(root, self._notifiers[root])
        return set(roots)

    def close(self) -> None:
        with self._lock:
            for root, cb in self._notifiers.items():
                session_controls.unregister_approval_notifier(root, cb)
            self._notifiers.clear()

    # ── a pending approval ──

    def on_pending(self, root: str, data: dict[str, Any]) -> None:
        approval_id = str(data.get("request_id") or "")
        with self._lock:
            instance_id, chats = self._roots.get(root, ("", []))
        if not approval_id or not chats:
            return
        buttons = [Button(label, f"{CALLBACK_PREFIX}:{approval_id}:{choice}") for choice, label in card_choices()]
        card = _Card(root, instance_id)
        text = card_text(data)
        for chat, thread in chats:
            try:
                card.refs.append(self.transport.send_card(chat, text, buttons, thread))
            except Exception:
                logger.warning("an approval card could not be sent to a %s chat", self.platform.value, exc_info=True)
        with self._lock:
            self._cards[approval_id] = card
        emit("messaging.approval_card", platform=self.platform.value, root=root, approval_id=approval_id,
             cards=len(card.refs))
        from tools.approval import register_gateway_settle

        register_gateway_settle(root, approval_id, lambda reason: self._ended(approval_id, reason))

    def _ended(self, approval_id: str, reason: str) -> None:
        """Upstream's settle hook: the wait ended. A card nobody answered here says how."""

        with self._lock:
            card = self._cards.pop(approval_id, None)
        if card is None or card.done:
            return
        self._edit(card, _timed_out_text() if reason == "timeout" else _ENDED_ELSEWHERE.get(reason, "Closed."))

    def _edit(self, card: _Card, text: str) -> None:
        card.done = True
        for ref in card.refs:
            try:
                self.transport.edit(ref, text)
            except Exception:
                logger.warning("an approval card could not be edited", exc_info=True)

    # ── a press ──

    def on_callback(self, press: CallbackPress) -> None:
        prefix, _sep, rest = press.data.partition(":")
        approval_id, _sep, choice = rest.partition(":")
        if prefix != CALLBACK_PREFIX:
            self.transport.answer_callback(press.callback_id, "")
            return
        if not self.operators.is_allowed(self.platform, press.user_id):
            emit("messaging.refused", platform=self.platform.value, update_id=press.update_id, chat_id=press.chat_id,
                 user_id=press.user_id, reason=Reason.UNKNOWN_OPERATOR.value)
            self.transport.answer_callback(press.callback_id, "Not allowed.")
            return
        with self._lock:
            card = self._cards.get(approval_id)
        if card is None:
            self.transport.answer_callback(press.callback_id, "This approval is no longer pending.")
            return
        params = {**self._identity(card.root, card.instance_id), "approval_id": approval_id, "choice": choice}
        card.done = True  # the settle hook this answer fires must not edit the card first
        try:
            operator_session_controls.respond_operator_approval(params)
        except operator_session_controls.OperatorConversationRefused as refused:
            emit("messaging.approval_refused", platform=self.platform.value, approval_id=approval_id,
                 reason=refused.reason)
            card.done = False
            if refused.reason == "approval_expired":
                self._edit(card, _timed_out_text())
            self.transport.answer_callback(press.callback_id, "Not accepted.")
            return
        labels = dict(card_choices())
        who = press.user_display or press.user_id
        self._edit(card, f"Denied by {who}." if choice == "deny" else f"Approved ({labels.get(choice, choice)}) by {who}.")
        emit("messaging.approval_answered", platform=self.platform.value, approval_id=approval_id, choice=choice,
             user_id=press.user_id)
        self.transport.answer_callback(press.callback_id, "Done.")
