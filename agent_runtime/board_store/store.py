"""``BoardStore`` — the single write chokepoint for the Mission Board domain.

Mirrors the ``WorkspaceStore`` / ``RealmStore`` pattern: file-per-card JSON
under the runtime root, the shared store-lock discipline, atomic writes, and a
typed ``EventLog`` event on EVERY mutation (standing store rule — an event-less
write is invisible to the watermark-gated snapshot/serve pipeline).
"""

from __future__ import annotations

import uuid
from typing import Any

from hermes_time import now

from .. import board_models, paths
from ..errors import (
    AlreadyExists,
    NotFound,
)
from ..events import EventLog
from ..locks import board_lock
from ..models import Board, BoardCard, BoardColumn
from ..serde import from_jsonable, read_json, safe_id
from ..store_conflicts import check_revision
from ..store_events import emit_store_event
from . import adopt
from .card_mechanics import CardOrdering, IdempotencyReceipts
from .files import (
    _write_board,
    _write_card,
    archive_card_locked,
    board_id_of_archived_card,
    guard_card_conflict,
    locate_card,
    scan_active_cards,
    scan_archived_cards,
)
from .models import (
    VERB_ADD_CARD,
    VERB_EDIT_CARD,
    VERB_MOVE_CARD,
    BoardScan,
    CardScan,
    _safe_actor,
    _safe_checklist,
    _safe_labels,
    _safe_text,
    _safe_title,
    _sort_cards,
)

__layer__ = "stores"


