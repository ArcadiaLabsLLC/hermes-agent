"""Resolve the current runtime's work authority on each call.

An owner is a workspace (``WorkScope(install, workspace_id)``); ``capabilities`` lists every
workspace with an office plus the default one, gives a workspace whose repos carry no brain its
machine-local default brain (plan §4, ruling 2026-10-18), and moves a default brain's rows into a
repo brain once one is bound (``store.normalize_default_brain``).
"""
from __future__ import annotations

from agent_runtime.call_authorization import (
    CALLER_LOCAL_CONSOLE, CALLER_STDIO_OWNER, TIER_CONSOLE, authorize_call,
)
from agent_runtime.gateway_identity import read_install_identity
from agent_runtime.paths import store_root

from . import store
from agent_runtime.errors import NotFound

from .model import Reason, WorkRefused, WorkScope, text

__layer__ = "lanes"
VERSION = 2
LIMITATIONS = ["Claims and write-backs land as git commits in Eternia Harness's own worktree; "
               "the operator's checkout sees them after a pull."]


def _lend_skills(scope, params, actor, *, context=None):
    """``runtime.work.lend_skills``: the row half of lending (the worker half is ``eternia.skills.lend``)."""
    from agent_runtime.chat_verbs.queue_skill import _rejected_skills

    return store.lend_skills(scope, params, actor, context=context, rejected=_rejected_skills)


#: The owner operations; each takes ``(scope, params, actor, *, context)``.
_WRITES = {"start": store.start, "assign": store.assign, "claim": store.claim, "release": store.release,
           "set_status": store.set_status, "done": store.done, "create_brain": store.create_brain,
           "lend_skills": _lend_skills}
_READS = {"list": store.list_work, "inspect": store.inspect}


def execute(operation, params, caller):
    if not authorize_call(TIER_CONSOLE, caller, method="runtime.work." + operation).ok:
        raise WorkRefused(Reason.DENIED)
    install = read_install_identity(store_root()).install_id
    if not install:
        raise WorkRefused(Reason.UNAVAILABLE)
    if operation == "capabilities":
        return _work_capabilities(install)
    if operation != "context":
        _require_git()
    return _scoped_work_request(operation, params, caller, install)


def git_shipped():
    from agent_runtime.loop_tool_lifecycles import shipped

    return shipped("agent_runtime.git_cmd")


def _require_git():
    if not git_shipped():
        raise WorkRefused(Reason.GIT_UNAVAILABLE, "git is switched off in this bundle")


def workspace_ids():
    from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID
    from agent_runtime.office_store.store import OfficeStore

    return sorted({*OfficeStore().list_workspaces(), DEFAULT_WORKSPACE_ID})


def _workspace_label(workspace_id):
    from agent_runtime.store import WorkspaceStore

    try:
        return WorkspaceStore().get(workspace_id).name or workspace_id
    except (NotFound, FileNotFoundError, KeyError, ValueError, OSError):
        return workspace_id


def _worded(remote, word):
    """A remote word replaces the tree's word; a local brain keeps its word and carries the remote's ``reason``."""
    if remote is None:
        return {"state": word}
    if remote["state"] == "present":
        return {**remote, "state": word}
    return remote


def _default_brain_state(workspace_id):
    """``capabilities.default_brain.<ws>``: ``{state, clone_url?, slot?, reason?, retry_after?}``.

    The tree's words stay (``absent``: a repo brain carries the board; ``present``: a live local default
    brain; ``created``; ``moved``; ``unavailable``) and promotion adds ``remote``,
    ``remote_pending_declare`` and ``remote_refused`` (``default_brain.remote_state``, p10-work §2.5).
    """
    from agent_runtime.work_store.board import declared_boards, default_board, needs_default_brain
    from agent_runtime.work_store.default_brain import ensure_default_brain, remote_state

    issued = store._now().isoformat(timespec="seconds")
    try:
        if not needs_default_brain(declared_boards(workspace_id)):
            _require_git()
            moved = store.normalize_default_brain(workspace_id)
            return {"state": "moved", "into": moved["into"]} if moved else _worded(remote_state(workspace_id), "absent")
        if default_board(workspace_id) is not None:
            if git_shipped():
                ensure_default_brain(workspace_id, issued_at=issued)  # the automatic promotion
            return _worded(remote_state(workspace_id), "present")
        _require_git()
        ensure_default_brain(workspace_id, issued_at=issued)
        return _worded(remote_state(workspace_id), "created")
    except WorkRefused as refusal:
        return {"state": "unavailable", "reason": refusal.reason.value}
    except (NotFound, FileNotFoundError, KeyError, ValueError, OSError):
        return {"state": "unavailable", "reason": Reason.UNAVAILABLE.value}


def _work_capabilities(install):
    ids = workspace_ids()
    return {"version": VERSION, "install_id": install, "execution_identity_guard": True, "chat_scopes": True,
            "owners": [WorkScope(install, ws).wire(_workspace_label(ws)) for ws in ids],
            "default_brain": {ws: _default_brain_state(ws) for ws in ids},
            "limitations": list(LIMITATIONS)}


def _actor(caller):
    if caller.kind in (CALLER_STDIO_OWNER, CALLER_LOCAL_CONSOLE):
        return store.OPERATOR
    return f"device:{caller.device_id or caller.kind}"


def _scoped_work_request(operation, params, caller, install):
    if text(params.get("install_id")) != install:
        raise WorkRefused(Reason.OWNER_CHANGED)
    from .context import resolve
    context = (resolve(params["conversation"], params.get("client_scope"), caller, install)
               if "conversation" in params else None)
    if operation == "context":
        if context is None:
            raise WorkRefused(Reason.INVALID)
        return {"version": VERSION, "install_id": install, **context.wire()}
    owner = text(params.get("owner"))
    scope = next((WorkScope(install, ws) for ws in workspace_ids() if WorkScope(install, ws).owner == owner), None)
    if scope is None:
        raise WorkRefused(Reason.OWNER_CHANGED)
    if operation == "start" and context is not None and not context.can_start:
        raise WorkRefused(Reason.UNAVAILABLE)
    if operation in _WRITES:
        result = _WRITES[operation](scope, params, _actor(caller), context=context)
    else:
        result = _READS[operation](scope, params, context=context)
    return {"version": VERSION, "install_id": install, "owner": scope.owner, **result}
