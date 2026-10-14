"""One recoverable command coordinating native file restore and chat rewind.

Files finish first. The canonical rewind and its receipt remain one SQLite
transaction. A small durable coordinator record joins those authorities; it
never claims the filesystem and SQLite form a single atomic transaction.
"""
from __future__ import annotations
from contextlib import closing, contextmanager
from enum import StrEnum
import json

from tools.checkpoint_pruning import CheckpointStoreBusy

from . import chat_session_scope
from .conversation_owner import require_session_owner
from .history_recovery import fence_history_operation, clear_history_operation
from .operator_checkpoints import _checkpoint_session, _operation_key
from .operator_conversation import OperatorConversationRefused
from .operator_history import _receipt_key, _digest, _apply_native, history_write_scope
from .operator_session_inspection import operator_session_read, inspection_identity
from .operator_turn_changes import preview_operator_undo
from .history_cancellation import require_not_cancelled

__layer__ = "lanes"


class UndoState(StrEnum):
    PREPARED = "prepared"
    PARTIAL = "partial"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"


class UndoDirection(StrEnum):
    UNDO = "undo"
    REDO = "redo"


_TERMINAL_STATES = frozenset({UndoState.COMPLETED, UndoState.ROLLED_BACK})
_TRANSITIONS = {
    None: frozenset({UndoState.PREPARED}),
    UndoState.PREPARED: frozenset({UndoState.PARTIAL, *_TERMINAL_STATES}),
    UndoState.PARTIAL: frozenset({UndoState.PARTIAL, *_TERMINAL_STATES}),
    UndoState.COMPLETED: frozenset({UndoState.COMPLETED}),
    UndoState.ROLLED_BACK: frozenset({UndoState.ROLLED_BACK}),
}


def _transition(db, params, record, state: UndoState, *, reason=None):
    """Persist one legal state before releasing its admission/recovery guards."""
    previous = UndoState(record["state"]) if "state" in record else None
    if state not in _TRANSITIONS[previous]:
        raise ValueError(f"Invalid Undo transition: {previous} -> {state}")
    record.update(state=state, reason=reason)
    from .operator_redo import settle_redo_retention
    if state in _TERMINAL_STATES:
        settle_redo_retention(db, params, record)
    _save(db, params, record)
    if state in _TERMINAL_STATES:
        clear_history_operation(params["session_id"], params["operation_id"])


@contextmanager
def _undo_store_writer(params):
    with operator_session_read(params) as (_, session):
        scope = session.scope
    db = chat_session_scope.open_chat_session_db(scope, access=chat_session_scope.SessionDbAccess.WRITE)
    if db is None:
        raise OperatorConversationRefused("session_db_unavailable")
    with closing(db):
        require_session_owner(db.get_session(params["session_id"]), params.get("client_scope"))
        yield db


def _key(params):
    return _receipt_key(params).replace("operator_history:", "operator_undo:", 1)


def _save(db, params, record):
    db.set_meta(_key(params), json.dumps(record))


def _result(params, record):
    result = {**inspection_identity(params, params.get("client_scope")), "operation_id": params["operation_id"],
            "state": record["state"], "mode": record["mode"], "files": record.get("files"),
            "history": record.get("history"), "reason": record.get("reason"),
            "direction": record.get("direction", UndoDirection.UNDO)}
    return {**result, "recovery_revision": _digest(result)}


def _rewind(db, params, record):
    receipt = db.get_meta(_receipt_key(params))
    if receipt:
        record["history"] = json.loads(receipt)["result"]
        return
    if record.get("direction") == UndoDirection.REDO:
        from .operator_redo import restore_redo_history
        restore_redo_history(db, params, record)
        return
    plan = record["plan"]["history"]
    source = db.get_session(params["session_id"])
    record["history"] = _apply_native(db, params, plan, json.loads(source.get("model_config") or "{}"),
        source.get("title") or "Conversation", _receipt_key(params), record["request_digest"])


