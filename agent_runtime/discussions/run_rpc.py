"""Run projections and admissions over the existing discussion service."""
from __future__ import annotations

from .contract import command_body
from .member_models import member_models
from .room_owner import require_room_owner

__layer__ = "lanes"


def _active(service, params, account_access):
    return {"rooms": service.active(params["workspace_id"], client_scope=params.get("client_scope"),
                                     include_owned=account_access)}


def _list(service, params, account_access):
    limit = params.get("limit", 50)
    rows = service.runs.list(params["workspace_id"], limit=limit, after=params.get("after") or "",
                             client_scope=params.get("client_scope"), include_owned=account_access)
    # A full page has a continuation even if the next page is empty.
    return {"runs": rows, "next_cursor": rows[-1]["run_id"] if len(rows) == limit else None}


def _get(service, params, _actor_id):
    return service.view(params["workspace_id"], params["run_id"],
        since_seq=params.get("since_seq", 0), limit=params.get("limit", 100))


def _start(service, params, actor_id):
    return {"run": service.begin(params["workspace_id"], params["table_id"],
        expect_revision=params["expect_revision"], key=params["idempotency_key"],
        topic=params["topic"], actor_id=actor_id, client_scope=params.get("client_scope"))}


def _start_room(service, params, actor_id):
    return {"run": service.begin_room(params["workspace_id"], params["spec"],
        key=params["idempotency_key"], topic=params["topic"], actor_id=actor_id,
        client_scope=params.get("client_scope"))}


def _start_group(service, params, actor_id):
    return {"run": service.begin_group(params["spec"], key=params["idempotency_key"],
        actor_id=actor_id, client=params["client_scope"])}


def _respond(service, params, _actor_id):
    return service.respond(params)


_CATALOG_READS = {"active": _active, "list": _list}
_READS_AND_STARTS = {"get": _get,
                    "member_models": lambda s, p, a: member_models(s, p),
                    "member_model": lambda s, p, a: member_models(s, p, select=True),
                    "start": _start, "start_room": _start_room, "start_group": _start_group, "respond": _respond}


def execute_run(service, action, params, actor_id, *, account_access=True):
    if "run_id" in params:
        require_room_owner(service.runs.get(params["run_id"], params["workspace_id"]), params.get("client_scope"),
                           account_access=account_access)
    if catalog := _CATALOG_READS.get(action):
        return catalog(service, params, account_access)
    handler = _READS_AND_STARTS.get(action)
    if handler is not None:
        return handler(service, params, actor_id)
    return service.command(params["workspace_id"], params["run_id"], action,
        key=params["idempotency_key"], expect_revision=params["expect_revision"],
        body=command_body(action, params), actor_id=actor_id)
