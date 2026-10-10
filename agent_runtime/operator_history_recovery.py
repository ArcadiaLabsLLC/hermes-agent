"""Discover an unfinished command by durable session, without client storage."""
from .history_recovery import pending_history_record, clear_history_operation
from .operator_history import history_write_scope
from .operator_session_inspection import operator_session_read, inspection_identity

__layer__ = "lanes"


def operator_history_pending(params):
    # Owner authorization precedes reading the session's private recovery index.
    with operator_session_read(params) as (_, session):
        identity = inspection_identity(params, session.owner)
    pending = pending_history_record(params["session_id"])
    if pending is None:
        return {**identity, "pending": None}
    scoped = {**params, "operation_id": pending["operation_id"]}
    with history_write_scope(scoped):
        if pending["action"] == "undo":
            from .operator_undo import _writer, _key, _reconcile
            import json
            with _writer(scoped) as db:
                raw = db.get_meta(_key(scoped))
                result = _reconcile(db, scoped, json.loads(raw)) if raw else None
        else:
            from .operator_checkpoints import _checkpoint_session, _operation_key
            with _checkpoint_session({**scoped, "workspace_path": pending["workspace_path"]}, receipt_only=True) as (owner, manager, workdir, _):
                result = manager.restore_receipt(_operation_key(owner, workdir, pending["operation_id"]))
        if result is None:
            # The writer lock proves the process is gone. Both implementations
            # persist their command before the first destructive write. A fence
            # without that command can therefore be retired without a discard UI.
            clear_history_operation(params["session_id"], pending["operation_id"])
            pending = None
    return {**identity, "pending": pending}


def cancel_unapplied_history(params):
    """A failed retry can retire its local note only after this durable fence.

    If any apply receipt exists, including a partial one, recovery still owns
    it. A delayed original request must observe the tombstone before writing.
    """
    from .operator_undo import _writer, _key
    from .operator_history import _receipt_key
    from .operator_checkpoints import _checkpoint_session, _operation_key
    from .history_cancellation import cancellation_key
    from .operator_conversation import OperatorConversationRefused
    action = params.get("action")
    if action not in {"branch", "rewind", "undo", "restore"}:
        raise OperatorConversationRefused("invalid_history_action")
    with _writer(params) as db, history_write_scope(params):
        applied = db.get_meta(_receipt_key(params)) or db.get_meta(_key(params))
        if action == "restore":
            with _checkpoint_session(params, receipt_only=True) as (identity, manager, workdir, _):
                applied = applied or manager.restore_receipt(_operation_key(identity, workdir, params["operation_id"]))
        if not applied:
            db.set_meta(cancellation_key(_receipt_key(params)), "cancelled")
            clear_history_operation(params["session_id"], params["operation_id"])
        return {**inspection_identity(params, params.get("client_scope")),
                "operation_id": params["operation_id"], "cancelled": not bool(applied)}
