"""The ``board_card`` fold's producer half (plan ``board-card-fold-2026-10-15.md``
S1 + S2, row RT-BOARD-CARD-FOLD-RUNTIME; archive / restore / rebalance, row
RT-BOARD-CARD-FOLD-ARCHIVE).

S0 measured the cost this retires: a card move acked in 10–12 ms and every
subscriber then received the demoted ~668 KB full core 2.0–2.4 s later.

Every fixture seeds TWO cards at DIFFERENT revisions (the office suite's
anti-vacuity rule: one row cannot catch a hoisted constant).
"""

from __future__ import annotations

import threading

import pytest

from agent_runtime import state_patches as sp
from agent_runtime.board_store import BoardStore
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.events import EventLog
from agent_runtime.patch_coverage import (
    BOARD_CARD_LIFECYCLE_CAPABILITY,
    HISTORICAL_FOLD_ENTITIES,
    batch_is_patch_coverable,
    batch_required_fold_tokens,
)
from agent_runtime.state_patches import (
    BOARD_CARD_ENTITY,
    PATCH_OP_REFRESH,
    PATCH_OP_REMOVE,
    PATCH_OP_UPSERT,
    STATE_PATCHED_EVENT_TYPE,
    board_card_patch_id,
)
from agent_runtime.store import WorkspaceStore


@pytest.fixture
def set_delta_patches(monkeypatch):
    def _apply(enabled: bool):
        def _loader(*args, **kwargs):
            cfg = load_agent_runtime_config(*args, **kwargs)
            cfg.read_model.delta_patches = enabled
            return cfg

        monkeypatch.setattr(sp.emit, "load_root_runtime_config", _loader)

    return _apply


@pytest.fixture
def seeded_board(isolate_agent_runtime_root):
    """``first`` at revision 2 (added then edited), ``second`` at revision 1."""

    ws = WorkspaceStore().create(name="Boards")
    store = BoardStore()
    board = store.ensure_default_board(ws.id)
    first = store.add_card(board_id=board.board_id, title="first")
    store.edit_card(first.card_id, board_id=board.board_id, title="first, edited")
    second = store.add_card(board_id=board.board_id, title="second")
    assert store.get_card(first.card_id).revision == 2
    assert store.get_card(second.card_id).revision == 1
    return store, board, first.card_id, second.card_id


def _log_end() -> int:
    return max((o for o, _ in EventLog().iter_from_offset(0)), default=-1)


def _since(offset: int) -> list:
    return [e for o, e in EventLog().iter_from_offset(0) if o > offset]


def _board_patches(events) -> list[dict]:
    return [
        e.payload
        for e in events
        if e.type == STATE_PATCHED_EVENT_TYPE and e.payload.get("entity") == BOARD_CARD_ENTITY
    ]


def _queued_column(board) -> str:
    return next(c.column_id for c in board.columns if c.column_id != board.columns[0].column_id)


@pytest.mark.parametrize("verb", ["add", "edit", "move"])
def test_each_card_write_emits_its_complete_row_before_the_domain_event(
    verb, seeded_board, set_delta_patches
):
    store, board, first_id, second_id = seeded_board
    set_delta_patches(True)
    before = _log_end()
    if verb == "add":
        card = store.add_card(board_id=board.board_id, title="third")
        event_type = "board.card.created"
    elif verb == "edit":
        card = store.edit_card(second_id, board_id=board.board_id, description="more")
        event_type = "board.card.edited"
    else:
        card = store.move_card(first_id, column_id=_queued_column(board), board_id=board.board_id)
        event_type = "board.card.moved"
    events = _since(before)
    patches = _board_patches(events)
    assert len(patches) == 1, patches
    (patch,) = patches
    assert patch["op"] == PATCH_OP_UPSERT
    assert patch["id"] == board_card_patch_id(board.board_id, card.card_id)
    # The row a full rebuild projects for this card, byte for byte.
    from agent_runtime.snapshot.boards import _boards_summary

    rebuilt = _boards_summary(BoardStore(), WorkspaceStore().list_all()).boards
    (row,) = [r for b in rebuilt for r in b["cards"] if r["card_id"] == card.card_id]
    assert patch["changed"] == row
    assert patch["changed"]["revision"] == card.revision
    assert patch.get("created") is (True if verb == "add" else None)
    types = [e.type for e in events]
    assert types.index(STATE_PATCHED_EVENT_TYPE) < types.index(event_type), types


