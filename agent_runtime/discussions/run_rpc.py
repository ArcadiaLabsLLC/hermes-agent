"""Run projections and admissions over the existing discussion service."""
from __future__ import annotations

from .contract import command_body

__layer__ = "lanes"


def _active(service, params, _actor_id):
    return {"rooms": service.active(params["workspace_id"])}


def _list(service, params, _actor_id):
    limit = params.get("limit", 50)
    rows = service.runs.list(params["workspace_id"], limit=limit, after=params.get("after") or "")
    # A full page has a continuation even if the next page is empty.
    return {"runs": rows, "next_cursor": rows[-1]["run_id"] if len(rows) == limit else None}


def _get(service, params, _actor_id):
    return service.view(params["workspace_id"], params["run_id"],
        since_seq=params.get("since_seq", 0), limit=params.get("limit", 100))


def _start(service, params, actor_id):
    return {"run": service.begin(params["workspace_id"], params["table_id"],
        expect_revision=params["expect_revision"], key=params["idempotency_key"],
        topic=params["topic"], actor_id=actor_id)}


def _start_room(service, params, actor_id):
    return {"run": service.begin_room(params["workspace_id"], params["spec"],
        key=params["idempotency_key"], topic=params["topic"], actor_id=actor_id)}


_READS_AND_STARTS = {"active": _active, "list": _list, "get": _get,
                    "start": _start, "start_room": _start_room}


def execute_run(service, action, params, actor_id):
    handler = _READS_AND_STARTS.get(action)
    if handler is not None:
        return handler(service, params, actor_id)
    return service.command(params["workspace_id"], params["run_id"], action,
        key=params["idempotency_key"], expect_revision=params["expect_revision"],
        body=command_body(action, params), actor_id=actor_id)
