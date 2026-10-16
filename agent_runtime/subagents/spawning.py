"""Observe and set the existing process-wide native spawning flag."""
import hmac
import time

from .model import VERSION, Refusal, SubagentError, validate_request
from .references import references

__layer__ = "lanes"


def inspect_spawning(operation, params, *, owner, host_kind, revalidate):
    from tools.delegate_tool import is_spawn_paused, set_spawn_paused

    validate_request(operation, params)
    generation = references.require_generation(owner, params.get("expected_generation"))
    host_ref = references.historical(owner, "spawning", host_kind, {})
    revalidate()
    if operation == "spawning.set":
        if not hmac.compare_digest(params["host_ref"], host_ref):
            raise SubagentError(Refusal.STALE)
        paused = set_spawn_paused(params["paused"])
    else:
        paused = is_spawn_paused()
    try:
        revalidate()
    except Exception as exc:
        if operation == "spawning.set":
            raise SubagentError(Refusal.UNKNOWN) from exc
        raise
    return {"version": VERSION, "generation": generation, "observed_at": time.time(),
            "scope": "execution_host", "host_kind": host_kind, "host_ref": host_ref, "paused": paused}
