"""``runtime.media.index`` / ``runtime.media.get`` — the media handle verbs and the
chunk frame they share with the peer lane.
"""

from __future__ import annotations

import base64
from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import (
    DEFERRED,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    RpcContext,
    deferred_reply,
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
    "MEDIA_CONTRACT",
    "_media_get_frame",
    "_runtime_media_get",
    "_runtime_media_index",
]


# ── runtime.media.index / runtime.media.get ──────────────────────────────────
#
# Gateway Stage 8, the ``fetch`` family §3.3 named. TWO verbs and not one, and
# the second is not a convenience: a chat image reaches a client as a
# ``MEDIA:<absolute path>`` line inside a message body, so the only pointer the
# client holds is a PATH — and a path is the one thing this lane will not
# accept. Something has to carry the client from what it holds to a handle it
# may spend, and the two candidates are (a) rewrite every stream frame's text
# server-side, which moves the stream contract for every client on every lane to
# solve a problem only a remote one has, or (b) let a client ask, once, what is
# in scope and join on the reference it already has. ``index`` is (b).
#
# The reference travels OUT and never IN. That asymmetry is the entire security
# story of this family: what comes back is a string the caller already rendered
# from a message it was already allowed to read, so it discloses nothing new;
# what goes in is `sha256:<64 hex>` and is refused by a regex before this
# process constructs a ``Path``. See ``agent_runtime/media_handles.py``.


#: The media lane's own shape number, beside ``PEER_PING_CONTRACT`` and for its
#: reason: it describes these two RESULTS and nothing else, so a later stage
#: that grows the family can move it without telling every ``runtime.office.*``
#: client that something changed.
MEDIA_CONTRACT = 1


@method("runtime.media.index", tier=TIER_CONSOLE)
def _runtime_media_index(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """What media this install can hand over, and under what name.

    Params: ``correlation_id`` (optional, echoed). Deliberately NOTHING else —
    no path, no directory, no filter, no chat id. A verb whose scope a caller
    could narrow is a verb whose scope a caller could WIDEN if the narrowing
    argument were ever mis-parsed, and there is no measured need: the whole live
    corpus on this machine is 46 mirrors and 17 declarations.

    Result::

        {contract: 1, cap_bytes, truncated, artifacts: [
            {handle, reference, media_type, size_bytes, fetchable}, …],
         scanned: {logs, declarations}, correlation_id?}

    ``fetchable`` is stated per artifact so a client never spends a round trip
    to be told the cap; :func:`_runtime_media_get` refuses the same artifact
    with the cap named anyway, because a client is free to ignore an index it
    did not read.

    **``truncated`` is not decoration.** It is the difference between "there is
    no handle for that picture" and "the scan stopped before it reached it", and
    a client that could not tell those apart would retry forever on one and never
    on the other.

    On the inline-dispatch budget, which this verb is the first to actually
    spend. The lane is answered on the reader loop; the derivation reads the
    live-log tails and hashes the images they declare, which on the measured
    corpus is 138,622 bytes of JSONL and 2.5 MB of PNG, and the per-file digest
    is memoized on ``(path, size, mtime_ns)`` so a second call in the same
    process re-hashes nothing. The bounds that keep the worst case bounded —
    logs scanned, artifacts minted, bytes read per mirror — are constants in
    ``media_handles`` with the rotation size they are derived from.
    """

    from agent_runtime import media_handles

    try:
        correlation_id = _correlation_id_param(params)
    except _CorrelationIdRefused as refused:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            refused.message,
            {"reason": CORRELATION_ID_INVALID_REASON},
        )

    scope = media_handles.build_media_scope()
    result: dict[str, Any] = {
        "contract": MEDIA_CONTRACT,
        "cap_bytes": media_handles.MAX_FETCH_BYTES,
        "truncated": scope.truncated,
        # Both halves, one ordering. A remote row (Stage P4) describes itself as
        # ``remote: true`` with the peer that holds it and NO path — because
        # there is no file here to name, and a row that claimed one would send
        # a client to a `File(path)` that cannot exist.
        "artifacts": [artifact.describe() for artifact in scope.rows()],
        "scanned": {
            "logs": scope.logs_scanned,
            "declarations": scope.declarations_seen,
            # Stage P4's second source, counted beside the first for the same
            # reason ``truncated`` exists: a client that sees zero completions
            # scanned knows the remote half was never derived, rather than
            # inferring it from an absence of remote rows.
            "completions": scope.completions_scanned,
        },
    }
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)


