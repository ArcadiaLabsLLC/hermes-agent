"""One card id on two boards: a card verb reaches the board the caller named,
and a verb that names none is refused ``card_ambiguous``.

How an install comes to hold one id twice: a card adopted from a Work row
keeps the row's id, a leave's re-key gives only board-MINTED cards
(``card_<hex32>``) new ids, and a re-join pulls the team's board fresh — so
the local copy's board and the team's board can each hold the same card id
(``RT-REJOIN-CARD-VERB-WITHOUT-BOARD-PICKS-EITHER-COPY``). The twin is seeded
here the way a pull writes it, ``BoardStore.adopt_remote_card``.

Driven through ``serve_rpc.handle_request`` — the entry every
``runtime.board.*`` request takes — and once through the store and the argv
twin's parser.
"""

from __future__ import annotations

import copy
import json

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.board_store import BoardStore
from agent_runtime.errors import CardAmbiguous
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, ERR_NOT_FOUND
from agent_runtime.store import WorkspaceStore

CARD_ID = "row_adopted_from_work"  # not ``card_<hex32>``: the re-key leaves it alone


def _rpc(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def _two_boards() -> tuple[str, str]:
    """The same card id, active, on the local copy's board and on the team's."""

    store = BoardStore()
    local = store.ensure_default_board(WorkspaceStore().create(name="Local copy").id)
    team = store.ensure_default_board(WorkspaceStore().create(name="Team, pulled fresh").id)
    minted = store.add_card(board_id=local.board_id, title="Local copy's card")
    for board, title in ((local, "Local copy's card"), (team, "Team's card")):
        twin = copy.deepcopy(minted)
        twin.card_id, twin.title = CARD_ID, title
        store.adopt_remote_card(twin, board_id=board.board_id)
    store.archive_card(minted.card_id, board_id=local.board_id)
    return local.board_id, team.board_id


def _file(folder, board_id: str) -> dict | None:
    path = folder(board_id, CARD_ID)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _state(boards: tuple[str, str]) -> list:
    """Every copy of the card on both boards: active, archived, conflict sidecar."""

    return [
        [_file(folder, board) for folder in (paths.board_card_path, paths.board_archived_card_path,
                                              paths.board_conflict_path)]
        for board in boards
    ]


def _archive_both(boards: tuple[str, str]) -> None:
    for board in boards:
        BoardStore().archive_card(CARD_ID, board_id=board)


def _conflict_both(boards: tuple[str, str]) -> None:
    for board in boards:
        path = paths.board_conflict_path(board, CARD_ID)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"card_id": CARD_ID, "kind": "both_changed"}), encoding="utf-8")


#: verb -> (what to set up beyond the two active copies, its params beyond the ids)
VERBS = {
    "runtime.board.card.edit": (None, {"title": "Renamed"}),
    "runtime.board.card.move": (None, {"column_id": "done"}),
    "runtime.board.card.archive": (None, {}),
    "runtime.board.card.restore": (_archive_both, {}),
    "runtime.board.resolve_conflict": (_conflict_both, {"take": "local"}),
}


@pytest.mark.parametrize("method", sorted(VERBS))
def test_a_verb_that_names_no_board_is_refused_and_changes_neither_copy(method):
    boards = _two_boards()
    prepare, extra = VERBS[method]
    if prepare is not None:
        prepare(boards)
    before = _state(boards)

    reply = _rpc(method, {"card_id": CARD_ID, **extra})

    assert "error" in reply, reply
    assert reply["error"]["code"] == ERR_INVALID_PARAMS
    assert reply["error"]["data"] == {"reason": "card_ambiguous", "card_id": CARD_ID, "board_ids": sorted(boards)}
    assert _state(boards) == before


