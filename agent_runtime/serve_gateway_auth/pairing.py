"""The ceremony: mint a pairing code, redeem it for a device credential.

Part of the :mod:`agent_runtime.serve_gateway_auth` layout; the package docstring is the design.
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any

from ..call_authorization import (
    DEVICE_KIND_CHANNEL,
    DEVICE_KIND_DEVICE,
    DEVICE_KINDS,
)
from ..clock import iso_stamp as _iso
from ..gateway_pairing_codes import (
    KIND_DEVICE,
    MAX_PENDING_CODES,
    expire_pending,
    lockout_remaining,
    match_pending,
    mint_into,
    note_failed_redeem,
    pending_codes,
    supersede_pending,
)
from ..gateway_channel import clean_bound_instances
from ..hello_address import HELLO_MACHINE_MISMATCH, HELLO_NAMESPACE_MISMATCH, clean_machine_id, own_namespace
from ..store_file_io import HarnessLockUnavailable
from ..store_file_io import os_error_reason as _os_reason
from .proof import device_verifier
from .records import (
    DEFAULT_DEVICE_TIER,
    DEVICE_TOKEN_BYTES,
    REVOKED_SUPERSEDED,
    DeviceCredential,
    PairingCode,
    StoreRefusal,
)
from .store import clean_name, decode_client_scope, decode_device, read_devices, read_pairing, store_lock, write_devices, write_pairing

__layer__ = "stores"


def mint_pairing_code(
    store_root: Path | str,
    *,
    name: str | None = None,
    credential_ttl_seconds: int | None = None,
    for_device_id: str | None = None,
    for_machine_id: str | None = None,
    correlation: str | None = None,
    kind: str = DEVICE_KIND_DEVICE,
    bound_instances: Any = (),
    client_scope: str | None = None,
    now: float | None = None,
) -> PairingCode | StoreRefusal:
    """Mint a short-TTL pairing code. The plaintext is returned, never stored.

    Refuses (rather than queues) when the install is locked out after repeated
    failed redeems, or when :data:`MAX_PENDING_CODES` are already outstanding.
    Both refusals are typed so the CLI verb can tell the operator which it was —
    "wait out the lockout" and "redeem or expire the codes you already made" are
    different next moves.

    Every code pairs at ``console``, the one level a device holds: there is no tier to choose
    (hermes row RT-FU-HERMES-PAIRS-A-DEVICE-ONLY-AT-FULL-CONTROL-WITH-NO-VIEW-ONLY-LEVEL).
    """

    tier = DEFAULT_DEVICE_TIER
    bound = clean_bound_instances(list(bound_instances or ()))
    refusal = _channel_mint_refusal(kind, bound) or _client_scope_refusal(kind, client_scope)
    if refusal is not None:
        return refusal
    stamp = now if now is not None else time.time()
    requester = clean_name(for_device_id) or None
    try:
        with store_lock(store_root):
            state = read_pairing(store_root)
            expire_pending(state, now=stamp)
            # R-D5, the device half. Same ruling and same ordering as
            # ``gateway_peers.mint_peer_code``: before the cap is counted, so a
            # launcher's retry for one device finds the cap where it started
            # instead of being refused by its own previous attempt. Scoped to a
            # named ``--for-device`` only — an unscoped ``harness gateway pair``
            # supersedes nothing, because there is no requester to attribute the
            # earlier code to and dropping a stranger's invitation on a mint
            # nobody asked for would be the cap working backwards.
            if requester:
                supersede_pending(
                    state, kind=KIND_DEVICE, field="for_device_id", value=requester
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
                    f"(max {MAX_PENDING_CODES}); redeem or wait for them to expire",
                )
            # The three ``introduce`` keys ride ``extra`` rather than growing
            # the pending entry's schema, which is exactly what ``mint_into``'s
            # merge-UNDER-the-fixed-keys contract is for: a caller cannot
            # overwrite the kind, the salt or the digest, and a caller that
            # passes none of them mints the byte-identical entry a pre-S2 build
            # did. ``for_device_id`` is a LABEL carried to the row (R-S2-4) and
            # ``correlation`` is the grant id, kept so the redeem-time event can
            # name the errand — never a row field, never a secret.
            code, request_id, expires_at = mint_into(
                state,
                kind=KIND_DEVICE,
                extra={
                    "tier": tier,
                    "name": clean_name(name) or None,
                    "credential_ttl_seconds": (
                        int(credential_ttl_seconds)
                        if credential_ttl_seconds
                        else None
                    ),
                    "for_device_id": requester,
                    # The machine the requester's account record names (``introduce --for-machine``):
                    # the redeeming hello must name it, and the row it mints is bound to it.
                    **({"for_machine_id": clean_machine_id(for_machine_id)} if clean_machine_id(for_machine_id) else {}),
                    "correlation": clean_name(correlation) or None,
                    # Absent on a plain device code, so its pending entry is byte-identical.
                    # ``device_kind``, never ``kind``: the pending entry's ``kind`` is the
                    # ceremony's (device | peer) and ``mint_into`` keeps it over ``extra``.
                    **({"device_kind": kind, "bound_instances": list(bound)} if kind == DEVICE_KIND_CHANNEL else {}),
                    **({"client_scope": client_scope} if kind == DEVICE_KIND_CHANNEL and client_scope else {}),
                },
                now=stamp,
            )
            write_pairing(store_root, state)
            return PairingCode(
                code=code,
                request_id=request_id,
                tier=tier,
                name=clean_name(name) or None,
                expires_at=expires_at,
            )
    except (OSError, HarnessLockUnavailable) as exc:
        return StoreRefusal(_os_reason(exc), str(exc))


def redeem_pairing_code(
    store_root: Path | str,
    code: str,
    *,
    device_name: str | None = None,
    machine_id: str | None = None, namespace: str | None = None, now: float | None = None,
) -> DeviceCredential | StoreRefusal:
    """Turn a code into a paired device. The token is returned ONCE, here.

    The lockout is checked BEFORE the pending lookup, which is the correction
    ``gateway/pairing.py`` had to make (#10195): checking it after would let a
    code that was already issued be redeemed while the lockout was armed, so the
    lockout would gate minting and not guessing — i.e. gate nothing.

    A successful redemption RESETS the failure streak. Without that, isolated
    mistyped codes accumulate for the life of the store and eventually trip a
    lockout on one fresh typo — the same defect, and the same fix, as the module
    this discipline comes from.
    """

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
            found = match_pending(state, candidate, kind=KIND_DEVICE)
            if found is None:
                note_failed_redeem(state, now=stamp)
                write_pairing(store_root, state)
                return StoreRefusal(
                    "invalid_code", "no pending pairing code matches (or it expired)"
                )
            matched_id, matched = found
            bound_machine, address = _bound_machine(matched, machine_id, namespace)
            if address is not None:
                return _address_refused(store_root, state, address, stamp, matched=matched, machine_id=machine_id)
            _spend(store_root, state, matched_id)

            token = secrets.token_hex(DEVICE_TOKEN_BYTES)
            device_id = f"dev_{secrets.token_hex(8)}"
            name = (
                clean_name(device_name)
                or clean_name(matched.get("name"))
                or device_id
            )
            # ``console`` whatever the pending entry says: a device holds one level, and the
            # entry's ``tier`` is not read.
            tier = DEFAULT_DEVICE_TIER
            ttl = matched.get("credential_ttl_seconds")
            try:
                ttl_seconds = int(ttl) if ttl else 0
            except (TypeError, ValueError):
                ttl_seconds = 0
            rows = read_devices(store_root)
            account_device_id = clean_name(matched.get("for_device_id")) or None
            # RL-23. One live row per account device, decided HERE because this
            # is the only moment the store learns that a far launcher has a NEW
            # credential — and therefore the only moment its old ones are
            # provably superfluous. Before this, a launcher re-pairing on a
            # backoff minted a row per attempt and revoked none: five live rows
            # on this machine for one Mac, fourteen on the Mac for this one.
            #
            # Scoped by ``account_device_id`` and skipped when it is absent: an
            # unlabelled row (every manual ``harness gateway pair`` — a phone has
            # no id until it redeems) is attributable to nobody, so treating the
            # absent label as a key would collapse every such device into one and
            # let each redeem unpair all the others.
            #
            # In the SAME write as the new row, so no reader ever observes two
            # live credentials for one device; and a revocation, not a delete,
            # because revocation has always kept its row — that is what lets an
            # audit tell "superseded on the 5th" from "never paired".
            if account_device_id:
                for prior in rows.values():
                    if not isinstance(prior, dict) or prior.get("revoked"):
                        continue
                    if prior.get("account_device_id") != account_device_id:
                        continue
                    prior["revoked"] = True
                    prior["revoked_at"] = _iso(stamp)
                    # Additive, and the pair is the point: the WORD says an
                    # operator did not do this, and the ID says which credential
                    # replaced it. A revoked row that explains itself is the
                    # difference between a history and five mysteries.
                    prior["revoked_reason"] = REVOKED_SUPERSEDED
                    prior["superseded_by"] = device_id
            rows[device_id] = {
                "device_id": device_id,
                "name": name,
                "tier": tier,
                "verifier": device_verifier(token),
                "created_at": _iso(stamp),
                "last_seen": None,
                "revoked": False,
                "revoked_at": None,
                # Computed at REDEEM and not at mint: the clock that matters is
                # when the credential started existing, and a code minted ten
                # minutes before it is spent should not lose ten minutes of its
                # thirty days. ``None`` when the mint named no TTL, which is
                # every manual ``harness gateway pair``.
                "expires_at": _iso(stamp + ttl_seconds) if ttl_seconds else None,
                # The account's own device id, copied through from the pending
                # entry. A label — see :class:`DeviceRecord` — and the join key
                # the launcher's sheet and S3's Unpair relate this row by.
                "account_device_id": clean_name(matched.get("for_device_id")) or None,
                **_kind_fields(matched, bound_machine),
            }
            write_devices(store_root, rows)
            return _issued(device_id, token, tier, name, rows[device_id])
    except (OSError, HarnessLockUnavailable) as exc:
        return StoreRefusal(_os_reason(exc), str(exc))


# ── internals ────────────────────────────────────────────────────────────────

def _address_refused(
    store_root: Path | str, state: dict[str, Any], address: str, stamp: float,
    *, matched: dict[str, Any], machine_id: Any,
) -> StoreRefusal:
    """Machine first, then the namespace: a code redeemed from another machine than the one it was
    minted for, from a device that names none, or from another namespace mints nothing. The code stays
    pending for the device it was meant for.

    The attempt charges the lockout unless it comes from a device the account record names: a code
    minted with both ``for_device_id`` and ``for_machine_id`` (``introduce`` writes them from the
    requester's account record) and a hello from that very machine. Only a namespace refusal can
    reach that path, and it is spared (owner 2026-11-26: failed hellos from a device your account
    already confirmed do not count toward the five-failure lockout). A machine refusal, a code with
    no device or no machine named (every manual ``harness gateway pair``) still charge."""

    if not _from_account_named_device(matched, machine_id):
        note_failed_redeem(state, now=stamp)
    write_pairing(store_root, state)
    return StoreRefusal(address, "the redeeming device is not the one this code was minted for")


def _from_account_named_device(matched: dict[str, Any], machine_id: Any) -> bool:
    """True when the code was minted for a device and machine the account record names, and the
    hello comes from that machine."""

    scoped = clean_machine_id(matched.get("for_machine_id"))
    return bool(clean_name(matched.get("for_device_id")) and scoped and clean_machine_id(machine_id) == scoped)


def _spend(store_root: Path | str, state: dict[str, Any], matched_id: str) -> None:
    """The code is spent: deleted before the token is minted, and the failure streak cleared."""

    del pending_codes(state)[matched_id]
    state["failed_redeems"] = 0
    state["locked_until"] = 0.0
    write_pairing(store_root, state)


def _bound_machine(matched: dict[str, Any], machine_id: Any, namespace: Any) -> tuple[str | None, str | None]:
    """``(machine id the minted row is bound to, refusal word)``, in address order.

    The minted row carries the value (MUTATION: drop it in ``_kind_fields`` and
    test_introduce_for_machine_binds_the_redeemed_row finds a row with no machine id).
    A code scoped ``--for-machine`` binds to that machine and refuses a hello naming another; an
    unscoped code (``harness gateway pair``, minted by the operator at this machine) binds to the
    machine its redeeming hello names. Then the hello's namespace must be this serve's own. A channel
    is the owner's external gateway, no device of yours: it proves no machine and is not checked.
    """

    if matched.get("device_kind") == DEVICE_KIND_CHANNEL:
        return None, None
    named = clean_machine_id(machine_id)
    scoped = clean_machine_id(matched.get("for_machine_id"))
    if named is None or (scoped is not None and scoped != named):
        return None, HELLO_MACHINE_MISMATCH
    if namespace != own_namespace():
        return None, HELLO_NAMESPACE_MISMATCH
    return named, None


def _channel_mint_refusal(kind: str, bound: tuple[str, ...]) -> StoreRefusal | None:
    """A channel code needs one bound instance (it holds ``console``, as every code does)."""

    if kind not in DEVICE_KINDS:
        return StoreRefusal("invalid_kind", f"kind must be one of {', '.join(DEVICE_KINDS)}; got {kind!r}")
    if kind != DEVICE_KIND_CHANNEL:
        return None if not bound else StoreRefusal(
            "invalid_bound_instances", "only a channel credential is bound to persona instances")
    if not bound:
        return StoreRefusal("bound_instances_required", "a channel credential must be bound to a persona instance")
    return None


def _client_scope_refusal(kind: str, value: str | None) -> StoreRefusal | None:
    """Only a channel carries an account namespace, and only the launcher's 64-hex digest form."""

    from ..conversation_owner import ConversationOwnerError, client_scope

    if value is None:
        return None
    if kind != DEVICE_KIND_CHANNEL:
        return StoreRefusal("invalid_client_scope", "only a channel credential carries a client scope")
    try:
        client_scope(value)
    except ConversationOwnerError:
        return StoreRefusal("invalid_client_scope", "client_scope must be the 64-character lowercase hex digest")
    return None


def _issued(device_id: str, token: str, tier: str, name: str, row: dict[str, Any]) -> DeviceCredential:
    record = decode_device(row)
    return DeviceCredential(
        device_id=device_id, token=token, tier=tier, name=name,
        kind=record.kind if record else DEVICE_KIND_DEVICE,
        bound_instances=record.bound_instances if record else (),
        machine_id=record.machine_id if record else None,
    )


def _kind_fields(matched: dict[str, Any], machine_id: str | None) -> dict[str, Any]:
    # A device's machine (``_bound_machine``), or a channel's kind and binding copied through from the
    # pending entry; absent → ``device``.

    if matched.get("device_kind") != DEVICE_KIND_CHANNEL:
        return {"machine_id": machine_id} if machine_id else {}
    scope = decode_client_scope(matched.get("client_scope"))
    return {"kind": DEVICE_KIND_CHANNEL, "bound_instances": list(clean_bound_instances(matched.get("bound_instances"))),
            **({"client_scope": scope} if scope else {})}
