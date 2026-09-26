"""The JSON-RPC 2.0 frame vocabulary: error codes, ``ok``/``err``/``notification``,
the deferred-reply sentinel and :class:`RpcContext`.

Separate because every other module of the package reads it and it reads none
of them: the frames a handler builds are a leaf the registry, the dispatcher
and all twenty verb families share.

----

The METHOD lane: named JSON-RPC 2.0 methods on the serve transports.

Increment 1 of the "CALL half" ruled in the launcher's
``docs/mission_control/DECISION_push_and_rpc_2026-08-13.md`` §3, and framed by
launcher commit ``fa2226750``: **mirror ``tui_gateway``'s JSON-RPC 2.0 shape;
do not invent a third convention.** Everything structural here is copied from
``tui_gateway/server.py`` rather than re-decided — the frames (``:1656``/
``:1660``), the ``@method`` registry (``:1664``), the request normalizer
(``:1672``) and the error-code vocabulary:

===========  ===========================================================
``-32600``   invalid request (not an object / no method / bad jsonrpc)
``-32601``   unknown method
``-32602``   invalid params (missing, wrong type, malformed)
``-32000``   the handler raised — mirrors ``server.py:1733``
``4001``     the named entity does not exist (upstream: "session not found")
``4090``     the write lost a race with the store (fork-minted — see below)
===========  ===========================================================

``4001`` is reused verbatim rather than minted: upstream already spends it on
exactly this meaning, and a fork that renumbers "not found" makes a future
union of the two dispatchers a translation layer instead of a merge.

``4090`` had to be minted — upstream has no concurrency code, because its
domain (one TUI session, one writer) never contends. The NUMBER is chosen to
survive that future merge: upstream allocates its 4xxx band sequentially from
4001 and has reached 4020, and ``4002`` — the number a first guess reaches for —
is already spent there on "invalid value", so taking it would have collided on
day one. 4090 sits far above the live allocation and reads as HTTP 409, which
is the one number every client developer already associates with this meaning.

Codes are the coarse family — "a guard refused this write" — and
``data.reason`` is the branch point (see :func:`err`). 4090 carries FOUR
reasons, and conflating any two of them would be the whole bug, because each
has a different cure:

``stale_revision``
    The client's own prediction is behind. Refetch and rebase.
``sync_conflict``
    A realm-sync sidecar is unresolved. NO amount of refetch-and-retry clears
    it — it needs an operator running ``harness office resolve-conflict``. A
    client that retried this one would spin forever.
``class_key_collision``
    The write is class-keyed and would undo the class→instance re-key
    migration (``office_class_key_guard``). Neither refetching nor retrying
    helps; the client must name WHICH instance it is placing.
``actor_archived``
    The key was DELETED on this server (D1). Terminal: the client drops its
    local row. Refetching confirms the absence and retrying re-opens the wedge
    this fence closed — re-placing the agent is a new create with a new id,
    never a re-add of this key.

Why this is a lane and not a replacement
----------------------------------------
``hermes_cli/harness_parts/serve/handle_message.py`` dispatches ``{"id","argv"}`` frames into
the harness argparse tree. That lane is byte-identity tested and stays the
fallback; this one sits BESIDE it. A frame is routed here when it carries
``jsonrpc`` or ``method`` — neither of which the argv lane has ever sent — so
the discrimination costs the argv lane nothing and cannot be ambiguous.

Both serve transports get it for free: ``serve.py``'s dispatcher is already
transport-agnostic, so one call site serves stdio and the socket alike.

How a client learns the method set
----------------------------------
``RPC_CONTRACT_VERSION`` + the method names ride the frames a client ALREADY
reads to learn what it is talking to — ``ready`` on stdio, ``hello_ok`` on the
socket, and the re-askable ``{"op":"version"}`` reply on both. That is the
``hello_contract`` precedent (``agent_runtime/serve_socket/hello.py``) followed
rather than a parallel discovery scheme: the server advertises, the client
asserts. See :func:`manifest`.

The version is a SET plus an integer, not an integer alone. The integer moves
when the SHAPE of an existing method changes (a client that folds v1 must
refuse v2); the set grows when a method is added, which needs no version bump
because a client only ever calls methods it found in the set. This is the same
reasoning as Stage 2d's ``fold_entities``: naming the capabilities lets them be
adopted one at a time, where a bare number couples them.

Projection rule (decision doc, Stage 2b)
----------------------------------------
The runtime owns who exists, where it sits, what state it is in, and a POINTER
to the character class. The launcher owns what that class looks like. So
``persona_id`` crosses the wire and nothing cosmetic does — and so does
``persona_instance_id``, which is identity (WHICH one of a class is placed
here), not cosmetics, and which no client can derive from the ids it already
has. The bound is the snapshot's own ``MAX_OFFICE_ACTORS_PROJECTED``, reused
rather than re-declared, and a truncation is ACCOUNTED (``actors_truncated``) —
a silent cut that reads as an empty office is the failure this whole document
is about. So is the OTHER way the list can be short: an actor file that exists
and will not decode is counted too (``actors_unreadable``), because the store's
skip-and-continue used to hand this projection a shortened list that then
computed its own truncation from the shortened length and arrived at zero.

Prediction and reconciliation (decision doc, Stage 2c)
-----------------------------------------------------
The write leg is game netcode, not request/response: the launcher renders a
drag immediately as a PREDICTION, sends it, and reconciles against the server's
answer. Two consequences shape ``runtime.office.upsert``.

The ack is LIGHT — ``{actor_key, revision}`` and nothing else. Returning the
re-projected actor would be returning the client its own input plus a number,
on the hot path of a drag, and would tempt a client to adopt the echo as truth
instead of keeping the prediction it already drew. The two fields are the two
facts the client provably cannot compute: ``actor_key`` because the store
canonicalizes the identity triple at its own boundary (drift aliases such as
``persona_personainst_dev_agent_*`` collapse), and ``revision`` because it is
the token the NEXT write must present.

Which is why ``revision`` also rides every item of the READ projection. It is
the actor's, repeated onto its items exactly as ``persona_instance_id`` is,
because ``expect_revision`` guards the ACTOR row while the surface-level
``revision`` beside it is the SURFACE's — and the surface's does not move when
an actor moves (``OfficeStore.upsert_actor`` rewrites the actor file and leaves
``office.json`` alone). Without it a client had no honest first value for
``expect_revision`` and could only write unguarded, which is precisely the
lost-update the guard exists to prevent. Additive, so the integer holds: the
launcher's item decoder gates on required-key PRESENCE
(``mission_office_rpc.dart:260``) and never on a key count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from agent_runtime.call_authorization import STDIO_OWNER, RpcCaller

__layer__ = "models"

__all__ = [
    "DEFERRED",
    "ERR_CONFLICT",
    "ERR_HANDLER_FAILED",
    "ERR_INVALID_PARAMS",
    "ERR_INVALID_REQUEST",
    "ERR_METHOD_NOT_FOUND",
    "ERR_NOT_FOUND",
    "JSONRPC_VERSION",
    "PEER_REQUESTED_BY_PREFIX",
    "RPC_CONTRACT_VERSION",
    "RpcContext",
    "deferred_reply",
    "err",
    "is_deferred",
    "logger",
    "notification",
    "ok",
]


logger = logging.getLogger(__name__)


# The method-surface contract. Bump ONLY when an existing method's request or
# result shape changes incompatibly; adding a method does not move it.
RPC_CONTRACT_VERSION = 1


JSONRPC_VERSION = "2.0"


# Mirrored from tui_gateway/server.py — see the module docstring.
ERR_INVALID_REQUEST = -32600


ERR_METHOD_NOT_FOUND = -32601


ERR_INVALID_PARAMS = -32602


ERR_HANDLER_FAILED = -32000


ERR_NOT_FOUND = 4001


# Fork-minted; see the module docstring for why the number is 4090 and not the
# 4002 a first guess reaches for.
ERR_CONFLICT = 4090


#: The ``--requested-by`` prefix a peer-executed turn carries. Beside
#: ``gateway_device`` (a device's, hardcoded in :func:`normalize_chat_message`)
#: and ``agent:<session>`` (a local relay's, ``tools/agent_chat_tool``). The
#: install id after the colon is the ONE variable part, and it is the reason
#: this is a prefix rather than a constant: an operator on B reading their own
#: chat has to be able to see WHICH paired install asked, and "a peer" would not
#: tell them.
PEER_REQUESTED_BY_PREFIX = "peer:"


def ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": rid, "result": result}


def err(rid: Any, code: int, message: str, data: dict | None = None) -> dict:
    """A JSON-RPC error frame.

    ``code``/``message`` are upstream's ``_err`` exactly. ``data`` is the
    JSON-RPC 2.0 spec's own optional member, not a fork extension, and it is
    populated so a client can branch on a machine-readable ``reason`` instead
    of pattern-matching a human sentence — a message is for an operator's eyes
    and is free to change.
    """

    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": rid, "error": error}


def notification(method_name: str, params: dict) -> dict:
    """A JSON-RPC 2.0 NOTIFICATION — a frame the runtime sends UNPROMPTED.

    The PUSH half of the union ruling, in its smallest form. Structurally it is
    a request object minus ``id`` (spec §4.1), and the ``id`` key is ABSENT
    rather than ``null``: ``null`` is a legal request id, so a strict client
    that correlates on key presence would file a null-id push into its
    pending-call table and leak the entry forever. Our own launcher happens to
    be tolerant here — it treats ``"id": null`` as a notification on purpose
    (``mission_control_serve_session_io.dart:691``) — so this is a contract
    choice for the next client, not a fix for the current one.

    There is NO reply, and therefore no error channel: a notification the
    transport cannot deliver is dropped. Whoever owns the fan-out has to
    ACCOUNT for that drop, because the client's only other way to learn it
    missed one is the sequence gap. That is why the patch lane carries ``seq``
    and why a dropped subscriber is closed rather than quietly skipped.
    """

    return {"jsonrpc": JSONRPC_VERSION, "method": method_name, "params": params}


#: What a handler returns instead of a frame when its reply is coming LATER,
#: from the transport's worker lane, on the same ``id``.
#:
#: A SENTINEL rather than ``None`` and rather than an exception, for one reason
#: each. ``None`` is what a dispatcher gets from a handler that forgot to
#: return, and the two must not look alike at the one place that decides whether
#: to write a frame. And an exception would be caught by
#: :func:`handle_request`'s own boundary and turned into ``-32000`` — the
#: boundary is right about every other escape and would be exactly wrong about
#: this one. Compared by IDENTITY (:func:`is_deferred`), never by shape, so no
#: result a handler could legitimately build can be mistaken for it.
DEFERRED: dict[str, Any] = {"deferred": True}


def is_deferred(frame: Any) -> bool:
    """True for the one object :data:`DEFERRED` is."""

    return frame is DEFERRED


def deferred_reply(
    rid: Any, method_name: str, build: Callable[[], dict]
) -> Callable[[], dict]:
    """Wrap ``build`` so the worker lane ALWAYS has a frame to emit.

    :func:`handle_request`'s try/except is the boundary that keeps a handler
    fault off the reader loop; a deferred handler runs after that boundary has
    returned, so it needs its own copy of it or a raise on a pool worker becomes
    a client that waits forever for a reply nobody will ever write. Same code,
    same ``reason``, same ``method`` — deliberately identical, because "the
    handler blew up" must not read differently to a client depending on which
    thread it blew up on.
    """

    def _run() -> dict:
        try:
            return build()
        except Exception as exc:  # noqa: BLE001 - the boundary is the point
            return err(
                rid,
                ERR_HANDLER_FAILED,
                f"handler error: {exc}",
                {"reason": "handler_failed", "method": method_name},
            )

    return _run


@dataclass(frozen=True)
class RpcContext:
    """WHO is calling — the half of a request that is not in its ``params``.

    Handlers took ``(rid, params)`` for the whole life of the CALL half, which
    was right while every method was request/response: an answer goes back the
    way the question came, and the transport already knew how. It stops being
    right the moment a method's job is to keep talking AFTERWARDS.
    ``runtime.office.subscribe`` cannot be written against ``(rid, params)`` at
    all — not because the emitter is missing (``SocketConnection.emit`` and
    ``ServeSocketServer.broadcast`` have always existed) but because a handler
    had no way to name the connection it would later push to. That was the
    first added argument, and for the whole life of the notification lane it
    was the only one.

    ``emit`` is the caller's own frame sink, already per-connection and stable
    across a connection's lifetime (``serve.py``'s ``_sink_for``). ``None``
    means the caller has no push channel, which is the honest state for a
    context built by a test or by a future non-duplex transport — a method that
    needs one must refuse rather than assume.

    ``connection_key`` is the SUBSCRIPTION identity: it is what the teardown
    path (``connection_sinks.pop`` on drop) can name, so a registry keyed on it
    can be swept when the socket dies. On stdio there is one implicit caller
    and no key, which is why a stdio subscribe is a different question from a
    socket one rather than the same code with a null.

    ``caller`` (Stage A2) is the second, and the only one that is not about
    talking back. It is what the transport PROVED about who is asking — the
    argument the front-door gate needs and the one no field here could supply,
    because ``connection_key`` is a subscription name and ``transport`` is a
    lane, and neither is an identity. It is built in one place
    (``call_authorization.caller_for_connection``, called from ``serve.py``'s
    dispatcher) and is never assembled from ``params``: a request that could
    name its own caller would be a request that authorizes itself.

    ``spawn_chat_turn`` (gateway Stage 3) is the third, and the first that is
    about work rather than about who or where. Every method before it finished
    on this thread; a chat turn runs for seconds to minutes, and the method lane
    is answered INLINE on the reader loop (see ``serve.py``'s method-lane
    comment, which names chat turns as the reason the pool exists). So the chat
    methods do not run their turn — they hand it to the transport's worker lane
    through this seam and ack. ``None`` means the caller has no worker lane,
    which is the honest state for a test-built context, and the chat methods
    REFUSE on it rather than falling back to running the turn inline: an inline
    chat turn would stall every other client on this serve for its whole length.

    ``spawn_reply`` is the fourth, and it is ``spawn_chat_turn``'s argument made
    general. A chat turn hands the pool a whole REQUEST and acks; this hands the
    pool the rest of THIS request — a zero-argument callable returning the very
    frame the handler would have returned — and the transport emits it on the
    same ``id`` when it is done. It exists because a handler that BLOCKS is not
    only the chat turn: ``runtime.media.get``'s proxy arm dials another machine,
    and a machine that is switched off is a stall on a loop every other request
    from that client is queued behind. ``None`` means the caller has no worker
    lane, and a handler that finds it absent answers on this thread — which is
    honest for a test-built context and for a transport with no pool, and is why
    this seam does not have to refuse the way ``spawn_chat_turn`` does: the work
    it defers is bounded at its own source, so the fallback is a bad latency
    rather than an unbounded hold. It returns True when the work was accepted.
    """

    connection_key: str | None = None
    transport: str = "stdio"
    emit: Callable[[dict], None] | None = None
    caller: RpcCaller = STDIO_OWNER
    spawn_chat_turn: Callable[[str, list[str], str], None] | None = None
    spawn_reply: Callable[[Callable[[], dict]], bool] | None = None

    def push(self, method_name: str, params: dict) -> bool:
        """Send one notification to THIS caller. False when there is no channel.

        Not exception-swallowing on purpose. A push raised from inside a
        handler is still inside :func:`handle_request`'s boundary, so it
        becomes a typed ``-32000`` on the very call that tried it — which is
        the one moment a dead channel is reportable at all. Fan-out to OTHER
        subscribers is a different path with a different answer (drop, account,
        close), and it must not borrow this one.
        """

        if self.emit is None:
            return False
        self.emit(notification(method_name, params))
        return True