def _finish(db, params, record):
    if record["mode"] != "files":
        try:
            _rewind(db, params, record)
        except Exception:
            # Files may already be restored. Even a definite native refusal is
            # now a partial command, never a claim that nothing changed.
            _transition(db, params, record, UndoState.PARTIAL, reason="chat_refresh_required")
            return _result(params, record)
    _transition(db, params, record, UndoState.COMPLETED)
    return _result(params, record)


def _release_backup(params, record):
    if (record.get("files") or {}).get("recovery_checkpoint"):
        with _checkpoint_session({**params, "workspace_path": record["plan"]["workspace_path"]}, receipt_only=True) as (identity, manager, workdir, _):
            manager.release_restore_checkpoints(_operation_key(identity, workdir, params["operation_id"]))


def _restore_files(params, plan):
    restore = plan["restore"]
    with _checkpoint_session(params) as (identity, manager, workdir, _):
        if workdir != plan["workspace_path"]:
            raise OperatorConversationRefused("workspace_changed")
        return manager.restore_preview(workdir, restore["checkpoint"], revision=restore["revision"],
            selected_paths=[row["path"] for row in plan["files"]],
            operation_id=_operation_key(identity, workdir, params["operation_id"]),
            **({"recovery_operation_id": restore["recovery_operation_id"]} if "recovery_operation_id" in restore else {}))


@contextmanager
def _workspace_writer():
    from .profile_runner.workdir import _WORKDIR_LOCK, agent_runs_in_flight
    if not _WORKDIR_LOCK.acquire(blocking=False):
        raise OperatorConversationRefused("workspace_busy")
    try:
        if agent_runs_in_flight():
            raise OperatorConversationRefused("workspace_busy")
        yield
    finally:
        _WORKDIR_LOCK.release()


def apply_operator_undo(params):
    return _apply_command(params, UndoDirection.UNDO)


def apply_operator_redo(params):
    return _apply_command(params, UndoDirection.REDO)


def _apply_command(params, direction):
    from .operator_redo import preview_operator_redo, prepare_redo_source
    digest = _digest(params)
    with _undo_store_writer(params) as db, _workspace_writer(), history_write_scope(params):
        require_not_cancelled(db, _receipt_key(params))
        raw = db.get_meta(_key(params))
        if raw:
            record = json.loads(raw)
            if record["request_digest"] != digest or record.get("direction", UndoDirection.UNDO) != direction:
                raise OperatorConversationRefused("operation_payload_changed")
            return _reconcile(db, params, record)
        plan = {UndoDirection.UNDO: preview_operator_undo, UndoDirection.REDO: preview_operator_redo}[direction](params)
        mode = plan["mode"] if direction == UndoDirection.REDO else params.get("mode")
        if mode not in {"both", "chat", "files"}:
            raise OperatorConversationRefused("invalid_undo_mode")
        if plan["preview_token"] != params.get("preview_token"):
            raise OperatorConversationRefused("history_changed")
        files = plan["files"]
        restores_files = mode != "chat"
        if restores_files and (plan["restore"] is None or not files or any(not row["eligible"] for row in files)):
            raise OperatorConversationRefused(plan.get("files_reason") or "restore_conflict")
        record = {"request_digest": digest, "mode": mode, "plan": plan, "direction": direction}
        if direction == UndoDirection.UNDO:
            prepare_redo_source(db, params, record)
        fence_history_operation(params["session_id"], params["operation_id"],
                                action=direction, workspace=plan["workspace_path"])
        _transition(db, params, record, UndoState.PREPARED)
        if restores_files:
            try:
                record["files"] = _restore_files(params, plan)
            except CheckpointStoreBusy:
                # The native lock refused before any file write. Retain a
                # terminal receipt so a delayed replay cannot apply it later.
                _transition(db, params, record, UndoState.ROLLED_BACK, reason="checkpoint_store_busy")
                return _result(params, record)
            except Exception:
                # Unclassified failures may follow writes; recovery owns them.
                _transition(db, params, record, UndoState.PARTIAL, reason="file_result_unconfirmed")
                return _result(params, record)
            _save(db, params, record)
            if not record["files"].get("success"):
                _transition(db, params, record, UndoState.PARTIAL)
                return _result(params, record)
        return _finish(db, params, record)


