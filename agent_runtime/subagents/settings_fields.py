"""The console's allowlist and input shapes; native code owns resolution."""
from dataclasses import dataclass
import math

from .model import Refusal, SubagentError

__layer__ = "policy"


@dataclass(frozen=True)
class Field:
    kind: type
    minimum: int = 0
    applies: str = "next_child"


FIELDS = {
    "model": Field(str), "provider": Field(str), "reasoning_effort": Field(str),
    "max_iterations": Field(int, 1), "max_concurrent_children": Field(int, 1),
    "max_spawn_depth": Field(int, 1), "orchestrator_enabled": Field(bool),
    "child_timeout_seconds": Field(float), "worktree_isolation": Field(bool),
    "independent_completions": Field(bool, applies="new_session"),
    "oneshot_max_children": Field(int), "compression_threshold_tokens": Field(int),
    "surface_child_process_notifications": Field(bool, applies="next_notification"),
    "inherit_mcp_toolsets": Field(bool),
}
ENVIRONMENT = {"max_concurrent_children": "DELEGATION_MAX_CONCURRENT_CHILDREN",
               "child_timeout_seconds": "DELEGATION_CHILD_TIMEOUT_SECONDS"}
ROUTE_KEYS = ("model", "provider")
ADVANCED_ROUTE_KEYS = ("base_url", "api_key", "api_mode", "command", "request_overrides", "fallback_providers")


def validate_changes(changes):
    from hermes_constants import parse_reasoning_effort

    if not isinstance(changes, dict) or not changes or changes.keys() - FIELDS.keys():
        raise SubagentError(Refusal.INVALID)
    for key, value in changes.items():
        if value is None:
            continue
        field = FIELDS[key]
        valid = type(value) is field.kind
        if field.kind is float:
            valid = type(value) in (int, float) and math.isfinite(value)
        if field.kind in (int, float) and valid:
            valid = value >= field.minimum
        if field.kind is str and valid:
            valid = len(value) <= 200 and value == value.strip() and not any(ord(char) < 32 for char in value)
        if key == "reasoning_effort" and value and valid:
            valid = parse_reasoning_effort(value) is not None
        if key in ("child_timeout_seconds", "compression_threshold_tokens") and valid:
            valid = value == 0 or value >= {"child_timeout_seconds": 30, "compression_threshold_tokens": 16000}[key]
        if not valid:
            raise SubagentError(Refusal.INVALID)


def effort_label(value):
    from hermes_constants import parse_reasoning_effort

    parsed = parse_reasoning_effort(value)
    return (parsed.get("effort", "none") if parsed else "")


def field_value(key, value):
    if key == "reasoning_effort":
        return effort_label(value)
    kind = FIELDS[key].kind
    if kind is str:
        from agent_runtime.redaction import scrub_secret_values
        return scrub_secret_values(str(value or ""))[:200]
    if type(value) is bool and kind is bool:
        return value
    if type(value) in (float, int) and kind in (int, float) and math.isfinite(value):
        return value
    raise SubagentError(Refusal.UNAVAILABLE)
