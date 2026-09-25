"""The two-operator pairing ceremony over ``pairing.json`` (R5).

``mint_peer_code`` (install A's operator) and ``redeem_peer_code`` (A's
listener, when B's operator joins). The row write is ``trust_store``'s.
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any

from ..gateway_identity import clean_display_name
from ..gateway_pairing_codes import (
    KIND_PEER,
    MAX_PENDING_CODES,
    expire_pending,
    lockout_remaining,
    match_pending,
    mint_into,
    note_failed_redeem,
    pending_codes,
    supersede_pending,
)
from ..serve_gateway_auth import StoreRefusal, read_pairing, store_lock, write_pairing
from ..store_file_io import HarnessLockUnavailable
from ..store_file_io import iso_stamp as _iso
from ..store_file_io import os_error_reason as _os_reason
from .cache import _clear_revoked_you
from .models import (
    PEER_EVENT_RECORDED,
    PEER_SECRET_BYTES,
    PeerCredential,
    PeerPairingCode,
    _clean_fingerprint,
    clean_endpoints,
)
from .trust_store import _emit_peer_event, _note_write, _read_peers, _write_peers, peer_row

__layer__ = "lanes"


def mint_peer_code(
    store_root: Path | str,
    *,
    note: str | None = None,
    credential_ttl_seconds: int | None = None,
    for_install_id: str | None = None,
    correlation: str | None = None,
    now: float | None = None,
) -> PeerPairingCode | StoreRefusal:
    """Mint a short-TTL PEER code. The plaintext is returned, never stored.

    Shares ``pairing.json``'s pending map, cap and lockout with the device
    ceremony — see ``gateway_pairing_codes`` for why the rate-limiting state is
    one and the credentials are two. The entry is stamped
    :data:`~agent_runtime.gateway_pairing_codes.KIND_PEER`, so this code cannot
    be spent on the device hello and a device code cannot be spent on the peer
    one.

    No ``tier`` argument, deliberately: a peer holds an allowlist, not a tier.
    See :class:`PeerPairingCode`.
    """

    stamp = now if now is not None else time.time()
    requester = str(for_install_id or "").strip()[:128] or None
    try:
        with store_lock(store_root):
            state = read_pairing(store_root)
            expire_pending(state, now=stamp)
            # R-D5, and it runs BEFORE the cap is counted rather than after —
            # that ordering IS the ruling. A launcher retrying one stalled edge
            # has to find the cap where it started, or its second attempt is
            # refused by the codes its first attempt minted.
            if requester:
                supersede_pending(
                    state, kind=KIND_PEER, field="for_install_id", value=requester
                )
            locked = lockout_remaining(state, now=stamp)
            if locked:
                return StoreRefusal(
                    "locked_out",
                    f"too many failed pairing attempts; retry in {locked}s",
                )
            pending = pending_codes(state)
            if len(pending) >= MAX_PENDING_CODES:
                return StoreRefusal(
                    "too_many_pending",
                    f"{len(pending)} pairing codes are already outstanding "
                    f"(max {MAX_PENDING_CODES}, counted across device and peer "
                    "codes alike); redeem or wait for them to expire",
                )
            cleaned = clean_display_name(note) or None
            # Three ``introduce`` keys on the pending entry, merged UNDER the
            # fixed ones (``mint_into``'s contract), so a caller that passes
            # none of them mints the byte-identical entry a pre-S2 build did.
            #
            # ``for_install_id`` is the one that is genuinely CHECKED — see
            # :func:`redeem_peer_code`. The peer half can be scoped because the
            # join hello names the redeemer's own install id; the device half
            # cannot, and its label says so out loud rather than looking like a
            # check that never fires (R-S2-4).
            code, request_id, expires_at = mint_into(
                state,
                kind=KIND_PEER,
                extra={
                    "note": cleaned,
                    "credential_ttl_seconds": (
                        int(credential_ttl_seconds) if credential_ttl_seconds else None
                    ),
                    "for_install_id": requester,
                    "correlation": str(correlation or "").strip()[:64] or None,
                },
                now=stamp,
            )
            write_pairing(store_root, state)
            return PeerPairingCode(
                code=code, request_id=request_id, note=cleaned, expires_at=expires_at
            )
    except (OSError, HarnessLockUnavailable) as exc:
        return StoreRefusal(_os_reason(exc), str(exc))


def redeem_peer_code(
    store_root: Path | str,
    code: str,
    *,
    peer_install_id: str,
    display_name: Any = None,
    endpoints: Any = None,
    cert_fingerprint: Any = None,
    now: float | None = None,
) -> PeerCredential | StoreRefusal:
    """Turn a peer code into an edge. The secret is returned ONCE, here.

    Run on install A — the side that minted the code — when install B dials in
    with it. A writes B's row and hands the secret back on the one ``hello_ok``
    that carries it; B writes A's row from that frame with :func:`record_peer`.

    The lockout is checked BEFORE the pending lookup, which is the correction
    ``gateway/pairing.py`` had to make (#10195), and a successful redemption
    RESETS the failure streak. Both rules are the shared discipline's; see
    ``gateway_pairing_codes``.

    **A re-pair of an install already in the store REPLACES its row**, secret
    and all, rather than being refused. That is the operator's own move — they
    minted a fresh code and ran ``join`` on the other machine — and refusing it
    would mean an install that was rebuilt, or whose secret was lost, could
    never be re-paired without an operator hand-editing JSON. What is NOT
    replaced is the id: an install keeps the ``install_id`` it minted at Stage
    0, so a re-pair updates an edge rather than creating a second one.
    """

    peer_install_id = str(peer_install_id or "").strip()
    if not peer_install_id or len(peer_install_id) > 128:
        return StoreRefusal(
            "invalid_peer_id", "the joining install named no usable install id"
        )
    stamp = now if now is not None else time.time()
    candidate = str(code or "").strip().upper()
    if not candidate:
        return StoreRefusal("invalid_code", "a pairing code is required")
    try:
        with store_lock(store_root):
            state = read_pairing(store_root)
            expire_pending(state, now=stamp)
            locked = lockout_remaining(state, now=stamp)
            if locked:
                write_pairing(store_root, state)
                return StoreRefusal(
                    "locked_out",
                    f"too many failed pairing attempts; retry in {locked}s",
                )
            found = match_pending(state, candidate, kind=KIND_PEER)
            if found is None:
                note_failed_redeem(state, now=stamp)
                write_pairing(store_root, state)
                return StoreRefusal(
                    "invalid_code", "no pending peer code matches (or it expired)"
                )
            matched_id, matched = found

            # **The scoping check (R-S2-4), and it is a real one.** A code is a
            # bearer for its ten minutes; an ``introduce`` that named the
            # install it was minted FOR turns it into a bearer only that install
            # can spend, because the join hello has to name the redeemer's own
            # id in the same frame. A mismatch is refused as ``invalid_code``
            # and CHARGES a failure — the same answer, and the same cost, as a
            # code that does not exist — so the wrong install cannot use the
            # difference between "not for you" and "no such code" to learn that
            # a pairing is in flight.
            #
            # The pending entry is left ALONE on this path: the code was not
            # spent, so the operator's own install can still redeem it inside
            # the window rather than having to re-run the ceremony because
            # somebody else guessed at it.
            wanted_install = str(matched.get("for_install_id") or "").strip()
            if wanted_install and wanted_install != peer_install_id:
                note_failed_redeem(state, now=stamp)
                write_pairing(store_root, state)
                return StoreRefusal(
                    "invalid_code", "no pending peer code matches (or it expired)"
                )

            del pending_codes(state)[matched_id]
            state["failed_redeems"] = 0
            state["locked_until"] = 0.0
            write_pairing(store_root, state)

            ttl = matched.get("credential_ttl_seconds")
            try:
                ttl_seconds = int(ttl) if ttl else 0
            except (TypeError, ValueError):
                ttl_seconds = 0
            # Computed at REDEEM, not at mint: the credential starts existing
            # now, and the code's own window should not be charged against it.
            expires_at = _iso(stamp + ttl_seconds) if ttl_seconds else None

            secret = secrets.token_hex(PEER_SECRET_BYTES)
            name = clean_display_name(display_name) or peer_install_id
            rows = _read_peers(store_root)
            rows[peer_install_id] = peer_row(
                peer_install_id=peer_install_id,
                display_name=name,
                endpoints=clean_endpoints(endpoints),
                cert_fingerprint=_clean_fingerprint(cert_fingerprint),
                secret=secret,
                stamp=stamp,
                expires_at=expires_at,
            )
            _write_peers(store_root, rows)
            _note_write(store_root)
            _emit_peer_event(
                PEER_EVENT_RECORDED,
                {
                    "peer_install_id": peer_install_id,
                    # ``introduce`` when the code was scoped and correlated, else
                    # the manual ``pair`` ceremony. Derived from the pending
                    # entry rather than passed in, so the word cannot disagree
                    # with what actually minted the code.
                    "source": "introduce" if matched.get("correlation") else "pair",
                    **(
                        {"grant_id": str(matched["correlation"])}
                        if matched.get("correlation")
                        else {}
                    ),
                },
                store_root=store_root,
            )
            credential = PeerCredential(
                peer_install_id=peer_install_id,
                secret=secret,
                display_name=name,
                expires_at=expires_at,
            )
    except (OSError, HarnessLockUnavailable) as exc:
        return StoreRefusal(_os_reason(exc), str(exc))
    # Cleared AFTER the lock closed, which is why the credential is captured
    # above and returned below rather than returned from inside the block.
    # :func:`_clear_revoked_you` writes through :func:`_touch_cache`, which takes
    # this root's lock for itself, and ``store_lock`` is not reentrant: called
    # from inside the block it spent the whole ten-second budget contending with
    # the write it was describing, so the re-pair stalled the join handshake for
    # a flag it might then fail to clear. :func:`record_peer` always cleared out
    # here; both credential writers now do.
    _clear_revoked_you(store_root, peer_install_id, now=stamp)
    return credential