def _reconcile(db, params, record):
    if record["state"] in _TERMINAL_STATES:
        _transition(db, params, record, UndoState(record["state"]), reason=record.get("reason"))
        return _result(params, record)
    # A status check observes only. Finishing the remaining writes is explicit.
    receipt = db.get_meta(_receipt_key(params))
    if receipt:
        record["history"] = json.loads(receipt)["result"]
        _transition(db, params, record, UndoState.COMPLETED)
    elif record["mode"] != "chat":
        with _checkpoint_session({**params, "workspace_path": record["plan"]["workspace_path"]}, receipt_only=True) as (identity, manager, workdir, _):
            record["files"] = manager.restore_receipt(_operation_key(identity, workdir, params["operation_id"]))
        state = UndoState.PARTIAL
        files = record.get("files") or {}
        if files.get("success") and (record["mode"] == "files" or files.get("reason") == UndoState.ROLLED_BACK):
            state = UndoState.ROLLED_BACK if files.get("reason") == UndoState.ROLLED_BACK else UndoState.COMPLETED
        _transition(db, params, record, state, reason=record.get("reason") if state == UndoState.PARTIAL else None)
    return _result(params, record)


def operator_undo_status(params):
    with _undo_store_writer(params) as db:
        raw = db.get_meta(_key(params))
        if not raw:
            return {**inspection_identity(params, params.get("client_scope")), "operation_id": params["operation_id"], "result": None}
        with history_write_scope(params):
            result = _reconcile(db, params, json.loads(raw))
        return {**inspection_identity(params, params.get("client_scope")), "operation_id": params["operation_id"], "result": result}


def recover_operator_undo(params):
    direction = params.get("direction")
    if direction not in {"finish", "rollback"}:
        raise OperatorConversationRefused("invalid_recovery_direction")
    with _undo_store_writer(params) as db, _workspace_writer(), history_write_scope(params):
        raw = db.get_meta(_key(params))
        if not raw:
            raise OperatorConversationRefused("restore_receipt_unavailable")
        record = json.loads(raw)
        _reconcile(db, params, record)
        if record["state"] in _TERMINAL_STATES:
            return _reconcile(db, params, record)
        if params.get("recovery_revision") != _result(params, record)["recovery_revision"]:
            raise OperatorConversationRefused("recovery_changed")
        if record["mode"] != "chat":
            result = _recover_undo_files(params, record, rollback=direction == "rollback")
            record["files"] = result
            _save(db, params, record)
            if not result.get("success"):
                _transition(db, params, record, UndoState.PARTIAL)
                return _result(params, record)
        if direction == "rollback":
            _transition(db, params, record, UndoState.ROLLED_BACK)
            return _result(params, record)
        return _finish(db, params, record)


def _recover_undo_files(params, record, *, rollback):
    restore = record["plan"]["restore"]
    with _checkpoint_session({**params, "workspace_path": restore["workspace_path"]}, receipt_only=True) as (identity, manager, workdir, _):
        key = _operation_key(identity, workdir, params["operation_id"])
        result = manager.restore_receipt(key)
        if result is None:
            if rollback:
                return {"success": True, "reason": "rolled_back", "restored_files": [], "failed_files": []}
            return manager.restore_preview(workdir, restore["checkpoint"], revision=restore["revision"],
                selected_paths=[row["path"] for row in record["plan"]["files"]], operation_id=key,
                **({"recovery_operation_id": restore["recovery_operation_id"]} if "recovery_operation_id" in restore else {}))
        from tools.checkpoint_manager import restore_revision
        return manager.resume_restore(key, revision=restore_revision(result), rollback=rollback)
