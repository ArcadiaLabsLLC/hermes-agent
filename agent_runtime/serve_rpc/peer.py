"""The ``peer.*`` verbs one runtime serves to another: ping, agent chat execute,
media get, announce, roster list and thread read.
"""

from __future__ import annotations

import base64
from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ
from agent_runtime.clock import iso_stamp as _now_iso

from agent_runtime.serve_rpc.protocol import (
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.reasons import RpcRefusal
from agent_runtime.serve_rpc.registry import method
from agent_runtime.serve_rpc.params import (
    ParamRefused,
    _correlation_id_param,
)
from agent_runtime.serve_rpc.media import MEDIA_CONTRACT

__layer__ = "lanes"

__all__ = [
    "PEER_ANNOUNCE_CONTRACT",
    "PEER_ANNOUNCE_NAMES_OTHER_REASON",
    "PEER_CHAT_NOT_A_PEER_REASON",
    "PEER_FOREIGN_SESSION_REASON",
    "PEER_PING_CONTRACT",
    "PEER_THREAD_UNREADABLE_REASON",
    "PEER_UNSUPPORTED_PERSONA_REASON",
    "_peer_agent_chat_execute",
    "_peer_announce",
    "_peer_media_get",
    "_peer_ping",
    "_peer_roster_list",
    "_peer_thread_read",
]


# ── peer.ping ────────────────────────────────────────────────────────────────
#
# Gateway Stage 6. The FIRST method outside the ``runtime.*`` family, and the
# prefix is the declaration: ``runtime.*`` verbs act on this install's level —
# they read it, mutate it, or run an agent on it — while ``peer.*`` verbs are
# about the EDGE between two installs and touch no level at all. A client
# reading the manifest can therefore tell the two apart without a table, which
# matters more here than usual because the peer surface is the one an operator
# on another machine is being asked to trust.


#: The peer lane's own shape number, and a THIRD beside ``RPC_CONTRACT_VERSION``
#: (this manifest's) and the two handshake ones. It describes the ``peer.ping``
#: RESULT and nothing else, so a Stage 7 that grows the peer surface can move it
#: without telling every ``runtime.*`` client that something changed.
PEER_PING_CONTRACT = 1


@method("peer.ping", tier=TIER_READ)
def _peer_ping(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Is the edge alive? Answers, and touches nothing.

    Params: ``echo`` (optional, a short opaque string returned verbatim).

    Result::

        {pong: true, contract: 1, peer: <caller's install id | null>,
         at: <iso8601>, echo?: <the string, bounded>}

    **Why the declared tier is ``read`` and why that is not a lie to device or
    console readers.** The ``tiers`` map answers one question — *what strength
    of credential does this verb require* — and the honest answer for a liveness
    ping that reads no store, writes nothing and mints no id is the same answer
    ``runtime.office.get`` gets. A ``console`` declaration would say a level
    mutation's credential is needed, which is false, and would make the map
    lie to exactly the readers it is for: a launcher rendering "what can this
    connection do" would grey out a ping any read-tier device may in fact call.

    What the tier map deliberately does NOT say is who may call this BESIDES
    a credential of that strength — and that asymmetry is already in the
    contract, not invented here. A manifest says what a call WANTS, never what a
    connection HOLDS (canon 03 §2, and the launcher's ``MissionRuntimeRpcManifest``
    branches on nothing). A PEER holds no tier at all: it is answered from
    ``call_authorization.PEER_METHOD_ALLOWLIST``, which contains this name and
    no other, so the peer lane is NARROWED by the allowlist rather than widened
    by this row. Nothing in the map would be more true if this said ``peer`` —
    there is no such tier, ``TIERS`` has two members, and inventing a third word
    that only one caller kind can hold would put a value in the map that every
    existing reader must be taught to ignore.

    So the row reads exactly as it should: any read-tier credential may ping,
    and a peer may ping AND NOTHING ELSE. The second half is the allowlist's to
    state, and it is stated where it is enforced.

    **No store read, and that is a property worth keeping.** The obvious
    temptation is to answer with this install's ``install_id`` — but the
    ``hello_ok`` the caller has already read carries the ``install`` block, so
    repeating it here would be a second authority for one fact, and it would
    make the cheapest verb on the wire open a file. What the result DOES name is
    the caller: ``peer`` is the install id the TRANSPORT proved, echoed back so
    the dialer can confirm it was recognised as the install it meant to be —
    which is a real answer to "is my credential still the one you know me by",
    and one no client-side check can give.
    """

    caller = None if context is None else context.caller
    echo = params.get("echo")
    result: dict[str, Any] = {
        "pong": True,
        "contract": PEER_PING_CONTRACT,
        # ``None`` for a non-peer caller (a console client or a device may call
        # this too — see the tier note above), and the key is present either way
        # so a client never has to branch on absence to read it.
        "peer": None if caller is None else caller.peer_install_id,
        "at": _now_iso(None),
    }
    if isinstance(echo, str) and echo.strip():
        # Bounded, because it comes off the wire and goes straight back onto it.
        # An echo is a correlation aid, never a channel: 128 characters is more
        # than any token this repo mints and less than anything worth smuggling.
        result["echo"] = echo.strip()[:128]
    return ok(rid, result)


# ── peer.agent_chat.execute ──────────────────────────────────────────────────
#
# Gateway Stage 7. The second verb on the peer surface, and the first one that
# DOES something: an agent on a paired install asks an agent on this one to take
# a turn. The row that remembers the ask lives on the SENDER's install; what
# lands here is one turn, executed and recorded in this install's own chat store
# exactly as any inbound agent message is, so this operator sees it too.


#: This install's ``data.reason`` for "you are not a peer". Its own value rather
#: than ``scope_denied``, because the two are different facts: ``scope_denied``
#: is the chokepoint saying a caller may not run a verb, this is the verb saying
#: it has no provenance to run under. A console client that calls this by
#: mistake should read the second, not the first.
PEER_CHAT_NOT_A_PEER_REASON = RpcRefusal.PEER_IDENTITY_REQUIRED


@method("peer.agent_chat.execute", tier=TIER_CONSOLE)
def _peer_agent_chat_execute(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Run ONE chat turn on this install, asked for by a paired install.

    Params: ``turn_request_id``, ``target``, ``message`` (required);
    ``session_id``, ``title``, ``new_session``, ``max_seconds``,
    ``correlation_id`` (optional).

    Result: :func:`runtime.chat.message`'s ack, plus ``peer`` — the install id
    THIS server proved about the caller, echoed for the same reason
    ``peer.ping`` echoes it.

    **Attribution comes off the CONNECTION, and this handler is where that is
    enforced.** ``context.caller.peer_install_id`` is set by
    ``call_authorization.caller_for_connection`` only for a connection whose
    peer HMAC verified against a row in ``gateway/peers.json``; it is not
    readable from, or writable by, anything in ``params``. A caller that reaches
    here without one is REFUSED rather than defaulted — including a perfectly
    legitimate local console client, which is the case that makes the refusal
    worth spelling: a turn run under "some console asked" would be a turn whose
    provenance nobody can audit, and the local console already has
    ``runtime.chat.message`` for turns of its own.

    **The tier says ``console`` and the tier is not what admits a peer.** It is
    the honest answer to what the map asks — *what strength of credential does
    this verb want* — and it is the same answer ``runtime.chat.message`` gives
    for the same reason: a chat turn runs an agent with tools, so anything
    softer would be a door around ``console``. What admits a peer is
    ``call_authorization.PEER_METHOD_ALLOWLIST``, which now names two verbs and
    still names neither ``runtime.agent.create`` nor ``runtime.agent.retire`` —
    canon 06's exclusion, holding by construction rather than by anybody
    remembering it.

    **The ack is an ACCEPT.** Stage 3's constraint, unchanged and inherited: this
    dispatcher answers inline on the reader loop, so the turn goes to the worker
    pool and its frames ride the per-request lane under ``request_id``. The
    dialling install reads those frames exactly as the local launcher does. That
    is what makes a remote turn and a local turn one execution rather than two
    implementations that agree today.
    """

    caller = None if context is None else context.caller
    peer_install_id = None if caller is None else caller.peer_install_id
    if not peer_install_id:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "peer.agent_chat.execute runs a turn on behalf of a PAIRED INSTALL, "
            "and this connection proved none; a local client sends chat turns "
            "with runtime.chat.message",
            {"reason": PEER_CHAT_NOT_A_PEER_REASON},
        )

    from agent_runtime.chat_turn import PEER_CHAT_EXECUTE_METHOD, perform_chat_turn

    outcome = perform_chat_turn(
        params,
        verb=PEER_CHAT_EXECUTE_METHOD,
        spawn=None if context is None else context.spawn_chat_turn,
        peer_install_id=peer_install_id,
    )
    if outcome.refusal is not None:
        refusal = outcome.refusal
        return err(rid, refusal.code, refusal.message, refusal.data)
    result = dict(outcome.result or {})
    result["peer"] = peer_install_id
    return ok(rid, result)


# ── peer.media.get ───────────────────────────────────────────────────────────
#
# Stage P4 (ruling R-P3). The third verb on the peer surface and the second one
# that hands anything over. It exists because of an asymmetry Stage 8 built and
# Stage 7 then made visible: install B runs a turn, B's reply declares an image
# on B's disk, and the reply is forged into A's chat — where the picture is a
# path to a machine A cannot read. B minted the handle at reply time (it holds
# the bytes; nobody else can hash them) and the map rode the completion home.
# This verb is the other end: A spends that handle, B answers with the bytes.
#
# It is deliberately the ONLY new door, and it is a keyhole rather than a door:
# no index, no reference, no path, no enumeration. A peer can spend a name it
# was given and can learn nothing else — which is the reference-out/handle-in
# asymmetry of the whole family, applied across an install boundary.


@method("peer.media.get", tier=TIER_CONSOLE)
def _peer_media_get(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Hand ONE local artifact's bytes to a PAIRED INSTALL, named by handle.

    Params: ``handle`` (required, ``sha256:<64 hex>``); ``correlation_id``
    (optional, echoed).

    Result: :func:`_runtime_media_get`'s, plus ``peer`` — the install id this
    server proved about the caller, echoed for the reason ``peer.ping`` echoes
    it. Refusals are the same family and the same words, because a client that
    had to learn a second refusal vocabulary for the same question would be
    branching on which hop answered.

    **It resolves the LOCAL half of the scope and nothing else, and that is what
    makes the lane acyclic.** A handle this install holds only as a REMOTE row —
    one IT learned from a third install — is ``unknown_handle`` here, not a
    second proxy hop. So there is no chain to bound, no A→B→C fan-out to
    reason about, and no way for two paired installs to bounce a fetch between
    them. Where the bytes are is where the answer comes from.

    **The tier says ``console`` and the tier is not what admits a peer** —
    ``peer.agent_chat.execute``'s note, unchanged. What admits a peer is
    ``call_authorization.PEER_METHOD_ALLOWLIST``, which Stage P4 widened by this
    one name with its reason attached. What the ``console`` word says is that
    handing over raw file bytes wants a level-mutation-strength credential:
    ``read`` is deliberately open to a caller the transport could not place, and
    that is precisely the caller who must not pull files off a disk.

    **A non-peer is REFUSED rather than defaulted**, the same way
    ``peer.agent_chat.execute`` refuses one — including a legitimate local
    console client, which already has ``runtime.media.get`` and gets a strictly
    larger scope from it.
    """

    from agent_runtime import media_handles

    caller = None if context is None else context.caller
    peer_install_id = None if caller is None else caller.peer_install_id
    if not peer_install_id:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "peer.media.get answers a PAIRED INSTALL, and this connection "
            "proved none; a local client fetches artifacts with "
            "runtime.media.get",
            {"reason": PEER_CHAT_NOT_A_PEER_REASON},
        )

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as refused:
        return refused.frame(rid)

    raw = params.get("handle")
    if raw is None:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: handle is required",
            {"reason": media_handles.REASON_HANDLE_INVALID},
        )
    # The grammar first, on the RAW argument, before a scope is derived — the
    # ordering ``runtime.media.get`` states its reason for, and the reason it
    # matters MORE here: this caller is on another machine, so "make the server
    # hash its disk" would be a remote-triggered cost.
    if not isinstance(raw, str) or not media_handles.HANDLE_RE.match(raw.strip()):
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "peer.media.get names an artifact by handle "
            "(sha256:<64 hex>); it does not accept a path",
            {"reason": media_handles.REASON_HANDLE_INVALID},
        )

    # ``remote_completions=()`` is the acyclicity, spelled as an argument rather
    # than trusted to a later check: the scope this verb resolves against simply
    # does not contain the remote half.
    scope = media_handles.build_media_scope(remote_completions=())
    resolved = media_handles.resolve_handle(raw, scope)
    if isinstance(resolved, media_handles.MediaRefusal):
        return err(
            rid,
            ERR_HANDLER_FAILED,
            f"peer.media.get refused: {resolved.reason}",
            resolved.refusal_data(),
        )

    data = media_handles.read_artifact_bytes(resolved)
    if isinstance(data, media_handles.MediaRefusal):
        return err(
            rid,
            ERR_HANDLER_FAILED,
            f"peer.media.get refused: {data.reason}",
            data.refusal_data(),
        )

    result: dict[str, Any] = {
        "contract": MEDIA_CONTRACT,
        "handle": resolved.handle,
        "media_type": resolved.media_type,
        "size_bytes": len(data),
        "encoding": "base64",
        "data": base64.b64encode(data).decode("ascii"),
        "peer": peer_install_id,
    }
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)


# ── peer.announce ────────────────────────────────────────────────────────────
#
# S2c (R-IP12: one local store, pushed never polled, filtered never copied).
# The only WRITING verb on the peer surface, and what it writes is the caller's
# own row in ``peers_cache.json`` — a file that gates nothing and that no
# credential path reads. It exists because the alternative to being told is
# polling: before it, a rename, a moved address, a rotated certificate and a
# revocation on the far side were each discovered as the NEXT call's failure, by
# an agent that had already written the message.


#: The announce lane's own shape number, beside ``PEER_PING_CONTRACT``'s and for
#: its reason: it describes this verb's params and result and nothing else, so a
#: later widening does not tell every ``runtime.*`` client that something moved.
PEER_ANNOUNCE_CONTRACT = 1


#: A payload that carries an install id different from the caller's. Its own
#: reason rather than a generic invalid-params, because the two are different
#: mistakes: a malformed field is a client bug, and this is a client asking to
#: write somebody else's row.
PEER_ANNOUNCE_NAMES_OTHER_REASON = RpcRefusal.ANNOUNCE_NAMES_OTHER_INSTALL


@method("peer.announce", tier=TIER_CONSOLE)
def _peer_announce(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Tell this install what changed about YOU. Writes the caller's cache row, only.

    Params: ``contract`` (optional, echoed), ``display_name``, ``endpoints``,
    ``cert_fingerprint``, ``roster_changed`` (bool), ``revoked_you`` (bool),
    ``correlation_id`` — all optional; an announce with none of them is a
    liveness stamp and is accepted.

    Result::

        {accepted: true, contract: 1, peer: <caller's install id>,
         cache_written: [field names], correlation_id?: <token>}

    **There is no install-id parameter, and that absence is the security
    property.** The row written is ``rows[context.caller.peer_install_id]`` —
    the id the TRANSPORT proved against a verifier in ``gateway/peers.json``,
    which is not readable from and not writable by anything in ``params``. It is
    the same posture ``normalize_peer_chat_execute`` takes with ``requested_by``
    and for the same reason: *the field a peer could type does not exist.* A
    payload that names another install is REFUSED rather than ignored (a caller
    doing that is either confused or probing, and both deserve to be told); one
    that names its own is ignored, because a client echoing what it already
    proved is harmless.

    **Three things this cannot do**, each by construction rather than by a check
    somebody has to remember. It cannot write a credential —
    ``apply_peer_announce`` opens the cache file and no other. It cannot
    un-revoke: ``revoked_you`` is one-way and both it and the trust ``revoked``
    are cleared only by a trust write, so no install can announce itself back
    into an edge this operator cut. And it cannot move the dial pin: an
    announced fingerprint is recorded as a ``fingerprint_rotation`` NOTICE for
    an operator to act on, never applied, because a peer that could nominate the
    certificate it is checked against could become a different machine.

    **The tier says ``console``**, and here that word is doing real work rather
    than being the honest answer to a map's question. ``read`` is deliberately
    open to a caller the transport could not place (``peer.media.get``'s
    argument), and a caller the transport could not place is precisely the one
    that must not write a row this install will act on. What ADMITS a peer is
    still the allowlist, not the tier.

    **``roster_changed`` drops the cached roster; it never fetches one.** A
    handler that answered an inbound announce by dialling back would make one
    push edge into a loop with two installs in it. The next read fetches, when
    somebody actually wants it.
    """

    from agent_runtime.gateway_peers import apply_peer_announce
    from agent_runtime.gateway_targets import peer_store_root

    caller = None if context is None else context.caller
    peer_install_id = None if caller is None else caller.peer_install_id
    if not peer_install_id:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "peer.announce records what a PAIRED INSTALL says about itself, and "
            "this connection proved none; there is no local caller this verb "
            "would mean anything for",
            {"reason": PEER_CHAT_NOT_A_PEER_REASON},
        )

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as refused:
        return refused.frame(rid)

    for key in ("peer_install_id", "install_id"):
        named = params.get(key)
        if named is None:
            continue
        if not isinstance(named, str) or named.strip() != peer_install_id:
            return err(
                rid,
                ERR_INVALID_PARAMS,
                "peer.announce writes the row of the install the transport "
                "proved, and this payload names a different one. There is no "
                "parameter for choosing whose row to write.",
                {"reason": PEER_ANNOUNCE_NAMES_OTHER_REASON},
            )

    payload = dict(params)
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    written = apply_peer_announce(peer_store_root(), peer_install_id, payload)

    result: dict[str, Any] = {
        "accepted": True,
        "contract": PEER_ANNOUNCE_CONTRACT,
        "peer": peer_install_id,
        # WHICH fields landed, so a caller that announced a rename can tell an
        # accepted-and-applied from an accepted-and-dropped without a second
        # round trip. An empty list is a legal answer: an announce with nothing
        # in it is a liveness stamp.
        "cache_written": written,
    }
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)


