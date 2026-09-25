"""``peers pair`` (Stage 6, the manual half) and ``introduce`` (S2): two
existing mints, one envelope for a launcher to post as a backend grant.
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime.gateway_endpoints import SOURCE_CONFIG, SOURCE_LIVE, SOURCE_UNKNOWN, listener_endpoint
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
    PhaseStop,
    _dial_target,
    parse_correlation,
    store_refusal_error,
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
    endpoint = listener_endpoint(root)
    dial, endpoints, failure = _dial_target(root, endpoint, args=args)
    if failure:
        return failure

    minted = mint_peer_code(root, note=getattr(args, "note", None))
    if isinstance(minted, StoreRefusal):
        # Into ``pairing.json``, the same file ``gateway pair`` mints into: one
        # store, one cap, one lockout across both ceremonies (R-D14).
        return store_refusal_error(minted, args=args, store_path=pairing_store_path(root))

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
    if endpoint["source"] != SOURCE_LIVE:
        row["note_endpoint"] = (
            "no running serve advertised a gateway listener for this root, so "
            "the endpoint in the payload is what the config says the NEXT boot "
            "will use. The joining install dials it — if nothing is listening "
            "there when they run `join`, the code is still valid and the join "
            "will simply fail to connect."
            if endpoint["source"] == SOURCE_CONFIG
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

    # The verb's own flags are read HERE, in the handler, and handed to the
    # phases as values: ``test_every_stage42_global_flag_is_honored`` walks the
    # handler for the reads, and a flag read only through ``self.args`` would be
    # a flag that gate cannot see anybody honouring.
    introduction = Introduce(
        args,
        for_install_id=str(getattr(args, "for_install", "") or "").strip(),
        for_device_id=str(getattr(args, "for_device", "") or "").strip(),
        note=getattr(args, "note", None),
    )
    try:
        introduction.flags()
        introduction.correlation = parse_correlation(args)
        row = introduction.build()
    except PhaseStop as stop:
        return stop.code
    envelope = attach_root_observability(_object_envelope("gateway_introduction", row))
    _print_stage42(envelope, args=args, default_output="json")
    return 0


class Introduce:
    """One ``gateway introduce`` run, as the phases its comment map named.

    ``flags -> correlation -> identity -> endpoint -> mint_halves ->
    grant_payload -> row``. A phase that refuses raises :class:`PhaseStop`
    carrying the already-rendered exit code; the verb's handler is the one place
    that turns it back into the return value, and the one place that prints.
    """

    def __init__(self, args, *, for_install_id: str, for_device_id: str, note: Any) -> None:
        from agent_runtime import paths

        self.args = args
        self.root = paths.store_root()
        self.for_install_id = for_install_id
        self.for_device_id = for_device_id
        self.note = note
        self.correlation: str | None = None
        self.peer_block: dict[str, Any] | None = None
        self.device_block: dict[str, Any] | None = None
        self.refusals: list[dict[str, str]] = []
        self.first_refusal = None

    def build(self) -> dict[str, Any]:
        """``identity -> endpoint -> mint_halves -> grant_payload -> row``."""

        self.identity()
        self.endpoint()
        self.mint_halves()
        self.grant_payload()
        return self.row()

    def flags(self) -> None:
        if self.for_install_id or self.for_device_id:
            return
        # At least one, never both required: a PHONE has no install id (the
        # device half is all there is to mint for it), and an install being
        # re-introduced after a rebuild may have no account device row yet. The
        # parent plan's "both that apply" is exactly this.
        raise PhaseStop(
            emit_harness_error(
                RuntimeError("no_requester"),
                reason="no_requester",
                args=self.args,
                code="invalid_payload",
                message=(
                    "gateway introduce needs at least one of --for-install (another "
                    "hermes install, which gets the peer half) or --for-device (an "
                    "account device, which gets the device half). With neither there "
                    "is nobody to scope the codes to, and an unscoped code is what "
                    "`harness gateway pair` and `peers pair` already mint."
                ),
            )
        )

    def identity(self) -> None:
        resolved, code_or_error = _install_and_certificate(self.args)
        if resolved is None:
            raise PhaseStop(code_or_error)
        self.install, self.certificate = resolved

    def endpoint(self) -> None:
        self.listener = listener_endpoint(self.root)
        if self.listener["source"] == SOURCE_UNKNOWN:
            raise PhaseStop(
                emit_harness_error(
                    RuntimeError("gateway_listener_off"),
                    reason="gateway_listener_off",
                    args=self.args,
                    code="runtime_unavailable",
                    message=LISTENER_OFF_SENTENCE,
                )
            )
        dial, self.endpoints, failure = _dial_target(self.root, self.listener, args=self.args)
        if failure:
            raise PhaseStop(failure)
        # R-D1: the DIAL host, not ``endpoint["host"]``. This is the line S4's
        # hardware attempt died on — a wildcard bind put ``0.0.0.0`` here, the
        # far install dialled it, and the receipt said ``runtime_unavailable``.
        self.dial_host = dial[0] if dial else None
        self.dial_port = dial[1] if dial else None

    def _payload(self, code_key: str, code: str) -> str:
        """One half's payload. Both halves name the SAME address: one
        introduction is one machine, and two halves that named different
        addresses would be an introduction to two different places."""

        return json.dumps(
            {
                "host": self.dial_host,
                "port": self.dial_port,
                "endpoints": self.endpoints,
                "install_id": self.install.install_id,
                "cert_fingerprint": self.certificate.fingerprint,
                code_key: code,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def mint_halves(self) -> None:
        """Two mints, not one atomic pair — see the verb's docstring."""

        from agent_runtime.serve_gateway_auth import pairing_store_path

        for wanted, mint in (
            (self.for_install_id, self._mint_peer_half),
            (self.for_device_id, self._mint_device_half),
        ):
            if wanted:
                mint()
        if self.first_refusal is not None:
            # The first refusal's family, not a generic one: a pending cap, a
            # lockout and a store this machine cannot write are three different
            # next moves, and the exit code is how a launcher tells them apart
            # without parsing prose. Both halves mint into ``pairing.json`` —
            # one file, one cap, one lockout across the two ceremonies — so one
            # path answers for whichever half refused first.
            raise PhaseStop(
                store_refusal_error(
                    self.first_refusal, args=self.args, store_path=pairing_store_path(self.root)
                )
            )

    def _refused_half(self, half: str, refusal) -> None:
        self.refusals.append({"half": half, "reason": refusal.reason})
        self.first_refusal = self.first_refusal or refusal

    def _mint_peer_half(self) -> None:
        from agent_runtime.gateway_peers import mint_peer_code
        from agent_runtime.serve_gateway_auth import (
            CREDENTIAL_TTL_SECONDS_INTRODUCED,
            StoreRefusal,
        )

        minted = mint_peer_code(
            self.root,
            note=self.note,
            credential_ttl_seconds=CREDENTIAL_TTL_SECONDS_INTRODUCED,
            for_install_id=self.for_install_id,
            correlation=self.correlation,
        )
        if isinstance(minted, StoreRefusal):
            self._refused_half("peer", minted)
            return
        self.peer_block = {
            "peer_code": minted.code,
            "expires_in_seconds": minted.expires_in_seconds(),
            "join_payload": self._payload("peer_code", minted.code),
        }

    def _mint_device_half(self) -> None:
        from agent_runtime.serve_gateway_auth import (
            CREDENTIAL_TTL_SECONDS_INTRODUCED,
            StoreRefusal,
            mint_pairing_code,
        )

        minted = mint_pairing_code(
            self.root,
            name=self.note,
            # ``console`` and not the operator's choice: an introduction is the
            # account saying "this is my own device on my own machine", which is
            # the exact provenance ``DEFAULT_DEVICE_TIER``'s ruling names. A
            # ``--tier`` flag here would be a knob whose only safe setting is
            # the default.
            tier="console",
            credential_ttl_seconds=CREDENTIAL_TTL_SECONDS_INTRODUCED,
            for_device_id=self.for_device_id,
            correlation=self.correlation,
        )
        if isinstance(minted, StoreRefusal):
            self._refused_half("device", minted)
            return
        self.device_block = {
            "code": minted.code,
            "tier": minted.tier,
            "expires_in_seconds": minted.expires_in_seconds(),
            "qr_payload": self._payload("code", minted.code),
        }

    def grant_payload(self) -> None:
        # **One writer of the backend's shape.** The launcher POSTs this object
        # verbatim; building it here rather than letting the launcher assemble it
        # from the envelope's other keys is what keeps "what fulfil receives" a
        # decision this repo made once. Its key set is :data:`GRANT_PAYLOAD_KEYS`.
        self.grant = {
            "peer_join_payload": (self.peer_block or {}).get("join_payload"),
            "device_pair_payload": (self.device_block or {}).get("qr_payload"),
            "install_id": self.install.install_id,
            "endpoints": self.endpoints,
            "cert_fingerprint": self.certificate.fingerprint,
            "correlation": self.correlation,
        }
        size = len(json.dumps(self.grant, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        if size <= GRANT_PAYLOAD_MAX_BYTES:
            return
        # Unreachable at four endpoints and two ~200-byte payloads; asserted
        # anyway because the alternative is discovering the ceiling as an opaque
        # 400 from a service this process cannot see.
        raise PhaseStop(
            emit_harness_error(
                RuntimeError("grant_payload_too_large"),
                reason="grant_payload_too_large",
                args=self.args,
                code="invalid_payload",
                message=(
                    f"the grant payload is {size} bytes and "
                    f"the backend accepts {GRANT_PAYLOAD_MAX_BYTES}. Reduce the "
                    "advertised endpoints (remote_gateway.listen can name one "
                    "interface instead of a wildcard)."
                ),
            )
        )

    def row(self) -> dict[str, Any]:
        from agent_runtime.gateway_capabilities import GATEWAY_CAPABILITIES
        from agent_runtime.serve_gateway_auth import CREDENTIAL_TTL_SECONDS_INTRODUCED

        row = {
            "install_id": self.install.install_id,
            "display_name": self.install.display_name,
            "cert_fingerprint": self.certificate.fingerprint,
            "endpoints": self.endpoints,
            "endpoints_source": self.listener["source"],
            "capabilities": list(GATEWAY_CAPABILITIES),
            "correlation": self.correlation,
            "for_install_id": self.for_install_id or None,
            "for_device_id": self.for_device_id or None,
            "credential_ttl_seconds": CREDENTIAL_TTL_SECONDS_INTRODUCED,
            "peer": self.peer_block,
            "device": self.device_block,
            "grant_payload": self.grant,
        }
        if self.refusals:
            row["refusals"] = self.refusals
        if self.listener["source"] != SOURCE_LIVE:
            row["note_endpoint"] = (
                "no running serve advertised a gateway listener for this root, so "
                "the endpoint in these payloads is what the config says the NEXT "
                "boot will use. The codes are valid either way; a requester that "
                "dials before this root boots simply fails to connect."
            )
        return row
