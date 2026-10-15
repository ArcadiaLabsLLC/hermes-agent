"""``runtime.board.card.add/edit/move/archive/restore`` and
``runtime.board.resolve_conflict`` — the board's console-tier write twins.

Each method calls the one ``BoardStore`` verb its argv twin
(``hermes_cli/harness_parts/board.py``) calls, and answers
``{"card": _card_row(card, full=True)}`` built from the card the STORE
returned — never from the request (``board-surface-rpc-lane.md`` rule 2: the
ack echoes store truth). ``resolve_conflict`` whose outcome archived the card
answers ``{"card": null, "card_id", "state": "archived", "take"}``, as the CLI
does.

**Refusals are terminal** (rule 1): a store exception is translated by
:data:`BOARD_WRITE_ERRORS` through ``office_errors.translate`` and the client
does not retry on argv. ``expect_revision`` and ``idempotency_key`` pass
through unchanged — the board's client already sends the guard.

**Tiers.** All six are ``console``: each mutates the board. **No fold** here
(rule 3): a ``board_card`` fold needs its producer inside ``board_lock``.

**Params.** The honoured keys are :data:`BOARD_METHOD_PARAMS`, published in the
manifest's ``params`` block (the L4.22 ruling). Each verb reads exactly those
keys; ``tests/agent_runtime/test_serve_rpc_board.py`` proves it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.errors import (
    AgentRuntimeError,
    AlreadyExists,
    ArchiveUnreadable,
    IdempotencyKeyVerbMismatch,
    IdempotentReplayUnresolved,
    NotFound,
    StaleRevision,
    SyncConflict,
)
from agent_runtime.serve_rpc.office_errors import (
    OfficeWriteScope,
    Translation,
    own_code,
    refusal,
    translate,
)
from agent_runtime.serve_rpc.params import ParamRefused, _correlation_id_param
from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    RpcContext,
    logger,
    ok,
)
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "BOARD_METHOD_PARAMS",
    "BOARD_WRITE_ERRORS",
    "RESOLVE_CONFLICT_ERRORS",
    "_runtime_board_card_add",
    "_runtime_board_card_archive",
    "_runtime_board_card_edit",
    "_runtime_board_card_move",
    "_runtime_board_card_restore",
    "_runtime_board_resolve_conflict",
]

CARD_ADD = "runtime.board.card.add"
CARD_EDIT = "runtime.board.card.edit"
CARD_MOVE = "runtime.board.card.move"
CARD_ARCHIVE = "runtime.board.card.archive"
CARD_RESTORE = "runtime.board.card.restore"
RESOLVE_CONFLICT = "runtime.board.resolve_conflict"

#: method -> the keys it honours, sorted (the manifest ``params`` block).
BOARD_METHOD_PARAMS: Mapping[str, tuple[str, ...]] = {
    CARD_ADD: ("assignee", "board_id", "column_id", "correlation_id", "created_by", "description",
               "idempotency_key", "labels", "priority", "title", "workspace_id"),
    CARD_EDIT: ("assignee", "card_id", "clear_assignee", "correlation_id", "description",
                "expect_revision", "idempotency_key", "labels", "priority", "title"),
    CARD_MOVE: ("after", "before", "card_id", "column_id", "correlation_id", "expect_revision",
                "idempotency_key"),
    CARD_ARCHIVE: ("card_id", "correlation_id"),
    CARD_RESTORE: ("card_id", "correlation_id"),
    RESOLVE_CONFLICT: ("card_id", "correlation_id", "take"),
}


# ── store exceptions → frames (office_errors.translate walks these) ──────────


def _not_found_reason(exc: BaseException) -> str:
    """``board:<id>`` / ``card:<id>`` — the prefix the store already writes."""

    return "unknown_board" if str(exc).startswith("board:") else "unknown_card"


#: The five card verbs' translation table.
BOARD_WRITE_ERRORS: Mapping[type[BaseException], Translation] = {
    # The office's spelling; no current revision rides ``data`` (a retry with
    # it is the lost update the guard refused).
    StaleRevision: refusal(ERR_CONFLICT, "stale_revision", carry=("card_id", "expect_revision")),
    NotFound: refusal(ERR_NOT_FOUND, _not_found_reason, carry=("card_id", "board_id")),
    AlreadyExists: refusal(ERR_CONFLICT, "card_exists", carry=("board_id",)),
    # ``card_conflict:<id>`` — the card carries an unresolved realm-sync
    # conflict; the cure is ``runtime.board.resolve_conflict``.
    SyncConflict: refusal(ERR_CONFLICT, "card_conflict", carry=("card_id",)),
    IdempotencyKeyVerbMismatch: refusal(ERR_INVALID_PARAMS, own_code, carry=("card_id",)),
    IdempotentReplayUnresolved: refusal(ERR_INVALID_REQUEST, own_code, carry=("card_id",)),
    # ``CardsUnreadable`` (and any other unreadable-archive subclass) by its own code.
    ArchiveUnreadable: refusal(ERR_INVALID_REQUEST, own_code, carry=("card_id", "board_id")),
    # The store's ``invalid_request``: an empty title, a column the board does
    # not have, no board and no workspace — fix the payload.
    ValueError: refusal(ERR_INVALID_PARAMS, "invalid_request", carry=("card_id", "board_id")),
}

#: ``resolve_conflict``: ``no_conflict:<id>`` is "there is no such conflict",
#: the office twin's ``conflict_not_found``.
RESOLVE_CONFLICT_ERRORS: Mapping[type[BaseException], Translation] = {
    **BOARD_WRITE_ERRORS,
    SyncConflict: refusal(ERR_NOT_FOUND, "conflict_not_found", carry=("card_id",)),
}


# ── the parameter readers (each raises ParamRefused) ─────────────────────────


def _str_param(params: dict, key: str) -> str | None:
    raw = params.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ParamRefused(f"invalid params: {key} must be a string or omitted", RpcRefusal.PARAM_TYPE_INVALID)
    return raw


def _required_param(params: dict, key: str, reason: RpcRefusal) -> str:
    value = (_str_param(params, key) or "").strip()
    if not value:
        raise ParamRefused(f"invalid params: {key} must be a non-empty string", reason)
    return value


def _priority_param(params: dict) -> str | None:
    from agent_runtime.board_models import CARD_PRIORITIES

    value = _str_param(params, "priority")
    if value is not None and value.strip().lower() not in CARD_PRIORITIES:
        raise ParamRefused(f"invalid params: priority must be one of {', '.join(CARD_PRIORITIES)}",
                           RpcRefusal.PRIORITY_INVALID)
    return value


def _labels_param(params: dict) -> list[str] | None:
    raw = params.get("labels")
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ParamRefused("invalid params: labels must be a list of strings", RpcRefusal.LABELS_INVALID)
    return [item.strip() for item in raw if item.strip()]


def _bool_param(params: dict, key: str) -> bool:
    raw = params.get(key)
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ParamRefused(f"invalid params: {key} must be a boolean or omitted", RpcRefusal.PARAM_TYPE_INVALID)
    return raw


def _expect_revision_param(params: dict) -> int | None:
    raw = params.get("expect_revision")
    # ``bool`` is an ``int``; ``True`` would silently mean revision 1.
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        raise ParamRefused("invalid params: expect_revision must be an integer or omitted",
                           RpcRefusal.EXPECT_REVISION_INVALID)
    return raw


def _take_param(params: dict) -> str:
    take = (_str_param(params, "take") or "").strip().lower()
    if take not in {"local", "remote"}:
        raise ParamRefused('invalid params: take must be "local" or "remote"', RpcRefusal.TAKE_INVALID)
    return take


# ── the one write path every verb runs ───────────────────────────────────────


def _card_write(
    rid: Any,
    op: str,
    params: dict,
    read: Callable[[dict], Callable[[Any], Any]],
    *,
    table: Mapping[type[BaseException], Translation] = BOARD_WRITE_ERRORS,
    answer: Callable[[Any, dict], dict] | None = None,
) -> dict:
    """Validate (``read`` returns the store call), write, translate, ack.

    ``read`` raises :class:`ParamRefused` before any store is opened, so a
    refused request writes nothing.
    """

    from agent_runtime.board_store import BoardStore
    from agent_runtime.board_store.rows import _card_row

    honoured = BOARD_METHOD_PARAMS[op]
    named = {
        key: params[key]
        for key in ("card_id", "board_id", "expect_revision")
        if key in honoured and params.get(key) is not None
    }
    try:
        correlation_id = _correlation_id_param(params)
        call = read(params)
    except ParamRefused as refused:
        return refused.frame(rid, **{k: v for k, v in named.items() if k != "expect_revision"})
    workspace_id = _str_param(params, "workspace_id") if "workspace_id" in honoured else None
    try:
        card = call(BoardStore())
    except (AgentRuntimeError, ValueError) as exc:
        return translate(exc, table, OfficeWriteScope(rid, workspace_id, named))
    result = answer(card, params) if answer is not None else {"card": _card_row(card, full=True)}
    logger.info(
        "board_write op=%s corr=%s card=%s board=%s revision=%s",
        op,
        correlation_id or "-",
        getattr(card, "card_id", None) or params.get("card_id") or "-",
        getattr(card, "board_id", None) or "-",
        getattr(card, "revision", None) or "-",
    )
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)


# ── the six verbs ────────────────────────────────────────────────────────────


@method(CARD_ADD, tier=TIER_CONSOLE)
def _runtime_board_card_add(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Add a card: ``title`` required; ``board_id`` else ``workspace_id`` else
    the active workspace's default board (the argv verb's rule)."""

    def read(p: dict):
        title = _required_param(p, "title", RpcRefusal.TITLE_REQUIRED)
        board_id, workspace_id = _str_param(p, "board_id"), _str_param(p, "workspace_id")
        fields = {"description": _str_param(p, "description") or "", "column": _str_param(p, "column_id"),
                  "priority": _priority_param(p), "labels": _labels_param(p), "assignee": _str_param(p, "assignee"),
                  "created_by": _str_param(p, "created_by") or "operator",
                  "idempotency_key": _str_param(p, "idempotency_key")}

        def call(store):
            from agent_runtime.store import WorkspaceStore

            workspace = workspace_id if (board_id or workspace_id) else WorkspaceStore().active_id()
            return store.add_card(board_id=board_id, workspace_id=workspace, title=title, **fields)

        return call

    return _card_write(rid, CARD_ADD, params, read)


