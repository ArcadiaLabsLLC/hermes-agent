"""Fork-owned child contracts and the single gateway registration point."""
from functools import partial

from agent_runtime.subagents.model import LIVE_OPERATIONS as OPERATIONS, ERROR_CODES, SubagentError

__layer__ = "lanes"


def declare_contracts():
    from tui_gateway.contracts import registry
    from tui_gateway.contracts.base import Result
    from tui_gateway.contracts.common import SessionParams
    from tui_gateway.contracts.profiles_vault_complete_foreign_subagents import SubagentSnapshot
    from pydantic import StrictBool

    class SubagentReadParams(SessionParams):
        owner_scope: str
        worker_generation: str
        expected_generation: str | None = None
        child_ref: str | None = None

    class SubagentCommandParams(SubagentReadParams):
        request_id: str

    class SubagentSteerParams(SubagentCommandParams):
        text: str

    class SpawningSetParams(SubagentReadParams):
        host_ref: str
        paused: StrictBool

    class OwnedSubagentSnapshot(SubagentSnapshot):
        child_ref: str | None
        controllable: bool

    class ChildObservation(Result):
        version: int
        generation: str
        observed_at: float

    class ChildCapabilities(ChildObservation):
        operations: list[str]
        tail_bytes: int

    class ChildRoster(ChildObservation):
        children: list[OwnedSubagentSnapshot]
        truncated: bool

    class ChildTail(ChildObservation):
        child_ref: str
        subagent_id: str
        available: bool
        text: str
        truncated: bool

    class ChildCapabilitiesResult(Result):
        data: ChildCapabilities

    class ChildRosterResult(Result):
        data: ChildRoster

    class ChildTailResult(Result):
        data: ChildTail

    class ChildCommand(ChildObservation):
        child_ref: str
        subagent_id: str | None
        request_id: str
        operation: str | None
        status: str
        missed_steer: bool | None

    class ChildCommandResult(Result):
        data: ChildCommand

    class SpawningObservation(ChildObservation):
        scope: str
        host_kind: str
        host_ref: str
        paused: bool

    class SpawningResult(Result):
        data: SpawningObservation

    results = {"capabilities": ChildCapabilitiesResult, "list": ChildRosterResult, "tail": ChildTailResult,
               "steer": ChildCommandResult, "stop": ChildCommandResult, "receipt": ChildCommandResult,
               "spawning": SpawningResult, "spawning.set": SpawningResult}
    parameters = {"steer": SubagentSteerParams, "stop": SubagentCommandParams,
                  "receipt": SubagentCommandParams, "spawning.set": SpawningSetParams}

    for operation in OPERATIONS:
        name = "eternia.subagents." + operation
        if name not in registry.METHODS:
            registry.method(name, params=parameters.get(operation, SubagentReadParams), result=results[operation])


def inspect(operation, rid, params):
    from agent_runtime.subagents.native import inspect_native
    try:
        data = inspect_native(operation, params)
        return {"jsonrpc": "2.0", "id": rid, "result": {"data": data}}
    except SubagentError as exc:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": ERROR_CODES[exc.reason], "message": "Subagent inspection refused.", "data": {"reason": exc.reason}}}


def register(server):
    from tui_gateway.contract_seam import pydantic_contracts_enabled

    if pydantic_contracts_enabled():
        declare_contracts()
    for operation in OPERATIONS:
        server.register_method("eternia.subagents." + operation, server._profile_scoped(partial(inspect, operation)))
