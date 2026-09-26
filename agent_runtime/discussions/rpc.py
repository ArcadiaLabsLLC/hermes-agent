"""Thin handlers on the existing authenticated serve method lane."""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from gateway.hosted_room_discussion import DiscussionReconstructionError, DiscussionValidationError
from gateway.hosted_rooms import HostedRoomError

from .contract import CONTRACT_VERSION, METHODS, PREFIX, command_body, contract_descriptor, validate_params
from .definitions import DefinitionError, plan_seats
from .run_store import DiscussionError, digest
from .service import DiscussionService, get_service

__layer__ = "lanes"

logger = logging.getLogger(__name__)


def _record(record) -> dict[str, Any]:
    row = record.to_dict()
    if record.kind == "table":
        plan = plan_seats(record.spec)
        row["seat_plan"] = {"capacity": record.spec.seat_count,
            "assignments": [a.to_dict() for a in plan.assignments],
            "remapped": [p.to_dict() for p in plan.remapped]}
    return row


def execute(service: DiscussionService, operation: str, raw: Any, *, actor_id: str) -> dict[str, Any]:
    params = validate_params(operation, raw)
    if operation == "capabilities":
        return {**contract_descriptor(), "accepting": service.accepting, "install_id": service.context.install_id}
    workspace = params["workspace_id"]
    service.context.workspace(workspace)
    if operation == "roster":
        return {"agents": service.context.roster(workspace), "install_id": service.context.install_id}
    family, action = operation.split(".", 1)
    if family in {"table", "preset"}:
        if action == "list":
            page = service.definitions.list(family, workspace, limit=params.get("limit", 50), after=params.get("after"))
            return {"records": [_record(r) for r in page.records], "next_cursor": page.next_cursor}
        key = params[family + "_id"]
        if action == "get":
            return {"record": _record(service.definitions.get(family, workspace, key))}
        if not service.accepting:
            raise DiscussionError("runtime_stopping")
        if action == "save":
            save = service.definitions.save_table if family == "table" else service.definitions.save_preset
            return {"record": _record(save(workspace, key, params["spec"], expect_revision=params["expect_revision"]))}
        if action == "delete":
            return {"revision": service.definitions.delete(family, workspace, key, expect_revision=params["expect_revision"])}
        if action == "load_preset":
            row = service.definitions.load_preset(workspace, key, params["preset_id"],
                expect_table_revision=params["expect_revision"], expect_preset_revision=params["expect_preset_revision"])
        elif action == "custom":
            row = service.definitions.custom_table(workspace, key, expect_revision=params["expect_revision"])
        else:
            row = service.definitions.revert_table(workspace, key, expect_revision=params["expect_revision"])
        return {"record": _record(row)}
    if action == "active":
        return {"rooms": service.active(workspace)}
    if action == "list":
        rows = service.runs.list(workspace, limit=params.get("limit", 50), after=params.get("after") or "")
        # A full page has a continuation even if the next page is empty. Never
        # silently truncate a history to what happened to fit this response.
        return {"runs": rows, "next_cursor": rows[-1]["run_id"] if len(rows) == params.get("limit", 50) else None}
    if action == "get":
        return service.view(workspace, params["run_id"], since_seq=params.get("since_seq", 0), limit=params.get("limit", 100))
    if action == "start":
        return {"run": service.begin(workspace, params["table_id"], expect_revision=params["expect_revision"],
            key=params["idempotency_key"], topic=params["topic"], actor_id=actor_id)}
    return service.command(workspace, params["run_id"], action, key=params["idempotency_key"],
        expect_revision=params["expect_revision"], body=command_body(action, params), actor_id=actor_id)


def register(method, ok, err) -> None:
    for operation, (tier, _required, _optional) in METHODS.items():
        def handler(rid, params, context, operation=operation):
            try:
                # A device's stable credential identity survives reconnect. Never
                # accept a self-declared actor/user ID from request parameters.
                actor_id = "console-" + digest({"kind": context.caller.kind, "device": context.caller.device_id})[:24]
                result = execute(get_service(), operation, params, actor_id=actor_id)
                return ok(rid, {"contract_version": CONTRACT_VERSION, **result})
            except DefinitionError as exc:
                code = 4090 if exc.reason in {"stale_revision", "stale_preset_revision", "definition_deleted", "table_busy"} else -32602
                return err(rid, code, str(exc), {"reason": exc.reason, "field": exc.field, **exc.details})
            except DiscussionError as exc:
                return err(rid, 4090, str(exc), {"reason": exc.reason, **exc.details})
            except (DiscussionValidationError, DiscussionReconstructionError) as exc:
                # Room policy raises plain ValueError subclasses that reach reads
                # (run.get / run.active / run.list) outside any command's own
                # refusal handling. Without this arm they land on serve_rpc's
                # generic boundary as ``handler_failed`` carrying the raw
                # exception text, which is neither branchable nor safe to show.
                reason = ("discussion_invalid" if isinstance(exc, DiscussionValidationError)
                          else "discussion_unreconstructable")
                logger.warning("Discussion policy refused %s: %s", operation, reason)
                return err(rid, 4090, "This discussion's state could not be read; reload it.", {"reason": reason})
            except HostedRoomError as exc:
                # Same class of escape from the hosted-room store itself. Typed
                # subclasses already name themselves; the rest are one reason.
                reason = getattr(exc, "reason", None) or "room_unavailable"
                logger.warning("Hosted room refused %s: %s", operation, reason)
                return err(rid, 4090, "This meeting room is unavailable; reload it.", {"reason": reason})
            except sqlite3.Error:
                logger.exception("Discussion storage operation failed: %s", operation)
                return err(rid, -32000, "Discussion storage unavailable; reconcile the original intent before retrying.", {"reason": "storage_unavailable"})
        method(PREFIX + operation, tier=tier)(handler)
