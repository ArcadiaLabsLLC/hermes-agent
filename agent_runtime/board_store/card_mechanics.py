"""The two mechanisms every card write consults under the board lock.

* :class:`CardOrdering` — THE one ordering read (:meth:`CardOrdering.cards`,
  which refuses a column it cannot fully see) and the three key decisions over
  it: append, allocate-between, rebalance.
* :class:`IdempotencyReceipts` — replay with typed refusals, and the per-board,
  per-verb receipt write.
"""

from __future__ import annotations

from collections.abc import Callable

from hermes_time import now
from utils import atomic_json_write

from .. import board_order, paths
from ..errors import (
    CardsUnreadable,
    IdempotencyKeyVerbMismatch,
    IdempotentReplayUnresolved,
    NotFound,
)
from ..models import BoardCard
from ..serde import from_jsonable, read_json, to_jsonable
from .files import _write_card, scan_active_cards
from .models import _order_key_of, _safe_idempotency_key, _sort_cards

__layer__ = "stores"


class CardOrdering:
    """Order keys for one board's columns. ``emit`` is the store's event append
    (a rebalance is a mutation and rides its own ``board.rebalanced``)."""

    def __init__(self, board_id: str, emit: Callable[..., None]) -> None:
        self.board_id = board_id
        self.emit = emit

    def cards(self) -> list[BoardCard]:
        """THE read every order-key decision goes through, and the one place
        that refuses.

        One chokepoint rather than a guard on each of the three allocators: two
        sufficient mechanisms answering the same question is how a fix survives
        its own sabotage and stops being a check. Every caller below allocates
        or rewrites keys, so none of them may proceed on a column it cannot
        fully see.
        """

        board_id = self.board_id

        scan = scan_active_cards(board_id)
        if scan.unreadable:
            raise CardsUnreadable(
                f"cards_unreadable board={board_id} unreadable={scan.unreadable}"
            )
        return scan.cards

    def next_key(self, column_id: str) -> str:
        cards = _sort_cards([c for c in self.cards() if c.column_id == column_id])
        last = cards[-1].order_key if cards else None
        return board_order.allocate_between(last, None)

    def allocate(self, column_id: str, *, before: str | None, after: str | None, exclude_card_id: str | None) -> str:
        column_cards = _sort_cards(
            [c for c in self.cards() if c.column_id == column_id and c.card_id != exclude_card_id]
        )
        keys = [c.order_key for c in column_cards]
        # ``after`` = the card the moved card should sit immediately AFTER (its
        # upper neighbour → lower key bound); ``before`` = the card it should sit
        # immediately BEFORE (its lower neighbour → upper key bound). Either may
        # be given alone (the missing bound is derived from the sorted column) or
        # both (an explicit bracket).
        lower_key = _order_key_of(column_cards, after)   # after → lower bound
        upper_key = _order_key_of(column_cards, before)  # before → upper bound
        if lower_key is None and upper_key is None:
            return board_order.allocate_between(keys[-1] if keys else None, None)
        if lower_key is not None and upper_key is None:
            idx = next((i for i, c in enumerate(column_cards) if c.card_id == after), None)
            if idx is not None:
                upper_key = column_cards[idx + 1].order_key if idx + 1 < len(column_cards) else None
        elif upper_key is not None and lower_key is None:
            idx = next((i for i, c in enumerate(column_cards) if c.card_id == before), None)
            if idx is not None:
                lower_key = column_cards[idx - 1].order_key if idx - 1 >= 0 else None
        try:
            return board_order.allocate_between(lower_key, upper_key)
        except ValueError:
            # Neighbours out of order or exhausted → rebalance the column, then
            # append at the end (one loud sweep, deterministic keys).
            self.rebalance(column_id, exclude_card_id=exclude_card_id)
            fresh = _sort_cards(
                [c for c in self.cards() if c.column_id == column_id and c.card_id != exclude_card_id]
            )
            return board_order.allocate_between(fresh[-1].order_key if fresh else None, None)

    def rebalance(self, column_id: str, *, exclude_card_id: str | None = None) -> None:
        column_cards = _sort_cards([c for c in self.cards() if c.column_id == column_id])
        if not column_cards:
            return
        keys = board_order.rebalance(len(column_cards))
        for card, key in zip(column_cards, keys):
            if card.order_key == key:
                continue
            card.order_key = key
            card.updated_at = now()
            _write_card(card)
        self.emit("board.rebalanced", board_id=self.board_id, column_id=column_id, card_count=len(column_cards))


