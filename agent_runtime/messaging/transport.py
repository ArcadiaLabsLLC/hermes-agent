"""The ``Transport`` protocol every platform transport implements (p10-messaging §3 M2), and its values.

A transport moves text and button presses between a platform and the bridge; it knows nothing of
personas, sessions or operators. Inbound it hands the bridge one :data:`Update` at a time — an
:class:`InboundMessage` (a text message) or a :class:`CallbackPress` (an inline-keyboard button) — and
outbound it sends, edits, shows typing and answers presses. Ids are strings whatever the platform's
own type, so a binding written from the launcher (JSON) and one derived from an update agree.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__layer__ = "models"
__all__ = ["Button", "CallbackPress", "InboundMessage", "MessageRef", "OnUpdate", "SendResult", "Transport",
           "Update"]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    update_id: int
    chat_id: str
    thread_id: str | None
    user_id: str
    user_display: str
    message_id: str
    text: str


@dataclass(frozen=True, slots=True)
class CallbackPress:
    update_id: int
    callback_id: str
    chat_id: str
    user_id: str
    user_display: str
    message_id: str
    data: str


Update = InboundMessage | CallbackPress
OnUpdate = Callable[[Update], None]


@dataclass(frozen=True, slots=True)
class MessageRef:
    chat_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class SendResult:
    """Every message one ``send`` produced, in order (a long reply is several)."""

    refs: tuple[MessageRef, ...]


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    data: str


@runtime_checkable
class Transport(Protocol):
    def start(self, on_update: OnUpdate) -> None: ...

    def stop(self) -> None: ...

    def send(self, chat: str, text: str, thread: str | None = None, reply_to: str | None = None) -> SendResult: ...

    def send_card(self, chat: str, text: str, buttons: Sequence[Button], thread: str | None = None) -> MessageRef: ...

    def edit(self, ref: MessageRef, text: str, buttons: Sequence[Button] | None = None) -> None: ...

    def typing(self, chat: str, thread: str | None = None) -> None: ...

    def answer_callback(self, callback_id: str, text: str = "") -> None: ...
