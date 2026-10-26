"""Resolve the current runtime's work authority on each call.

An owner is a workspace (``WorkScope(install, workspace_id)``); ``capabilities`` lists every
workspace with an office plus the default one, gives a workspace whose repos carry no brain its
machine-local default brain (plan §4, ruling 2026-10-18), and moves a default brain's rows into a
repo brain once one is bound (``store.normalize_default_brain``).

The general todo (plan ``general-todo-2026-10-25.md`` §2.2): one more owner, the ``personal`` board —
the operator's machine-local brain under the namespace, never promoted to a remote
(RT-GENERAL-TODO-G1) — and ``list`` with ``kind: agent``, the rows assigned to one persona instance
across every board it can see, answered as a view over the same owners (RT-GENERAL-TODO-G2).
"""
from __future__ import annotations

from agent_runtime.call_authorization import (
    CALLER_LOCAL_CONSOLE, CALLER_STDIO_OWNER, TIER_CONSOLE, authorize_call,
)
from agent_runtime.gateway_identity import read_install_identity
from agent_runtime.paths import store_root

from . import store
from agent_runtime.errors import NotFound

from .model import BOARD_KINDS, KIND_AGENT, KIND_PERSONAL, KIND_WORKSPACE, Reason, WorkRefused, WorkScope, text

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
#: The operations that take ``observe: true`` — a read with no provisioning, normalization, promotion,
#: worktree sync or row write (RT-WORK-OBSERVATION-READ); advertised as ``capabilities.observe``.
OBSERVE_OPERATIONS = ("capabilities", "list", "inspect")


def execute(operation, params, caller):
    if not authorize_call(TIER_CONSOLE, caller, method="runtime.work." + operation).ok:
        raise WorkRefused(Reason.DENIED)
    install = read_install_identity(store_root()).install_id
    if not install:
        raise WorkRefused(Reason.UNAVAILABLE)
    if operation == "capabilities":
        return _work_capabilities(install, observe=params.get("observe") is True)
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


def personal_scope(install):
    from agent_runtime.work_store.board import PERSONAL_BOARD_ID

    return WorkScope(install, PERSONAL_BOARD_ID, KIND_PERSONAL)


def scopes(install):
    """Every Work owner on this install: one per workspace, then the personal board."""

    return [*(WorkScope(install, ws) for ws in workspace_ids()), personal_scope(install)]


def _label(scope):
    return "Personal" if scope.kind == KIND_PERSONAL else _workspace_label(scope.workspace_id)


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


def _observed_brain_state(workspace_id):
    """``capabilities{observe: true}.default_brain.<ws>``: the same words, read without acting.

    No creation, promotion or move (RT-WORK-OBSERVATION-READ). What the lifecycle WOULD do next is said
    as its own word: ``missing`` (a full read would create the default brain) and ``move_pending`` (a
    full read would move its rows into the bound repo brain).
    """
    from agent_runtime.work_store.board import declared_boards, default_board, needs_default_brain
    from agent_runtime.work_store.default_brain import remote_state

    try:
        live = default_board(workspace_id) is not None
        if not needs_default_brain(declared_boards(workspace_id)):
            return {"state": "move_pending"} if live else _worded(remote_state(workspace_id), "absent")
        return _worded(remote_state(workspace_id), "present") if live else {"state": "missing"}
    except (NotFound, FileNotFoundError, KeyError, ValueError, OSError):
        return {"state": "unavailable", "reason": Reason.UNAVAILABLE.value}


def _personal_board_state(*, observe):
    """``capabilities.personal_board``: ``present`` / ``created`` (``missing`` on an observe read) /
    ``unavailable``. Machine-local by contract, so it has no remote words."""
    from agent_runtime.work_store.board import PERSONAL_BOARD_ID, default_board
    from agent_runtime.work_store.default_brain import ensure_default_brain

    try:
        if default_board(PERSONAL_BOARD_ID) is not None:
            return {"state": "present"}
        if observe:
            return {"state": "missing"}
        _require_git()
        ensure_default_brain(PERSONAL_BOARD_ID, issued_at=store._now().isoformat(timespec="seconds"))
        return {"state": "created"}
    except WorkRefused as refusal:
        return {"state": "unavailable", "reason": refusal.reason.value}
    except (NotFound, FileNotFoundError, KeyError, ValueError, OSError):
        return {"state": "unavailable", "reason": Reason.UNAVAILABLE.value}


