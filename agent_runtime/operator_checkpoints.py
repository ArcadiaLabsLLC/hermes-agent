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

__layer__ = "lanes"


@contextmanager
def _checkpoint_session(params):
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
            workdir = current.get("cwd") or (options.mission_chat_workdir.path if options.mission_chat_workdir else None)
            if not workdir or not Path(workdir).is_absolute() or not Path(workdir).is_dir():
                raise OperatorConversationRefused("workspace_unavailable")
            config = checkpoint_configuration()
            manager = CheckpointManager(**{key: config[key] for key in (
                "enabled", "max_snapshots", "max_total_size_mb", "max_file_size_mb")})
            token = set_session_cwd(str(workdir))
            try:
                if manager.unsupported_backend_reason():
                    raise OperatorConversationRefused("checkpoint_backend_unsupported")
                yield identity, manager, manager.get_working_dir_for_path(str(workdir)), config
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
        with history_write_scope(params), _checkpoint_session(params) as (identity, manager, workdir, _):
            if workdir != params.get("workspace_path"):
                raise OperatorConversationRefused("workspace_changed")
            operation_key = _operation_key(identity, workdir, operation)
            result = manager.restore_preview(workdir, params.get("checkpoint"), revision=params.get("revision"),
                selected_paths=selected, operation_id=operation_key)
            return {**identity, "operation_id": operation, "workspace_path": workdir, **result}
    finally:
        _WORKDIR_LOCK.release()


def _operation_key(identity, workdir, operation):
    if not isinstance(operation, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,100}", operation) is None:
        raise OperatorConversationRefused("invalid_operation_id")
    return hashlib.sha256(json.dumps([identity, workdir, operation], sort_keys=True).encode()).hexdigest()


def operator_checkpoint_status(params):
    with _checkpoint_session(params) as (identity, manager, workdir, _):
        if workdir != params.get("workspace_path"):
            raise OperatorConversationRefused("workspace_changed")
        result = manager.restore_receipt(_operation_key(identity, workdir, params.get("operation_id")))
        return {**identity, "workspace_path": workdir, "operation_id": params["operation_id"], "result": result}
