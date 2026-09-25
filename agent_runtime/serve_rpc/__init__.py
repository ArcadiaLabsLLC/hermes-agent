"""The METHOD lane — named JSON-RPC 2.0 methods on the serve transports (the package map, rule 16).

Entry points (what calls in):

* ``dispatch.handle_request`` / ``dispatch.is_rpc_frame`` — the serve dispatcher
  (``harness_parts.serve.handle_message``) routes a ``jsonrpc``/``method`` frame here.
* ``registry.manifest`` — rides ``ready`` / ``hello_ok`` / the ``version`` reply.
* ``protocol`` — the frames and ``ERR_*`` codes every handler and several
  services (``chat_turn``, ``persona_open_chat``, ``scope_activation``) spend.

Modules, lowest layer first (no module imports one above it — W0-G6):

=======================  ======  ================================================
module                   layer   owns
=======================  ======  ================================================
protocol                 models  frames, ``ERR_*`` codes, ``RpcContext`` (and the
                                 protocol prose, as its docstring)
registry                 models  ``_METHODS`` / ``_METHOD_TIERS`` and ``@method``
                                 (the rule-12 reference registry), the manifest
reasons                  models  ``RpcRefusal``: every ``data.reason`` a guard here spends
params                   policy  the typed parameter readers, ``ParamRefused``, and
                                 the guard frames every office/level verb shares
office_errors            policy  store exception -> frame rows and the MRO walker
                                 the four office write verbs' tables use
dispatch                 lanes   ``handle_request``: the one reader of ``_METHODS``
office_read              lanes   ``runtime.office.get/subscribe/unsubscribe``
office_actor_writes      lanes   ``runtime.office.upsert/remove``
office_surface_writes    lanes   ``runtime.office.surface_update/resolve_conflict``
level                    lanes   ``runtime.level.*``
map                      lanes   ``runtime.map.*``
agent                    lanes   ``runtime.agent.create/retire``
chat                     lanes   open_chat, prewarm, ``runtime.chat.message/steer``
scope                    lanes   ``runtime.workspace.use`` / ``runtime.realm.use``
media                    lanes   ``runtime.media.index/get``
peer                     lanes   the ``peer.*`` verbs
gateway_peers            lanes   ``runtime.gateway.peers.*``
=======================  ======  ================================================

Each verb family registers its handlers on import; the family import below is
in the original definition order, so ``method_names()`` and ``manifest()`` are
the same table the single module built. Stores written: none directly — every
write goes through the owning store (``OfficeStore``, ``LevelStore``,
``MapStore``, the agent/chat services). Never imported from here:
``hermes_cli.harness``.
"""

from __future__ import annotations

from agent_runtime.call_authorization import STDIO_OWNER, authorize_call
from agent_runtime.serve_rpc import (  # noqa: F401 — every family, in the original definition order
    protocol,
    registry,
    dispatch,
    params,
    office_read,
    office_actor_writes,
    office_surface_writes,
    level,
    map,
    agent,
    chat,
    scope,
    media,
    peer,
    gateway_peers,
)
from agent_runtime.serve_rpc.protocol import (
    DEFERRED,
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_METHOD_NOT_FOUND,
    ERR_NOT_FOUND,
    RPC_CONTRACT_VERSION,
    RpcContext,
    deferred_reply,
    is_deferred,
    notification,
    ok,
)
from agent_runtime.serve_rpc.registry import (
    _METHODS,
    _METHOD_TIERS,
    manifest,
    method,
    method_names,
    method_tier,
    method_tiers,
)
from agent_runtime.serve_rpc.dispatch import handle_request, is_rpc_frame
from agent_runtime.serve_rpc.params import CORRELATION_ID_INVALID_REASON
from agent_runtime.serve_rpc.office_read import _runtime_office_get
from agent_runtime.serve_rpc.office_actor_writes import _runtime_office_upsert
from agent_runtime.serve_rpc.agent import _runtime_agent_create
from agent_runtime.serve_rpc.media import MEDIA_CONTRACT
from agent_runtime.serve_rpc.peer import (
    PEER_ANNOUNCE_NAMES_OTHER_REASON,
    PEER_CHAT_NOT_A_PEER_REASON,
    PEER_PING_CONTRACT,
    PEER_THREAD_UNREADABLE_REASON,
)

__layer__ = "lanes"

__all__ = [
    "CORRELATION_ID_INVALID_REASON",
    "DEFERRED",
    "ERR_CONFLICT",
    "ERR_HANDLER_FAILED",
    "ERR_INVALID_PARAMS",
    "ERR_METHOD_NOT_FOUND",
    "ERR_NOT_FOUND",
    "MEDIA_CONTRACT",
    "PEER_ANNOUNCE_NAMES_OTHER_REASON",
    "PEER_CHAT_NOT_A_PEER_REASON",
    "PEER_PING_CONTRACT",
    "PEER_THREAD_UNREADABLE_REASON",
    "RPC_CONTRACT_VERSION",
    "RpcContext",
    "STDIO_OWNER",
    "_METHODS",
    "_METHOD_TIERS",
    "_runtime_agent_create",
    "_runtime_office_get",
    "_runtime_office_upsert",
    "authorize_call",
    "deferred_reply",
    "handle_request",
    "is_deferred",
    "is_rpc_frame",
    "manifest",
    "method",
    "method_names",
    "method_tier",
    "method_tiers",
    "notification",
    "ok",
]
