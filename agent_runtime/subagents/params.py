"""Honored parameter discovery for both conversation families."""
from .model import OPERATIONS, COMMAND_PARAMS

__layer__ = "models"

_READ = ("expected_generation", "child_ref")
_NATIVE = ("install_id", "session_id", "client_scope", "profile")
_OPERATOR = ("install_id", "workspace_id", "persona_id", "persona_instance_id", "session_id", "client_scope")
METHOD_PARAMS = {
    prefix + operation: (*identity, *(COMMAND_PARAMS if operation in ("steer", "stop", "receipt") else _READ),
                         *(("text",) if operation == "steer" else ()))
    for prefix, identity in (
        ("runtime.conversation.subagents.", _NATIVE),
        ("runtime.operator.conversation.subagents.", _OPERATOR))
    for operation in OPERATIONS
}
