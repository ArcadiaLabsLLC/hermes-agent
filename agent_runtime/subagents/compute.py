"""Use the existing compute observation/control lanes without starting a host."""
import queue
import time

from agent_runtime import _upstream_doors as upstream
from .model import VERSION, ERROR_CODES, MUTATIONS, Refusal, SubagentError
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
        if operation in MUTATIONS:
            frame = supervisor.control(params["session_id"], route_name="eternia.subagents." + operation,
                payload={"params": forwarded}, existing_only=True)
            reply = frame.get("response")
            if not isinstance(reply, dict):
                raise RuntimeError("Missing child command acknowledgement")
        else:
            reply = supervisor.observe(params["session_id"], "eternia.subagents." + operation, forwarded)
    except (OSError, RuntimeError, queue.Empty) as exc:
        if operation == "spawning.set":
            raise SubagentError(Refusal.UNKNOWN) from exc
        if operation in MUTATIONS:
            return {"version": VERSION, "generation": params["expected_generation"], "observed_at": time.time(),
                    "request_id": params["request_id"], "child_ref": params["child_ref"], "subagent_id": None,
                    "operation": operation, "status": "unknown", "missed_steer": None}
        raise SubagentError(Refusal.UNAVAILABLE) from exc
    if error := reply.get("error"):
        reason = next((reason for reason, code in ERROR_CODES.items() if code == error.get("code")), Refusal.UNAVAILABLE)
        raise SubagentError(reason)
    data = reply["result"]["data"]
    if operation in ("spawning", "spawning.set"):
        data = {**data, "host_kind": "isolated_compute"}
    return data


def control_ack(server, frame, transport):
    """The existing compute control handler calls the one registered child RPC."""
    from tui_gateway.transport import bind_transport, reset_transport

    token = bind_transport(transport)
    try:
        response = server.handle_request({"jsonrpc": "2.0", "id": frame["request_id"],
            "method": frame["route_name"], "params": {**frame.get("params", {}), "session_id": frame["sid"]}})
        return {"response": response}
    finally:
        reset_transport(token)
