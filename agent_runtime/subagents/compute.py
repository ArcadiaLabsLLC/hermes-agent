"""Forward an authorized read to the existing compute owner without starting it."""
from agent_runtime import _upstream_doors as upstream
from .model import ERROR_CODES, Refusal, SubagentError
from .references import references

__layer__ = "lanes"


def observe(operation: str, params: dict, owner: tuple) -> dict:
    supervisor = upstream.subagent_compute_supervisor()
    if supervisor is None:
        raise SubagentError(Refusal.UNAVAILABLE)
    # Carry the outer session/transport generation into the child's own authority.
    # The compute host still verifies its attached transport and exact child object.
    forwarded = {**params, "owner_scope": references.generation(owner)}
    try:
        reply = supervisor.observe(params["session_id"], "eternia.subagents." + operation, forwarded)
    except (OSError, RuntimeError) as exc:
        raise SubagentError(Refusal.UNAVAILABLE) from exc
    if error := reply.get("error"):
        reason = next((reason for reason, code in ERROR_CODES.items() if code == error.get("code")), Refusal.UNAVAILABLE)
        raise SubagentError(reason)
    return reply["result"]["data"]