# ── peer.roster.list / peer.thread.read ──────────────────────────────────────
#
# S2b (R-IP9). The two READ verbs. Since Stage 7 an agent on install A has been
# able to send to ``@B/neko`` and have the reply delivered back; what it could
# not do was anything a person does before and after sending — see who is on B,
# or read the thread it was just handed. The dispatch delivery has been printing
# "Their thread: persona_chat_… (agent_chat_open with this session_id …)", a
# pointer that resolved to NOTHING on the machine that received it. These two
# doors make that sentence true.
#
# Both are thin: the projection, the guard and the reader all live in
# ``peer_directory``, shared byte-for-byte with the local tool, so the far door
# and the near door cannot drift into two answers about one thread.


#: Refused when ``peer.thread.read``'s reader answered ``ok: False``. Its own
#: word rather than the reader's, because the reader's vocabulary
#: (``chat_scope_unresolved``, ``session_db_unavailable``, …) describes THIS
#: install's storage and means nothing to a caller on another machine — so the
#: caller branches on one stable string and the detail rides ``data``.
PEER_THREAD_UNREADABLE_REASON = RpcRefusal.THREAD_UNREADABLE


#: Refused when the named target is not a teammate here. Shared spelling with
#: the local tool's own refusal, so an agent that reads both surfaces learns one
#: word for one condition.
PEER_UNSUPPORTED_PERSONA_REASON = RpcRefusal.UNSUPPORTED_PERSONA


