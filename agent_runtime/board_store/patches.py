"""The board store's ``state.patched`` producer: one ``board_card`` row per card
write, emitted from the card just written, INSIDE ``board_lock`` and BEFORE the
paired ``board.card.*`` event.

The placement is the monotonicity guarantee, for the reason
``office_store.patches._emit_actor_patch`` gives at length: ``board_lock`` is a
cross-process file lock, so holding it across (write file → append patch →
append event) makes EventLog order agree with card-revision order. A patch
appended after release admits writer A taking rev 2, writer B rev 3, and B's
append landing first — the client folds rev 3 then rev 2 and holds the older
card with nothing downstream to notice.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..models import BoardCard

if TYPE_CHECKING:
    from .store import BoardStore

__layer__ = "stores"

logger = logging.getLogger(__name__)


def _projection_incomplete(store: BoardStore, board_id: str, *, departed: int = 0) -> bool:
    """Whether a client's held card list for ``board_id`` was, or now is, not
    the board's whole active list — the case no card row can fold.

    Past ``MAX_BOARD_CARDS_PROJECTED`` the snapshot ships a CUT of the active
    cards chosen by ``(order_key, card_id)``; a write that moves, adds or drops
    a card changes which cards survive it, which no client can reproduce. An
    unreadable card file shortens the list the other way (``cards_unreadable``
    rides the board row). ``departed`` is how many cards this write took OUT of
    the active list (1 for an archive): the client still holds the pre-write
    list, so ``len(after) + departed`` is the length it was cut from.
    """

    from ..snapshot.boards import MAX_BOARD_CARDS_PROJECTED

    scan = store.scan_cards(board_id)
    return bool(scan.unreadable) or len(scan.cards) + departed > MAX_BOARD_CARDS_PROJECTED


def board_flag(board: Any) -> bool | None:
    """The board row's ``unpublished`` flag now — taken BEFORE an archive or a
    restore rewrites the board def, so the emitter can tell a flip it cannot
    fold (``state_patches.board.board_def_unpublished``; ``None`` on any
    fault, never raising into the write)."""

    try:
        from ..state_patches.board import board_def_unpublished

        return board_def_unpublished(board)
    except Exception:
        return None


def _warn(card: BoardCard, exc: Exception) -> None:
    logger.warning(
        "board card patch emit failed: %s error=%s",
        card.card_id,
        type(exc).__name__,
        exc_info=True,
    )


def emit_card_patch(store: BoardStore, card: BoardCard, *, created: bool = False) -> None:
    """Emit the card's ``board_card`` upsert — or the accounted ``refresh``
    when the board's projected card list is not complete
    (:func:`_projection_incomplete`).

    Best-effort: a patch-lane fault never takes a card write down — a missing
    patch is a missing PROMOTION, and the stream then demotes the batch whose
    covered event lost its pair (the class name rides the warning so that
    demote is attributable).
    """

    try:
        from ..state_patches.board import emit_board_card_patch, emit_board_card_refresh

        if _projection_incomplete(store, card.board_id):
            emit_board_card_refresh(store.event_log, card.board_id, card.card_id)
        else:
            emit_board_card_patch(store.event_log, card, created=created)
    except Exception as exc:
        _warn(card, exc)


def emit_card_remove(
    store: BoardStore,
    card: BoardCard,
    *,
    ledger_recorded: bool,
    board_flag_before: bool | None,
) -> None:
    """An ARCHIVE's ``board_card`` ``remove`` — or the accounted ``refresh``.

    Called from ``archive_card_locked`` after the archive copy, the active-file
    unlink and the board-def write, and before ``board.card.archived``.

    The remove's fold mirrors the board row's ``archived_card_ids`` (append if
    absent, capped), so it is only emitted when that mirror is the truth:

    * ``ledger_recorded`` false — the diagnostic no-tombstone archive (realm
      revert's ``added`` arm) leaves the ledger untouched, so the client's
      append would invent an entry: refresh.
    * the board row's ``unpublished`` flipped (``board_flag_before`` vs. now):
      ``archived_card_ids`` is in the board's content hash, and no card row
      carries the board flag: refresh.
    * the held list was a cut or short (:func:`_projection_incomplete` with the
      departed card counted back in): refresh.
    """

    try:
        from ..state_patches.board import (
            board_def_unpublished,
            emit_board_card_refresh,
            emit_board_card_remove,
        )

        if (
            not ledger_recorded
            or board_def_unpublished(store.get(card.board_id)) != board_flag_before
            or _projection_incomplete(store, card.board_id, departed=1)
        ):
            emit_board_card_refresh(store.event_log, card.board_id, card.card_id)
        else:
            emit_board_card_remove(store.event_log, card.board_id, card.card_id)
    except Exception as exc:
        _warn(card, exc)


def emit_card_restore(store: BoardStore, card: BoardCard, *, board_flag_before: bool | None) -> None:
    """A RESTORE's complete-row create — the ``created: true`` upsert a card
    create already emits — or the accounted ``refresh``.

    The fold inserts the row and drops its id from the mirrored
    ``archived_card_ids`` (remove if present — ``restore_card``'s own rule, and
    a no-op for a plain create, whose id is never in the ledger). A flip of the
    board row's ``unpublished`` is the one board-row move a card row cannot
    carry, so it refreshes, as :func:`emit_card_remove` does.
    """

    try:
        from ..state_patches.board import board_def_unpublished, emit_board_card_refresh

        if board_def_unpublished(store.get(card.board_id)) != board_flag_before:
            emit_board_card_refresh(store.event_log, card.board_id, card.card_id)
            return
    except Exception as exc:
        _warn(card, exc)
        return
    emit_card_patch(store, card, created=True)


def emit_rebalance_patches(store: BoardStore, board_id: str, cards: list[BoardCard]) -> None:
    """One ``board_card`` upsert per card a column rebalance rewrote — or ONE
    accounted ``refresh`` (which demotes the whole batch) when the held list is
    incomplete.

    A rebalance rewrites sibling ``order_key``s (and ``updated_at``) with no
    revision bump and nothing on the board def, so each rewritten card's
    complete row is the whole of its effect; the fold replaces each row (equal
    revision is accepted — only an OLDER one is refused) and re-sorts. The
    list is scanned ONCE for the whole sweep, not once per card.
    """

    if not cards:
        return
    try:
        from ..state_patches.board import emit_board_card_patch, emit_board_card_refresh

        if _projection_incomplete(store, board_id):
            emit_board_card_refresh(store.event_log, board_id, cards[0].card_id)
            return
        for card in cards:
            emit_board_card_patch(store.event_log, card)
    except Exception as exc:
        _warn(cards[0], exc)