class BoardStore:
    def __init__(self, event_log: EventLog | None = None) -> None:
        self.event_log = event_log or EventLog()

    # --- event emission (single chokepoint) ------------------------------

    def _emit(self, event_type: str, **payload: Any) -> None:
        emit_store_event(self.event_log, event_type, payload, domain="board")

    # --- board-level reads ------------------------------------------------

    def get(self, board_id: str) -> Board:
        path = paths.board_def_path(board_id)
        if not path.exists():
            raise NotFound(f"board:{board_id}")
        return from_jsonable(Board, read_json(path))

    def exists(self, board_id: str) -> bool:
        return paths.board_def_path(board_id).exists()

    def scan_all(self, *, include_archived: bool = True) -> BoardScan:
        """Every board this root HAS, plus how many board files did not decode.

        THE chokepoint. ``list_all`` is the thin list view over it, so the many
        callers that only want rows keep their signature while the ones that
        must not describe a short answer as complete — the snapshot projection
        and the realm-publish artifact set — can ask the fuller question.
        """

        root = paths.boards_root()
        boards: list[Board] = []
        unreadable = 0
        if not root.exists():
            return BoardScan([], 0)
        for child in sorted(root.iterdir()):
            def_path = child / "board.json"
            if not def_path.exists():
                continue
            try:
                boards.append(from_jsonable(Board, read_json(def_path)))
            except Exception:
                unreadable += 1
                continue
        return BoardScan(sorted(boards, key=lambda b: b.board_id), unreadable)

    def list_all(self, *, include_archived: bool = True) -> list[Board]:
        return self.scan_all(include_archived=include_archived).boards

    def list_for_workspace(self, workspace_id: str, *, include_archived: bool = True) -> list[Board]:
        wanted = safe_id(workspace_id)
        return [b for b in self.list_all() if b.workspace_id == wanted]

    # --- board-level writes ----------------------------------------------

    def ensure_default_board(self, workspace_id: str, *, created_by: str = "operator") -> Board:
        """Lazily create the deterministic default board for a workspace.

        Idempotent: if the board already exists it is returned unchanged (no
        event). Two machines calling this converge on identical semantic content
        (fixed column ids + timestamp-excluded content hash)."""

        wsid = safe_id(workspace_id)
        if not wsid:
            raise ValueError("invalid_request")
        board_id = board_models.default_board_id(wsid)
        if self.exists(board_id):
            return self.get(board_id)
        with board_lock(board_id):
            if self.exists(board_id):
                return self.get(board_id)
            board = board_models.default_board(wsid, created_at=now(), updated_by=_safe_actor(created_by))
            _write_board(board)
            self._emit("board.created", board_id=board.board_id, workspace_id=board.workspace_id, title=board.title)
        return self.get(board_id)

    def create(
        self,
        *,
        workspace_id: str,
        title: str | None = None,
        board_id: str | None = None,
        columns: list[BoardColumn] | None = None,
        created_by: str = "operator",
    ) -> Board:
        wsid = safe_id(workspace_id)
        if not wsid:
            raise ValueError("invalid_request")
        resolved_id = safe_id(board_id) or f"board_{uuid.uuid4().hex[:10]}"
        if self.exists(resolved_id):
            raise AlreadyExists(resolved_id)
        with board_lock(resolved_id):
            if self.exists(resolved_id):
                raise AlreadyExists(resolved_id)
            ts = now()
            board = Board(
                board_id=resolved_id,
                workspace_id=wsid,
                title=_safe_title(title) or board_models.DEFAULT_BOARD_TITLE,
                columns=columns if columns else board_models.default_board_columns(),
                archived_card_ids=[],
                revision=1,
                created_at=ts,
                updated_at=ts,
                updated_by=_safe_actor(created_by),
            )
            _write_board(board)
            self._emit("board.created", board_id=board.board_id, workspace_id=board.workspace_id, title=board.title)
        return self.get(resolved_id)

    def update_board(
        self,
        board_id: str,
        *,
        title: str | None = None,
        columns: list[BoardColumn] | None = None,
        updated_by: str = "operator",
        expect_revision: int | None = None,
    ) -> Board:
        with board_lock(board_id):
            board = self.get(board_id)
            check_revision(board.revision, expect_revision)
            change = []
            if title is not None:
                board.title = _safe_title(title) or board.title
                change.append("title")
            if columns is not None:
                board.columns = columns
                change.append("columns")
            board.revision += 1
            board.updated_at = now()
            board.updated_by = _safe_actor(updated_by)
            _write_board(board)
            self._emit(
                "board.updated",
                board_id=board.board_id,
                change=",".join(change) or "saved",
                title=board.title,
                revision=board.revision,
            )
        return self.get(board_id)

    # --- card reads -------------------------------------------------------

    def get_card(self, card_id: str, *, board_id: str | None = None) -> BoardCard:
        board_id, path = locate_card(card_id, board_id=board_id)
        if path is None or not path.exists():
            raise NotFound(f"card:{card_id}")
        return from_jsonable(BoardCard, read_json(path))

    def scan_cards(self, board_id: str, *, include_archived: bool = False) -> CardScan:
        """Every card this board HAS, plus how many card files did not decode.

        THE read chokepoint; ``list_cards`` is the thin list view over it. The
        projection asks the fuller question so a rendered board cannot describe
        a column the platform partly ate as complete.
        """

        scan = scan_active_cards(board_id)
        cards = scan.cards
        unreadable = scan.unreadable
        if include_archived:
            archived = scan_archived_cards(board_id)
            cards = [*cards, *archived.cards]
            unreadable += archived.unreadable
        return CardScan(_sort_cards(cards), unreadable)

    def list_cards(self, board_id: str, *, include_archived: bool = False) -> list[BoardCard]:
        return self.scan_cards(board_id, include_archived=include_archived).cards

    # --- card writes ------------------------------------------------------

    def add_card(
        self,
        *,
        board_id: str | None = None,
        workspace_id: str | None = None,
        title: str,
        description: str = "",
        column: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        assignee: str | None = None,
        checklist: list[Any] | None = None,
        created_by: str = "operator",
        idempotency_key: str | None = None,
    ) -> BoardCard:
        clean_title = _safe_title(title)
        if not clean_title:
            raise ValueError("invalid_request")
        board = self._resolve_board_for_write(board_id=board_id, workspace_id=workspace_id, created_by=created_by)
        with board_lock(board.board_id):
            receipts = IdempotencyReceipts(board.board_id, self.get_card)
            replay = receipts.replay(idempotency_key, verb=VERB_ADD_CARD)
            if replay is not None:
                return replay
            board = self.get(board.board_id)
            column_id = board_models.resolve_column_id(board, column)
            if column_id is None:
                raise ValueError("invalid_request")
            order_key = CardOrdering(board.board_id, self._emit).next_key(column_id)
            ts = now()
            actor = _safe_actor(created_by)
            card = BoardCard(
                card_id=f"card_{uuid.uuid4().hex}",
                board_id=board.board_id,
                column_id=column_id,
                title=clean_title,
                order_key=order_key,
                description=_safe_text(description),
                priority=board_models.normalize_priority(priority),
                labels=_safe_labels(labels),
                assignee=safe_id(assignee),
                checklist=_safe_checklist(checklist),
                state="active",
                created_by=actor,
                revision=1,
                created_at=ts,
                updated_at=ts,
                updated_by=actor,
            )
            _write_card(card)
            self._emit(
                "board.card.created",
                board_id=card.board_id,
                card_id=card.card_id,
                title=card.title,
                column_id=card.column_id,
                created_by=card.created_by,
            )
            receipts.record(idempotency_key, card.card_id, verb=VERB_ADD_CARD)
        return self.get_card(card.card_id, board_id=board.board_id)

    def edit_card(
        self,
        card_id: str,
        *,
        board_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        assignee: str | None = None,
        clear_assignee: bool = False,
        checklist: list[Any] | None = None,
        updated_by: str = "operator",
        expect_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> BoardCard:
        board_id, _ = locate_card(card_id, board_id=board_id)
        with board_lock(board_id):
            receipts = IdempotencyReceipts(board_id, self.get_card)
            replay = receipts.replay(idempotency_key, verb=VERB_EDIT_CARD)
            if replay is not None:
                return replay
            card = self.get_card(card_id, board_id=board_id)
            guard_card_conflict(card)
            check_revision(card.revision, expect_revision)
            fields: list[str] = []
            if title is not None:
                card.title = _safe_title(title) or card.title
                fields.append("title")
            if description is not None:
                card.description = _safe_text(description)
                fields.append("description")
            if priority is not None:
                card.priority = board_models.normalize_priority(priority)
                fields.append("priority")
            if labels is not None:
                card.labels = _safe_labels(labels)
                fields.append("labels")
            if clear_assignee:
                card.assignee = None
                fields.append("assignee")
            elif assignee is not None:
                card.assignee = safe_id(assignee)
                fields.append("assignee")
            if checklist is not None:
                card.checklist = _safe_checklist(checklist)
                fields.append("checklist")
            card.revision += 1
            card.updated_at = now()
            card.updated_by = _safe_actor(updated_by)
            _write_card(card)
            self._emit(
                "board.card.edited",
                board_id=card.board_id,
                card_id=card.card_id,
                fields=",".join(fields) or "touched",
                revision=card.revision,
            )
            receipts.record(idempotency_key, card.card_id, verb=VERB_EDIT_CARD)
        return self.get_card(card_id, board_id=board_id)

    def move_card(
        self,
        card_id: str,
        *,
        column_id: str,
        before: str | None = None,
        after: str | None = None,
        board_id: str | None = None,
        updated_by: str = "operator",
        expect_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> BoardCard:
        board_id, _ = locate_card(card_id, board_id=board_id)
        with board_lock(board_id):
            receipts = IdempotencyReceipts(board_id, self.get_card)
            replay = receipts.replay(idempotency_key, verb=VERB_MOVE_CARD)
            if replay is not None:
                return replay
            board = self.get(board_id)
            card = self.get_card(card_id, board_id=board_id)
            guard_card_conflict(card)
            check_revision(card.revision, expect_revision)
            target_column = board_models.resolve_column_id(board, column_id)
            if target_column is None:
                raise ValueError("invalid_request")
            from_column = card.column_id
            order_key = CardOrdering(board_id, self._emit).allocate(
                target_column, before=before, after=after, exclude_card_id=card_id
            )
            card.column_id = target_column
            card.order_key = order_key
            card.revision += 1
            card.updated_at = now()
            card.updated_by = _safe_actor(updated_by)
            _write_card(card)
            self._emit(
                "board.card.moved",
                board_id=card.board_id,
                card_id=card.card_id,
                column_id=card.column_id,
                from_column_id=from_column,
                order_key=card.order_key,
            )
            receipts.record(idempotency_key, card.card_id, verb=VERB_MOVE_CARD)
        return self.get_card(card_id, board_id=board_id)

    def archive_card(
        self,
        card_id: str,
        *,
        board_id: str | None = None,
        reason: str = "operator",
        updated_by: str = "operator",
        record_tombstone: bool = True,
    ) -> BoardCard:
        """Archive one card — the board's delete.

        ``record_tombstone`` is the AUTHORED-vs-DIAGNOSTIC split, the office
        twin's parameter for the office twin's reason (``OfficeStore.
        remove_actor``, operator ruling 2026-08-30 / AX7). Defaulted true, which
        is every caller that carries an operator's intent to delete. ``False``
        is for a repair aimed only at THIS install's projection — the realm-sync
        REVERT lane's ``added`` arm, where the operator is saying "my
        unpublished local row is noise", not "delete this card realm-wide":
        ``archived_card_ids`` rides the PUBLISHED board def, so a tombstone
        minted from a local-only revert would archive the row on every machine
        in the realm. The archive copy is written either way — archive-never-
        delete is not what is being traded, and ``restore_card`` still works.
        """

        board_id, _ = locate_card(card_id, board_id=board_id)
        with board_lock(board_id):
            board = self.get(board_id)
            card = self.get_card(card_id, board_id=board_id)
            archive_card_locked(
                board,
                card,
                reason=reason,
                updated_by=updated_by,
                emit=self._emit,
                record_tombstone=record_tombstone,
            )
            archived = from_jsonable(BoardCard, read_json(paths.board_archived_card_path(board_id, card_id)))
        return archived

    def restore_card(self, card_id: str, *, board_id: str | None = None, updated_by: str = "operator") -> BoardCard:
        board_id = board_id or board_id_of_archived_card(card_id)
        if not board_id:
            raise NotFound(f"card:{card_id}")
        with board_lock(board_id):
            archive_path = paths.board_archived_card_path(board_id, card_id)
            if not archive_path.exists():
                raise NotFound(f"card:{card_id}")
            card = from_jsonable(BoardCard, read_json(archive_path))
            board = self.get(board_id)
            # Re-home to a valid column (its old column may have been deleted).
            if not any(col.column_id == card.column_id for col in board.columns):
                landing = board_models.first_queued_column(board)
                card.column_id = landing.column_id if landing else card.column_id
            card.order_key = CardOrdering(board_id, self._emit).next_key(card.column_id)
            card.state = "active"
            card.revision += 1
            card.updated_at = now()
            card.updated_by = _safe_actor(updated_by)
            _write_card(card)
            archive_path.unlink(missing_ok=True)
            # Drop from the resurrection-guard ledger so it can sync again.
            if card.card_id in board.archived_card_ids:
                board.archived_card_ids = [cid for cid in board.archived_card_ids if cid != card.card_id]
                board.updated_at = now()
                _write_board(board)
            self._emit("board.card.restored", board_id=board_id, card_id=card.card_id, column_id=card.column_id)
        return self.get_card(card_id, board_id=board_id)

    # --- realm-pull adopt arms (the office H1 shape, board family) ---------

    def adopt_remote_board(self, board: Board, *, updated_by: str = "realm_sync") -> Board:
        """Write a PEER's board DEF verbatim — see :func:`.adopt.adopt_remote_board`."""

        return adopt.adopt_remote_board(self, board, updated_by=updated_by)

    def adopt_remote_card(
        self,
        card: BoardCard,
        *,
        board_id: str | None = None,
        updated_by: str = "realm_sync",
    ) -> BoardCard:
        """Write a PEER's CARD verbatim — see :func:`.adopt.adopt_remote_card`."""

        return adopt.adopt_remote_card(self, card, board_id=board_id, updated_by=updated_by)

    def resolve_conflict(self, card_id: str, *, take: str, board_id: str | None = None, updated_by: str = "operator") -> BoardCard | None:
        """Resolve a realm-sync conflict sidecar — see :func:`.adopt.resolve_conflict`."""

        return adopt.resolve_conflict(self, card_id, take=take, board_id=board_id, updated_by=updated_by)

    # --- internal helpers -------------------------------------------------

    def _resolve_board_for_write(self, *, board_id: str | None, workspace_id: str | None, created_by: str) -> Board:
        if board_id:
            if not self.exists(board_id):
                raise NotFound(f"board:{board_id}")
            return self.get(board_id)
        if workspace_id:
            return self.ensure_default_board(workspace_id, created_by=created_by)
        raise ValueError("invalid_request")

    # --- idempotency ledger ----------------------------------------------


