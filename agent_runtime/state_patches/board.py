"""The board lane: the ``board_card`` wire row (built by the snapshot's own row
builder) and its two emitters — upsert and refresh.

Plan: ``docs/agent-runtime-harness/planned/board-card-fold-2026-10-15.md``
(S1, S2). Measured before it was built (S0, 2026-10-25): a card move acked in
10–12 ms and every subscriber then received the demoted ~668 KB full core
2.0–2.4 s later.
"""

from __future__ import annotations

from typing import Any

from ..config import AgentRuntimeConfig
from ..events import EventLog
from ..models import payload_bytes
from .emit import delta_patches_enabled, emit_state_patch
from .models import (
    BOARD_CARD_ENTITY,
    PATCH_OP_REFRESH,
    PATCH_OP_UPSERT,
    PATCH_VALUE_BUDGET_BYTES,
)
from .payload import board_card_patch_id

__layer__ = "stores"


def project_board_card_wire_row(card: Any) -> dict[str, Any]:
    """The board-card WIRE row, produced by the SNAPSHOT's own row builder.

    ``snapshot.boards.board_card_row`` is pure (a field copy plus the secret
    mask and the description cut), so calling it makes byte-parity with a full
    rebuild structural: a field added to the projection reaches the patch in
    the same commit.

    ``unpublished`` is recomputed here for the reason the office twin gives
    (``state_patches.office.project_office_actor_wire_row``): an edit or a
    move changes the card's content hash, so a realm-bound card can flip
    ``unpublished`` on this very write.
    """

    from ..snapshot.boards import board_card_row

    return board_card_row(card, unpublished=_board_card_unpublished(card))


def _board_card_unpublished(card: Any) -> bool | None:
    """``True``/``False`` for a realm-bound board's card, ``None`` (key
    omitted) otherwise — ``snapshot.boards._boards_summary``'s
    ``_card_unpublished`` closure, reproduced.

    That closure resolves the realm through the snapshot's workspace list,
    which excludes archived workspaces, so a card under an archived workspace
    resolves to ``None`` there and must here. Best-effort: a publication flag
    never takes a board write down.
    """

    try:
        from ..board_models import board_content_hash
        from ..board_store import BoardStore
        from ..board_sync import read_board_baseline
        from ..store import WorkspaceStore

        board_id = str(getattr(card, "board_id", "") or "")
        board = BoardStore().get(board_id)
        workspace = WorkspaceStore().get(str(getattr(board, "workspace_id", "") or ""))
        if getattr(workspace, "archived", False):
            return None
        realm_id = getattr(workspace, "realm_id", None)
        if not realm_id:
            return None
        baseline = read_board_baseline(str(realm_id))
        return baseline.get(f"{board_id}:card:{card.card_id}") != board_content_hash(card)
    except Exception:
        return None


def emit_board_card_patch(
    event_log: EventLog,
    card: Any,
    *,
    created: bool = False,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit a ``board_card`` ``upsert`` carrying the card's COMPLETE wire row.

    Complete, like ``office_actor``'s: the store rewrites a card file whole, so
    the fold is a plain row replace — and insert-on-absent for a create, which
    ``created=True`` marks. The client re-sorts the column by
    ``(order_key, card_id)``, the snapshot's own order, and derives
    ``active_card_count`` from the rows it holds (§ Owner decision 2).

    **Whole row or nothing.** A row past :data:`PATCH_VALUE_BUDGET_BYTES` (a
    long description plus a checklist can reach it) would leave
    ``build_state_patch`` marking its largest field ``oversize`` — a partial
    row a REPLACE fold would write over the real one. So such a write emits the
    accounted :func:`emit_board_card_refresh` instead, and its batch demotes.
    """

    if not delta_patches_enabled(config):
        return False
    row = project_board_card_wire_row(card)
    if payload_bytes(row) > PATCH_VALUE_BUDGET_BYTES:
        return emit_board_card_refresh(
            event_log, card.board_id, card.card_id, correlation_id=correlation_id, config=config
        )
    return emit_state_patch(
        event_log,
        entity=BOARD_CARD_ENTITY,
        entity_id=board_card_patch_id(card.board_id, card.card_id),
        op=PATCH_OP_UPSERT,
        changed=row,
        created=True if created else None,
        correlation_id=correlation_id,
        config=config,
    )


def emit_board_card_refresh(
    event_log: EventLog,
    board_id: Any,
    card_id: Any,
    *,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """The accounted degrade for a card write no fold can express.

    Three producers: a row over the value budget (above), a board whose card
    list is TRUNCATED in the projection (past ``MAX_BOARD_CARDS_PROJECTED`` the
    cut is chosen by order, so a move or a create changes which cards survive
    it), and a board with an unreadable card file (``cards_unreadable`` rides
    the board row, which no card patch moves). ``refresh`` is not foldable, so
    the batch demotes to the full core — the refetch. Emitting it, rather than
    staying silent, keeps the paired covered ``board.card.*`` event from being
    the only entry of a coverable batch: a patch frame with an EMPTY
    ``patches`` list, which a client folds as "nothing changed".
    """

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=BOARD_CARD_ENTITY,
        entity_id=board_card_patch_id(board_id, card_id),
        op=PATCH_OP_REFRESH,
        correlation_id=correlation_id,
        config=config,
    )
