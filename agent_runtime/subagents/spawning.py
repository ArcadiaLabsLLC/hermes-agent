"""The spawning pause of ONE execution host process: the process that runs delegate_task.

Upstream's pause (``tools.delegate_tool_registry.set_spawn_paused``) is process-global, so
the reply names its scope: ``native_worker`` (the conversation's worker), ``isolated_compute``
(the compute host process) or ``operator_runtime`` (the serve itself, every persona turn in
it). Each is answered IN that process. ``host_ref`` binds the process: a restarted host
(new pid, new boot stamp, new reference key) refuses every older reference as stale.
Pinned by ``tests/agent_runtime/test_subagent_spawning_native.py`` and
``test_subagent_spawning_compute.py``.
"""
import hmac
import os
import time

from .model import VERSION, Refusal, SubagentError
from .references import references

__layer__ = "lanes"

HOST_KINDS = ("native_worker", "isolated_compute", "operator_runtime")
_BOOT = time.time_ns()


def host_ref(host_kind: str) -> str:
    return references.generation(("execution_host", host_kind, os.getpid(), _BOOT))


def inspect_spawning(operation: str, params: dict, *, generation: str, host_kind: str) -> dict:
    """``spawning`` / ``spawning.set`` in the owning process; the caller validated the owner."""
    from tools.delegate_tool_registry import is_spawn_paused, set_spawn_paused

    if host_kind not in HOST_KINDS:
        raise SubagentError(Refusal.INVALID)
    current = host_ref(host_kind)
    if operation == "spawning.set":
        if not hmac.compare_digest(current, params["host_ref"]):
            raise SubagentError(Refusal.STALE)
        paused = set_spawn_paused(params["paused"])
    else:
        paused = is_spawn_paused()
    return {"version": VERSION, "generation": generation, "observed_at": time.time(),
            "scope": "execution_host", "host_kind": host_kind, "host_ref": current, "paused": paused}