@pytest.mark.parametrize("method", sorted(VERBS))
@pytest.mark.parametrize("named", [0, 1])
def test_a_verb_reaches_the_board_it_names_and_leaves_the_twin(method, named):
    boards = _two_boards()
    prepare, extra = VERBS[method]
    if prepare is not None:
        prepare(boards)
    before = _state(boards)

    reply = _rpc(method, {"card_id": CARD_ID, "board_id": boards[named], **extra})

    assert "result" in reply, reply
    assert reply["result"]["card"]["board_id"] == boards[named]
    after = _state(boards)
    assert after[1 - named] == before[1 - named]
    assert after[named] != before[named]


def test_a_named_board_that_does_not_hold_the_card_is_unknown_card_not_the_twin():
    boards = _two_boards()
    other = BoardStore().ensure_default_board(WorkspaceStore().create(name="Third").id).board_id
    before = _state(boards)
    reply = _rpc("runtime.board.card.edit", {"card_id": CARD_ID, "board_id": other, "title": "x"})
    assert (reply["error"]["code"], reply["error"]["data"]["reason"]) == (ERR_NOT_FOUND, "unknown_card")
    assert _state(boards) == before


def test_one_copy_active_and_its_twin_archived_is_still_ambiguous():
    """Archiving one copy must not make the next unnamed verb land on the other."""

    boards = _two_boards()
    BoardStore().archive_card(CARD_ID, board_id=boards[0])
    before = _state(boards)
    for method, extra in (("runtime.board.card.edit", {"title": "x"}), ("runtime.board.card.restore", {})):
        reply = _rpc(method, {"card_id": CARD_ID, **extra})
        assert reply["error"]["data"]["reason"] == "card_ambiguous", (method, reply)
    assert _state(boards) == before


def test_a_card_on_one_board_needs_no_board_named():
    store = BoardStore()
    board = store.ensure_default_board(WorkspaceStore().create(name="Only").id)
    card = store.add_card(board_id=board.board_id, title="Alone")
    reply = _rpc("runtime.board.card.edit", {"card_id": card.card_id, "title": "Still found"})
    assert reply["result"]["card"]["title"] == "Still found"


def test_the_store_read_refuses_too_and_names_the_boards():
    boards = _two_boards()
    with pytest.raises(CardAmbiguous) as caught:
        BoardStore().get_card(CARD_ID)
    assert caught.value.board_ids == tuple(sorted(boards))
    assert BoardStore().get_card(CARD_ID, board_id=boards[1]).title == "Team's card"


@pytest.mark.parametrize("argv", [
    ["card", "edit", CARD_ID, "--title", "Renamed"],
    ["card", "move", CARD_ID, "--column", "done"],
    ["card", "archive", CARD_ID],
    ["card", "restore", CARD_ID],
    ["resolve-conflict", CARD_ID, "--take", "local"],
])
def test_the_argv_twin_takes_the_board_and_hands_it_to_the_store(argv, monkeypatch):
    import argparse

    from hermes_cli.harness_parts import board as board_commands
    from hermes_cli.harness_parts.parser.surfaces import add_board

    boards = _two_boards()
    if argv[1] == "restore":
        _archive_both(boards)
    if argv[0] == "resolve-conflict":
        _conflict_both(boards)
    before = _state(boards)
    parser = argparse.ArgumentParser()
    add_board(parser.add_subparsers(dest="surface"))
    monkeypatch.setattr(board_commands, "_print_stage42", lambda *a, **k: None)

    args = parser.parse_args(["board", *argv, "--board", boards[1]])
    assert args.func(args) == 0

    after = _state(boards)
    assert after[0] == before[0] and after[1] != before[1]


def test_the_argv_twin_without_a_board_exits_as_a_request_to_fix_not_a_crash():
    from hermes_cli.harness_support import ERROR_EXIT_CODES, _error_code_for_exception

    boards = _two_boards()
    with pytest.raises(CardAmbiguous) as caught:
        BoardStore().archive_card(CARD_ID)
    code = _error_code_for_exception(caught.value)
    assert (code, ERROR_EXIT_CODES[code]) == ("card_ambiguous", 2)
    assert all(board in str(caught.value) for board in boards)