def test_a_card_write_batch_promotes_only_for_a_client_that_declares_board_card(
    seeded_board, set_delta_patches
):
    store, board, first_id, _ = seeded_board
    set_delta_patches(True)
    before = _log_end()
    store.edit_card(first_id, board_id=board.board_id, title="renamed")
    events = _since(before)
    assert _board_patches(events), events
    # Positive control: the same batch promotes once the entity is declared.
    assert batch_is_patch_coverable(events, fold_entities=HISTORICAL_FOLD_ENTITIES | {BOARD_CARD_ENTITY})
    # A client that never heard of it keeps its full core.
    assert not batch_is_patch_coverable(events, fold_entities=None)
    assert not batch_is_patch_coverable(events, fold_entities=HISTORICAL_FOLD_ENTITIES)


_CARD_ONLY = HISTORICAL_FOLD_ENTITIES | {BOARD_CARD_ENTITY}
_LIFECYCLE = _CARD_ONLY | {BOARD_CARD_LIFECYCLE_CAPABILITY}


def _rebuilt_board(board_id: str) -> dict:
    from agent_runtime.snapshot.boards import _boards_summary

    (row,) = [
        b for b in _boards_summary(BoardStore(), WorkspaceStore().list_all()).boards if b["board_id"] == board_id
    ]
    return row


def _mirror_fold(held: dict, patches: list[dict]) -> dict:
    """The fold the lifecycle token names, written out: splice / replace /
    insert by id, re-sort by ``(order_key, card_id)``, recount, and mirror the
    ``archived_card_ids`` ledger. The tests compare its result with a full
    rebuild, so a producer that left any board-row move out reddens here."""

    from agent_runtime.board_store.models import ARCHIVED_LEDGER_CAP

    board = {**held, "cards": list(held["cards"]), "archived_card_ids": list(held["archived_card_ids"])}
    for patch in patches:
        card_id = patch["id"].split("/", 1)[1]
        cards = [c for c in board["cards"] if c["card_id"] != card_id]
        if patch["op"] == PATCH_OP_REMOVE:
            if card_id not in board["archived_card_ids"]:
                board["archived_card_ids"] = [*board["archived_card_ids"], card_id][-ARCHIVED_LEDGER_CAP:]
        else:
            assert patch["op"] == PATCH_OP_UPSERT, patch
            cards.append(patch["changed"])
            if patch.get("created") is True:
                board["archived_card_ids"] = [c for c in board["archived_card_ids"] if c != card_id]
        board["cards"] = sorted(cards, key=lambda c: (c["order_key"], c["card_id"]))
        board["active_card_count"] = len(board["cards"])
    return board


def _without_updated_at(board: dict) -> dict:
    # The board def's ``updated_at`` has no launcher reader (patch_coverage's
    # audit); everything else must match the rebuild byte for byte.
    return {k: v for k, v in board.items() if k != "updated_at"}


def test_an_archive_emits_a_remove_that_folds_to_the_rebuilt_board(seeded_board, set_delta_patches):
    store, board, first_id, second_id = seeded_board
    set_delta_patches(True)
    held = _rebuilt_board(board.board_id)
    before = _log_end()
    store.archive_card(first_id, board_id=board.board_id)
    events = _since(before)
    patches = _board_patches(events)
    assert [(p["op"], p["id"]) for p in patches] == [
        (PATCH_OP_REMOVE, board_card_patch_id(board.board_id, first_id))
    ]
    assert "changed" not in patches[0]
    types = [e.type for e in events]
    assert types.index(STATE_PATCHED_EVENT_TYPE) < types.index("board.card.archived"), types
    rebuilt = _rebuilt_board(board.board_id)
    assert first_id in rebuilt["archived_card_ids"]
    assert _without_updated_at(_mirror_fold(held, patches)) == _without_updated_at(rebuilt)
    assert [c["card_id"] for c in rebuilt["cards"]] == [second_id]


def test_a_restore_emits_a_complete_create_that_folds_to_the_rebuilt_board(seeded_board, set_delta_patches):
    store, board, first_id, _ = seeded_board
    store.archive_card(first_id, board_id=board.board_id)
    set_delta_patches(True)
    held = _rebuilt_board(board.board_id)
    assert first_id in held["archived_card_ids"]
    before = _log_end()
    card = store.restore_card(first_id, board_id=board.board_id)
    events = _since(before)
    patches = _board_patches(events)
    assert [(p["op"], p.get("created")) for p in patches] == [(PATCH_OP_UPSERT, True)]
    assert patches[0]["changed"]["revision"] == card.revision
    types = [e.type for e in events]
    assert types.index(STATE_PATCHED_EVENT_TYPE) < types.index("board.card.restored"), types
    rebuilt = _rebuilt_board(board.board_id)
    assert first_id not in rebuilt["archived_card_ids"]
    assert _without_updated_at(_mirror_fold(held, patches)) == _without_updated_at(rebuilt)


