"""Turn-attributed changes and an exact, read-only combined undo preview."""
from __future__ import annotations

from .operator_checkpoints import _checkpoint_session
from .operator_conversation import OperatorConversationRefused
from .operator_history import _target, _plan, _digest, require_history_idle
from .operator_session_inspection import operator_session_read
from .turn_checkpoints import read_turn_checkpoint, checkpoint_for_tree

__layer__ = "lanes"


def operator_turn_changes(params):
    turn = params.get("client_message_id")
    if not isinstance(turn, str) or not turn:
        raise OperatorConversationRefused("invalid_history_target")
    with operator_session_read(params) as (_, session):
        _target(session.db, params["session_id"], client_message_id=turn, after_reply=True)
    try:
        with _checkpoint_session(params) as (identity, manager, workdir, _):
            record = read_turn_checkpoint(params["session_id"], turn)
            workspace = (record or {}).get("workspaces", {}).get(workdir)
            checkpoint = checkpoint_for_tree(manager, workdir, workspace["before_tree"]) if workspace else None
            return {**identity, "client_message_id": turn, "workspace_path": workdir,
                    "files": list(workspace["files"].values()) if workspace else [],
                    "checkpoint": checkpoint, "tracked": workspace is not None,
                    "other_workspaces": bool(record and set(record["workspaces"]) - {workdir})}
    except OperatorConversationRefused as exc:
        if exc.reason not in {"workspace_unavailable", "checkpoint_backend_unsupported"}:
            raise
        from .operator_session_inspection import inspection_identity
        return {**inspection_identity(params, params.get("client_scope")), "client_message_id": turn,
                "workspace_path": "", "files": [], "checkpoint": None, "tracked": False,
                "other_workspaces": False, "unavailable_reason": exc.reason}



def preview_operator_undo(params):
    from agent.context_compressor import user_originated_turn_view
    from .persona_chat_history.vocabulary import logical_persona_chat_client_message_id

    with operator_session_read(params) as (_, session):
        require_history_idle(params)
        history = _plan({**params, "action": "rewind"}, session)
        rows = session.db.get_messages_as_conversation(history["tip"], include_row_ids=True)
        turns = [logical_persona_chat_client_message_id(row.get("message_id")) for row in rows
                 if row["_row_id"] >= history["row_id"] and user_originated_turn_view(row) is not None]
    files, checkpoint, restore, reason, workspace_path = [], None, None, None, None
    try:
        with _checkpoint_session(params) as (_, manager, workdir, _):
            workspace_path = workdir
            baseline = None
            attributed = {}
            for turn in turns:
                record = read_turn_checkpoint(params["session_id"], turn) if turn else None
                if record and set(record["workspaces"]) - {workdir}:
                    reason = "multiple_workspaces"
                workspace = (record or {}).get("workspaces", {}).get(workdir)
                if workspace:
                    baseline = baseline or workspace["before_tree"]
                    attributed.update(workspace["files"])
            if baseline and reason is None:
                checkpoint = checkpoint_for_tree(manager, workdir, baseline)
                if checkpoint is None:
                    reason = "checkpoint_expired"
                else:
                    restore = manager.preview_restore(workdir, checkpoint)
                    if not restore.get("success"):
                        reason = restore["reason"]
                        restore = None
                    else:
                        # Unattributed changes remain untouched, even if another
                        # chat happened to write them inside this workspace.
                        files = [row for row in restore["files"] if row["path"] in attributed]
                        for row in files:
                            evidence = attributed[row["path"]]
                            if row["current_sha256"] != evidence["sha256"]:
                                row.update(eligible=False, reason="changed_after_turn")
                        # Review uses the exact attributed paths. The workspace
                        # diff can contain another chat's work and is not shown.
                        restore = {**restore, "workspace_path": workdir, "files": files, "diff": "", "diff_truncated": False}
            elif not attributed and reason is None:
                reason = "no_tracked_changes"
    except OperatorConversationRefused as exc:
        reason = exc.reason
    body = {"history": history, "restore": restore, "files_reason": reason,
            "workspace_path": workspace_path, "files": files}
    return {**history, **body, "client_message_id": params["client_message_id"], "preview_token": _digest(body)}
