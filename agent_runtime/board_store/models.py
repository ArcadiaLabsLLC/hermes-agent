"""The board's vocabulary and bounds (a vocabulary/bounds module — floor-exempt):
``BoardScan`` / ``CardScan`` (rows beside their unreadable count), the three
verb tokens, ``ARCHIVED_LEDGER_CAP``, the title / text / actor / label /
checklist bounds, the card sort and order-key lookup, the idempotency-key grammar.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from ..models import Board, BoardCard
from ..serde import safe_id

__layer__ = "models"


#: The three card verbs that share one board's idempotency namespace. Recorded
#: ON the receipt (``_record_idempotency``) and checked on replay
#: (``_idempotent_replay``) so a key cannot cross from one to another.
VERB_ADD_CARD = "add_card"
VERB_EDIT_CARD = "edit_card"
VERB_MOVE_CARD = "move_card"

# Bounded projection / ledger caps (honest accounting, never silent).
ARCHIVED_LEDGER_CAP = 5000


class BoardScan(NamedTuple):
    """The boards a scan FOUND, beside how many board files it could not read.

    ``OfficeStore.ActorScan``'s law, applied to the board family: the two facts
    have to travel together, because any seam that carries only the list
    re-opens the hole at that seam. A board whose ``board.json`` will not decode
    is absent from ``list_all`` — and ``list_all`` is what realm publish walks
    to decide which boards travel and what the snapshot projects.
    """

    boards: list[Board]
    #: Board directories whose ``board.json`` existed and did not decode. NEVER
    #: folded into ``boards`` and never silently zero.
    unreadable: int


class CardScan(NamedTuple):
    """The cards a scan FOUND, beside how many card files it could not read.

    The count is load-bearing in two different ways, which is why it may not be
    dropped at either seam: a READER that renders the short list under-reports
    the column, and the order-key ALLOCATOR that reads it computes neighbour
    keys against rows it cannot see (see :class:`~agent_runtime.errors.
    CardsUnreadable`).
    """

    cards: list[BoardCard]
    unreadable: int


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _safe_title(value: Any) -> str:
    return " ".join(str(value or "").split())[:280]


def _safe_actor(value: Any, *, fallback: str = "operator") -> str:
    return safe_id(value) or fallback


def _safe_labels(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    for value in values:
        label = " ".join(str(value or "").split())[:60]
        if label and label not in out:
            out.append(label)
        if len(out) >= 24:
            break
    return out


def _safe_checklist(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, dict):
            text = _safe_text(item.get("text"), limit=280)
            done = bool(item.get("done"))
        else:
            text = _safe_text(item, limit=280)
            done = False
        if text:
            out.append({"text": text, "done": done})
        if len(out) >= 100:
            break
    return out


def _sort_cards(cards: list[BoardCard]) -> list[BoardCard]:
    # Fractional order_key ascending; equal keys tiebreak by card_id ascending
    # (deterministic on every machine).
    return sorted(cards, key=lambda c: (c.order_key, c.card_id))


def _order_key_of(cards: list[BoardCard], card_id: str | None) -> str | None:
    if not card_id:
        return None
    for card in cards:
        if card.card_id == card_id:
            return card.order_key
    return None


def _safe_idempotency_key(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text) else None
