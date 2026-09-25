"""Stage 1's device verbs: ``harness gateway pair``, ``devices list``,
``devices revoke``, and the identity + certificate every pairing needs.
"""

from __future__ import annotations

import json

from agent_runtime.gateway_endpoints.candidates import _endpoint
from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import (
    _list_envelope,
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

from .refusals import LISTENER_OFF_SENTENCE, _dial_target, _refusal

__layer__ = "lanes"


def cmd_gateway_pair(args) -> int:
    """``harness gateway pair`` — mint a short-TTL code and the QR payload.

    Both halves of R3 from one mint, which is the point: a code shown as text
    and a code shown as a QR that disagree would be two ceremonies wearing one
    name.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.gateway_tls import ensure_certificate
    from agent_runtime.serve_gateway_auth import (
        StoreRefusal,
        mint_pairing_code,
        pairing_store_path,
    )

    root = paths.store_root()
    tier = str(getattr(args, "tier", None) or "console")
    name = getattr(args, "name", None)

    # ENSURE, not read, and for both of these. `pair` is a write verb — it is
    # already minting a credential channel — and an operator must be able to run
    # it against a root that has never booted, which `gateway rename` already
    # established. The identity and the certificate are exactly what the payload
    # has to name, so a `pair` that could not produce them would print a payload
    # with holes in it.
    identity = ensure_install_identity(root)
    certificate = ensure_certificate(
        root, common_name=identity.display_name if identity.ok else None
    )
    if not certificate.ok:
        # R1 ruled encrypt, so a payload without a fingerprint is a payload that
        # tells a phone to trust any certificate it is handed. Refused rather
        # than printed with a null.
        return emit_harness_error(
            RuntimeError(certificate.state),
            reason=certificate.state,
            args=args,
            code="runtime_unavailable",
            message=(
                f"{certificate.cert_path}: the gateway certificate is "
                f"{certificate.state}, so there is no fingerprint for a device "
                "to pin. Pairing without one would tell the device to trust "
                "whatever certificate answers."
            ),
        )

    # The dial host is decided BEFORE the mint, so a root that cannot say where
    # a phone should dial refuses without having burned one of the three pending
    # codes the operator is allowed.
    endpoint = _endpoint(root)
    dial, endpoints, failure = _dial_target(root, endpoint, args=args)
    if failure:
        return failure

    code = mint_pairing_code(root, tier=tier, name=name)
    if isinstance(code, StoreRefusal):
        # R-D14: a pairing.json this machine cannot write is not the network's
        # fault, and the refusal now says which file to fix.
        return _refusal(code, args=args, store_path=pairing_store_path(root))

    payload = {
        # R-D1: a DIALABLE address, never the bind. ``endpoint`` below still
        # reports the bind, because that is the honest answer to "what is this
        # listener on" — what changed is that the bind stopped being what a
        # phone is told to dial.
        "host": dial[0] if dial else None,
        "port": dial[1] if dial else None,
        # R-D3's list, on the payload a phone scans. ``host``/``port`` remain and
        # equal ``endpoints[0]``, so a scanner that predates this key reads the
        # same first candidate it always did.
        "endpoints": endpoints,
        "install_id": identity.install_id,
        "cert_fingerprint": certificate.fingerprint,
        "code": code.code,
    }
    row = {
        # The typed fallback: eight characters, and the endpoint beside them so
        # an operator typing by hand has everything on one screen.
        "code": code.code,
        "expires_in_seconds": code.expires_in_seconds(),
        "tier": code.tier,
        "device_name": code.name,
        "install_id": identity.install_id,
        "cert_fingerprint": certificate.fingerprint,
        "endpoint": endpoint,
        # The QR half. A STRING, not a nested object: what a QR encodes is bytes,
        # and handing the operator the exact bytes to encode removes the chance
        # that two renderers serialise the same object differently and only one
        # of them scans.
        "qr_payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }
    if endpoint["source"] != "live":
        # Stated, never silent: a code minted against a lane nobody is listening
        # on is still a valid code, and an operator who does not know that will
        # blame the code.
        row["note"] = (
            "no running serve advertised a gateway listener for this root, so "
            "the endpoint above is what the config says the NEXT boot will use. "
            "The code is valid either way."
            if endpoint["source"] == "config"
            else LISTENER_OFF_SENTENCE + " The code is valid either way."
        )

    envelope = attach_root_observability(_object_envelope("gateway_pairing", row))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def cmd_gateway_devices_list(args) -> int:
    """``harness gateway devices list`` — every paired device, revoked included.

    Revoked rows are SHOWN. A list that hid them would make "never paired" and
    "thrown out" the same answer, and the second is the one an operator auditing
    a lost phone needs.
    """

    from agent_runtime import paths
    from agent_runtime.serve_gateway_auth import list_devices

    rows = [record.payload() for record in list_devices(paths.store_root())]
    envelope = attach_root_observability(_list_envelope("gateway_device", rows))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def cmd_gateway_devices_revoke(args) -> int:
    """``harness gateway devices revoke <device_id>`` — refuse it from now on.

    Takes effect on the NEXT handshake, not on connections already open, and
    that is stated in the ack rather than left for an operator to discover: a
    revocation someone believes is immediate, applied to a device that is
    currently attached, is the gap between what they think they did and what
    happened. Closing an in-flight session is a separate decision — the operator
    can drain the runtime — and inventing it here would make revoke a verb that
    disconnects people.
    """

    from agent_runtime import paths
    from agent_runtime.serve_gateway_auth import (
        StoreRefusal,
        device_store_path,
        revoke_device,
    )

    device_id = str(getattr(args, "device_id", "") or "").strip()
    if bool(getattr(args, "dry_run", False)):
        from agent_runtime.serve_gateway_auth import lookup_device

        record = lookup_device(paths.store_root(), device_id)
        if record is None:
            return emit_harness_error(
                RuntimeError("unknown_device"),
                reason="unknown_device",
                args=args,
                code="not_found",
                message=f"no device {device_id!r} is paired with this root",
            )
        row = record.payload()
        # What the WRITE would land, not what is there now.
        row["revoked"] = True
        envelope = attach_root_observability(_object_envelope("gateway_device", row))
        envelope["dry_run"] = True
        _print_stage42(envelope, args=args, default_output="json")
        return 0

    outcome = revoke_device(paths.store_root(), device_id)
    if isinstance(outcome, StoreRefusal):
        return _refusal(
            outcome, args=args, store_path=device_store_path(paths.store_root())
        )
    row = outcome.payload()
    row["takes_effect"] = "next_handshake"
    envelope = attach_root_observability(_object_envelope("gateway_device", row))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


# ── Stage 6: peers ───────────────────────────────────────────────────────────


def _install_and_certificate(args):
    """This root's install identity and gateway certificate, both ENSURED.

    Shared by ``peers pair`` and ``peers join`` because both need the same two
    facts about THIS install and for the same reason ``pair`` needs them: a peer
    edge is symmetric, so each side has to be nameable and dialable by the
    other, and a payload with a hole in it is a payload that tells the far side
    to trust whatever certificate answers.

    Returns ``(pair, 0)`` or ``(None, exit_code)`` — the error branch is already
    rendered when it returns, so callers propagate the int.
    """

    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity
    from agent_runtime.gateway_tls import ensure_certificate

    root = paths.store_root()
    identity = ensure_install_identity(root)
    if not identity.ok or not identity.install_id:
        return None, emit_harness_error(
            RuntimeError(identity.state),
            reason=identity.state,
            args=args,
            code="runtime_unavailable",
            message=(
                f"{identity.path}: this root's install identity is "
                f"{identity.state}, so it has no id to name itself to a peer. "
                "A peer edge is keyed by install id on both sides; there is "
                "nothing to pair without one."
            ),
        )
    certificate = ensure_certificate(root, common_name=identity.display_name)
    if not certificate.ok:
        return None, emit_harness_error(
            RuntimeError(certificate.state),
            reason=certificate.state,
            args=args,
            code="runtime_unavailable",
            message=(
                f"{certificate.cert_path}: the gateway certificate is "
                f"{certificate.state}, so there is no fingerprint for the other "
                "install to pin. Pairing without one would tell it to trust "
                "whatever certificate answers."
            ),
        )
    return (identity, certificate), 0
