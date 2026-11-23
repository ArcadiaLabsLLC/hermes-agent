"""``runtime.health`` — the ``harness health`` block on the method lane.

The launcher's start-up probe (``probeHermesRuntimeHealth``) and its
Connections probe (``provider_probe.dart``) both spawned a COLD process for one
key: ``harness health``, or ``harness status`` and its ~3 MB projection read for
``runtime_health`` alone (argv census rows 20-21, 7.95 s measured). Both doors
call :func:`agent_runtime.provider_health.runtime_health`, so the method's
result IS the argv verb's JSON.

Tier ``read``: it writes nothing, emits nothing and mints nothing — the
``runtime.admission.status`` / ``runtime.speech.status`` row. It names local
paths (interpreter, runtime root, hermes home) and package availability, never
credentials, env or provider config bodies; the block was written
redaction-safe for ``harness status``, which already ships it. Only a caller at
console reach reads those paths: below it (a computer at Look or Run chats, a
view-only device) each is null and an ``issues`` sentence names no path
(``console_operations._detail_for_caller``,
RT-FU-A-LOOK-COMPUTER-IS-SENT-WHERE-A-PHONE-KEEPS-HERMES-BY-ITS-HEALTH-CHECK-AND-AGENT-LIST).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import COMPUTER_REACH_LOOK, TIER_READ

from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["HEALTH_UNEXPECTED_PARAMS_REASON", "_runtime_health"]

#: ``data.reason`` for a call that sent parameters: the verb takes none, and a
#: client that believes it is filtering must be told it is not.
HEALTH_UNEXPECTED_PARAMS_REASON = "unexpected_params"


@method("runtime.health", tier=TIER_READ, computer=COMPUTER_REACH_LOOK)
def _runtime_health(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Params: none. Result: ``harness health --json`` verbatim — ``ok``,
    ``interpreter``, ``runtime_root``, ``hermes_home``, ``hermes_profile``,
    ``required_packages``, ``package_available``, ``issues``."""
    if params:
        return err(rid, ERR_INVALID_PARAMS, "runtime.health takes no parameters.",
                   {"reason": HEALTH_UNEXPECTED_PARAMS_REASON})
    from agent_runtime.provider_health import runtime_health
    from agent_runtime.serve_rpc.console_operations import _detail_for_caller

    # MUTATION: return ``runtime_health()`` unprojected and test_a_look_computer_reads_no_path_in_the_health_check
    # reddens, while test_the_console_keeps_the_health_check_paths stays green.
    return ok(rid, _detail_for_caller(runtime_health(), context.caller if context is not None else None))
