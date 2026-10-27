"""Account-scoped pages over native persona-chat history, never a second catalog."""
from __future__ import annotations

import json
import math
from contextlib import closing

from . import chat_session_scope
from .conversation_owner import ConversationOwnerError, request_client_scope
from .instance_selection import verify_instance_install, InstanceSelectionError
from .instance_sessions import instance_session_clause
from .persona_assignments import PersonaInstanceStore, chat_session_owner_instance_id
from .persona_assignments.lookups import normalize_persona_or_template_id
from .persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from .persona_chat_history.history_rows import _history_row, _model_config
from .workspace_scope import effective_workspace_id

__layer__ = "lanes"


class InstanceHistoryRefused(ValueError):
    pass


#: The keys ``runtime.operator.conversation.list`` honours, published in the serve
#: manifest's ``params`` block (``serve_rpc.registry.manifest``) so a client can tell
#: an honoured ``persona_instance_id`` / ``persona_id`` filter from a runtime that
#: would ignore it.
#: Pinned by ``tests/agent_runtime/serve_rpc_manifest.expected.json`` and
#: ``tests/agent_runtime/test_instance_history.py``.
CONVERSATION_LIST_METHOD = "runtime.operator.conversation.list"
CONVERSATION_LIST_METHOD_PARAMS = (
    "all_accounts", "before", "client_scope", "install_id", "limit", "persona_id",
    "persona_instance_id", "legacy_route_id",
)

_INSTANCE_ID_LIMIT = 200


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
    instance_id = params.get("persona_instance_id")
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id
                                    or len(instance_id) > _INSTANCE_ID_LIMIT):
        raise InstanceHistoryRefused("invalid_history_query")
    persona_id = _requested_persona(params.get("persona_id"))
    legacy_route = params.get("legacy_route_id")
    if legacy_route is not None and (not isinstance(legacy_route, str) or not legacy_route
                                     or len(legacy_route) > 512):
        raise InstanceHistoryRefused("invalid_history_query")
    scope = (params["install_id"], owner, all_accounts, instance_id, persona_id, legacy_route)
    before = _history_position(params.get("before"), scope)
    db = chat_session_scope.open_chat_session_db(access=chat_session_scope.SessionDbAccess.READ)
    if db is None:
        if chat_session_scope.chat_session_store_exists():
            raise InstanceHistoryRefused("session_db_unavailable")
        return {"conversations": [], "next_cursor": None, "legacy_route_id": legacy_route}
    with closing(db):
        scan = PersonaInstanceStore().scan_all()
        if scan.unreadable:
            raise InstanceHistoryRefused("instance_roster_unreadable")
        instances = {instance.id: instance for instance in scan.instances}
        persona = None if persona_id is None else (persona_id, sorted(
            instance.id for instance in scan.instances if instance.persona_id == persona_id))
        # Cross-agent fan-out (chat-head plan §2.4): each per_profile head opened
        # once, read-only, paged with the same keyset, merged by that key.
        with chat_session_scope.per_profile_read_heads(scan.instances, process_db=db) as heads:
            sources = [read.db for read in {id(r): r for r in heads.values()}.values()
                       if read.db is not None] + [db]
            raw = _merged_pages([(source, _history_page(
                source, owner=None if all_accounts else owner, instance_id=instance_id,
                persona=persona, legacy_route=legacy_route, before=before, limit=limit))
                for source in sources], limit)
            visible = raw[:limit]
            rows = [_project_instance_history(source, item, instances, params["install_id"])
                    for source, item in visible]
    cursor = None
    if len(raw) > limit:
        last = visible[-1][1]
        cursor = json.dumps([*scope, last["started_at"], last["id"]], separators=(",", ":"))
    return {"conversations": rows, "next_cursor": cursor, "legacy_route_id": legacy_route}


def _merged_pages(pages, limit):
    """``(source, row)`` pairs from every store's page, newest first, first copy of an id wins.

    Each page is already ``started_at DESC, id DESC`` before the same cursor, so
    the merged first ``limit + 1`` is the page one store would have answered.
    SQLite sorts a NULL ``started_at`` last under DESC; the key does too.
    """

    seen, merged = set(), []
    for source, rows in pages:
        for row in rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                merged.append((source, row))
    merged.sort(key=lambda pair: (pair[1]["started_at"] is not None, pair[1]["started_at"] or 0,
                                  pair[1]["id"]), reverse=True)
    return merged[:limit + 1]


def _project_instance_history(db, raw, instances, install_id):
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
    origin = config.get("legacy_conversation")
    if isinstance(origin, dict):
        row["legacy_conversation"] = {key: origin.get(key) for key in ("route_id", "profile")}
    return row


def _requested_persona(value):
    """The persona filter, canonical the way ``ensure_persona_chat_session`` stamps it."""

    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > _INSTANCE_ID_LIMIT:
        raise InstanceHistoryRefused("invalid_history_query")
    try:
        canonical = normalize_persona_or_template_id(value)
    except Exception as exc:
        raise InstanceHistoryRefused("invalid_history_query") from exc
    if not canonical:
        raise InstanceHistoryRefused("invalid_history_query")
    return canonical


def _history_position(value, scope):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError()
        row = json.loads(value)
        width = len(scope)
        if (not isinstance(row, list) or len(row) != width + 2 or tuple(row[:width]) != scope
                or type(row[width]) not in (int, float) or not math.isfinite(row[width])
                or not isinstance(row[width + 1], str) or not row[width + 1]):
            raise ValueError()
        return row[width], row[width + 1]
    except (ValueError, TypeError) as exc:
        raise InstanceHistoryRefused("invalid_history_cursor") from exc


def _history_page(db, *, owner, instance_id=None, persona=None, legacy_route=None, before, limit):
    # SessionDB has no metadata predicate on list_sessions_rich. Use its pooled
    # read boundary; owner, instance AND persona filtering must precede the page
    # bound, not follow it. Both predicates mirror _project_instance_history: the
    # instance is the model_config's persona_instance_id, else the owner minted
    # into the id; the persona is the model_config's persona_id, else the persona
    # of that instance in the roster (``persona`` = (id, roster instance ids)).
    clauses = ["source=?", "hidden=0", "(model_config IS NULL OR json_valid(model_config))",
               "COALESCE(json_extract(model_config,'$.mission_chat_root_id'),id)=id"]
    args = [PERSONA_CHAT_SESSION_SOURCE]
    if owner is not None:
        clauses.append("json_extract(model_config,'$.client_scope')=?")
        args.append(owner)
    if legacy_route is not None:
        clauses.append("json_extract(model_config,'$.legacy_conversation.route_id')=?")
        args.append(legacy_route)
    if instance_id is not None:
        clause, values = instance_session_clause(instance_id)
        clauses.append(clause)
        args.extend(values)
    if persona is not None:
        persona_id, roster = persona
        fallback = [instance_session_clause(member) for member in roster]
        unstamped = ("(COALESCE(json_extract(model_config,'$.persona_id'),'')='' AND ("
                     + " OR ".join(clause for clause, _ in fallback) + "))") if fallback else None
        clauses.append("(json_extract(model_config,'$.persona_id')=?"
                       + (" OR " + unstamped if unstamped else "") + ")")
        args.append(persona_id)
        for _, values in fallback:
            args.extend(values)
    if before is not None:
        clauses.append("(started_at,id)<(?,?)")
        args.extend(before)
    return [dict(row) for row in db._read_all(
        "SELECT * FROM sessions WHERE " + " AND ".join(clauses)
        + " ORDER BY started_at DESC,id DESC LIMIT ?", [*args, limit + 1])]
