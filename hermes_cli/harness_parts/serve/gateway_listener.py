"""The gateway lane: its listen config, the no-listener block, the listener start and
the hello authenticator it installs.
"""

from __future__ import annotations

from functools import partial
from typing import Any

# The listen config moved DOWN to agent_runtime.gateway_endpoints (layout sheet
# gateway_commands.md §1a); this lane keeps the name by import, and its own two
# reads below go through this module's binding.
from agent_runtime.gateway_endpoints.candidates import gateway_listen_config
from hermes_cli.harness_parts.serve.constants import (
    GATEWAY_TRANSPORT,
)

__layer__ = "lanes"

__all__ = [
    "GATEWAY_OUTCOME_SOCKET_UNAVAILABLE",
    "_gateway_authenticator",
    "gateway_block_when_no_listener",
    "gateway_listen_config",
    "start_gateway_listener",
]


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
    from agent_runtime.serve_socket.server import ServeSocketServer

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

    FOUR hellos reach this seam — a device credential, a device pairing code, a
    peer credential and a peer join code — and the dispatch among them is a
    TABLE: ``agent_runtime.serve_gateway_credentials.CREDENTIAL_KINDS``, keyed by
    ``credential_kind``, which refuses a frame that names more than one field.
    That module carries the reasoning for each arm (why a pairing code is safe in
    one round trip, why the peer join is the one arm that writes the far side's
    assertions, why every failure is the same ``bad_proof``); this function only
    binds the store root the listener was started on.
    """

    from agent_runtime.serve_gateway_credentials import authenticate_hello

    return partial(authenticate_hello, store_root)