class IdempotencyReceipts:
    """One board's idempotency receipts. ``get_card`` is the store's live-card
    read (a replay re-reads the row it describes, never echoes the receipt)."""

    def __init__(self, board_id: str, get_card: Callable[..., BoardCard]) -> None:
        self.board_id = board_id
        self.get_card = get_card

    def replay(self, key: str | None, *, verb: str) -> BoardCard | None:
        """The recorded card for this key, or ``None`` when there is no receipt.

        ``None`` means EXACTLY ONE thing to every caller: nothing has been
        recorded for this key, so go and do the write. It used to mean five
        things — no key, no receipt, an undecodable receipt, a receipt with no
        ``card_id``, and a ``card_id`` resolving to neither a live nor an
        archived card — and the caller ran the write for all five. The last
        three are "a receipt EXISTS and I cannot honour it", where re-running is
        the one thing that must not happen: ``add_card`` mints a new id per
        call, so the key meant to prevent a duplicate created one.

        Those three now refuse :class:`IdempotentReplayUnresolved`. This is the
        board's version of ``agent_create``'s ``actor_fresh: false`` — a replay
        that cannot re-read the row it describes says so rather than inventing
        an answer; the board's ack carries no field to degrade, so it refuses.

        ``verb`` closes the FOURTH way this used to answer wrongly. The receipt
        namespace is one directory per BOARD, and ``add_card``, ``edit_card``
        and ``move_card`` all read it, so a key reused across verbs replayed
        the other verb's card and the second write silently did not happen —
        an unmoved card returned from ``move_card`` with an ack no caller could
        tell from a real move. A receipt whose recorded verb is not this one
        refuses :class:`IdempotencyKeyVerbMismatch`, naming both verbs. That is
        a different class from the three above on purpose: this fault is in the
        REQUEST (retrying is futile; the cure is a distinct key), where those
        are damaged FILES (retrying works once the file is repaired).

        **Backward compatibility, decided here.** A receipt written before this
        change carries no ``verb`` field, and it is honoured EXACTLY as before —
        replayed for whichever verb presents the key. Refusing an unlabelled
        receipt would turn every in-flight key on every existing board into a
        hard failure at upgrade, to protect against a cross-verb reuse that
        already happened and cannot now be undone by refusing. The receipts are
        per-board scratch state that ages out with the board; the fence closes
        as they are rewritten. Only a receipt that STATES a different verb is
        refused.
        """

        board_id = self.board_id

        safe = _safe_idempotency_key(key)
        if not safe:
            return None
        path = paths.board_idempotency_path(board_id, safe)
        if not path.exists():
            return None
        try:
            record = read_json(path)
        except Exception as exc:
            raise IdempotentReplayUnresolved(
                f"idempotency receipt for {safe!r} on board {board_id} could not "
                f"be decoded ({type(exc).__name__}); the write it recorded is not "
                "safe to repeat"
            ) from exc
        recorded_verb = str(record.get("verb") or "").strip()
        if recorded_verb and recorded_verb != str(verb):
            raise IdempotencyKeyVerbMismatch(
                f"idempotency key {safe!r} on board {board_id} was already used by "
                f"{recorded_verb}; it cannot be reused by {verb}. One key names ONE "
                "gesture — replaying the other verb's card here would silently skip "
                "this write. Retry with a key of its own."
            )
        card_id = record.get("card_id")
        if not card_id:
            raise IdempotentReplayUnresolved(
                f"idempotency receipt for {safe!r} on board {board_id} names no "
                "card; the write it recorded is not safe to repeat"
            )
        try:
            return self.get_card(card_id, board_id=board_id)
        except NotFound:
            pass
        # Card archived since; surface the archived copy so replay is stable.
        archive_path = paths.board_archived_card_path(board_id, card_id)
        if not archive_path.exists():
            raise IdempotentReplayUnresolved(
                f"idempotency receipt for {safe!r} on board {board_id} names card "
                f"{card_id}, which is neither live nor archived; cards are never "
                "hard-deleted, so this is a truncated or corrupted write and the "
                "recorded write is not safe to repeat"
            )
        try:
            return from_jsonable(BoardCard, read_json(archive_path))
        except Exception as exc:
            raise IdempotentReplayUnresolved(
                f"idempotency receipt for {safe!r} on board {board_id} names card "
                f"{card_id}, whose archived copy could not be decoded "
                f"({type(exc).__name__}); the recorded write is not safe to repeat"
            ) from exc

    def record(self, key: str | None, card_id: str, *, verb: str) -> None:
        """Write the receipt, naming the VERB that earned it.

        ``verb`` is what makes the namespace per-verb without moving the files:
        the directory stays one per board and the receipt states which gesture
        wrote it, so :meth:`replay` can refuse a key crossing verbs
        instead of replaying the wrong card. A receipt from before this field
        existed reads back with no ``verb`` and is honoured as before.
        """

        board_id = self.board_id

        safe = _safe_idempotency_key(key)
        if not safe:
            return
        atomic_json_write(
            paths.board_idempotency_path(board_id, safe),
            {
                "idempotency_key": safe,
                "card_id": card_id,
                "verb": str(verb),
                "recorded_at": to_jsonable(now()),
            },
            indent=2,
            sort_keys=True,
        )