@pytest.mark.parametrize("verb", ["archive", "restore"])
def test_a_lifecycle_batch_promotes_only_for_a_client_that_names_the_lifecycle_token(
    verb, seeded_board, set_delta_patches
):
    store, board, first_id, _ = seeded_board
    if verb == "restore":
        store.archive_card(first_id, board_id=board.board_id)
    set_delta_patches(True)
    before = _log_end()
    if verb == "archive":
        store.archive_card(first_id, board_id=board.board_id)
    else:
        store.restore_card(first_id, board_id=board.board_id)
    events = _since(before)
    assert batch_is_patch_coverable(events, fold_entities=_LIFECYCLE)
    assert batch_required_fold_tokens(events) == {BOARD_CARD_ENTITY, BOARD_CARD_LIFECYCLE_CAPABILITY}
    # The fielded ``board_card`` fold answers a remove with patch_unknown_op and
    # does not mirror the ledger: it keeps its full core.
    assert not batch_is_patch_coverable(events, fold_entities=_CARD_ONLY)
    assert not batch_is_patch_coverable(events, fold_entities=None)


def test_a_no_tombstone_archive_takes_the_refresh(seeded_board, set_delta_patches):
    """The realm-revert arm writes no ledger entry, so a remove's ledger mirror
    would invent one."""

    store, board, first_id, _ = seeded_board
    set_delta_patches(True)
    before = _log_end()
    store.archive_card(first_id, board_id=board.board_id, record_tombstone=False)
    events = _since(before)
    assert [p["op"] for p in _board_patches(events)] == [PATCH_OP_REFRESH]
    assert not batch_is_patch_coverable(events, fold_entities=_LIFECYCLE)


@pytest.mark.parametrize("verb", ["archive", "restore"])
def test_a_flip_of_the_board_rows_unpublished_takes_the_refresh(
    verb, seeded_board, set_delta_patches, monkeypatch
):
    store, board, first_id, _ = seeded_board
    if verb == "restore":
        store.archive_card(first_id, board_id=board.board_id)
    set_delta_patches(True)
    flags = iter([False, True])
    monkeypatch.setattr(
        "agent_runtime.state_patches.board.board_def_unpublished", lambda _board: next(flags)
    )
    before = _log_end()
    if verb == "archive":
        store.archive_card(first_id, board_id=board.board_id)
    else:
        store.restore_card(first_id, board_id=board.board_id)
    assert [p["op"] for p in _board_patches(_since(before))] == [PATCH_OP_REFRESH]


def test_an_archive_from_a_cut_list_takes_the_refresh(seeded_board, set_delta_patches, monkeypatch):
    """Two active cards, a cut of ONE: after the archive one card is left, which
    fits — but the client held the cut, so the departed card is counted back."""

    store, board, first_id, _ = seeded_board
    set_delta_patches(True)
    monkeypatch.setattr("agent_runtime.snapshot.boards.MAX_BOARD_CARDS_PROJECTED", 1)
    before = _log_end()
    store.archive_card(first_id, board_id=board.board_id)
    assert [p["op"] for p in _board_patches(_since(before))] == [PATCH_OP_REFRESH]


def test_a_rebalancing_move_emits_one_row_per_rewritten_card_and_promotes(
    seeded_board, set_delta_patches, monkeypatch
):
    """Force the allocator to exhaust so the move rebalances its column: the
    sweep's rows land before ``board.rebalanced``, the moved card's after, and
    the folded board equals the rebuild under bare ``board_card``."""

    store, board, first_id, second_id = seeded_board
    third = store.add_card(board_id=board.board_id, title="third")
    set_delta_patches(True)
    import agent_runtime.board_order as board_order

    real = board_order.allocate_between
    calls = {"n": 0}

    def exhausted_once(lower, upper):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("exhausted")
        return real(lower, upper)

    monkeypatch.setattr(board_order, "allocate_between", exhausted_once)
    held = _rebuilt_board(board.board_id)
    before = _log_end()
    column_id = store.get_card(first_id).column_id
    assert third.column_id == column_id
    store.move_card(third.card_id, column_id=column_id, after=first_id, board_id=board.board_id)
    events = _since(before)
    types = [e.type for e in events]
    assert "board.rebalanced" in types, types
    patches = _board_patches(events)
    assert all(p["op"] == PATCH_OP_UPSERT for p in patches), patches
    rebalanced_at = types.index("board.rebalanced")
    sweep = [e for e in events[:rebalanced_at] if e.type == STATE_PATCHED_EVENT_TYPE]
    assert {e.payload["id"].split("/", 1)[1] for e in sweep} <= {first_id, second_id, third.card_id}
    assert sweep, "the rebalance rewrote keys with no row"
    assert _without_updated_at(_mirror_fold(held, patches)) == _without_updated_at(_rebuilt_board(board.board_id))
    assert batch_is_patch_coverable(events, fold_entities=_CARD_ONLY)
    assert not batch_is_patch_coverable(events, fold_entities=HISTORICAL_FOLD_ENTITIES)


