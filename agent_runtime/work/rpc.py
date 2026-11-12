"""Console-private Task methods (``runtime.work.<operation>``); every board read and git write runs off the reader lane.

A Task is a row of a workspace board. What is running now (processes, builds, helper agents, tool
calls) is ``agent_runtime/serve_rpc/work.py``'s ``runtime.work.{cancel,restart,background.promote}`` —
a separate id space; the messages here say "task" so a refusal is never read as one about running
things (RT-WORK-WORD-MEANS-TASKS-AND-RUNNING-THINGS).
"""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.work.model import Reason, WorkRefused
from agent_runtime.work.service import execute
from agent_runtime.serve_rpc.protocol import defer_or_refuse, err, ok

__layer__ = "lanes"


def _work_reply(rid, operation, params, caller):
    try:
        return ok(rid, execute(operation, params, caller))
    except WorkRefused as refusal:
        return err(rid, 4090, "This task request could not be accepted.",
                   {"reason": refusal.reason, "detail": refusal.detail, **refusal.data})
    except (KeyError, TypeError, ValueError):
        return err(rid, -32602, "Invalid task request.", {"reason": Reason.INVALID})
    except Exception:
        return err(rid, -32000, "The task outcome could not be verified.", {"reason": Reason.UNKNOWN})


def _work_method(operation):
    def handle(rid, params, context):
        return defer_or_refuse(rid, "runtime.work." + operation, context,
                               lambda: _work_reply(rid, operation, params, context.caller))
    return handle


OPERATIONS = ("capabilities", "context", "list", "inspect", "start", "edit", "assign", "claim", "release", "set_status",
              "move", "answer", "pull", "done", "close", "create_brain", "lend_skills")


def register(method):
    for operation in OPERATIONS:
        method("runtime.work." + operation, tier=TIER_CONSOLE)(_work_method(operation))
