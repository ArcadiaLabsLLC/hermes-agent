"""Honored parameter discovery for the operator conversation family.

Manifest pins: tests/agent_runtime/test_serve_rpc_office.py,
test_serve_rpc_office_subscribe.py and test_serve_rpc_office_upsert.py.
Regenerate tests/agent_runtime/serve_rpc_manifest.expected.json with its producer.
"""
from .model import REQUIRED_PARAMS

__layer__ = "models"

_READ = ("expected_generation", "child_ref")
#: The identity params of a ``runtime.operator.conversation.*`` method; ``console_suggestions`` reads them too.
OPERATOR_IDENTITY_PARAMS = ("install_id", "workspace_id", "persona_id", "persona_instance_id", "session_id", "client_scope")
METHOD_PARAMS = {
    "runtime.operator.conversation.subagents." + operation:
        (*OPERATOR_IDENTITY_PARAMS, *_READ, *(key for key in required if key not in _READ))
    for operation, required in REQUIRED_PARAMS.items()
}

SKILLS_OPERATIONS = ("list", "detail", "history", "lend")

#: ``runtime.operator.conversation.skills`` (one verb, ``operation`` = one of :data:`SKILLS_OPERATIONS`):
#: the conversation's skills, or with ``child_ref`` (from ``runtime.operator.conversation.subagents.list``)
#: a worker child's; ``operation: lend`` always names a child (RT-SERVE-SKILLS-OPERATOR-CHILD-ADDRESS).
METHOD_PARAMS["runtime.operator.conversation.skills"] = (
    *OPERATOR_IDENTITY_PARAMS, "operation", "child_ref", "skill_id", "skills", "mode", "request_id")
