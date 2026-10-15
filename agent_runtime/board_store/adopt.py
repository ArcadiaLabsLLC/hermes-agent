"""The realm-pull arms on the board store: ``adopt_remote_board``,
``adopt_remote_card`` and ``resolve_conflict``. ``BoardStore`` delegates each in
one line, so the verb a caller names is unchanged; this module holds the rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hermes_time import now

from .. import paths
from ..errors import NotFound, SyncConflict
from ..locks import board_lock
from ..models import Board, BoardCard
from ..serde import from_jsonable, read_json, safe_id
from ..store_conflicts import archive_conflict_sidecar
from ..sync_merge import merge_archived_ledgers
from .files import (
    _write_board,
    _write_card,
    archive_card_locked,
    board_id_of_conflict,
    card_path_active,
    locate_card,
)
from .models import ARCHIVED_LEDGER_CAP, _safe_actor

if TYPE_CHECKING:
    from .store import BoardStore

__layer__ = "stores"


def adopt_remote_board(store: BoardStore, board: Board, *, updated_by: str = "realm_sync") -> Board:
    """Write a PEER's board DEF verbatim — the realm pull's board-def arm.

    The board family's half of the H1 asymmetry, closed here for the reason
    ``OfficeStore.adopt_remote_surface`` closed the office family's:
    ``board_sync.apply_board_pull`` wrote this row with a raw
    ``atomic_json_write``, so a pull that ARCHIVED a card emitted
    ``board.card.archived`` and reached every live consumer while a pull that
    GAVE you a board — or renamed a column, or changed the whole column
    taxonomy — emitted nothing at all: no batch, no delta frame, no
    ``harness events tail`` line. This module's own standing rule (see the
    module docstring: an event on EVERY mutation, because an event-less write
    is invisible to the watermark-gated snapshot/serve pipeline) had one lane
    exempt from it by accident.

    A verb of its own rather than ``update_board``, for the office twin's
    reason: ``update_board`` authors LOCAL intent — it BUMPS the revision and
    re-times the row — while a pull adopts a record the peer already
    numbered. Renumbering here would hand the next ``classify_board_pull`` a
    row that looks locally edited, turning every later pull of an untouched
    board into a conflict.

    ``updated_by`` records the SYNC, matching the archive arm
    (``archive_card(..., reason="remote_removed")``). Hash-neutral:
    ``board_models.board_content_hash`` excludes ``updated_by`` along with
    ``revision`` and the timestamps, so the caller's ``baseline[key] =
    remote_hash`` stays keyed off the remote CONTENT.

    Verbatim in every field EXCEPT ``archived_card_ids``, which is UNIONED
    with the local ledger (:func:`sync_merge.merge_archived_ledgers`) —
    operator ruling 2026-09-03, closing the last leg of the H1 asymmetry.
    That field is not the peer's opinion about this board: it is the
    resurrection guard, and the pull is the one lane that can reach it from
    outside this machine. Adopting it wholesale erased any tombstone the
    peer had not heard of, which is a deletion of the exact evidence
    ``classify_board_pull(..., locally_archived=…)`` reads to refuse a
    resurrection. Reachable, not theoretical: publish records the LOCAL hash
    as the baseline, so an install that archives a card and publishes is
    ``unchanged`` on its next pull — and one peer edit away from
    ``take_remote`` over its own ledger.

    The merge is hash-neutral wherever nothing was actually lost (the peer's
    order leads, so a local subset re-hashes to the remote's exact list); it
    is deliberately hash-CHANGING when a local-only id survives, which leaves
    the board classified as locally edited until the next publish carries the
    fuller ledger back to the realm. That is the honest state: this install
    now holds a ledger the realm has not seen.
    """

    bid = safe_id(board.board_id)
    if not bid:
        raise ValueError("invalid_request")
    board.board_id = bid
    board.updated_by = _safe_actor(updated_by)
    with board_lock(bid):
        existed = store.exists(bid)
        if existed:
            # Read INSIDE the lock that will hold for the write: a local
            # archive racing this pull must land on one side of the union or
            # the other, never between the read and the write. The surface
            # twin's discipline, for the surface twin's reason.
            board.archived_card_ids = merge_archived_ledgers(
                board.archived_card_ids,
                store.get(bid).archived_card_ids,
                cap=ARCHIVED_LEDGER_CAP,
            )
        _write_board(board)
        if existed:
            store._emit(
                "board.updated",
                board_id=bid,
                change="realm_sync",
                title=board.title,
                revision=board.revision,
            )
        else:
            store._emit(
                "board.created",
                board_id=bid,
                workspace_id=board.workspace_id,
                title=board.title,
            )
    return board


def adopt_remote_card(
    store: BoardStore,
    card: BoardCard,
    *,
    board_id: str | None = None,
    updated_by: str = "realm_sync",
) -> BoardCard:
    """Write a PEER's CARD verbatim — the realm pull's adopt/converge arm,
    and the half that actually puts a card on somebody's board.

    Twin of :meth:`adopt_remote_board` above and of
    ``OfficeStore.adopt_remote_actor``; every property that docstring pins
    holds here. The revision is the REMOTE's (no ``+1``), nothing is
    re-derived from the write (the caller keys its baseline off the REMOTE
    content hash and this verb returns the object it wrote), and the event is
    the one a LOCAL write of the same shape emits — ``board.card.created``
    for a card this board did not have, ``board.card.edited`` for one it did.
    A consumer tailing the board lane therefore cannot tell "a peer gave me
    this card" from "somebody added it" by the event's SHAPE, only by its
    ``realm_sync`` attribution, and that symmetry is the point: the FACT that
    changed is the same either way.

    NOT guarded by ``_guard_no_conflict``, and that is the pull's rule rather
    than an omission: the pull is exactly the lane that DECIDES a card is a
    conflict (``apply_board_pull`` writes the sidecar on its ``CONFLICT`` arm
    and never reaches this verb for that card), so consulting the guard here
    would refuse to adopt a card whose conflict this same pass is about to
    file, with no operator present to take the refusal. Same discriminator
    ``OfficeStore.adopt_remote_actor`` records for the fences it does not
    spend: those refuse LOCAL authoring intent, and a pull has none.
    """

    bid = safe_id(board_id or card.board_id)
    cid = safe_id(card.card_id)
    if not bid or not cid:
        raise ValueError("invalid_request")
    card.board_id = bid
    card.card_id = cid
    card.updated_by = _safe_actor(updated_by)
    with board_lock(bid):
        # ABSENCE asked under the lock that will hold for the write — the
        # question that picks the event, and the only thing it turns on.
        existed = card_path_active(bid, cid)
        _write_card(card)
        if existed:
            store._emit(
                "board.card.edited",
                board_id=bid,
                card_id=cid,
                fields="realm_sync",
                revision=card.revision,
            )
        else:
            store._emit(
                "board.card.created",
                board_id=bid,
                card_id=cid,
                title=card.title,
                column_id=card.column_id,
                created_by=card.created_by,
            )
    return card


def resolve_conflict(store: BoardStore, card_id: str, *, take: str, board_id: str | None = None, updated_by: str = "operator") -> BoardCard | None:
    """Resolve a realm-sync conflict sidecar for a card. ``take=local`` keeps
    the local card; ``take=remote`` adopts the sidecar's remote copy (or
    archives the local card for an edit-vs-remove tombstone). Always archives
    the sidecar and emits ``board.card.conflict_resolved``."""

    take = str(take or "").strip().lower()
    if take not in {"local", "remote"}:
        raise ValueError("invalid_request")
    board_id, _ = locate_card(card_id, board_id=board_id, allow_missing=True)
    if not board_id:
        board_id = board_id_of_conflict(card_id)
    if not board_id:
        raise NotFound(f"card:{card_id}")
    with board_lock(board_id):
        sidecar_path = paths.board_conflict_path(board_id, card_id)
        if not sidecar_path.exists():
            raise SyncConflict(f"no_conflict:{card_id}")
        sidecar = read_json(sidecar_path)
        result_card: BoardCard | None = None
        if take == "local":
            # Keep the local card as-is; simply clear the conflict.
            if card_path_active(board_id, card_id):
                result_card = store.get_card(card_id, board_id=board_id)
        else:  # take == remote
            remote = sidecar.get("remote_card")
            if isinstance(remote, dict):
                card = from_jsonable(BoardCard, remote)
                card.board_id = board_id
                card.state = "active"
                card.revision = max(int(card.revision or 1), 1) + 1
                card.updated_at = now()
                card.updated_by = _safe_actor(updated_by)
                _write_card(card)
                result_card = card
            else:
                # Remote removed the card (edit-vs-remove) → archive local.
                if card_path_active(board_id, card_id):
                    board = store.get(board_id)
                    card = store.get_card(card_id, board_id=board_id)
                    archive_card_locked(board, card, reason="remote_removed", updated_by=updated_by, emit=None)
        archive_conflict_sidecar(
            sidecar_path,
            paths.board_conflicts_dir(board_id) / f"{paths.safe_path_token(card_id)}.resolved.json",
            fallback={"card_id": card_id},
        )
        store._emit(
            "board.card.conflict_resolved",
            board_id=board_id,
            card_id=card_id,
            take=take,
            revision=getattr(result_card, "revision", None),
        )
    return result_card
