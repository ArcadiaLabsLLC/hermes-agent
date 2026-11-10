"""The paired-device rows: list, look up, verify a hello's proof, note seen, revoke, prune.

Part of the :mod:`agent_runtime.serve_gateway_auth` layout; the package docstring is the design.
"""

from __future__ import annotations

import hmac
import time
from pathlib import Path
from typing import Any

from ..clock import iso_stamp as _iso
from ..clock import stamp_passed as _stamp_passed
from ..store_file_io import HarnessLockUnavailable
from ..store_file_io import os_error_reason as _os_reason
from .proof import proof_from_verifier
from .records import (
    AUTH_BAD_PROOF,
    AUTH_EXPIRED,
    AUTH_MALFORMED,
    AUTH_OK,
    AUTH_REVOKED,
    AUTH_UNKNOWN_DEVICE,
    REVOKED_ROW_RETENTION_SECONDS,
    DeviceAuth,
    DeviceRecord,
    StoreRefusal,
)
from .store import decode_device, read_devices, store_lock, write_devices

__layer__ = "stores"


# ── device store: reads ──────────────────────────────────────────────────────


def list_devices(store_root: Path | str) -> list[DeviceRecord]:
    """Every paired device, revoked ones included, oldest first.

    Revoked rows are KEPT and shown. A revocation that deleted the row would
    make "this device was never paired" and "this device was thrown out" the
    same answer, and the second one is the one an operator auditing a lost phone
    needs. It also keeps the device id from being re-minted onto a different
    device, which would make a stale log line name the wrong hardware.
    """

    rows = read_devices(store_root)
    records = [record for record in (decode_device(row) for row in rows.values()) if record]
    records.sort(key=lambda record: (record.created_at, record.device_id))
    return records


def lookup_device(store_root: Path | str, device_id: str) -> DeviceRecord | None:
    """One device by id, or ``None``. Never raises; never returns a secret."""

    device_id = str(device_id or "").strip()
    if not device_id:
        return None
    row = read_devices(store_root).get(device_id)
    return decode_device(row) if isinstance(row, dict) else None


def verify_device_proof(
    store_root: Path | str,
    device_id: Any,
    presented: Any,
    nonce: str,
    *,
    port: int,
) -> DeviceAuth:
    """Constant-time check of a device hello's proof. Fails CLOSED, always.

    Every missing input is a refusal rather than a degrade: no store, an unknown
    id, a revoked row, an empty nonce, a non-string proof. "Nothing configured,
    let everyone in" is the failure mode that turns a hardening into a bypass,
    and this function is reachable by an unauthenticated peer on a listener that
    is bound beyond loopback.

    The outcomes are DISTINGUISHED here and deliberately COLLAPSED on the wire:
    the socket lane answers every one of them with the same typed rejection, so
    a peer cannot use the reason to learn whether a device id exists. The
    distinction is for the runtime's own log and for the rate limiter, which
    charges a bad proof and an unknown device alike.
    """

    device_id = str(device_id or "").strip()
    if not device_id or len(device_id) > 128:
        return DeviceAuth(outcome=AUTH_MALFORMED)
    if not isinstance(presented, str) or not presented.strip():
        return DeviceAuth(outcome=AUTH_MALFORMED, device_id=device_id)
    if not nonce:
        return DeviceAuth(outcome=AUTH_MALFORMED, device_id=device_id)
    row = read_devices(store_root).get(device_id)
    if not isinstance(row, dict):
        return DeviceAuth(outcome=AUTH_UNKNOWN_DEVICE, device_id=device_id)
    record = decode_device(row)
    if record is None:
        return DeviceAuth(outcome=AUTH_UNKNOWN_DEVICE, device_id=device_id)
    verifier = str(row.get("verifier") or "").strip()
    if not verifier:
        return DeviceAuth(outcome=AUTH_UNKNOWN_DEVICE, device_id=device_id)
    expected = proof_from_verifier(verifier, nonce, port=port, device_id=device_id)
    # BYTES, never str: ``hmac.compare_digest`` RAISES TypeError when either str
    # operand is non-ASCII, and ``presented`` is attacker-controlled on a path
    # no credential is needed to reach. One accented character used to unwind
    # out of the loopback handshake entirely (``serve_socket.verify_hello_proof``
    # carries the same note and the same fix); encoding first makes a hostile
    # proof merely wrong.
    if not hmac.compare_digest(
        presented.strip().lower().encode("utf-8", "replace"), expected.encode("ascii")
    ):
        return DeviceAuth(outcome=AUTH_BAD_PROOF, device_id=device_id)
    # Revocation is checked AFTER the proof on purpose. Checking it first would
    # let an unauthenticated peer probe which device ids are revoked (and, by
    # difference, which are live) without holding any credential at all. A
    # revoked device that still holds its token learns it is revoked; nobody
    # else learns anything.
    if record.revoked:
        return DeviceAuth(outcome=AUTH_REVOKED, device_id=device_id, record=record)
    # Expiry sits in the SAME place as revocation and for the same reason: after
    # the proof. Checking a stamp before the HMAC would let an unauthenticated
    # peer sweep device ids and learn which ones have lapsed — and, by
    # difference, which are live — while holding nothing. It also keeps the two
    # end-of-life conditions answering in one order everywhere: a revoked AND
    # expired row reports ``device_revoked``, because that is the decision an
    # operator made rather than a clock running out.
    if record.expired:
        return DeviceAuth(outcome=AUTH_EXPIRED, device_id=device_id, record=record)
    return DeviceAuth(outcome=AUTH_OK, device_id=device_id, record=record)


