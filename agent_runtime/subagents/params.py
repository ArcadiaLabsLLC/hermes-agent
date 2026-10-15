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
