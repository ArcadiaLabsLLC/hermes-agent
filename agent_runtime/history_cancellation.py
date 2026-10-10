"""Durable refusal of an unapplied history request, serialized by its writer."""

from .operator_conversation import OperatorConversationRefused

__layer__ = "lanes"


def cancellation_key(receipt_key: str) -> str:
    return receipt_key.replace("operator_history:", "operator_history_cancelled:", 1)


def require_not_cancelled(db, receipt_key: str) -> None:
    if db.get_meta(cancellation_key(receipt_key)):
        raise OperatorConversationRefused("operation_cancelled")
