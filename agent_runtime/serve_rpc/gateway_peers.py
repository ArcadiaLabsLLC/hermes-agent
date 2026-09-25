"""``runtime.gateway.peers.subscribe`` / ``list`` / ``roster`` — the gateway peer
directory verbs a local client calls.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.store_file_io import iso_stamp as _now_iso

from agent_runtime.serve_rpc.protocol import (
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method
from agent_runtime.serve_rpc.params import (
    CORRELATION_ID_INVALID_REASON,
    _CorrelationIdRefused,
    _correlation_id_param,
)

__layer__ = "lanes"

__all__ = [
    "_runtime_gateway_peers_list",
    "_runtime_gateway_peers_roster",
    "_runtime_gateway_peers_subscribe",
]


# ── runtime.gateway.peers.* ──────────────────────────────────────────────────
#
# S2d (launcher S3-R13). The serve's peer-directory door for its OWN launcher,
# and the reason it exists is one measured fact: **the launcher's hermes stream
# carries no events.** The five ``gateway.peer.*`` contracts S2c registers reach
# a stream consumer, a snapshot and an operator, and reach a launcher never — no
# matter how many are emitted, because its hydrate core has no key for them and
# its fold entities have no entity for them. Canon 03 invariant 6 names where
# new server→client push goes instead, and this is it.
#
# The shape is ``runtime.office.subscribe`` → ``runtime.office.patch``'s, minus
# the parts the office needs and this does not: no watermark, no fold-entity
# negotiation, no re-baseline receipt. An office patch is a DELTA, so a
# subscriber that misses one is out of sync; a peer-directory notification
# carries the whole row, so a dropped frame costs one row's freshness until that
# row next changes.


@method("runtime.gateway.peers.subscribe", tier=TIER_READ)
def _runtime_gateway_peers_subscribe(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """The directory AND the registration, in one call.

    Params: none.

    Result::

        {contract: 1, store_revision: [trust_ns, cache_ns],
         count, peers: [<row>], subscribed: true}

    where ``<row>`` is exactly what ``harness gateway peers list --json``
    prints — including ``usable``, ``unusable_reason``, ``ref``, ``expires_at``
    and the nested ``cache`` block with its ``roster``.

    **One call and not two**, for ``runtime.office.subscribe``'s reason: a read
    followed by a separate join is two reads of one truth with a window between
    them, and nothing tells the client whether anything moved inside it. Taking
    the directory and the registration together makes "I have the directory, now
    push me every change" a statement the runtime can honour.

    **The rows are the CLI verb's rows and not a second shape.** The launcher
    already greets by running that verb; a push lane whose rows differed would
    make every consumer branch on which door a row came through.

    **A caller with no push channel is REFUSED**, not registered and ignored: a
    subscription that can never deliver is a promise the runtime cannot keep,
    and the honest moment to say so is the call that asked for it.

    Tier ``read`` — it reads two files and mutates nothing — plus membership of
    ``LOCAL_CONSOLE_METHODS``, which is what actually narrows it. The directory
    is the operator's own map of their network: which machines they paired, what
    those are called, the addresses they answer at. A console-tier phone holds a
    real credential and has no business with that map, and the tier vocabulary
    has no word for a KIND.
    """

    from agent_runtime.gateway_peers import peer_store_revision
    from agent_runtime.gateway_targets import peer_store_root
    from agent_runtime.serve_gateway_peers_rpc import (
        PEER_DIRECTORY_CONTRACT,
        PEER_DIRECTORY_SUBSCRIPTIONS,
        peer_directory_rows,
    )

    key = None if context is None else context.connection_key
    emit = None if context is None else context.emit
    if not PEER_DIRECTORY_SUBSCRIPTIONS.register(key, emit):
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "runtime.gateway.peers.subscribe needs a connection that can be "
            "pushed to; this caller has no notification channel, so a "
            "subscription here would be a promise nothing could keep. Read the "
            "directory with runtime.gateway.peers.list instead.",
            {"reason": "no_push_channel"},
        )

    root = peer_store_root()
    rows = peer_directory_rows(root)
    return ok(
        rid,
        {
            "contract": PEER_DIRECTORY_CONTRACT,
            "store_revision": list(peer_store_revision(root)),
            "count": len(rows),
            "peers": rows,
            "subscribed": True,
        },
    )


@method("runtime.gateway.peers.list", tier=TIER_READ)
def _runtime_gateway_peers_list(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """The directory, read once, with no subscription.

    The same body :func:`_runtime_gateway_peers_subscribe` answers with, minus
    ``subscribed``. It exists for the caller that has no push channel — a
    one-shot probe, a test, a future non-duplex transport — because the
    alternative is that such a caller reads the directory by subscribing to it,
    which is how a registry fills with sinks nothing will ever write to.
    """

    from agent_runtime.gateway_peers import peer_store_revision
    from agent_runtime.gateway_targets import peer_store_root
    from agent_runtime.serve_gateway_peers_rpc import (
        PEER_DIRECTORY_CONTRACT,
        peer_directory_rows,
    )

    root = peer_store_root()
    rows = peer_directory_rows(root)
    return ok(
        rid,
        {
            "contract": PEER_DIRECTORY_CONTRACT,
            "store_revision": list(peer_store_revision(root)),
            "count": len(rows),
            "peers": rows,
        },
    )


@method("runtime.gateway.peers.roster", tier=TIER_CONSOLE)
def _runtime_gateway_peers_roster(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Ask a paired install who is on it, ON THE CALLER'S BEHALF, and cache it.

    Params: ``install`` (required — a display name or install id, the same ref
    the directory prints); ``correlation_id`` (optional, echoed).

    Result: ``{contract: 1, install, workspace_id, count, truncated, roster,
    fetched_at}``.

    **This is a fetch-THROUGH and it exists because a launcher cannot do it.**
    ``peer.roster.list`` is a PEER method: its handler refuses any caller whose
    connection did not prove a peer install id, and a launcher holds a DEVICE
    credential. So the launcher asks its own hermes — which IS a peer of that
    install — and the answer lands in ``peers_cache.json``, where the next
    ``runtime.gateway.peers.changed`` frame carries it. One directory, two
    readers, and R-IP9's "B's projection shaped by B's rules" is preserved
    because only B's peer ever asks.

    **Tier ``console`` and console-KIND both**, and here they say different
    things. ``console`` is the honest strength: this verb opens a socket to
    another machine and spends this install's peer credential. The KIND gate
    (``LOCAL_CONSOLE_METHODS``) is what stops a paired device from spending that
    credential at all — a remote caller that could make this install dial its
    peers has borrowed an authority nobody granted it.

    A far install that is unreachable, revoked, expired or too old to know the
    verb answers with its own reason (``peer_unreachable`` /
    ``capability_missing`` / …) rather than an empty roster, for
    ``agent_chat_open``'s reason: an empty list over an unmade call is the most
    misleading answer available.
    """

    from agent_runtime.gateway_peers import cache_peer_roster
    from agent_runtime.gateway_targets import (
        TargetRefusal,
        peer_store_root,
        resolve_install_ref,
    )
    from agent_runtime.serve_gateway_peers_rpc import PEER_DIRECTORY_CONTRACT
    from tools.agent_chat_remote import call_peer_method

    try:
        correlation_id = _correlation_id_param(params)
    except _CorrelationIdRefused as refused:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            refused.message,
            {"reason": CORRELATION_ID_INVALID_REASON},
        )

    install = params.get("install")
    if not isinstance(install, str) or not install.strip() or len(install) > 200:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: install is required and names a paired install by "
            "its ref or id (runtime.gateway.peers.list prints both)",
            {"reason": "unknown_peer_install"},
        )

    root = peer_store_root()
    resolved = resolve_install_ref(root, install.strip())
    if isinstance(resolved, TargetRefusal):
        data = {"reason": resolved.reason}
        if resolved.candidates:
            data["candidates"] = list(resolved.candidates)
        return err(rid, ERR_HANDLER_FAILED, resolved.message, data)

    outcome = call_peer_method(
        root, resolved.peer_install_id, "peer.roster.list", {}
    )
    refusal = outcome.get("refusal")
    if refusal:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            str(refusal.get("message") or refusal.get("reason")),
            {"reason": str(refusal.get("reason")), "install_id": resolved.peer_install_id},
        )

    result = outcome.get("result") or {}
    rows = [row for row in (result.get("rows") or []) if isinstance(row, dict)]
    # Cached BEFORE the reply, so the ``changed`` notification the cache write
    # emits and this reply describe the same roster. A client that got the reply
    # first and the notification second would briefly render two answers.
    cache_peer_roster(
        root,
        resolved.peer_install_id,
        workspace_id=result.get("workspace_id"),
        rows=rows,
    )

    reply: dict[str, Any] = {
        "contract": PEER_DIRECTORY_CONTRACT,
        "install": {
            "install_id": resolved.peer_install_id,
            "display_name": resolved.display_name,
        },
        "workspace_id": result.get("workspace_id"),
        "count": len(rows),
        "truncated": bool(result.get("truncated")),
        "roster": rows,
        "fetched_at": _now_iso(None),
    }
    if correlation_id is not None:
        reply["correlation_id"] = correlation_id
    return ok(rid, reply)