@method(CARD_EDIT, tier=TIER_CONSOLE)
def _runtime_board_card_edit(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Edit a card's title / description / priority / labels / assignee."""

    def read(p: dict):
        card_id = _required_param(p, "card_id", RpcRefusal.CARD_ID_REQUIRED)
        fields = {"title": _str_param(p, "title"), "description": _str_param(p, "description"),
                  "priority": _priority_param(p), "labels": _labels_param(p), "assignee": _str_param(p, "assignee"),
                  "clear_assignee": _bool_param(p, "clear_assignee"), "expect_revision": _expect_revision_param(p),
                  "idempotency_key": _str_param(p, "idempotency_key")}
        return lambda store: store.edit_card(card_id, **fields)

    return _card_write(rid, CARD_EDIT, params, read)


@method(CARD_MOVE, tier=TIER_CONSOLE)
def _runtime_board_card_move(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Move a card to ``column_id`` (an id or a kind), ``before`` / ``after`` a card."""

    def read(p: dict):
        card_id = _required_param(p, "card_id", RpcRefusal.CARD_ID_REQUIRED)
        fields = {"column_id": _required_param(p, "column_id", RpcRefusal.COLUMN_ID_REQUIRED),
                  "before": _str_param(p, "before"), "after": _str_param(p, "after"),
                  "expect_revision": _expect_revision_param(p), "idempotency_key": _str_param(p, "idempotency_key")}
        return lambda store: store.move_card(card_id, **fields)

    return _card_write(rid, CARD_MOVE, params, read)


@method(CARD_ARCHIVE, tier=TIER_CONSOLE)
def _runtime_board_card_archive(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Archive a card (archive-never-delete); the ack is the archived copy."""

    def read(p: dict):
        card_id = _required_param(p, "card_id", RpcRefusal.CARD_ID_REQUIRED)
        return lambda store: store.archive_card(card_id, reason="operator")

    return _card_write(rid, CARD_ARCHIVE, params, read)


@method(CARD_RESTORE, tier=TIER_CONSOLE)
def _runtime_board_card_restore(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Restore an archived card to a live column."""

    def read(p: dict):
        card_id = _required_param(p, "card_id", RpcRefusal.CARD_ID_REQUIRED)
        return lambda store: store.restore_card(card_id)

    return _card_write(rid, CARD_RESTORE, params, read)


def _resolve_answer(card: Any, params: dict) -> dict:
    from agent_runtime.board_store.rows import _card_row

    take = _take_param(params)
    if card is None:
        return {"card": None, "card_id": params["card_id"].strip(), "state": "archived", "take": take}
    return {"card": _card_row(card, full=True), "take": take}


@method(RESOLVE_CONFLICT, tier=TIER_CONSOLE)
def _runtime_board_resolve_conflict(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Resolve a card's realm-sync conflict: ``take`` is ``local`` or ``remote``."""

    def read(p: dict):
        card_id = _required_param(p, "card_id", RpcRefusal.CARD_ID_REQUIRED)
        take = _take_param(p)
        return lambda store: store.resolve_conflict(card_id, take=take)

    return _card_write(rid, RESOLVE_CONFLICT, params, read, table=RESOLVE_CONFLICT_ERRORS, answer=_resolve_answer)
