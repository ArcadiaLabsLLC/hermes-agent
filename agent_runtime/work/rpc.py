"""Console-private Work methods; every board read and git write runs off the reader lane."""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.work.model import Reason, WorkRefused
from agent_runtime.work.service import execute
from agent_runtime.serve_rpc.protocol import DEFERRED, err, ok

__layer__ = "lanes"


def _work_reply(rid, operation, params, caller):
    try:
        return ok(rid, execute(operation, params, caller))
    except WorkRefused as refusal:
        return err(rid, 4090, "This work request could not be accepted.", {"reason": refusal.reason, "detail": refusal.detail})
    except (KeyError, TypeError, ValueError):
        return err(rid, -32602, "Invalid work request.", {"reason": Reason.INVALID})
    except Exception:
        return err(rid, -32000, "The work outcome could not be verified.", {"reason": Reason.UNKNOWN})


def _handler(operation):
    def handle(rid, params, context):
        reply = lambda: _work_reply(rid, operation, params, context.caller)
        if context.spawn_reply is None or not context.spawn_reply(reply):
            return err(rid, 4090, "The runtime is unavailable.", {"reason": "runtime_stopping"})
        return DEFERRED
    return handle


OPERATIONS = ("capabilities", "context", "list", "inspect", "start", "assign", "claim", "release", "set_status",
              "done", "create_brain")


def register(method):
    for operation in OPERATIONS:
        method("runtime.work." + operation, tier=TIER_CONSOLE)(_handler(operation))
