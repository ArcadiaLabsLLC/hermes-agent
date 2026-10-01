"""Account-scoped pages over native persona-chat history, never a second catalog."""
from __future__ import annotations

import json
import math
from contextlib import closing

from . import chat_session_scope
from .conversation_owner import ConversationOwnerError, request_client_scope
from .instance_selection import verify_instance_install, InstanceSelectionError
from .persona_assignments import PersonaInstanceStore, chat_session_owner_instance_id
from .persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from .persona_chat_history.history_rows import _history_row, _model_config
from .workspace_scope import effective_workspace_id

__layer__ = "lanes"


class InstanceHistoryRefused(ValueError):
    pass


def list_instance_conversations(params: dict) -> dict:
    if not params.get("install_id"):
        raise InstanceHistoryRefused("installation_required")
    try:
        verify_instance_install(params)
        owner = request_client_scope(params)
    except (ConversationOwnerError, InstanceSelectionError) as exc:
        raise InstanceHistoryRefused(str(exc)) from exc
    all_accounts = params.get("all_accounts", False)
    limit = params.get("limit", 50)
    if type(all_accounts) is not bool or type(limit) is not int or not 1 <= limit <= 100:
        raise InstanceHistoryRefused("invalid_history_query")
    if owner is None and not all_accounts:
        raise InstanceHistoryRefused("client_scope_required")
    scope = (params["install_id"], owner, all_accounts)
    before = _history_position(params.get("before"), scope)
    db = chat_session_scope.open_chat_session_db(access=chat_session_scope.SessionDbAccess.READ)
    if db is None:
        if chat_session_scope.chat_session_store_exists():
            raise InstanceHistoryRefused("session_db_unavailable")
        return {"conversations": [], "next_cursor": None}
    with closing(db):
        raw = _page(db, owner=None if all_accounts else owner, before=before, limit=limit)
        visible = raw[:limit]
        scan = PersonaInstanceStore().scan_all()
        if scan.unreadable:
            raise InstanceHistoryRefused("instance_roster_unreadable")
        instances = {instance.id: instance for instance in scan.instances}
        rows = [_project_history(db, item, instances, params["install_id"]) for item in visible]
    cursor = None
    if len(raw) > limit:
        last = visible[-1]
        cursor = json.dumps([*scope, last["started_at"], last["id"]], separators=(",", ":"))
    return {"conversations": rows, "next_cursor": cursor}


def _project_history(db, raw, instances, install_id):
    config = _model_config(raw["model_config"])
    instance_id = config.get("persona_instance_id") or chat_session_owner_instance_id(raw["id"])
    instance = instances.get(instance_id)
    persona_id = config.get("persona_id") or (instance.persona_id if instance else "unknown")
    row = _history_row(raw, persona_id=persona_id, instance_id=instance_id,
                       session_id=raw["id"], session_db=db, message_tail=1)
    row.update(install_id=install_id, persona_instance_id=instance_id,
               workspace_id=effective_workspace_id(instance, active_workspace_id=None) if instance else None,
               display_name=instance.display_name if instance else None,
               available=instance is not None and instance.persona_id == persona_id)
    if row["messages"]:
        row["last_message_preview"] = row["messages"][-1]["text"][:180]
    row.pop("messages")
    return row


def _history_position(value, scope):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError()
        row = json.loads(value)
        if (not isinstance(row, list) or len(row) != 5 or tuple(row[:3]) != scope
                or type(row[3]) not in (int, float) or not math.isfinite(row[3])
                or not isinstance(row[4], str) or not row[4]):
            raise ValueError()
        return row[3], row[4]
    except (ValueError, TypeError) as exc:
        raise InstanceHistoryRefused("invalid_history_cursor") from exc


def _page(db, *, owner, before, limit):
    # SessionDB has no metadata predicate on list_sessions_rich. Use its pooled
    # read boundary; owner filtering must precede the page bound, not follow it.
    clauses = ["source=?", "hidden=0", "json_valid(model_config)",
               "COALESCE(json_extract(model_config,'$.mission_chat_root_id'),id)=id"]
    args = [PERSONA_CHAT_SESSION_SOURCE]
    if owner is not None:
        clauses.append("json_extract(model_config,'$.client_scope')=?")
        args.append(owner)
    if before is not None:
        clauses.append("(started_at,id)<(?,?)")
        args.extend(before)
    return [dict(row) for row in db._read_all(
        "SELECT * FROM sessions WHERE " + " AND ".join(clauses)
        + " ORDER BY started_at DESC,id DESC LIMIT ?", [*args, limit + 1])]
