"""Profile-scoped workspace checkpoint inspection and reviewed restoration."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re

from . import paths
from .config import load_agent_runtime_config
from .checkpoint_config import checkpoint_configuration
from .models import apply_instance_model_overrides
from .operator_conversation import OperatorConversationRefused
from .operator_history import history_write_scope
from .operator_session_inspection import _inspection_persona, inspection_identity, operator_session_read
from .profile_context import persona_profile_scope, resolve_persona_profile
from .history_recovery import fence_history_operation, clear_history_operation, pending_history_operation
from tools.checkpoint_recovery import restore_revision

__layer__ = "lanes"


@contextmanager
def _checkpoint_session(params, *, receipt_only=False):
    from agent.runtime_cwd import set_session_cwd, reset_session_cwd
    from tools.checkpoint_manager import CheckpointManager
    from .chat_lane_scope import apply_chat_lane_tool_scope
    from .tool_permissions import permission_options_for_chat
    from .persona_chat_continuity.lease import chat_root_session_key_scope

    with operator_session_read(params) as (instance, session):
        persona = apply_instance_model_overrides(_inspection_persona(instance, load_agent_runtime_config()), instance)
        binding = resolve_persona_profile(persona)
        if binding.readiness != "ready":
            raise OperatorConversationRefused("profile_unavailable")
        tip = session.db.resolve_resume_session_id(params["session_id"])
        current = session.db.get_session(tip) or session.row
        identity = inspection_identity(params, session.owner)
        with persona_profile_scope(binding, runtime_root=paths.store_root()), chat_root_session_key_scope(params["session_id"]):
            options = apply_chat_lane_tool_scope(persona, permission_options_for_chat(
                persona, session_id=params["session_id"]), session_id=params["session_id"])
            workdir = (params.get("workspace_path") if receipt_only else
                       current.get("cwd") or (options.mission_chat_workdir.path if options.mission_chat_workdir else None))
            if not isinstance(workdir, str) or not Path(workdir).is_absolute() or (not receipt_only and not Path(workdir).is_dir()):
                raise OperatorConversationRefused("workspace_unavailable")
            config = checkpoint_configuration()
            manager = CheckpointManager(**{key: config[key] for key in (
                "enabled", "max_snapshots", "max_total_size_mb", "max_file_size_mb")})
            token = set_session_cwd(str(workdir))
            try:
                if not receipt_only and manager.unsupported_backend_reason():
                    raise OperatorConversationRefused("checkpoint_backend_unsupported")
                yield identity, manager, workdir if receipt_only else manager.get_working_dir_for_path(str(workdir)), config
            finally:
                reset_session_cwd(token)


def list_operator_checkpoints(params):
    with _checkpoint_session(params) as (identity, manager, workdir, config):
        return {**identity, "scope": "workspace", "workspace_path": workdir,
                "capture_enabled": config["enabled"], "checkpoints": manager.list_checkpoints(workdir),
                "max_file_size_mb": config["max_file_size_mb"], "ignored_files_included": False}


def preview_operator_checkpoint(params):
    with _checkpoint_session(params) as (identity, manager, workdir, _):
        result = manager.preview_restore(workdir, params.get("checkpoint"))
        if not result["success"]:
            raise OperatorConversationRefused(result["reason"])
        return {**identity, "workspace_path": workdir, **result}


def restore_operator_checkpoint(params):
    from .profile_runner.workdir import _WORKDIR_LOCK, agent_runs_in_flight

    operation = params.get("operation_id")
    selected = params.get("selected_paths")
    if (not isinstance(operation, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,100}", operation) is None
            or not isinstance(selected, list) or len(selected) > 1000
            or any(not isinstance(path, str) or not path for path in selected)):
        raise OperatorConversationRefused("invalid_restore_request")
    # The current host serializes native agent runs through this existing owner.
    # A restore must not interleave with a sibling chat's tools on this serve.
    if not _WORKDIR_LOCK.acquire(blocking=False):
        raise OperatorConversationRefused("workspace_busy")
    try:
        if agent_runs_in_flight():
            raise OperatorConversationRefused("workspace_busy")
        with _checkpoint_session(params) as (identity, manager, workdir, _), history_write_scope(params):
            from .history_cancellation import require_not_cancelled
            from .operator_history import _receipt_key
            with operator_session_read(params) as (_, session):
                require_not_cancelled(session.db, _receipt_key(params))
            if workdir != params.get("workspace_path"):
                raise OperatorConversationRefused("workspace_changed")
            operation_key = _operation_key(identity, workdir, operation)
            previous = pending_history_operation(params["session_id"])
            fence_history_operation(params["session_id"], operation, action="restore", workspace=workdir)
            from tools.checkpoint_pruning import CheckpointStoreBusy
            try:
                result = manager.restore_preview(workdir, params.get("checkpoint"), revision=params.get("revision"),
                    selected_paths=selected, operation_id=operation_key)
            except CheckpointStoreBusy:
                if previous is None:
                    clear_history_operation(params["session_id"], operation)
                raise
            if result.get("success") or result.get("recovery_checkpoint") is None:
                clear_history_operation(params["session_id"], operation)
            if result.get("success"):
                manager.release_restore_checkpoints(operation_key)
            return {**identity, "operation_id": operation, "workspace_path": workdir, **result,
                    "recovery_revision": restore_revision(result)}
    finally:
        _WORKDIR_LOCK.release()


def _operation_key(identity, workdir, operation):
    if not isinstance(operation, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,100}", operation) is None:
        raise OperatorConversationRefused("invalid_operation_id")
    return hashlib.sha256(json.dumps([identity, workdir, operation], sort_keys=True).encode()).hexdigest()


def operator_checkpoint_status(params):
    # The stored workspace participates only in the receipt key. No filesystem
    # read/write uses it: ownership is revalidated against the durable session,
    # even if that session subsequently changed workspace or the drive is gone.
    with _checkpoint_session(params, receipt_only=True) as (identity, manager, workdir, _):
        result = manager.restore_receipt(_operation_key(identity, workdir, params.get("operation_id")))
        if result is not None and result.get("success"):
            clear_history_operation(params["session_id"], params["operation_id"])
            manager.release_restore_checkpoints(_operation_key(identity, workdir, params["operation_id"]))
        return {**identity, "workspace_path": workdir, "operation_id": params["operation_id"],
                "result": {**result, "recovery_revision": restore_revision(result)} if result else None}


def recover_operator_checkpoint(params):
    from .operator_undo import _workspace_writer
    direction = params.get("direction")
    if direction not in {"finish", "rollback"}:
        raise OperatorConversationRefused("invalid_recovery_direction")
    with _checkpoint_session(params, receipt_only=True) as (identity, manager, workdir, _), _workspace_writer(), history_write_scope(params):
        key = _operation_key(identity, workdir, params.get("operation_id"))
        result = manager.resume_restore(key, revision=params.get("recovery_revision"), rollback=direction == "rollback")
        if result.get("recovery_stale"):
            raise OperatorConversationRefused("recovery_changed")
        if result.get("success"):
            clear_history_operation(params["session_id"], params["operation_id"])
            manager.release_restore_checkpoints(key)
        return {**identity, "workspace_path": workdir, "operation_id": params["operation_id"], **result,
                "recovery_revision": restore_revision(result)}
