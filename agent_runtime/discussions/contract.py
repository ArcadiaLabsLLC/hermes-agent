"""The additive Discussion RPC contract. Importing it never initializes a store."""
from __future__ import annotations

from typing import Any, Mapping
from .definitions import CAPACITIES, TableStyle, DefinitionError, ParticipantRef, identifier, revision
from .run_store import text

__layer__ = "stores"

CONTRACT_VERSION = 1
PREFIX = "runtime.discussion."
# Each method owns an exact parameter shape; body keys are not accepted by a
# catch-all action endpoint. Explicit fields also drive the compatibility fixture.
METHODS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "capabilities": ("read", (), ()),
    "roster": ("read", ("workspace_id",), ()),
    "table.list": ("read", ("workspace_id",), ("limit", "after")),
    "table.get": ("read", ("workspace_id", "table_id"), ()),
    "table.save": ("console", ("workspace_id", "table_id", "expect_revision", "spec"), ()),
    "table.delete": ("console", ("workspace_id", "table_id", "expect_revision"), ()),
    "table.load_preset": ("console", ("workspace_id", "table_id", "preset_id", "expect_revision", "expect_preset_revision"), ()),
    "table.revert": ("console", ("workspace_id", "table_id", "expect_revision"), ()),
    "table.custom": ("console", ("workspace_id", "table_id", "expect_revision"), ()),
    "preset.list": ("read", ("workspace_id",), ("limit", "after")),
    "preset.get": ("read", ("workspace_id", "preset_id"), ()),
    "preset.save": ("console", ("workspace_id", "preset_id", "expect_revision", "spec"), ()),
    "preset.delete": ("console", ("workspace_id", "preset_id", "expect_revision"), ()),
    "run.list": ("read", ("workspace_id",), ("limit", "after")),
    "run.active": ("read", ("workspace_id",), ()),
    "run.get": ("read", ("workspace_id", "run_id"), ("since_seq", "limit")),
    "run.start": ("console", ("workspace_id", "table_id", "expect_revision", "idempotency_key", "topic"), ()),
}
_COMMAND_FIELDS = {
    "send": ("message",), "stop": (), "end": (), "invite": ("participant",),
    "remove": ("member_id",), "answer": ("task_id", "generation", "native_id", "answer"),
    "retry": ("task_id", "generation", "confirm"),
    "abandon": ("task_id", "generation", "native_id", "confirm"),
}
for _operation, _fields in _COMMAND_FIELDS.items():
    METHODS["run." + _operation] = ("console", ("workspace_id", "run_id", "expect_revision", "idempotency_key", *_fields), ())


def validate_params(method: str, value: Any) -> dict[str, Any]:
    required, optional = set(METHODS[method][1]), set(METHODS[method][2])
    if not isinstance(value, Mapping) or not required <= value.keys() or value.keys() - required - optional:
        raise DefinitionError("invalid_params", "params")
    result = dict(value)
    for key in ("workspace_id", "table_id", "preset_id", "run_id", "idempotency_key", "member_id", "task_id", "native_id"):
        if key in result:
            result[key] = identifier(result[key], key)
    if "after" in result and result["after"] is not None:
        result["after"] = identifier(result["after"], "after")
    for key in ("expect_revision", "expect_preset_revision", "generation", "since_seq"):
        if key in result:
            result[key] = revision(result[key], key, minimum=1 if key in {"expect_preset_revision", "generation"} else 0)
    if "limit" in result and (type(result["limit"]) is not int or not 1 <= result["limit"] <= (200 if method == "run.get" else 100)):
        raise DefinitionError("invalid_limit", "limit")
    if "confirm" in result and result["confirm"] is not True:
        raise DefinitionError("confirmation_required", "confirm")
    for key in ("topic", "message", "answer"):
        if key in result:
            result[key] = text(result[key], field=key, max_bytes=8000 if key == "answer" else 12000)
    if "participant" in result:
        result["participant"] = ParticipantRef.parse(result["participant"]).to_dict()
    return result


def command_body(operation: str, params: Mapping[str, Any]) -> dict[str, Any]:
    return {key: params[key] for key in _COMMAND_FIELDS[operation]}


def contract_descriptor() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "capacities": list(CAPACITIES), "auto_capacity": "auto", "styles": [s.value for s in TableStyle],
        "participant_fields": ["install_id", "instance_id"],
        "run_phases": ["initializing", "open", "stopping", "paused", "ending", "ended", "failed"],
        "member_states": ["joining", "active", "removing", "removed"],
        "methods": {PREFIX + name: {"tier": tier, "required": list(required), "optional": list(optional)}
                    for name, (tier, required, optional) in sorted(METHODS.items())},
        "features": {"local_instances": True, "same_profile_instances": True, "presets": True,
                     "exact_stop": True, "human_input": True, "instance_presence": True,
                     "history": True, "remote_members": False, "realm_replication": False,
                     "agent_invitations": False, "automatic_failover": False},
    }
