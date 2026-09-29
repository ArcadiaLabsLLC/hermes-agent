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

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.launcher_app_functions import METHOD_PREFIX, declare_answerer
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["KNOWN_NAMESPACES", "_runtime_client_capabilities"]

#: The server→client request namespaces this runtime sends.
KNOWN_NAMESPACES = (METHOD_PREFIX,)


@method("runtime.client.capabilities", tier=TIER_CONSOLE)
def _runtime_client_capabilities(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Record which request namespaces the calling connection answers."""
    context = context or RpcContext()
    answers = (params or {}).get("answers") if isinstance(params, dict) else None
    if not isinstance(answers, list) or not all(isinstance(item, str) for item in answers):
        return err(rid, ERR_INVALID_PARAMS, "answers must be a list of request namespaces",
                   {"reason": "answers_invalid"})
    owner = "stdio" if context.connection_key is None else str(context.connection_key)
    declare_answerer(owner, METHOD_PREFIX in answers)
    return ok(rid, {"contract": 1, "answers": [ns for ns in KNOWN_NAMESPACES if ns in answers]})
