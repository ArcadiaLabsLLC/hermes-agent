"""Definition authoring handlers; live-run dispatch lives separately."""
from __future__ import annotations

from .definitions import plan_seats
from .run_store import DiscussionError

__layer__ = "lanes"


def _definition_record(record):
    row = record.to_dict()
    if record.kind == "table":
        plan = plan_seats(record.spec)
        row["seat_plan"] = {"capacity": record.spec.seat_count,
            "assignments": [a.to_dict() for a in plan.assignments],
            "remapped": [p.to_dict() for p in plan.remapped]}
    return row


def _save(store, family, params):
    save = {"table": store.save_table, "preset": store.save_preset}[family]
    return {"record": _definition_record(save(params["workspace_id"], params[family + "_id"],
        params["spec"], expect_revision=params["expect_revision"]))}


def _delete(store, family, params):
    return {"revision": store.delete(family, params["workspace_id"], params[family + "_id"],
        expect_revision=params["expect_revision"])}


def _load_preset(store, _family, params):
    return {"record": _definition_record(store.load_preset(params["workspace_id"], params["table_id"],
        params["preset_id"], expect_table_revision=params["expect_revision"],
        expect_preset_revision=params["expect_preset_revision"]))}


def _custom(store, _family, params):
    return {"record": _definition_record(store.custom_table(params["workspace_id"], params["table_id"],
        expect_revision=params["expect_revision"]))}


def _revert(store, _family, params):
    return {"record": _definition_record(store.revert_table(params["workspace_id"], params["table_id"],
        expect_revision=params["expect_revision"]))}


_WRITES = {"save": _save, "delete": _delete, "load_preset": _load_preset,
           "custom": _custom, "revert": _revert}


def execute_definition(service, family, action, params):
    store, workspace = service.definitions, params["workspace_id"]
    if action == "list":
        page = store.list(family, workspace, limit=params.get("limit", 50), after=params.get("after"))
        return {"records": [_definition_record(r) for r in page.records], "next_cursor": page.next_cursor}
    if action == "get":
        return {"record": _definition_record(store.get(family, workspace, params[family + "_id"]))}
    if not service.accepting:
        raise DiscussionError("runtime_stopping")
    return _WRITES[action](store, family, params)
