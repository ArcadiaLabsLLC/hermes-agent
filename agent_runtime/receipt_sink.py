"""The agent's ``status_callback`` with ONE calling convention, and the fork's receipts on their own door.

Upstream calls ``agent.status_callback(kind, text)`` (``agent/status_output.py``,
``agent/conversation_compression.py``). The fork's timing receipts (``init_observability``,
``conversation_observability``, ``codex_observability``) are one dict
each. They used to be handed to the same callback, so every upstream surface's callback (CLI,
gateway, TUI, api_server) received dicts it does not read — the TUI's ``_agent_status_update``
stringified one into a ``status.update`` kind. A receipt now goes ONLY to a :class:`ReceiptSink`
(the profile runner's), through :func:`receipt_callback`; any other callback never sees one.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

__layer__ = "models"

Receipt = Callable[[dict], None]


class ReceiptSink:
    """A ``status_callback`` whose owner also reads the fork's receipts.

    ``sink(kind, text)`` is upstream's convention, forwarded to *status* (when given);
    ``sink.receipt(payload)`` is the fork's, forwarded to *receipt*.
    """

    __slots__ = ("_receipt", "_status")

    def __init__(self, receipt: Receipt, status: Optional[Callable[[str, Any], None]] = None) -> None:
        self._receipt = receipt
        self._status = status

    def __call__(self, kind: str, text: Any = None) -> None:
        if self._status is not None:
            self._status(kind, text)

    def receipt(self, payload: dict) -> None:
        self._receipt(payload)


def receipt_callback(status_callback: Any) -> Optional[Receipt]:
    """Where a fork receipt goes: the sink's receipt door, or nowhere (``None``)."""

    return status_callback.receipt if isinstance(status_callback, ReceiptSink) else None


def agent_receipt_callback(agent: Any) -> Optional[Receipt]:
    """:func:`receipt_callback` for the agent's current ``status_callback``."""

    return receipt_callback(getattr(agent, "status_callback", None))
