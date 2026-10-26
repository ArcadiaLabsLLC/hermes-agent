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
from typing import TYPE_CHECKING

from ..models import BoardCard

if TYPE_CHECKING:
    from .store import BoardStore

__layer__ = "stores"

logger = logging.getLogger(__name__)


def emit_card_patch(store: BoardStore, card: BoardCard, *, created: bool = False) -> None:
    """Emit the card's ``board_card`` upsert — or the accounted ``refresh``
    when the board's projected card list is not complete.

    Past ``MAX_BOARD_CARDS_PROJECTED`` the snapshot ships a CUT of the active
    cards chosen by ``(order_key, card_id)``; a move or a create changes which
    cards survive it, which no client can reproduce. An unreadable card file
    shortens the list the other way (``cards_unreadable`` rides the board row).
    Either demotes the write to the full core.

    Best-effort: a patch-lane fault never takes a card write down — a missing
    patch is a missing PROMOTION, and the stream then demotes the batch whose
    covered event lost its pair (the class name rides the warning so that
    demote is attributable).
    """

    try:
        from ..snapshot.boards import MAX_BOARD_CARDS_PROJECTED
        from ..state_patches.board import emit_board_card_patch, emit_board_card_refresh

        scan = store.scan_cards(card.board_id)
        if scan.unreadable or len(scan.cards) > MAX_BOARD_CARDS_PROJECTED:
            emit_board_card_refresh(store.event_log, card.board_id, card.card_id)
        else:
            emit_board_card_patch(store.event_log, card, created=created)
    except Exception as exc:
        logger.warning(
            "board card patch emit failed: %s error=%s",
            card.card_id,
            type(exc).__name__,
            exc_info=True,
        )
