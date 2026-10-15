"""``runtime.board.card.*`` / ``runtime.board.resolve_conflict`` — the board's
console-tier write twins (D2.11 = L4.26).

What the twins must prove:

1. **The ack is the STORE's row**, never the request echoed: fed unnormalized
   input (padded title, duplicate and blank labels), the ack equals
   ``_card_row`` of the card re-read from disk.
2. **``expect_revision`` passes through**: a stale guard is ``stale_revision``
   and the card on disk is unchanged.
3. **``idempotency_key`` passes through**: the same key twice is one card.
4. **All six are ``console``** and the manifest publishes exactly the keys each
   verb reads (the L4.22 ruling).
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import board_models, paths, serve_rpc
from agent_runtime.board_store import BoardStore
from agent_runtime.board_store.rows import _card_row
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.board import BOARD_METHOD_PARAMS
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND
from agent_runtime.store import WorkspaceStore


def _rpc(method: str, params: dict, rid: str = "b1") -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})


def _workspace() -> str:
    ws = WorkspaceStore().create(name="Board twins")
    WorkspaceStore().set_active(ws.id)
    return ws.id


def _card(ws: str, title: str = "Seed"):
    return BoardStore().add_card(workspace_id=ws, title=title)


def _on_disk(card_id: str) -> dict:
    return _card_row(BoardStore().get_card(card_id), full=True)


# ── the ack is the store's row ───────────────────────────────────────────────


def test_add_acks_the_stored_card_not_the_request():
    ws = _workspace()
    reply = _rpc("runtime.board.card.add", {
        "workspace_id": ws, "title": "  Ship it  ", "labels": ["ui", "ui", "  ", "infra"],
        "priority": "P1", "column_id": "active", "correlation_id": "corr-add",
    })
    result = reply["result"]
    card = result["card"]
    assert card == _on_disk(card["id"])
    assert (card["title"], card["labels"], card["priority"], card["column_id"]) == (
        "Ship it", ["ui", "infra"], "p1", "col_active")
    assert result["correlation_id"] == "corr-add"


def test_add_without_board_or_workspace_lands_on_the_active_workspace():
    ws = _workspace()
    card = _rpc("runtime.board.card.add", {"title": "Defaulted"})["result"]["card"]
    assert card["board_id"] == board_models.default_board_id(ws)


def test_edit_move_archive_restore_each_ack_the_store_row():
    ws = _workspace()
    first, card = _card(ws, "Anchor"), _card(ws, "Mover")

    edited = _rpc("runtime.board.card.edit", {"card_id": card.card_id, "title": " Renamed ",
                                              "assignee": "neko", "expect_revision": 1})["result"]["card"]
    assert edited == _on_disk(card.card_id) and edited["title"] == "Renamed" and edited["revision"] == 2

    moved = _rpc("runtime.board.card.move", {"card_id": card.card_id, "column_id": "queued",
                                             "before": first.card_id})["result"]["card"]
    assert moved == _on_disk(card.card_id)
    assert moved["order_key"] < _on_disk(first.card_id)["order_key"]

    archived = _rpc("runtime.board.card.archive", {"card_id": card.card_id})["result"]["card"]
    board_id = board_models.default_board_id(ws)
    stored = json.loads(paths.board_archived_card_path(board_id, card.card_id).read_text(encoding="utf-8"))
    assert archived["state"] == stored["state"] == "archived"
    assert archived["revision"] == stored["revision"]

    restored = _rpc("runtime.board.card.restore", {"card_id": card.card_id})["result"]["card"]
    assert restored == _on_disk(card.card_id) and restored["state"] == "active"


# ── the two guards pass through ──────────────────────────────────────────────


@pytest.mark.parametrize("method,extra", [
    ("runtime.board.card.edit", {"title": "Lost update"}),
    ("runtime.board.card.move", {"column_id": "done"}),
])
def test_a_stale_expect_revision_refuses_and_writes_nothing(method, extra):
    ws = _workspace()
    card = _card(ws)
    before = _on_disk(card.card_id)
    reply = _rpc(method, {"card_id": card.card_id, "expect_revision": 7, **extra})
    assert reply["error"]["code"] == ERR_CONFLICT
    assert reply["error"]["data"] == {"reason": "stale_revision", "card_id": card.card_id, "expect_revision": 7}
    assert _on_disk(card.card_id) == before


def test_the_same_idempotency_key_twice_is_one_card():
    ws = _workspace()
    params = {"workspace_id": ws, "title": "Once", "idempotency_key": "gesture-1"}
    a = _rpc("runtime.board.card.add", params, rid="a")["result"]["card"]
    b = _rpc("runtime.board.card.add", params, rid="b")["result"]["card"]
    assert a["id"] == b["id"]
    assert [c.card_id for c in BoardStore().list_cards(board_models.default_board_id(ws))] == [a["id"]]


def test_a_key_reused_across_verbs_is_refused_by_name():
    ws = _workspace()
    card = _rpc("runtime.board.card.add", {"workspace_id": ws, "title": "K", "idempotency_key": "k"})["result"]["card"]
    reply = _rpc("runtime.board.card.move", {"card_id": card["id"], "column_id": "done", "idempotency_key": "k"})
    assert reply["error"]["code"] == ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "idempotency_key_verb_mismatch"
    assert _on_disk(card["id"])["column_id"] == "col_queued"


# ── refusals ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method,params,code,reason", [
    ("runtime.board.card.edit", {}, ERR_INVALID_PARAMS, "card_id_required"),
    ("runtime.board.card.add", {"title": "  "}, ERR_INVALID_PARAMS, "title_required"),
    ("runtime.board.card.move", {"card_id": "card_x"}, ERR_INVALID_PARAMS, "column_id_required"),
    ("runtime.board.card.edit", {"card_id": "card_x", "priority": "urgent"}, ERR_INVALID_PARAMS, "priority_invalid"),
    ("runtime.board.card.edit", {"card_id": "card_x", "labels": "a,b"}, ERR_INVALID_PARAMS, "labels_invalid"),
    ("runtime.board.card.edit", {"card_id": "card_x", "expect_revision": True}, ERR_INVALID_PARAMS,
     "expect_revision_invalid"),
    ("runtime.board.card.edit", {"card_id": "card_x", "clear_assignee": "yes"}, ERR_INVALID_PARAMS,
     "param_type_invalid"),
    ("runtime.board.resolve_conflict", {"card_id": "card_x", "take": "both"}, ERR_INVALID_PARAMS, "take_invalid"),
    ("runtime.board.card.edit", {"card_id": "card_ghost", "title": "x"}, ERR_NOT_FOUND, "unknown_card"),
    ("runtime.board.card.restore", {"card_id": "card_ghost"}, ERR_NOT_FOUND, "unknown_card"),
    ("runtime.board.card.add", {"board_id": "board_ghost", "title": "x"}, ERR_NOT_FOUND, "unknown_board"),
])
def test_refusals_are_typed(method, params, code, reason):
    _workspace()
    reply = _rpc(method, params)
    assert reply["error"]["code"] == code
    assert reply["error"]["data"]["reason"] == reason


def test_an_unknown_column_is_invalid_and_writes_nothing():
    ws = _workspace()
    card = _card(ws)
    before = _on_disk(card.card_id)
    reply = _rpc("runtime.board.card.move", {"card_id": card.card_id, "column_id": "col_nowhere"})
    assert reply["error"]["data"] == {"reason": "invalid_request", "card_id": card.card_id}
    assert _on_disk(card.card_id) == before


# ── resolve_conflict ─────────────────────────────────────────────────────────


def _conflict(ws: str, card_id: str, body: dict) -> None:
    path = paths.board_conflict_path(board_models.default_board_id(ws), card_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"card_id": card_id, **body}), encoding="utf-8")


def test_a_card_under_conflict_refuses_writes_until_resolved():
    ws = _workspace()
    card = _card(ws)
    _conflict(ws, card.card_id, {"kind": "both_changed"})
    blocked = _rpc("runtime.board.card.edit", {"card_id": card.card_id, "title": "nope"})
    assert (blocked["error"]["code"], blocked["error"]["data"]["reason"]) == (ERR_CONFLICT, "card_conflict")

    reply = _rpc("runtime.board.resolve_conflict", {"card_id": card.card_id, "take": "LOCAL"})["result"]
    assert reply == {"card": _on_disk(card.card_id), "take": "local"}
    again = _rpc("runtime.board.resolve_conflict", {"card_id": card.card_id, "take": "local"})
    assert (again["error"]["code"], again["error"]["data"]["reason"]) == (ERR_NOT_FOUND, "conflict_not_found")


def test_resolve_remote_without_a_card_answers_the_archived_shape():
    ws = _workspace()
    card = _card(ws)
    _conflict(ws, card.card_id, {"kind": "edit_vs_remove"})
    reply = _rpc("runtime.board.resolve_conflict", {"card_id": card.card_id, "take": "remote"})["result"]
    assert reply == {"card": None, "card_id": card.card_id, "state": "archived", "take": "remote"}


# ── tiers and the published params ───────────────────────────────────────────


def test_all_six_are_console_and_published():
    manifest = serve_rpc.manifest()
    assert len(BOARD_METHOD_PARAMS) == 6
    for name, keys in BOARD_METHOD_PARAMS.items():
        assert manifest["tiers"][name] == TIER_CONSOLE
        assert manifest["params"][name] == list(keys) == sorted(keys)


class _RecordingParams(dict):
    """A params mapping that remembers every key a handler asked for."""

    def __init__(self, values: dict):
        super().__init__(values)
        self.asked: set[str] = set()

    def get(self, key, default=None):  # type: ignore[override]
        self.asked.add(key)
        return super().get(key, default)


_EVERY_VALUE = {
    "assignee": "neko", "board_id": None, "card_id": "card_x", "clear_assignee": False,
    "column_id": "queued", "correlation_id": "corr-1", "created_by": "operator", "description": "d",
    "expect_revision": 1, "idempotency_key": "k1", "labels": ["a"], "priority": "p1",
    "take": "local", "title": "T", "workspace_id": None, "before": None, "after": None,
}


@pytest.mark.parametrize("name", sorted(BOARD_METHOD_PARAMS))
def test_the_published_params_are_exactly_the_keys_the_verb_reads(name):
    _workspace()
    recorder = _RecordingParams({key: _EVERY_VALUE[key] for key in BOARD_METHOD_PARAMS[name]})
    serve_rpc.registry._METHODS[name]("r", recorder)
    assert sorted(recorder.asked) == list(BOARD_METHOD_PARAMS[name])
