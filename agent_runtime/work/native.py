"""Adapter to public native task APIs. No private imports or lifecycle writes."""
from __future__ import annotations

from pathlib import Path

from hermes_cli import kanban_db as tasks
from hermes_cli.kanban_db_connect import connect_closing
from hermes_cli.profiles import get_profile_dir, list_profile_names

from .model import Reason, WorkRefused, WorkScope, fingerprint, text

__layer__ = "stores"
PAGE_SIZE = 40
OUTPUT_LIMIT = 64000


def scopes(install):
    profiles = [(name, str(get_profile_dir(name).resolve())) for name in list_profile_names()]
    owners = {}
    for board in tasks.list_boards(include_archived=False):
        if board.get("archived"):
            continue
        database = str(tasks.kanban_db_path(board["slug"]).resolve())
        for name, home in profiles:
            # HERMES_KANBAN_DB can pin all slugs to one native database. Present
            # that authority once, rather than offering duplicate task sources.
            owners.setdefault((database, name, home),
                (WorkScope(install, board["slug"], name, database, home), board["name"]))
    return list(owners.values())


def project(task, summary=None, *, detail=False, context=None):
    result = task.result or summary or ""
    value = {"id": task.id, "title": task.title, "status": task.status,
             "assignee": task.assignee, "block_kind": task.block_kind,
             "created_at": task.created_at, "started_at": task.started_at,
             "completed_at": task.completed_at, "heartbeat_at": task.last_heartbeat_at,
             "result": result[:OUTPUT_LIMIT] if detail else "",
             "result_truncated": detail and len(result) > OUTPUT_LIMIT,
             "body": (task.body or "")[:50000] if detail else "",
             "body_truncated": detail and len(task.body or "") > 50000}
    if context is not None:
        value["in_conversation"] = bool(context.session and task.session_id == context.session)
    value["revision"] = fingerprint(value)
    return value


def _owned(conn, scope, task_id):
    task = tasks.get_task(conn, task_id)
    if task is None:
        return None
    if task.assignee != scope.profile:
        raise WorkRefused(Reason.OWNER_CHANGED)
    return task


def inspect(scope, params, *, context=None):
    task_id = text(params.get("task_id"))
    if not Path(scope.database).is_file():
        return {"task": None}
    with connect_closing(db_path=Path(scope.database), board=scope.board) as conn:
        task = _owned(conn, scope, task_id)
        return {"task": None if task is None else project(
            task, tasks.latest_summary(conn, task.id), detail=True, context=context)}


def list_work(scope, params, *, context=None):
    view = params.get("view", "all")
    if view not in ("all", "agent", "conversation") or (view != "all" and context is None):
        raise WorkRefused(Reason.INVALID)
    if context and ((view == "conversation" and not context.session)
                    or (view == "agent" and scope.profile != context.profile)):
        return {"tasks": [], "cursor": None}
    cursor = params.get("cursor")
    if cursor is not None and (not isinstance(cursor, list) or len(cursor) != 2
            or type(cursor[0]) is not int or not isinstance(cursor[1], str)):
        raise WorkRefused(Reason.INVALID)
    if not Path(scope.database).is_file():
        return {"tasks": [], "cursor": None}
    with connect_closing(db_path=Path(scope.database), board=scope.board) as conn:
        # Native API owns queries/schema. Keyset slicing avoids offset skips when
        # another surface inserts or archives work between requests.
        rows = tasks.list_tasks(conn, assignee=scope.profile, order_by="created-desc",
                                session_id=context.session if view == "conversation" else None)
        eligible = (row for row in rows if cursor is None or (row.created_at, row.id) < tuple(cursor))
        from itertools import islice
        page = list(islice(eligible, PAGE_SIZE + 1))
        visible = page[:PAGE_SIZE]
        after = [visible[-1].created_at, visible[-1].id] if len(page) > PAGE_SIZE else None
        return {"tasks": [project(row, context=context) for row in visible], "cursor": after}


def start(scope, params, actor, *, context=None):
    title = text(params.get("title"), maximum=160).strip()
    body = text(params.get("body"), maximum=50000, multiline=True)
    request = text(params.get("request_id"))
    client = text(params.get("client_scope"))
    session = context.session if context else None
    key = "eternia:work:" + fingerprint([actor, client, scope.owner, request])
    with connect_closing(db_path=Path(scope.database), board=scope.board) as conn:
        # Native create permits an outer IMMEDIATE transaction. Acquire it BEFORE
        # replay lookup: simultaneous surfaces cannot create duplicate requests.
        with tasks.write_txn(conn):
            previous = next((row for row in tasks.list_tasks(conn, include_archived=True)
                             if row.idempotency_key == key), None)
            if previous is not None:
                if (previous.title, previous.body, previous.assignee, previous.session_id) != (title, body, scope.profile, session):
                    raise WorkRefused(Reason.CONFLICT)
                task = previous
            else:
                task_id = tasks.create_task(conn, title=title, body=body, assignee=scope.profile,
                    idempotency_key=key, created_by="user", workspace_kind="scratch", board=scope.board,
                    session_id=session)
                task = _owned(conn, scope, task_id)
        return {"task": project(task, tasks.latest_summary(conn, task.id), detail=True, context=context),
                "disposition": "accepted"}
