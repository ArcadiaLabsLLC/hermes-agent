"""Console history controls: the same exact-conversation RPC boundary."""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.operator_history import apply_operator_history, preview_operator_history, operator_history_status
from agent_runtime.operator_conversation import OperatorConversationRefused
from agent_runtime.operator_checkpoints import (
    list_operator_checkpoints, preview_operator_checkpoint, restore_operator_checkpoint, operator_checkpoint_status,
)
from .operator_inspection import _inspect_off_reader
from .registry import method
from .protocol import DEFERRED, deferred_reply, ok, err
from tools.checkpoint_pruning import CheckpointStoreBusy

__layer__ = "lanes"


@method("runtime.operator.conversation.history.preview", tier=TIER_CONSOLE)
def preview_history(rid, params, context=None):
    return _inspect_off_reader(rid, params, context,
                              "runtime.operator.conversation.history.preview", preview_operator_history)


@method("runtime.operator.conversation.history.apply", tier=TIER_CONSOLE)
def apply_history(rid, params, context=None):
    return _mutate_off_reader(rid, params, context,
                              "runtime.operator.conversation.history.apply", apply_operator_history)


@method("runtime.operator.conversation.checkpoints", tier=TIER_CONSOLE)
def checkpoints(rid, params, context=None):
    return _inspect_off_reader(rid, params, context,
                              "runtime.operator.conversation.checkpoints", list_operator_checkpoints)


@method("runtime.operator.conversation.checkpoint.preview", tier=TIER_CONSOLE)
def preview_checkpoint(rid, params, context=None):
    return _inspect_off_reader(rid, params, context,
                              "runtime.operator.conversation.checkpoint.preview", preview_operator_checkpoint)


@method("runtime.operator.conversation.checkpoint.restore", tier=TIER_CONSOLE)
def restore_checkpoint(rid, params, context=None):
    return _mutate_off_reader(rid, params, context,
                              "runtime.operator.conversation.checkpoint.restore", restore_operator_checkpoint)


@method("runtime.operator.conversation.history.status", tier=TIER_CONSOLE)
def history_status(rid, params, context=None):
    return _inspect_off_reader(rid, params, context,
                              "runtime.operator.conversation.history.status", operator_history_status)


@method("runtime.operator.conversation.checkpoint.status", tier=TIER_CONSOLE)
def checkpoint_status(rid, params, context=None):
    return _inspect_off_reader(rid, params, context,
                              "runtime.operator.conversation.checkpoint.status", operator_checkpoint_status)


def _mutate_off_reader(rid, params, context, operation, mutate):
    def reply():
        try:
            return ok(rid, mutate(params))
        except OperatorConversationRefused as exc:
            return err(rid, 4090, "This operation could not be applied.", {"reason": exc.reason})
        except CheckpointStoreBusy:
            return err(rid, 4090, "File history is busy. Try again shortly.", {"reason": "checkpoint_store_busy"})
        except Exception:
            return err(rid, -32000, "The operation's outcome could not be confirmed.",
                       {"reason": "turn_outcome_unknown"})
    build = deferred_reply(rid, operation, reply)
    if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
        return DEFERRED
    return build()