#: The lane guard's refusal, likewise shared with ``agent_chat_open``: the
#: session named is not part of that teammate's chat lane.
PEER_FOREIGN_SESSION_REASON = RpcRefusal.FOREIGN_SESSION


@method("peer.roster.list", tier=TIER_READ)
def _peer_roster_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Who is addressable on THIS install, projected by THIS install's rules.

    Params: ``target`` (optional — the address the caller means to use, which is
    what decides the workspace); ``correlation_id`` (optional, echoed).

    Result::

        {contract: 1, peer, workspace_id, count, truncated, rows, at}

    where each row is ``{handle, persona_id, label, is_canonical_primary,
    last_turn_at, workspace_id}``.

    **B projects; A never filters.** A roster is not a list of rows, it is the
    answer to *who is addressable from this scope*, and the scope rules —
    workspace narrowing, canonical-row shadowing, placement-beats-plumbing —
    belong to this install. Handing the raw instance list over and letting the
    caller apply them would be a second implementation of
    ``workspace_scope.addressable_roster`` that drifts the first time either
    side is edited, and the drift would surface as an agent addressing a
    teammate this install does not consider addressable.

    **``target`` decides the workspace, and answering the SAME question the send
    path answers is the point.** A bare ``@B/dev`` turn resolves in B's ACTIVE
    workspace (a peer turn carries no ``--workspace-id``); a
    ``personainst_*`` handle resolves in that instance's own. A roster scoped
    one way and a send resolved another would offer a teammate the very next
    message could not reach.

    **The tier is ``read``** and it is the honest answer: these are the same
    facts ``runtime.office.get`` hands a read-tier device — names and handles of
    agents on a level, no transcript, no credential, no path. What ADMITS a peer
    is the allowlist, as always.
    """

    from agent_runtime.peer_directory import (
        peer_roster_projection,
        resolve_far_target_scope,
    )

    caller = None if context is None else context.caller
    peer_install_id = None if caller is None else caller.peer_install_id
    if not peer_install_id:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "peer.roster.list answers a PAIRED INSTALL about who is addressable "
            "here; this connection proved none, and a local client already has "
            "agent_chat_threads",
            {"reason": PEER_CHAT_NOT_A_PEER_REASON},
        )

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as refused:
        return refused.frame(rid)

    target = params.get("target")
    if target is not None and (not isinstance(target, str) or len(target) > 200):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: target must be a string of at most 200 characters "
            "or omitted",
            {"reason": PEER_UNSUPPORTED_PERSONA_REASON},
        )

    projection = peer_roster_projection(
        scope_workspace_id=resolve_far_target_scope(target)
    )
    result = {**projection, "peer": peer_install_id}
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)


@method("peer.thread.read", tier=TIER_CONSOLE)
def _peer_thread_read(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The bounded tail of ONE thread on this install, named by target AND session.

    Params: ``target`` and ``session_id`` (both REQUIRED); ``limit`` (optional,
    clamped 1..40); ``correlation_id`` (optional, echoed).

    Result: ``agent_chat_open``'s dict plus ``contract`` and ``peer``.

    **``target`` is required, and that is the security decision in this
    handler.** With only a session id this would be a transcript reader: a
    caller could spend any session id it ever saw against any thread on this
    machine. With the target, the SAME lane guard the local ``agent_chat_open``
    applies runs here — ``_session_belongs_to_chat_lane``, through the shared
    ``peer_directory.read_chat_lane_tail`` — so a session that is not part of
    that teammate's chat lane is ``foreign_session`` exactly as it is locally. A
    paired install can spend a pointer it was handed and can discover nothing
    else, which is ``peer.media.get``'s asymmetry applied to conversations.

    **The tier is ``console``** because transcript text is the operator's own
    conversation: ``read`` is deliberately open to a caller the transport could
    not place, and that is precisely the caller who must not read what people
    said to each other.

    **A failed read is ``thread_unreadable``, never an empty page.** The reader
    has its own vocabulary for storage faults (``chat_scope_unresolved``,
    ``chat_scope_mismatch``, ``session_db_unavailable``) and it describes THIS
    install's storage, so it rides in ``data`` while the caller branches on one
    stable word. Answering ``count: 0`` for an unread transcript would be the
    single most misleading result available here — an agent checking whether a
    teammate replied would conclude they had not.

    **The env var is never set.** ``resolve_chat_session_scope``'s ambient rung
    is gated behind ``HERMES_ALLOW_AMBIENT_CHAT_READS``, and a peer door that
    set it would quietly grant itself more scope than the local tool has. If the
    scope refuses, the refusal travels.
    """

    from agent_runtime.peer_directory import PEER_THREAD_CONTRACT, read_chat_lane_tail

    caller = None if context is None else context.caller
    peer_install_id = None if caller is None else caller.peer_install_id
    if not peer_install_id:
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "peer.thread.read answers a PAIRED INSTALL with one thread it was "
            "already given the session id for; this connection proved none, and "
            "a local client has agent_chat_open",
            {"reason": PEER_CHAT_NOT_A_PEER_REASON},
        )

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as refused:
        return refused.frame(rid)

    target = params.get("target")
    session_id = params.get("session_id")
    for name, value in (("target", target), ("session_id", session_id)):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            return err(
                rid,
                ERR_INVALID_PARAMS,
                f"invalid params: {name} is required and must be a non-empty "
                "string of at most 200 characters. peer.thread.read names the "
                "teammate AND the thread, so the same lane guard the local read "
                "applies can run here.",
                {"reason": PEER_UNSUPPORTED_PERSONA_REASON},
            )
    limit = params.get("limit")
    if limit is not None and not isinstance(limit, int):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: limit must be an integer or omitted",
            {"reason": PEER_UNSUPPORTED_PERSONA_REASON},
        )

    data = read_chat_lane_tail(target, session_id=session_id, limit=limit or 20)
    if data.get("ok") is False:
        kind = str(data.get("error_kind") or "")
        # Three distinct refusals, in this order, because an operator (and a
        # calling agent) acts differently on each: an unknown teammate is a
        # target to fix, a foreign session is a pointer that does not belong to
        # that lane, and everything else is this install's storage answering.
        if kind == PEER_UNSUPPORTED_PERSONA_REASON:
            reason = PEER_UNSUPPORTED_PERSONA_REASON
        elif kind == PEER_FOREIGN_SESSION_REASON:
            reason = PEER_FOREIGN_SESSION_REASON
        else:
            reason = PEER_THREAD_UNREADABLE_REASON
        return err(
            rid,
            ERR_HANDLER_FAILED,
            str(data.get("error") or reason),
            {"reason": reason, "error_kind": kind or reason},
        )

    result = {**data, "contract": PEER_THREAD_CONTRACT, "peer": peer_install_id}
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)
