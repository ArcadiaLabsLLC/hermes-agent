"""The ``board_card`` fold's producer half (plan ``board-card-fold-2026-10-15.md``
S1 + S2, row RT-BOARD-CARD-FOLD-RUNTIME).

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
    HISTORICAL_FOLD_ENTITIES,
    batch_is_patch_coverable,
)
from agent_runtime.state_patches import (
    BOARD_CARD_ENTITY,
    PATCH_OP_REFRESH,
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


def test_archive_stays_uncovered(seeded_board, set_delta_patches):
    store, board, first_id, _ = seeded_board
    set_delta_patches(True)
    before = _log_end()
    store.archive_card(first_id, board_id=board.board_id)
    events = _since(before)
    assert not batch_is_patch_coverable(events, fold_entities=HISTORICAL_FOLD_ENTITIES | {BOARD_CARD_ENTITY})


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

    store, board, first_id, _ = seeded_board
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
