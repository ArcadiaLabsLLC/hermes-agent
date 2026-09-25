"""``peers pair`` (Stage 6, the manual half) and ``introduce`` (S2): two
existing mints, one envelope for a launcher to post as a backend grant.
"""

from __future__ import annotations

import json

from agent_runtime.gateway_endpoints.candidates import _endpoint
from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import (
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

from .devices import _install_and_certificate
from .refusals import (
    GRANT_PAYLOAD_MAX_BYTES,
    LISTENER_OFF_SENTENCE,
    _dial_target,
    _refusal,
)

__layer__ = "lanes"


def cmd_gateway_peers_pair(args) -> int:
    """``harness gateway peers pair`` — mint a PEER code plus the join payload.

    Run on install A. The operator carries the payload (or the eight characters)
    to install B and runs ``peers join`` there. Nothing is written to
    ``peers.json`` by this verb: a code is an invitation, and an install that
    never redeems it leaves no row behind.

    R3's two halves from one mint, exactly as ``gateway pair`` does it — and the
    payload's code field is ``peer_code`` rather than ``code``, so a device
    payload pasted into ``peers join`` (or the reverse) is refused for its shape
    rather than half-parsed into the wrong ceremony.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_peers import mint_peer_code
    from agent_runtime.serve_gateway_auth import StoreRefusal, pairing_store_path

    root = paths.store_root()
    resolved, code_or_error = _install_and_certificate(args)
    if resolved is None:
        return code_or_error
    identity, certificate = resolved

    # Before the mint, for ``gateway pair``'s reason: a refusal that had already
    # written a pending entry burns one of the operator's three.
    endpoint = _endpoint(root)
    dial, endpoints, failure = _dial_target(root, endpoint, args=args)
    if failure:
        return failure

    minted = mint_peer_code(root, note=getattr(args, "note", None))
    if isinstance(minted, StoreRefusal):
        # Into ``pairing.json``, the same file ``gateway pair`` mints into: one
        # store, one cap, one lockout across both ceremonies (R-D14).
        return _refusal(minted, args=args, store_path=pairing_store_path(root))

    payload = {
        # R-D1 / R-D3, exactly as ``gateway pair`` writes them: a dialable first
        # candidate, the whole ordered list beside it, and never the bind.
        "host": dial[0] if dial else None,
        "port": dial[1] if dial else None,
        "endpoints": endpoints,
        "install_id": identity.install_id,
        "cert_fingerprint": certificate.fingerprint,
        "peer_code": minted.code,
    }
    row = {
        "peer_code": minted.code,
        "expires_in_seconds": minted.expires_in_seconds(),
        "note": minted.note,
        "install_id": identity.install_id,
        "display_name": identity.display_name,
        "cert_fingerprint": certificate.fingerprint,
        "endpoint": endpoint,
        # A STRING, not a nested object, for ``gateway pair``'s reason: what a QR
        # encodes is bytes, and handing the operator the exact bytes removes the
        # chance that two renderers serialise the same object differently and
        # only one of them scans.
        "join_payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
        # Said out loud on the mint, because this is the half an operator can get
        # wrong silently: a code that is never carried to the other machine pairs
        # nothing, and R5 is the reason there is no way around that.
        "next_step": (
            "run `harness gateway peers join <join_payload>` on the OTHER "
            "install. Both sides approve an edge; nothing here can pair on its "
            "own."
        ),
    }
    if endpoint["source"] != "live":
        row["note_endpoint"] = (
            "no running serve advertised a gateway listener for this root, so "
            "the endpoint in the payload is what the config says the NEXT boot "
            "will use. The joining install dials it — if nothing is listening "
            "there when they run `join`, the code is still valid and the join "
            "will simply fail to connect."
            if endpoint["source"] == "config"
            else LISTENER_OFF_SENTENCE + " The code is valid either way."
        )

    envelope = attach_root_observability(_object_envelope("gateway_peer_pairing", row))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def cmd_gateway_introduce(args) -> int:
    """``harness gateway introduce`` — one envelope a launcher can post as a grant.

    **A COMPOSITION, not a third ceremony.** It calls ``mint_peer_code`` and
    ``mint_pairing_code`` — the same two functions ``peers pair`` and ``pair``
    call, under the same lockout, the same pending cap and the same ten-minute
    TTL — and prints their two codes in one object shaped the way the backend's
    fulfil endpoint wants it (S1 packet §4.1). Nothing is stored that those two
    verbs do not store, and there is no new credential kind. What is new is the
    scoping: both halves are minted FOR a named requester, and the peer half is
    genuinely refused to anybody else (``gateway_peers.redeem_peer_code``).

    **Why it refuses when the listener is off, where ``peers pair`` prints a
    note.** ``peers pair``'s consumer is a human who can read a note, shrug, and
    go turn the listener on. This verb's consumer is a machine: a launcher posts
    the envelope to the backend, the requester reads it once and dials, and the
    dial fails against a door that was never open. A note in that chain is a
    string nobody renders. So an ``unknown`` endpoint is ``runtime_unavailable``
    (family 7, retryable — the identical command succeeds after a restart), with
    ``peers pair``'s own sentence, and a ``config`` endpoint is ALLOWED with a
    note, because "the serve has not booted yet" is a real and recoverable
    ordering rather than a lane that is off.

    **Two mints, not one atomic pair.** The pending cap
    (``MAX_PENDING_CODES = 3``, counted across both ceremonies) can legitimately
    refuse the second half after the first has been written, and holding one
    lock across both would not change that — it would only make the refusal
    arrive with a half-built envelope and no way to report which half failed.
    So each mint is its own atomic write, the envelope carries ``null`` for a
    half that did not mint, ``refusals`` names it, and the exit is 0 only when
    every requested half is present.

    **The codes appear exactly here.** In ``peer.peer_code`` / ``device.code``
    and inside the two payload strings, on stdout, once. Never in an event,
    never in a row, never in a log line — the codes discipline
    (``gateway_pairing_codes``), unchanged, and the reason its ten-minute TTL is
    allowed to be short.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_capabilities import GATEWAY_CAPABILITIES
    from agent_runtime.gateway_peers import mint_peer_code
    from agent_runtime.serve_gateway_auth import (
        CREDENTIAL_TTL_SECONDS_INTRODUCED,
        StoreRefusal,
        mint_pairing_code,
        pairing_store_path,
    )
    from agent_runtime.state_patches import (
        CORRELATION_ID_MAX_LEN,
        normalize_correlation_id,
    )

    root = paths.store_root()
    for_install_id = str(getattr(args, "for_install", "") or "").strip()
    for_device_id = str(getattr(args, "for_device", "") or "").strip()
    if not for_install_id and not for_device_id:
        # At least one, never both required: a PHONE has no install id (the
        # device half is all there is to mint for it), and an install being
        # re-introduced after a rebuild may have no account device row yet. The
        # parent plan's "both that apply" is exactly this.
        return emit_harness_error(
            RuntimeError("no_requester"),
            reason="no_requester",
            args=args,
            code="invalid_payload",
            message=(
                "gateway introduce needs at least one of --for-install (another "
                "hermes install, which gets the peer half) or --for-device (an "
                "account device, which gets the device half). With neither there "
                "is nobody to scope the codes to, and an unscoped code is what "
                "`harness gateway pair` and `peers pair` already mint."
            ),
        )

    raw_correlation = getattr(args, "correlation", None)
    correlation = None
    if raw_correlation is not None and str(raw_correlation).strip():
        # The SAME fence the RPC lane applies to ``correlation_id``
        # (``serve_rpc._correlation_id_param`` → ``state_patches``), read from
        # the module that owns the rule rather than restated here — R-IP17 says
        # the grant id is one token and every party writes it, which is only
        # true if every party agrees what a legal one looks like. Refused and
        # never repaired: a sanitized id would print a value neither the backend
        # nor this install used.
        correlation = normalize_correlation_id(raw_correlation)
        if correlation is None:
            return emit_harness_error(
                RuntimeError("correlation_id_invalid"),
                reason="correlation_id_invalid",
                args=args,
                code="invalid_payload",
                message=(
                    "--correlation is the backend grant id and must be a "
                    f"generated token of at most {CORRELATION_ID_MAX_LEN} "
                    "characters from [A-Za-z0-9_.:-]"
                ),
            )

    resolved, code_or_error = _install_and_certificate(args)
    if resolved is None:
        return code_or_error
    identity, certificate = resolved

    endpoint = _endpoint(root)
    if endpoint["source"] == "unknown":
        return emit_harness_error(
            RuntimeError("gateway_listener_off"),
            reason="gateway_listener_off",
            args=args,
            code="runtime_unavailable",
            message=LISTENER_OFF_SENTENCE,
        )

    dial, endpoints, failure = _dial_target(root, endpoint, args=args)
    if failure:
        return failure
    note = getattr(args, "note", None)

    peer_block = None
    device_block = None
    refusals: list[dict[str, str]] = []
    first_refusal = None

    if for_install_id:
        minted = mint_peer_code(
            root,
            note=note,
            credential_ttl_seconds=CREDENTIAL_TTL_SECONDS_INTRODUCED,
            for_install_id=for_install_id,
            correlation=correlation,
        )
        if isinstance(minted, StoreRefusal):
            refusals.append({"half": "peer", "reason": minted.reason})
            first_refusal = first_refusal or minted
        else:
            peer_block = {
                "peer_code": minted.code,
                "expires_in_seconds": minted.expires_in_seconds(),
                "join_payload": json.dumps(
                    {
                        # R-D1: the DIAL host, not ``endpoint["host"]``. This is
                        # the line S4's hardware attempt died on — a wildcard
                        # bind put ``0.0.0.0`` here, the far install dialled it,
                        # and the receipt said ``runtime_unavailable``.
                        "host": dial[0] if dial else None,
                        "port": dial[1] if dial else None,
                        "endpoints": endpoints,
                        "install_id": identity.install_id,
                        "cert_fingerprint": certificate.fingerprint,
                        "peer_code": minted.code,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }

    if for_device_id:
        minted_device = mint_pairing_code(
            root,
            name=note,
            # ``console`` and not the operator's choice: an introduction is the
            # account saying "this is my own device on my own machine", which is
            # the exact provenance ``DEFAULT_DEVICE_TIER``'s ruling names. A
            # ``--tier`` flag here would be a knob whose only safe setting is
            # the default.
            tier="console",
            credential_ttl_seconds=CREDENTIAL_TTL_SECONDS_INTRODUCED,
            for_device_id=for_device_id,
            correlation=correlation,
        )
        if isinstance(minted_device, StoreRefusal):
            refusals.append({"half": "device", "reason": minted_device.reason})
            first_refusal = first_refusal or minted_device
        else:
            device_block = {
                "code": minted_device.code,
                "tier": minted_device.tier,
                "expires_in_seconds": minted_device.expires_in_seconds(),
                "qr_payload": json.dumps(
                    {
                        # The device half's copy of the same correction, and it
                        # has to be the same object: one introduction is one
                        # machine, and two halves that named different addresses
                        # would be an introduction to two different places.
                        "host": dial[0] if dial else None,
                        "port": dial[1] if dial else None,
                        "endpoints": endpoints,
                        "install_id": identity.install_id,
                        "cert_fingerprint": certificate.fingerprint,
                        "code": minted_device.code,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }

    if first_refusal is not None:
        # The first refusal's family, not a generic one: a pending cap, a
        # lockout and a store this machine cannot write are three different next
        # moves, and the exit code is how a launcher tells them apart without
        # parsing prose. Both halves mint into ``pairing.json`` — one file, one
        # cap, one lockout across the two ceremonies — so one path answers for
        # whichever half refused first.
        return _refusal(
            first_refusal, args=args, store_path=pairing_store_path(root)
        )

    # **One writer of the backend's shape.** The launcher POSTs this object
    # verbatim; building it here rather than letting the launcher assemble it
    # from the envelope's other keys is what keeps "what fulfil receives" a
    # decision this repo made once. Its key set is :data:`GRANT_PAYLOAD_KEYS`.
    grant_payload = {
        "peer_join_payload": (peer_block or {}).get("join_payload"),
        "device_pair_payload": (device_block or {}).get("qr_payload"),
        "install_id": identity.install_id,
        "endpoints": endpoints,
        "cert_fingerprint": certificate.fingerprint,
        "correlation": correlation,
    }
    compact = json.dumps(grant_payload, separators=(",", ":"), sort_keys=True)
    if len(compact.encode("utf-8")) > GRANT_PAYLOAD_MAX_BYTES:
        # Unreachable at four endpoints and two ~200-byte payloads; asserted
        # anyway because the alternative is discovering the ceiling as an opaque
        # 400 from a service this process cannot see.
        return emit_harness_error(
            RuntimeError("grant_payload_too_large"),
            reason="grant_payload_too_large",
            args=args,
            code="invalid_payload",
            message=(
                f"the grant payload is {len(compact.encode('utf-8'))} bytes and "
                f"the backend accepts {GRANT_PAYLOAD_MAX_BYTES}. Reduce the "
                "advertised endpoints (remote_gateway.listen can name one "
                "interface instead of a wildcard)."
            ),
        )

    row = {
        "install_id": identity.install_id,
        "display_name": identity.display_name,
        "cert_fingerprint": certificate.fingerprint,
        "endpoints": endpoints,
        "endpoints_source": endpoint["source"],
        "capabilities": list(GATEWAY_CAPABILITIES),
        "correlation": correlation,
        "for_install_id": for_install_id or None,
        "for_device_id": for_device_id or None,
        "credential_ttl_seconds": CREDENTIAL_TTL_SECONDS_INTRODUCED,
        "peer": peer_block,
        "device": device_block,
        "grant_payload": grant_payload,
    }
    if refusals:
        row["refusals"] = refusals
    if endpoint["source"] != "live":
        row["note_endpoint"] = (
            "no running serve advertised a gateway listener for this root, so "
            "the endpoint in these payloads is what the config says the NEXT "
            "boot will use. The codes are valid either way; a requester that "
            "dials before this root boots simply fails to connect."
        )

    envelope = attach_root_observability(_object_envelope("gateway_introduction", row))
    _print_stage42(envelope, args=args, default_output="json")
    return 0