# ── device store: writes ─────────────────────────────────────────────────────


def note_device_seen(
    store_root: Path | str, device_id: str, *, now: float | None = None
) -> None:
    """Stamp ``last_seen``. Best effort, and never in the handshake's way.

    Bookkeeping must not be the thing that fails an authentication: every error
    is swallowed, because a device whose proof verified has authenticated
    whether or not this write lands.
    """

    device_id = str(device_id or "").strip()
    if not device_id:
        return
    stamp = _iso(now)
    try:
        with store_lock(store_root):
            rows = read_devices(store_root)
            row = rows.get(device_id)
            if not isinstance(row, dict):
                return
            row["last_seen"] = stamp
            write_devices(store_root, rows)
    except Exception:
        return


def revoke_device(
    store_root: Path | str, device_id: str, *, now: float | None = None
) -> DeviceRecord | StoreRefusal:
    """Mark a device revoked. Idempotent; the row is kept (see :func:`list_devices`)."""

    device_id = str(device_id or "").strip()
    if not device_id:
        return StoreRefusal("invalid_device_id", "a device id is required")
    try:
        with store_lock(store_root):
            rows = read_devices(store_root)
            row = rows.get(device_id)
            if not isinstance(row, dict):
                return StoreRefusal(
                    "unknown_device", f"no device {device_id!r} is paired with this root"
                )
            if not row.get("revoked"):
                row["revoked"] = True
                row["revoked_at"] = _iso(now)
                write_devices(store_root, rows)
            record = decode_device(row)
            if record is None:  # pragma: no cover - a row we just wrote
                return StoreRefusal("store_corrupt", "the device row will not decode")
            return record
    except (OSError, HarnessLockUnavailable) as exc:
        return StoreRefusal(_os_reason(exc), str(exc))


def prune_revoked_devices(
    store_root: Path | str,
    *,
    retention_seconds: int = REVOKED_ROW_RETENTION_SECONDS,
    now: float | None = None,
) -> dict[str, Any]:
    """Delete revoked rows whose ``revoked_at`` is older than the retention.

    The floor under RL-23's supersession, and it is needed because that rule
    turns every re-pair into a kept row: without a floor, a launcher that
    re-pairs on a backoff writes a permanent line per attempt. Called once at
    serve boot, beside the ``serve_instances`` prunes and for the same reason
    they run there — a boot is a WRITE moment, and a read must not destroy the
    evidence it reports.

    Three things it will not do, each a fail-safe direction rather than an
    optimisation:

    * **A live row is never a candidate**, at any age. Age is not a revocation;
      a credential nobody threw out is one somebody is still using.
    * **An unreadable ``revoked_at`` is kept.** ``stamp_passed`` reads a stamp it
      cannot parse as "not yet", and this call inherits that — a clock this build
      cannot read must not authorise a delete.
    * **It never raises.** A bookkeeping sweep that could fail a boot would be a
      worse defect than the growth it exists to bound.
    """

    stamp = now if now is not None else time.time()
    cutoff = stamp - max(0, int(retention_seconds))
    deleted: list[str] = []
    try:
        with store_lock(store_root):
            rows = read_devices(store_root)
            for device_id, row in list(rows.items()):
                if not isinstance(row, dict) or not row.get("revoked"):
                    continue
                if not _stamp_passed(row.get("revoked_at"), now=cutoff):
                    continue
                del rows[device_id]
                deleted.append(str(device_id))
            if deleted:
                write_devices(store_root, rows)
            return {
                "deleted": deleted,
                "deleted_count": len(deleted),
                "kept_count": len(rows),
            }
    except (OSError, HarnessLockUnavailable) as exc:
        return {
            "deleted": [],
            "deleted_count": 0,
            "kept_count": 0,
            "error": _os_reason(exc),
        }