def test_a_truncated_board_takes_the_accounted_refresh(seeded_board, set_delta_patches, monkeypatch):
    store, board, first_id, _ = seeded_board
    set_delta_patches(True)
    monkeypatch.setattr("agent_runtime.snapshot.boards.MAX_BOARD_CARDS_PROJECTED", 1)
    before = _log_end()
    store.edit_card(first_id, board_id=board.board_id, title="past the cut")
    events = _since(before)
    assert [p["op"] for p in _board_patches(events)] == [PATCH_OP_REFRESH]
    assert not batch_is_patch_coverable(events, fold_entities=HISTORICAL_FOLD_ENTITIES | {BOARD_CARD_ENTITY})


def test_a_row_over_the_value_budget_refreshes_instead_of_a_partial_row(
    seeded_board, set_delta_patches
):
    store, board, first_id, _ = seeded_board
    set_delta_patches(True)
    before = _log_end()
    store.edit_card(first_id, board_id=board.board_id, description="é" * 2000)
    assert [p["op"] for p in _board_patches(_since(before))] == [PATCH_OP_REFRESH]


def test_flag_off_emits_no_board_patch(seeded_board, set_delta_patches):
    store, board, first_id, _ = seeded_board
    set_delta_patches(False)
    before = _log_end()
    store.edit_card(first_id, board_id=board.board_id, title="quiet")
    events = _since(before)
    assert not _board_patches(events)
    assert "board.card.edited" in [e.type for e in events]


def test_a_patch_fault_never_takes_the_card_write_down(seeded_board, set_delta_patches, monkeypatch):
    store, board, first_id, _ = seeded_board
    set_delta_patches(True)

    def _boom(*_a, **_k):
        raise RuntimeError("patch lane down")

    monkeypatch.setattr("agent_runtime.state_patches.board.emit_board_card_patch", _boom)
    before = _log_end()
    card = store.edit_card(first_id, board_id=board.board_id, title="still written")
    assert BoardStore().get_card(card.card_id).title == "still written"
    # The unpaired event never free-rides at a client that cannot fold its row.
    events = _since(before)
    assert [e.type for e in events] == ["board.card.edited"]
    assert not batch_is_patch_coverable(events, fold_entities=HISTORICAL_FOLD_ENTITIES)


def test_a_forced_interleaving_never_inverts_revision_against_offset(
    seeded_board, set_delta_patches, monkeypatch
):
    """S1's killing test. Writer A is held inside its patch emit until writer B
    has finished (or one second passes). With the emit INSIDE ``board_lock`` B
    cannot start its write until A releases, so A's lower revision lands first.
    Move the emit past the lock and B writes, emits and finishes first — the
    revisions land inverted in offset order."""

    _store, board, first_id, _ = seeded_board
    set_delta_patches(True)
    import agent_runtime.board_store.store as store_module

    real = store_module.emit_card_patch
    a_in_emit = threading.Event()
    b_done = threading.Event()
    calls = {"n": 0}

    def held(s, card, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            a_in_emit.set()
            b_done.wait(timeout=1.0)
        return real(s, card, **kwargs)

    monkeypatch.setattr(store_module, "emit_card_patch", held)
    before = _log_end()
    errors: list[BaseException] = []

    def write(title: str, done: threading.Event | None = None) -> None:
        try:
            BoardStore().edit_card(first_id, board_id=board.board_id, title=title)
        except BaseException as exc:  # reported, never swallowed
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    a = threading.Thread(target=write, args=("A",))
    a.start()
    assert a_in_emit.wait(timeout=10)
    b = threading.Thread(target=write, args=("B", b_done))
    b.start()
    a.join(timeout=30)
    b.join(timeout=30)
    assert not errors, errors
    revisions = [p["changed"]["revision"] for p in _board_patches(_since(before))]
    assert len(revisions) == 2, revisions
    assert revisions == sorted(revisions), revisions
