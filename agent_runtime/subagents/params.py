"""Honored parameter discovery for both conversation families.

Manifest pins: tests/agent_runtime/test_serve_rpc_office.py,
test_serve_rpc_office_subscribe.py and test_serve_rpc_office_upsert.py.
Regenerate tests/agent_runtime/serve_rpc_manifest.expected.json with its producer.
"""
from .model import REQUIRED_PARAMS

__layer__ = "models"

_READ = ("expected_generation", "child_ref")
_NATIVE = ("install_id", "session_id", "client_scope", "profile")
_OPERATOR = ("install_id", "workspace_id", "persona_id", "persona_instance_id", "session_id", "client_scope")
METHOD_PARAMS = {
    prefix + operation: (*identity, *_READ, *(key for key in required if key not in _READ))
    for prefix, identity in (
        ("runtime.conversation.subagents.", _NATIVE),
        ("runtime.operator.conversation.subagents.", _OPERATOR))
    for operation, required in REQUIRED_PARAMS.items()
}

#: ``runtime.conversation.skills.*``: the session's skills, or (``child_ref``, from a
#: ``runtime.conversation.subagents.*`` read) a worker child's; ``lend`` writes a child's lend
#: (``eternia.skills.lend``). Published so a client can tell a child read from a runtime that
#: would silently answer the parent's catalog.
SKILLS_OPERATIONS = ("list", "detail", "history", "lend")
_SKILLS_EXTRA = {"list": (), "detail": ("skill_id",), "history": (), "lend": ("skills", "mode", "request_id")}
METHOD_PARAMS.update({
    "runtime.conversation.skills." + operation: (*_NATIVE, "child_ref", *_SKILLS_EXTRA[operation])
    for operation in SKILLS_OPERATIONS
})
