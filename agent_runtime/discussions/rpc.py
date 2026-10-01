"""Thin handlers on the existing authenticated serve method lane."""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from gateway.hosted_room_discussion import DiscussionReconstructionError, DiscussionValidationError
from gateway.hosted_rooms import HostedRoomError

from .contract import CONTRACT_VERSION, METHODS, PREFIX, contract_descriptor, validate_params
from .definition_rpc import execute_definition
from .definitions import DefinitionError
from .run_rpc import execute_run
from .run_store import DiscussionError, digest
from .service import DiscussionService, get_service
from .profile_groups import group_scope, is_group_scope
from agent_runtime.conversations.model import ConversationError
from .app_functions import requesting_launcher
from agent_runtime.call_authorization import authorize_call, TIER_CONSOLE

__layer__ = "lanes"

logger = logging.getLogger(__name__)


_CONTEXT_READS = {
    "capabilities": lambda s, p: {**contract_descriptor(), "accepting": s.accepting,
        "install_id": s.context.install_id, "execution_identity_guard": True},
    "workspaces": lambda s, p: {"workspaces": s.context.workspaces(), "install_id": s.context.install_id},
    "roster": lambda s, p: {"agents": s.context.roster(p["workspace_id"]), "install_id": s.context.install_id},
}


def execute(service: DiscussionService, operation: str, raw: Any, *, actor_id: str,
            account_access: bool = True) -> dict[str, Any]:
    params = validate_params(operation, raw)
    if "workspace_id" in params:
        scope = params["workspace_id"]
        if is_group_scope(scope) or operation == "run.start_group":
            if (not params.get("client_scope") or scope != group_scope(actor_id, params["client_scope"])
                    or not operation.startswith("run.")):
                raise DiscussionError("conversation_owner_changed")
        else:
            service.context.workspace(scope)
    if operation in _CONTEXT_READS:
        result = _CONTEXT_READS[operation](service, params)
        if operation == "capabilities" and params.get("client_scope"):
            result["group_scope"] = group_scope(actor_id, params["client_scope"])
        return result
    family, action = operation.split(".", 1)
    if family in {"table", "preset"}:
        return execute_definition(service, family, action, params)
    return execute_run(service, action, params, actor_id, account_access=account_access)


def register(method, ok, err) -> None:
    for operation, (tier, _required, _optional) in METHODS.items():
        def handler(rid, params, context, operation=operation):
            try:
                # A device's stable credential identity survives reconnect. Never
                # accept a self-declared actor/user ID from request parameters.
                actor_id = "console-" + digest({"kind": context.caller.kind, "device": context.caller.device_id})[:24]
                with requesting_launcher(context.launcher_request):
                    result = execute(get_service(), operation, params, actor_id=actor_id,
                        account_access=authorize_call(TIER_CONSOLE, context.caller, method=PREFIX + operation).ok)
                return ok(rid, {"contract_version": CONTRACT_VERSION, **result})
            except DefinitionError as exc:
                code = 4090 if exc.reason in {"stale_revision", "stale_preset_revision", "definition_deleted", "table_busy"} else -32602
                return err(rid, code, str(exc), {"reason": exc.reason, "field": exc.field, **exc.details})
            except DiscussionError as exc:
                return err(rid, 4090, str(exc), {"reason": exc.reason, **exc.details})
            except ConversationError as exc:
                return err(rid, 4090, "The agent's response could not be confirmed. Check the pending request.",
                           {"reason": str(exc.reason)})
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
