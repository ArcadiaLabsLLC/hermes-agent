"""Focused native conversations on the existing authenticated method lane."""
from __future__ import annotations

import logging
from functools import partial

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import DEFERRED

from .binding import get_service
from .model import ConversationError, ConversationScope, Refusal, digest, identifier

__layer__ = "lanes"
PREFIX = "runtime.conversation."
logger = logging.getLogger(__name__)


def _open(service, scope, params):
    return service.open(scope, key=identifier(params["key"]), cwd=identifier(params["cwd"]),
                        resume=params.get("resume"), expected_home=identifier(params["profile_home"]))


def _send(service, scope, params):
    return service.send(scope, identifier(params["session_id"]), identifier(params["turn_id"]), params["prompt"])


def _read_conversation(service, scope, params):
    cursor = params.get("cursor", 0)
    if type(cursor) is not int or cursor < 0:
        raise ConversationError(Refusal.INVALID_REQUEST)
    return service.read(scope, identifier(params["session_id"]), cursor, params.get("turn_id"))


def _stop(service, scope, params):
    return service.stop(scope, identifier(params["session_id"]), identifier(params["turn_id"]))


def _respond(service, scope, params):
    if not isinstance(params["result"], dict):
        raise ConversationError(Refusal.INVALID_REQUEST)
    return service.respond(scope, identifier(params["session_id"]), identifier(params["request_id"]), params["result"])


def _facts(service, scope, params):
    return service.facts(scope, identifier(params["session_id"]))


def _model(service, scope, params):
    return service.select_model(scope, identifier(params["session_id"]), identifier(params["model_id"]))


def _skills(action, service, scope, params):
    return service.skills(scope, identifier(params["session_id"]), action,
                          identifier(params["skill_id"]) if action == "detail" else None)


OPERATIONS = {"open": _open, "send": _send, "read": _read_conversation, "stop": _stop,
              "respond": _respond, "facts": _facts, "model": _model,
              **{"skills." + action: partial(_skills, action) for action in ("list", "detail", "history")}}


def execute(operation: str, params: dict, caller) -> dict:
    service = get_service()
    if operation == "capabilities":
        return service.capabilities()
    if params["install_id"] != service.install_id:
        raise ConversationError(Refusal.WRONG_OWNER)
    actor = digest({"kind": caller.kind, "device": caller.device_id})
    scope = ConversationScope(actor, identifier(params["client_scope"]), identifier(params["profile"]))
    return OPERATIONS[operation](service, scope, params)


def register(method, ok, err) -> None:
    for operation in ("capabilities", *OPERATIONS):
        def handler(rid, params, context, operation=operation):
            def run():
                try:
                    return ok(rid, execute(operation, params, context.caller))
                except ConversationError as exc:
                    return err(rid, 4090, "This conversation is unavailable.",
                               {"reason": exc.reason, "native_code": exc.native_code})
                except (KeyError, TypeError, ValueError):
                    return err(rid, -32602, "Invalid conversation request.", {"reason": Refusal.INVALID_REQUEST})
                except Exception:
                    # Never include provider diagnostics, prompts or credentials.
                    logger.warning("Native conversation operation failed: %s", operation)
                    return err(rid, -32000, "The conversation could not be verified.",
                               {"reason": Refusal.UNKNOWN})
            if operation in {"capabilities", "read", "stop", "respond"}:
                return run()
            if context.spawn_reply is None or not context.spawn_reply(run):
                return err(rid, 4090, "The runtime cannot accept this request.",
                           {"reason": Refusal.RUNTIME_STOPPING})
            return DEFERRED
        # Transcripts, tool arguments and server questions are console-private,
        # not a read-tier monitoring projection. Execution also requires console.
        method(PREFIX + operation, tier=TIER_CONSOLE)(handler)
