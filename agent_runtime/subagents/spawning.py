"""The spawning pause of ONE execution host process: the process that runs delegate_task.

Upstream's pause (``tools.delegate_tool_registry.set_spawn_paused``) is process-global, so
the reply names its scope: ``native_worker`` (the conversation's worker), ``isolated_compute``
(the compute host process) or ``operator_runtime`` (the serve itself, every persona turn in
it). Each is answered IN that process. ``host_ref`` binds the process: a restarted host
(new pid, new boot stamp, new reference key) refuses every older reference as stale.
Pinned by ``tests/agent_runtime/test_subagent_spawning_native.py`` and
``test_subagent_spawning_compute.py``.

A conversation's worker runs in the serve process now (``RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-
INTELLIGENCE-CHAT``), so ``native_worker``'s pause can no longer be the process flag: that would pause every
agent in the serve. It is the PROFILE's — the home the gateway binds for the worker's request and for its
turns' tool calls (``get_hermes_home_override``) — and the eternia-harness ``pre_tool_call`` hook refuses a
paused profile's new ``delegate_task`` spawn (:func:`spawn_pause_refusal`) with upstream's own words.
"""
import hmac
import os
import threading
import time

from .model import VERSION, Refusal, SubagentError
from .references import references

__layer__ = "lanes"

HOST_KINDS = ("native_worker", "isolated_compute", "operator_runtime")
_BOOT = time.time_ns()
#: Profile homes whose in-process worker was told to pause spawning.
_paused_homes: set[str] = set()
_paused_lock = threading.Lock()
#: Upstream's refusal (``tools.delegate_tool.delegate_task``), word for word.
PAUSED_MESSAGE = ("Delegation spawning is paused. Clear the pause via the TUI "
                  "(`p` in /agents) or the `delegation.pause` RPC before retrying.")


def _bound_profile_home() -> str | None:
    """The profile home the gateway bound for this request or tool call, else None (the serve's own)."""

    from hermes_constants import get_hermes_home_override

    override = get_hermes_home_override()
    return os.path.normcase(os.path.abspath(str(override))) if override else None


def _profile_paused(home: str, paused: bool | None = None) -> bool:
    with _paused_lock:
        if paused is True:
            _paused_homes.add(home)
        elif paused is False:
            _paused_homes.discard(home)
        return home in _paused_homes


def spawn_pause_refusal(tool_name, args) -> str | None:
    """Upstream's refusal for a NEW ``delegate_task`` spawn by a turn of a paused profile, else None."""

    if tool_name != "delegate_task":
        return None
    action = str((args or {}).get("action") or "").strip().lower() if isinstance(args, dict) else ""
    if action not in ("", "spawn"):
        return None
    home = _bound_profile_home()
    return PAUSED_MESSAGE if home is not None and _profile_paused(home) else None


def host_ref(host_kind: str) -> str:
    return references.generation(("execution_host", host_kind, os.getpid(), _BOOT))


def inspect_spawning(operation: str, params: dict, *, generation: str, host_kind: str) -> dict:
    """``spawning`` / ``spawning.set`` in the owning process; the caller validated the owner."""
    from tools.delegate_tool_registry import is_spawn_paused, set_spawn_paused

    if host_kind not in HOST_KINDS:
        raise SubagentError(Refusal.INVALID)
    current = host_ref(host_kind)
    profile = _bound_profile_home() if host_kind == "native_worker" else None
    if operation == "spawning.set":
        if not hmac.compare_digest(current, params["host_ref"]):
            raise SubagentError(Refusal.STALE)
        paused = (_profile_paused(profile, bool(params["paused"])) if profile is not None
                  else set_spawn_paused(params["paused"]))
    else:
        paused = _profile_paused(profile) if profile is not None else is_spawn_paused()
    return {"version": VERSION, "generation": generation, "observed_at": time.time(),
            "scope": "execution_host", "host_kind": host_kind, "host_ref": current, "paused": paused}
