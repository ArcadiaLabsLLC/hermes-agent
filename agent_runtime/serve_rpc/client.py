"""``runtime.client.capabilities`` — a client says which server→client requests it answers.

The serve wire carries requests in both directions: a client calls ``runtime.*`` methods,
and this runtime asks the Launcher its app functions (``launcher.*``, Stage 7 —
:mod:`agent_runtime.launcher_app_functions`). A client that never answers them would leave a
turn waiting on silence, and a client with no such handler must never see the frame at all,
so the runtime asks only a connection that DECLARED it answers the namespace — the same
rule ``tui_gateway``'s ``client.capabilities {server_requests}`` applies on the TUI wire.

Params: ``answers`` — the request namespaces this connection answers (today only
``"launcher."``). Sent once per connection; a later call replaces the declaration, and
``answers: []`` withdraws it.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import COMPUTER_REACH_CHAT, TIER_CONSOLE, is_machine_owner
from agent_runtime.launcher_app_functions import METHOD_PREFIX, declare_answerer
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["KNOWN_NAMESPACES", "_runtime_client_capabilities"]

#: The server→client request namespaces this runtime sends.
KNOWN_NAMESPACES = (METHOD_PREFIX,)


@method("runtime.client.capabilities", tier=TIER_CONSOLE, computer=COMPUTER_REACH_CHAT)
def _runtime_client_capabilities(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Record which request namespaces the calling connection answers."""
    context = context or RpcContext()
    answers = (params or {}).get("answers") if isinstance(params, dict) else None
    if not isinstance(answers, list) or not all(isinstance(item, str) for item in answers):
        return err(rid, ERR_INVALID_PARAMS, "answers must be a list of request namespaces",
                   {"reason": "answers_invalid"})
    owner = "stdio" if context.connection_key is None else str(context.connection_key)
    # The machine owner's own connection may be this device's Eternia for a request with no turn
    # (``device_local_launcher_link``); a paired device, a peer or a computer never is. The sink
    # is the one this connection's replies go out on (``emit`` is its bound method).
    # MUTATION: pass every caller's sink and test_agent_files_virtual_tree's paired-device test
    # asks the phone's own Eternia for this device's tree.
    owner_sink = getattr(context.emit, "__self__", None) if is_machine_owner(context.caller) else None
    declare_answerer(owner, METHOD_PREFIX in answers, owner_sink=owner_sink)
    return ok(rid, {"contract": 1, "answers": [ns for ns in KNOWN_NAMESPACES if ns in answers]})