def _work_capabilities(install, *, observe=False):
    ids = workspace_ids()
    brain_state = _observed_brain_state if observe else _default_brain_state
    return {"version": VERSION, "install_id": install, "execution_identity_guard": True, "chat_scopes": True,
            "observe": list(OBSERVE_OPERATIONS), "board_kinds": list(BOARD_KINDS),
            "owners": [scope.wire(_label(scope)) for scope in scopes(install)],
            "default_brain": {ws: brain_state(ws) for ws in ids},
            "personal_board": _personal_board_state(observe=observe),
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
    kind = params.get("kind")
    view = _KIND_VIEWS.get((kind, operation))
    if view is not None:
        return {"version": VERSION, "install_id": install, **view(params, context, install)}
    if kind is not None and kind not in (KIND_WORKSPACE, KIND_PERSONAL):
        raise WorkRefused(Reason.INVALID, "kind is workspace | personal (agent: list only)")
    owner = text(params.get("owner"))
    scope = next((found for found in scopes(install) if found.owner == owner), None)
    if scope is None:
        raise WorkRefused(Reason.OWNER_CHANGED)
    if kind is not None and kind != scope.kind:
        raise WorkRefused(Reason.INVALID, f"owner is a {scope.kind} board")
    if operation == "start" and context is not None and not context.can_start:
        raise WorkRefused(Reason.UNAVAILABLE)
    if operation in _WRITES:
        result = _WRITES[operation](scope, params, _actor(caller), context=context)
    else:
        result = _READS[operation](scope, params, context=context)
    return {"version": VERSION, "install_id": install, "owner": scope.owner, **result}


# ── the agent view (RT-GENERAL-TODO-G2) ─────────────────────────────────────


def _agent_reach(install, token):
    """``(tokens, scopes)`` for an agent view of ``token``.

    A persona INSTANCE sees its own workspace's boards and the personal board, and a row is its when
    the row is assigned to the instance or to its persona (``assignee: persona:<persona_id>`` means any
    of that persona's instances). A runtime-global instance (no workspace) and a bare persona id (no
    instance of that id) see every owner here.
    """
    from agent_runtime.persona_assignments.store import PersonaInstanceStore
    from agent_runtime.workspace_scope import effective_workspace_id

    try:
        instance = PersonaInstanceStore().get(token)
    except (NotFound, FileNotFoundError, KeyError, ValueError, OSError):
        instance = None
    if instance is None:
        return frozenset({store.resolve_assignee(token).token}), scopes(install)
    tokens = frozenset({instance.id, *([instance.persona_id] if instance.persona_id else [])})
    workspace = effective_workspace_id(instance, active_workspace_id=None)
    visible = [scope for scope in scopes(install)
               if workspace is None or scope.kind == KIND_PERSONAL or scope.workspace_id == workspace]
    return tokens, visible


def _agent_view(params, context, install):
    """``runtime.work.list`` with ``kind: agent``: one persona instance's rows across the boards it can see.

    A VIEW, never a note: each owner is read through the same ``store.list_work`` (``observe`` and
    ``stale_ok`` honoured), filtered to the rows assigned to the agent. The assignee is
    ``params.assignee`` or, from an operator conversation, the instance it talks to. One owner that
    cannot be read is reported with its refusal reason, never dropped and never fatal to the rest.
    """

    assigned = params.get("assignee") or (context.assignee if context is not None else None)
    if not assigned:
        raise WorkRefused(Reason.INVALID, "an agent view names assignee: persona:<instance_id>")
    token = store._assignee_token(assigned)
    tokens, visible = _agent_reach(install, token)
    read = {key: value for key, value in params.items() if key not in ("assignee", "kind", "owner", "slot")}
    owners = []
    for scope in visible:
        entry = {"owner": scope.owner, "workspace_id": scope.workspace_id, "kind": scope.kind,
                 "label": _label(scope)}
        try:
            owners.append({**entry, **store.list_work(scope, read, context=context, assignees=tokens)})
        except WorkRefused as refusal:
            owners.append({**entry, "boards": [], "refused": refusal.reason.value})
    return {"kind": KIND_AGENT, "assignee": f"persona:{token}", "assignees": sorted(tokens), "owners": owners,
            "read_at": store._now().isoformat(timespec="seconds"),
            "stale": any(owner.get("stale") or "refused" in owner for owner in owners)}


#: ``(kind, operation)`` pairs answered as a VIEW over every owner instead of one owner's board.
_KIND_VIEWS = {(KIND_AGENT, "list"): _agent_view}
