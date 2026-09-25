"""The gateway lane: its listen config, the no-listener block, the listener start and
the hello authenticator it installs.
"""

from __future__ import annotations

from typing import Any

from hermes_cli.harness_parts.serve.constants import (
    GATEWAY_TRANSPORT,
)
from hermes_cli.harness_parts.serve.manifest import (
    _credential_kind,
)

__layer__ = "lanes"

__all__ = [
    "GATEWAY_OUTCOME_SOCKET_UNAVAILABLE",
    "_gateway_authenticator",
    "gateway_block_when_no_listener",
    "gateway_listen_config",
    "start_gateway_listener",
]


def gateway_listen_config() -> tuple[str | None, int]:
    """``(host, port)`` from ``remote_gateway.*``; ``(None, …)`` means off.

    The FIRST reader of the keys Stage 0a declared — and the read that found
    they had never existed: Stage 0a put them under ``"gateway"``, which is
    already a top-level key in ``config_defaults``' one big dict literal, so
    Python kept the later entry and dropped this one at parse time. They are
    ``remote_gateway.*`` now, guarded by an AST test.

    ``listen`` is a HOST STRING when it is on, and a boolean ``True`` is
    deliberately refused rather than resolved to a default interface: an
    operator opening a port onto a LAN should have to say which one, and
    "guessed an interface for you" is not a sentence this runtime should be able
    to say about a listener that executes agents with tools. Anything unreadable
    is off, because the failure direction for a config that cannot be parsed is
    "do not bind".
    """

    try:
        from hermes_cli.config import load_config_readonly

        block = load_config_readonly().get("remote_gateway") or {}
    except Exception:
        return None, 0
    if not isinstance(block, dict):
        return None, 0
    listen = block.get("listen")
    if not isinstance(listen, str):
        return None, 0
    host = listen.strip()
    if not host or host.lower() in {"false", "off", "no", "true"}:
        return None, 0
    try:
        port = int(block.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    return host, max(0, min(65535, port))


#: R-L1's fourth outcome word. The LAN listener is deliberately coupled to the
#: loopback lane — the serve that owns the socket for a root is the serve that
#: opens that root's doors, or two serves bind one operator-chosen port and the
#: second one loses — so every way the socket lane fails is also a way this
#: listener never starts. Until this stage all of them arrived as ``disabled``,
#: which is the word for "the operator did not ask for a listener": the launcher
#: could not tell a config it had just written from a lock it had just lost, and
#: on 2026-09-04 it did not.
GATEWAY_OUTCOME_SOCKET_UNAVAILABLE = "socket_unavailable"


def gateway_block_when_no_listener(
    socket_block: dict[str, Any] | None, *, root_resolved: bool
) -> dict[str, Any]:
    """The ``gateway`` block for a boot that never reached the listener (R-L1).

    Three ways to not be listening, and they are three different sentences a
    launcher has to be able to say:

    * ``error:root_unresolved`` — there is no runtime root, so there is nothing
      to open a door onto. Same word the ``auth`` and ``install`` blocks use for
      the same failure, so an operator reading ``ready`` sees one story.
    * ``disabled`` — ``remote_gateway.listen`` is off. Nobody asked for a
      listener and there is nothing wrong. This is the default, forever.
    * ``socket_unavailable`` — **the config asked for a listener and the socket
      lane is why there is none.** ``reason`` is the ``socket`` block's own
      outcome, verbatim (``disabled`` | ``lock_held_by`` | ``error:<token>``), so
      the two blocks cannot tell different stories about one boot, and ``pid`` /
      ``owner_started_at`` name the process that is holding the lane. ``host``
      and ``port`` are the config's, carried the way the ``error:*`` outcomes
      already carry them — the door the operator ASKED for, not one that opened.

    Config-off wins over socket-unavailable when both are true, and that
    ordering is deliberate: ``disabled`` is the actionable answer (turn it on),
    while ``socket_unavailable`` on a runtime nobody asked to listen would send a
    launcher chasing a lock for a door it was never told to open.

    Note that ``socket_unavailable`` can only ever ride ``ready`` and a stdio
    ``version`` reply. There is no loopback listener in this state, so no
    ``hello_ok`` exists to carry it — which is precisely why the block on
    ``ready`` has to be complete.

    Module-level and pure so it is testable without standing up a runtime, the
    same reason ``start_gateway_listener`` below is.
    """

    if not root_resolved:
        return {"outcome": "error:root_unresolved"}
    host, port = gateway_listen_config()
    if host is None:
        return {"outcome": "disabled"}
    block = socket_block if isinstance(socket_block, dict) else {}
    pid = block.get("pid")
    started_at = block.get("owner_started_at")
    return {
        "outcome": GATEWAY_OUTCOME_SOCKET_UNAVAILABLE,
        # Always present, null when unknown, rather than absent-when-unknown:
        # this block IS the explanation, and a reader of an explanation should
        # not have to tell "the field is missing" from "the field is empty".
        "reason": str(block.get("outcome") or "unknown"),
        "pid": pid if isinstance(pid, int) else None,
        "owner_started_at": started_at if isinstance(started_at, str) else None,
        "host": host,
        "port": port,
    }


def start_gateway_listener(
    store_root: Any,
    *,
    boot_id: str,
    display_name: Any,
    dispatch_line: Any,
    hello_payload: Any,
    on_disconnect: Any,
    log: Any,
    frame_contract: int,
) -> tuple[Any, dict[str, Any]]:
    """Bind the second listener, or say precisely why there is none.

    Returns ``(server_or_None, block)`` where ``block`` is what rides the
    greeting frames. It follows the ``socket`` block's standing rule — a block
    states its own outcome rather than vanishing — because the failure this
    guards against is specific and quiet: an operator sets ``remote_gateway.listen``,
    restarts, and a phone cannot reach the install. Without a stated outcome
    that looks identical whether the port was taken, the certificate could not be
    minted, or the config was never read at all.

    Module-level rather than a closure inside ``serve_loop`` so it is testable
    without standing up a runtime, and so the credential wiring — the one part
    that must not be got wrong — is readable in one screen instead of inside a
    2000-line function.
    """

    host, port = gateway_listen_config()
    if host is None:
        return None, {"outcome": "disabled"}

    from agent_runtime.gateway_tls import ensure_certificate, server_ssl_context
    from agent_runtime.serve_socket import ServeSocketServer

    certificate = ensure_certificate(
        store_root, common_name=display_name if isinstance(display_name, str) else None
    )
    if not certificate.ok:
        # R1 ruled ENCRYPT, so a listener that cannot encrypt does not open.
        # Degrading to plaintext here would be the single worst thing this file
        # could do: the operator asked for a LAN door, would get one, and the
        # only thing missing would be the property they were promised.
        return None, {
            "outcome": f"error:{certificate.state}",
            "host": host,
            "port": port,
        }
    try:
        context = server_ssl_context(store_root)
    except Exception as exc:
        return None, {
            "outcome": f"error:{type(exc).__name__}",
            "host": host,
            "port": port,
        }

    server = ServeSocketServer(
        store_root,
        boot_id=boot_id,
        dispatch_line=dispatch_line,
        hello_payload=hello_payload,
        # The per-root token is NOT this lane's credential, and the provider is
        # wired to refuse rather than left absent: `token_provider` is a required
        # argument, and one that returned the root token while `authenticator`
        # happened to be set would be a live fallback waiting for a refactor to
        # find it. There is no path on this listener that consults the install's
        # own secret.
        token_provider=lambda: None,
        authenticator=_gateway_authenticator(store_root),
        ssl_context=context,
        host=host,
        port=port,
        transport_name=GATEWAY_TRANSPORT,
        frame_contract=frame_contract,
        on_disconnect=on_disconnect,
        log=log,
    )
    try:
        bound = server.bind()
    except Exception as exc:
        # A port already in use is the ordinary case here, not the exotic one:
        # this lane's port is usually FIXED (an operator wrote a firewall rule
        # for it), so a stale process holding it is a Tuesday. Typed, and never
        # fatal — the loopback lane and the stdio lane are unaffected.
        return None, {
            "outcome": f"error:{type(exc).__name__}",
            "host": host,
            "port": port,
        }
    return server, {
        "outcome": "listening",
        "host": host,
        "port": bound,
        "started_at": server.started_at,
        # The value a pairing payload carries and a client pins. Published on
        # the greeting because a client that has to ask a second question to
        # learn what it should have pinned has a window in which it is trusting
        # nothing — and this is the same argument the `build` block beside it
        # makes about code.
        "cert_fingerprint": certificate.fingerprint,
    }


def _gateway_authenticator(store_root: Any):
    """The gateway lane's credential check, as a ``ServeSocketServer`` seam.

    FOUR hellos reach this function and it is the only place that tells them
    apart: a device credential, a device pairing code, a peer credential, and a
    peer join code. The dispatch is on which FIELD the frame names, and the
    first thing it does is refuse a frame that names more than one — see
    ``_credential_kind`` below, which is where Stage 6's "device-tier and
    peer-tier credentials are never interchangeable" is actually enforced.

    A device names itself in the hello (``device_id``) and answers the challenge
    with an HMAC keyed by its own token's digest, bound to the port it dialled.
    A peer names itself with ``peer_install_id`` and answers with an HMAC keyed
    by the shared verifier, over a message with a different prefix, bound to the
    same port. Every failure of any kind — no id, unknown id, revoked row, wrong
    proof, wrong code, wrong ceremony — comes back as the SAME ``bad_proof``
    rejection, so a caller that has proven nothing cannot enumerate which device
    ids or which paired installs exist by watching the reason change, and cannot
    even learn which of the two ceremonies it just failed. The runtime's own log
    keeps the distinction; the wire does not.

    **The other arm is the pairing ceremony's second half**, and it is here
    rather than in a stage of its own because the alternative is shipping a
    device tier no device can ever enter. A hello carrying ``pairing_code``
    instead of ``device_id`` is a phone that has just been shown eight
    characters on the operator's terminal; the store redeems them under all of
    ``gateway/pairing.py``'s discipline (TTL, pending cap, lockout, constant-time
    compare) and the connection is admitted as the device it just created, with
    the minted token riding the ``hello_ok`` it was going to send anyway.

    Three properties make that safe enough to do in one round trip. The link is
    already TLS with a fingerprint the operator handed over out of band, so the
    token is not readable and not deliverable to an impostor. The code is
    one-shot — redeemed, it is deleted before the token is minted — so a replay
    finds nothing. And a failed redemption collapses into the same ``bad_proof``
    as every other credential failure and charges the same limiter, so the code
    space cannot be ground down any faster than the device-id space can.

    **The peer join (Stage 6) is those same three properties over the same
    machinery**, plus one the device ceremony has no need of: it is the only arm
    that WRITES facts the other side asserted — the joining install's name, its
    endpoints, its certificate fingerprint. They are bounded and cleaned by
    ``gateway_peers`` before they land, and what makes them safe to keep at all
    is R5's second operator: the code was minted seconds earlier by a human at
    THIS machine, which is a stronger provenance than anything the wire could
    supply.
    """

    from agent_runtime.gateway_peers import (
        PeerCredential,
        cache_peer_hello,
        note_dial_result,
        note_peer_seen,
        note_peer_store_read,
        redeem_peer_code,
        verify_peer_proof,
    )
    from agent_runtime.serve_gateway_auth import (
        DeviceCredential,
        note_device_seen,
        redeem_pairing_code,
        verify_device_proof,
    )
    from agent_runtime.serve_socket import HelloAuthOutcome, REJECT_BAD_PROOF

    def _reject():
        return HelloAuthOutcome(ok=False, reject_reason=REJECT_BAD_PROOF)

    def _authenticate(message: dict[str, Any], nonce: str, port: int):
        kind = _credential_kind(message)
        if kind is None:
            # Zero credentials named, or more than one. A handshake with two
            # credentials in it is exactly where a downgrade lives, and the
            # server must not get to pick which one it liked.
            return _reject()

        if kind == "pairing_code":
            outcome = redeem_pairing_code(
                store_root,
                message.get("pairing_code"),
                device_name=message.get("client")
                if isinstance(message.get("client"), str)
                else None,
            )
            if not isinstance(outcome, DeviceCredential):
                return _reject()
            return HelloAuthOutcome(
                ok=True,
                device_id=outcome.device_id,
                device_tier=outcome.tier,
                issued_token=outcome.token,
            )

        if kind == "peer_code":
            # The joining install must NAME itself in the same frame: the edge
            # is symmetric, so a row keyed by nothing would be a peer this
            # install could never dial back and could never recognise again.
            outcome = redeem_peer_code(
                store_root,
                message.get("peer_code"),
                peer_install_id=str(message.get("peer_install_id") or ""),
                display_name=message.get("peer_display_name")
                or message.get("client"),
                endpoints=message.get("peer_endpoints"),
                cert_fingerprint=message.get("peer_cert_fingerprint"),
            )
            if not isinstance(outcome, PeerCredential):
                return _reject()
            # R-D16, this side of the ceremony. The joining install just
            # completed a TLS handshake against this listener and proved a code
            # a human minted here seconds ago — the same evidence the
            # ``peer_install_id`` arm below turns into ``reachable`` through
            # ``cache_peer_hello``. Without this the MINTING side's cache stayed
            # at whatever a past dial left, so an edge both stores had just
            # written read as unusable on one of them.
            #
            # Outside ``redeem_peer_code``'s own lock rather than inside it:
            # ``_store_lock`` is not reentrant (``locks._file_lock``), so a
            # cache touch taken within that span would spend its ten-second
            # budget contending with the write it is describing and then give up
            # silently.
            note_dial_result(store_root, outcome.peer_install_id, ok=True)
            return HelloAuthOutcome(
                ok=True,
                peer_install_id=outcome.peer_install_id,
                issued_peer_secret=outcome.secret,
                # S2: whatever the mint decided, carried straight through. The
                # store computed it at redemption; this function neither derives
                # nor defaults one, so the two ends of the edge hold one value.
                issued_peer_secret_expires_at=outcome.expires_at,
            )

        if kind == "peer_install_id":
            # S2c (R-S2-8). The revision read that makes an EXTERNAL write
            # visible, taken on a read this lane was making anyway. The serve is
            # the process that notices because it is the one that reads
            # repeatedly; a fresh CLI process seeds on its first read and emits
            # nothing, having no baseline to claim a change against.
            note_peer_store_read(store_root)
            peer = verify_peer_proof(
                store_root,
                message.get("peer_install_id"),
                message.get("proof"),
                nonce,
                port=port,
            )
            if not peer.ok or peer.record is None:
                return _reject()
            note_peer_seen(store_root, peer.record.peer_install_id)
            # …and the three OPTIONAL facts the hello may carry about itself,
            # after the proof and never before it: these are assertions by a
            # party that has now authenticated, and writing them for a caller
            # that had not would let an unpaired stranger grow this file.
            cache_peer_hello(
                store_root,
                peer.record.peer_install_id,
                display_name=message.get("peer_display_name"),
                endpoints=message.get("peer_endpoints"),
                cert_fingerprint=message.get("peer_cert_fingerprint"),
            )
            return HelloAuthOutcome(
                ok=True, peer_install_id=peer.record.peer_install_id
            )

        auth = verify_device_proof(
            store_root,
            message.get("device_id"),
            message.get("proof"),
            nonce,
            port=port,
        )
        if not auth.ok or auth.record is None:
            return _reject()
        note_device_seen(store_root, auth.record.device_id)
        return HelloAuthOutcome(
            ok=True,
            device_id=auth.record.device_id,
            device_tier=auth.record.tier,
        )

    return _authenticate
