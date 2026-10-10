"""One recoverable command coordinating native file restore and chat rewind.

Files finish first. The canonical rewind and its receipt remain one SQLite
transaction. A small durable coordinator record joins those authorities; it
never claims the filesystem and SQLite form a single atomic transaction.
"""
from __future__ import annotations
from contextlib import closing, contextmanager
import json

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
            "history": record.get("history"), "reason": record.get("reason")}
    return {**result, "recovery_revision": _digest(result)}


def _rewind(db, params, record):
    receipt = db.get_meta(_receipt_key(params))
    if receipt:
        record["history"] = json.loads(receipt)["result"]
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
            record.update(state="partial", reason="chat_refresh_required")
            _save(db, params, record)
            return _result(params, record)
    record.update(state="completed", reason=None)
    _save(db, params, record)
    clear_history_operation(params["session_id"], params["operation_id"])
    _release_backup(params, record)
    return _result(params, record)


def _release_backup(params, record):
    if record["mode"] != "chat":
        with _checkpoint_session({**params, "workspace_path": record["plan"]["workspace_path"]}, receipt_only=True) as (identity, manager, workdir, _):
            manager.release_restore_checkpoints(_operation_key(identity, workdir, params["operation_id"]))


def _restore_files(params, plan):
    restore = plan["restore"]
    with _checkpoint_session(params) as (identity, manager, workdir, _):
        if workdir != plan["workspace_path"]:
            raise OperatorConversationRefused("workspace_changed")
        return manager.restore_preview(workdir, restore["checkpoint"], revision=restore["revision"],
            selected_paths=[row["path"] for row in plan["files"]],
            operation_id=_operation_key(identity, workdir, params["operation_id"]))


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
    mode = params.get("mode")
    if mode not in {"both", "chat", "files"}:
        raise OperatorConversationRefused("invalid_undo_mode")
    digest = _digest(params)
    with _undo_store_writer(params) as db, _workspace_writer(), history_write_scope(params):
        require_not_cancelled(db, _receipt_key(params))
        raw = db.get_meta(_key(params))
        if raw:
            record = json.loads(raw)
            if record["request_digest"] != digest:
                raise OperatorConversationRefused("operation_payload_changed")
            return _reconcile(db, params, record)
        plan = preview_operator_undo(params)
        if plan["preview_token"] != params.get("preview_token"):
            raise OperatorConversationRefused("history_changed")
        files = plan["files"]
        if mode != "chat" and (plan["restore"] is None or not files or any(not row["eligible"] for row in files)):
            raise OperatorConversationRefused(plan["files_reason"] or "restore_conflict")
        record = {"state": "prepared", "request_digest": digest, "mode": mode, "plan": plan}
        fence_history_operation(params["session_id"], params["operation_id"],
                                action="undo", workspace=plan["workspace_path"])
        _save(db, params, record)
        if mode != "chat":
            try:
                record["files"] = _restore_files(params, plan)
            except Exception:
                # A durable command now exists. Even an acquisition refusal is
                # recovered through that command, so the client never drops its
                # local receipt while the server retains the admission fence.
                record.update(state="partial", reason="file_result_unconfirmed")
                _save(db, params, record)
                return _result(params, record)
            _save(db, params, record)
            if not record["files"].get("success"):
                record["state"] = "partial"
                _save(db, params, record)
                return _result(params, record)
        return _finish(db, params, record)


def _reconcile(db, params, record):
    if record["state"] in {"completed", "rolled_back"}:
        clear_history_operation(params["session_id"], params["operation_id"])
        _release_backup(params, record)
        return _result(params, record)
    # A status check observes only. Finishing the remaining writes is explicit.
    receipt = db.get_meta(_receipt_key(params))
    if receipt:
        record["history"] = json.loads(receipt)["result"]
        record["state"] = "completed"
        _save(db, params, record)
        clear_history_operation(params["session_id"], params["operation_id"])
        _release_backup(params, record)
    elif record["mode"] != "chat":
        with _checkpoint_session({**params, "workspace_path": record["plan"]["workspace_path"]}, receipt_only=True) as (identity, manager, workdir, _):
            record["files"] = manager.restore_receipt(_operation_key(identity, workdir, params["operation_id"]))
        record["state"] = "partial"
        files = record.get("files") or {}
        if files.get("success") and (record["mode"] == "files" or files.get("reason") == "rolled_back"):
            record["state"] = "rolled_back" if files.get("reason") == "rolled_back" else "completed"
            clear_history_operation(params["session_id"], params["operation_id"])
        _save(db, params, record)
        if record["state"] in {"completed", "rolled_back"}:
            _release_backup(params, record)
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
        if record["state"] in {"completed", "rolled_back"}:
            return _reconcile(db, params, record)
        if params.get("recovery_revision") != _result(params, record)["recovery_revision"]:
            raise OperatorConversationRefused("recovery_changed")
        if record["mode"] != "chat":
            result = _recover_undo_files(params, record, rollback=direction == "rollback")
            record["files"] = result
            _save(db, params, record)
            if not result.get("success"):
                record["state"] = "partial"
                _save(db, params, record)
                return _result(params, record)
        if direction == "rollback":
            record.update(state="rolled_back", reason=None)
            _save(db, params, record)
            clear_history_operation(params["session_id"], params["operation_id"])
            _release_backup(params, record)
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
                selected_paths=[row["path"] for row in record["plan"]["files"]], operation_id=key)
        from tools.checkpoint_manager import restore_revision
        return manager.resume_restore(key, revision=restore_revision(result), rollback=rollback)