@method("runtime.media.get", tier=TIER_CONSOLE)
def _runtime_media_get(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Hand over ONE artifact's bytes, named by handle and by nothing else.

    Params: ``handle`` (required, ``sha256:<64 hex>``); ``correlation_id``
    (optional, echoed).

    Result::

        {contract: 1, handle, media_type, size_bytes, encoding: "base64",
         data, correlation_id?}

    Refusals, all ``-32000`` with ``data.reason`` as the branch point:
    ``handle_invalid`` (not the grammar — where a path-shaped argument lands),
    ``unknown_handle`` (well-formed, in no scope), ``artifact_too_large``
    (carrying ``cap_bytes`` and ``size_bytes``), ``artifact_unreadable``.

    **``base64`` and the key that says so.** JSON carries no bytes, so there is
    exactly one honest choice and the ``encoding`` key states it rather than
    leaving a client to assume — a reply that silently changed encoding would be
    an image that decoded to noise. The cost is stated too: 5 MiB of artifact is
    ~6.99 MB on one NDJSON line, which is a size this lane can carry in ONE
    frame because the direction matters. ``serve_socket.MAX_LINE_BYTES`` (1 MiB)
    bounds what a CLIENT sends; this request is ~200 bytes. Nothing about this
    reply touches that bound, and the launcher's reader splits lines without one.
    No ranging is built, and the reason is measured rather than assumed — see
    ``media_handles``' cap argument.

    **The tier is ``console``, and this is the row where the one-line rule
    ("a level MUTATION is console, everything else is read") does not decide
    it.** Handing a caller the raw BYTES of a file on this machine is not a read
    of the level, it is an egress; and the read tier is deliberately open to
    ``unknown`` — a caller the transport authenticated but could not place —
    which is precisely the caller who must not be able to pull files off the
    disk. ``console`` is also what a ``read``-tier device gets refused with:
    "viewer" is an operator saying *look at my level*, not *stream me every
    proof screenshot on the machine*.

    **A peer is still refused THIS verb, and Stage P4 did not change that.**
    ``PEER_METHOD_ALLOWLIST`` admits nothing it was not edited to admit, and
    what P4 edited it to admit is :func:`_peer_media_get` — a narrower verb that
    resolves LOCAL rows only. A peer calling ``runtime.media.get`` would be
    asking this install to proxy on its behalf, i.e. to spend a third install's
    edge for a caller that never approved it; the arm below is for the DEVICE
    lane, whose caller is an operator holding a screen on the install that owns
    the peer edge.

    **The proxy arm (Stage P4, ruling R-P3).** A handle that resolves to a
    :class:`~agent_runtime.media_handles.RemoteMediaArtifact` — an artifact a
    paired install minted for a cross-install reply forged into this install's
    chat — is fetched through ``agent_runtime.media_proxy``: one dial, the bytes
    verified against the handle, cached by content address, served in a reply
    shaped exactly like a local one. The client cannot tell, and has nothing it
    would do differently if it could.

    **The dial is NOT on the reader loop, and that is the one thing about this
    arm that moved after P4.** P4 shipped it inline and filed the cost: a remote
    handle whose peer is switched off parked the loop for the proxy's own
    timeouts — up to ``PEER_DIAL_TIMEOUT_SECONDS`` to give up dialling, up to
    ``PEER_READ_TIMEOUT_SECONDS`` more if the far install accepted and then went
    quiet — and every other request from that client waited behind a machine
    that was not even on. The fetch now goes to the transport's worker lane
    through ``RpcContext.spawn_reply`` and the finished frame is emitted there,
    on this same ``id``. Three things deliberately did NOT move: the frame (byte
    for byte, refusals included), the bound (``media_proxy``'s two timeouts are
    still the only clock — a watchdog on the reader would be a second one, and
    a second clock is how the long-run lane learned not to bound work anywhere
    but at its source), and the LOCAL arm, which never dialled and still answers
    on the reader. What moved is arrival ORDER: a client correlates on ``id``,
    which JSON-RPC 2.0 §6 already requires of it and which this lane's own
    clients (``media_proxy._ask``) already do.
    """

    from agent_runtime import media_handles

    try:
        correlation_id = _correlation_id_param(params)
    except _CorrelationIdRefused as refused:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            refused.message,
            {"reason": CORRELATION_ID_INVALID_REASON},
        )

    raw = params.get("handle")
    if raw is None:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: handle is required",
            {"reason": media_handles.REASON_HANDLE_INVALID},
        )

    # The grammar runs against a scope that is only derived once the argument
    # has passed it, so a malformed handle costs no scan at all. That ordering
    # is also what keeps a caller from using this verb as a way to make the
    # server hash its disk.
    if not isinstance(raw, str) or not media_handles.HANDLE_RE.match(raw.strip()):
        return err(
            rid,
            ERR_HANDLER_FAILED,
            "runtime.media.get names an artifact by handle "
            "(sha256:<64 hex>); it does not accept a path",
            {"reason": media_handles.REASON_HANDLE_INVALID},
        )

    scope = media_handles.build_media_scope()
    resolved = media_handles.resolve_handle(raw, scope)
    if isinstance(resolved, media_handles.MediaRefusal):
        return err(
            rid,
            ERR_HANDLER_FAILED,
            f"runtime.media.get refused: {resolved.reason}",
            resolved.refusal_data(),
        )

    if isinstance(resolved, media_handles.RemoteMediaArtifact):
        # Stage P4's proxy arm. The client asked THIS install and this install
        # answers — it simply has to spend a peer edge to do it. Nothing about
        # the reply's shape changes, which is the point: a device cannot tell a
        # proxied artifact from a local one and has nothing to do differently
        # if it could.
        from agent_runtime import media_proxy

        def _proxied() -> dict:
            return _media_get_frame(
                rid,
                resolved,
                media_proxy.fetch_remote_artifact(resolved),
                correlation_id,
            )

        # …and the DIAL is the transport's to wait on, not the reader's. The
        # frame built above is the one built below; only the thread that builds
        # it moves. A transport with no worker lane falls through and answers
        # here, which is what every direct-call test does.
        spawn = None if context is None else context.spawn_reply
        if spawn is not None and spawn(
            deferred_reply(rid, "runtime.media.get", _proxied)
        ):
            return DEFERRED
        data: bytes | media_handles.MediaRefusal = media_proxy.fetch_remote_artifact(
            resolved
        )
    else:
        data = media_handles.read_artifact_bytes(resolved)
    return _media_get_frame(rid, resolved, data, correlation_id)


def _media_get_frame(
    rid: Any,
    resolved: Any,
    data: Any,
    correlation_id: str | None,
) -> dict:
    """The bytes (or the refusal) behind a resolved handle → ONE reply frame.

    Lifted out of :func:`_runtime_media_get` so the proxy arm can build its
    answer on a pool worker and the local arm can build it on the reader, from
    the same six lines. A second copy is how "a client cannot tell a proxied
    artifact from a local one" would quietly stop being true.
    """

    from agent_runtime import media_handles

    if isinstance(data, media_handles.MediaRefusal):
        return err(
            rid,
            ERR_HANDLER_FAILED,
            f"runtime.media.get refused: {data.reason}",
            data.refusal_data(),
        )

    result: dict[str, Any] = {
        "contract": MEDIA_CONTRACT,
        "handle": resolved.handle,
        "media_type": resolved.media_type,
        "size_bytes": len(data),
        "encoding": "base64",
        "data": base64.b64encode(data).decode("ascii"),
    }
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)
