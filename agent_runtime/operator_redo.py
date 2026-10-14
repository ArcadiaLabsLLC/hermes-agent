"""One reversible Undo, owned by the existing history coordinator and stores.

Only references, revisions and an expiry are added to the Undo record. Native
message rows and checkpoint receipts remain the sole owners of saved content.
"""
from __future__ import annotations

import json
import time

from hermes_state_history_controls import HistoryControlError
from .operator_checkpoints import _checkpoint_session, _operation_key
from .operator_conversation import OperatorConversationRefused
from .operator_history import _digest, _receipt_key, require_history_idle
from .operator_session_inspection import inspection_identity, operator_session_read

__layer__ = "lanes"

REDO_RETENTION_SECONDS = 7 * 86400


def _latest_key(params):
    return "operator_redo:" + _digest([params["session_id"], params.get("client_scope")])


def prepare_redo_source(db, params, record):
    """Capture the native revision before Undo; publish no extra transcript."""
    history = record["plan"]["history"]
    snapshot = db.history_control_snapshot(history["tip"])
    if snapshot["revision"] != history["revision"]:
        raise OperatorConversationRefused("history_changed")
    record["redo_source"] = {"snapshot": snapshot, "expires_at": time.time() + REDO_RETENTION_SECONDS}


def replace_redo_source(db, params):
    from .operator_undo import _key, _release_backup
    previous = db.get_meta(_latest_key(params))
    if previous and previous != params["operation_id"]:
        scoped = {**params, "operation_id": previous}
        raw = db.get_meta(_key(scoped))
        if raw:
            _release_backup(scoped, json.loads(raw))
    db.set_meta(_latest_key(params), params["operation_id"])


def settle_redo_retention(db, params, record):
    """Called by the single coordinator transition, including crash recovery."""
    from .operator_undo import _key, _release_backup, UndoDirection, UndoState
    completed = record["state"] == UndoState.COMPLETED
    if record.get("direction", UndoDirection.UNDO) == UndoDirection.REDO:
        if completed:
            source = {**params, "operation_id": record["plan"]["undo_operation_id"]}
            raw = db.get_meta(_key(source))
            if raw:
                _release_backup(source, json.loads(raw))
            if db.get_meta(_latest_key(params)) == source["operation_id"]:
                db.set_meta(_latest_key(params), "")
        _release_backup(params, record)
        return
    source = record.get("redo_source")
    if completed and source is not None and not source.get("published"):
        replace_redo_source(db, params)
        source["published"] = True
    if (not completed or source is None
            or db.get_meta(_latest_key(params)) != params["operation_id"]
            or source["expires_at"] <= time.time()):
        _release_backup(params, record)
        return
    if (record.get("files") or {}).get("recovery_checkpoint"):
        with _checkpoint_session({**params, "workspace_path": record["plan"]["workspace_path"]}, receipt_only=True) as (identity, manager, workdir, _):
            manager.retain_restore_checkpoints(_operation_key(identity, workdir, params["operation_id"]),
                                               until=source["expires_at"])


def _completed_redo_source(db, params):
    from .operator_undo import _key, UndoState
    operation = db.get_meta(_latest_key(params))
    if not operation:
        raise OperatorConversationRefused("redo_unavailable")
    raw = db.get_meta(_key({**params, "operation_id": operation}))
    record = json.loads(raw) if raw else {}
    if record.get("state") != UndoState.COMPLETED or not record.get("redo_source"):
        raise OperatorConversationRefused("redo_unavailable")
    if record["redo_source"]["expires_at"] <= time.time():
        raise OperatorConversationRefused("redo_expired")
    return operation, record


def _eligible_redo_history_revision(db, params, record):
    history, snapshot = record["plan"]["history"], record["redo_source"]["snapshot"]
    if db.resolve_resume_session_id(params["session_id"]) != history["tip"]:
        raise OperatorConversationRefused("history_changed")
    try:
        if record["mode"] == "files":
            if db.history_control_snapshot(history["tip"]) != snapshot:
                raise HistoryControlError("history_changed")
            revision = snapshot["revision"]
        else:
            revision = db.preview_rewind_redo(history["tip"], snapshot, history["row_id"])
    except HistoryControlError as exc:
        raise OperatorConversationRefused(exc.reason) from exc
    current = db.get_session(params["session_id"])
    if _digest([current.get("model_config"), current.get("cwd")]) != history["settings_revision"]:
        raise OperatorConversationRefused("history_changed")
    return revision


def preview_operator_redo(params):
    with operator_session_read(params) as (_, session):
        require_history_idle(params)
        operation, record = _completed_redo_source(session.db, params)
        history = record["plan"]["history"]
        snapshot = record["redo_source"]["snapshot"]
        revision = _eligible_redo_history_revision(session.db, params, record)
        identity = inspection_identity(params, session.owner)
    restore = None
    workspace = record["plan"]["workspace_path"]
    if record["mode"] != "chat":
        with _checkpoint_session(params) as (owner, manager, workdir, _):
            if workdir != workspace:
                raise OperatorConversationRefused("workspace_changed")
            recovery_id = _operation_key(owner, workdir, operation)
            restore = manager.preview_restore_reversal(workdir, recovery_id)
            if not restore.get("success"):
                raise OperatorConversationRefused(restore["reason"])
            restore.update(workspace_path=workdir, recovery_operation_id=recovery_id, diff="", diff_truncated=False)
            if not restore["files"] or any(not row["eligible"] for row in restore["files"]):
                raise OperatorConversationRefused("restore_conflict")
    body = {**identity, "direction": "redo", "mode": record["mode"], "undo_operation_id": operation,
            "expires_at": record["redo_source"]["expires_at"], "snapshot": snapshot,
            "history": {**history, "action": "redo", "revision": revision, "draft": ""},
            "workspace_path": workspace, "restore": restore, "files": restore["files"] if restore else []}
    return {**body, "preview_token": _digest(body)}


def operator_redo_available(params):
    # No file scan just to draw the action. Opening its review validates files.
    with operator_session_read(params) as (_, session):
        identity = inspection_identity(params, session.owner)
        try:
            _, record = _completed_redo_source(session.db, params)
            _eligible_redo_history_revision(session.db, params, record)
        except OperatorConversationRefused as exc:
            return {**identity, "available": False, "reason": exc.reason}
        return {**identity, "available": True, "mode": record["mode"],
                "expires_at": record["redo_source"]["expires_at"]}


def restore_redo_history(db, params, record):
    plan = record["plan"]
    result = {**inspection_identity(params, params.get("client_scope")), "action": "redo",
              "operation_id": params["operation_id"], "draft": "", "replayed": False,
              "result_session_id": params["session_id"], "affected_turns": plan["history"]["affected_turns"]}
    db.redo_rewind(plan["history"]["tip"], snapshot=plan["snapshot"], boundary=plan["history"]["row_id"],
        expected_history_digest=plan["history"]["revision"],
        operation_receipt=(_receipt_key(params), json.dumps({"request_digest": record["request_digest"], "result": result})))
    record["history"] = result
