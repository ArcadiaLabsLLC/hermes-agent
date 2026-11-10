"""The two gateway credential files: their paths, decode, read, write and the store lock.

Part of the :mod:`agent_runtime.serve_gateway_auth` layout; the package docstring is the design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..call_authorization import (
    DEVICE_KIND_CHANNEL,
    DEVICE_KIND_DEVICE,
    DEVICE_KINDS,
    TIER_READ,
    TIERS,
)
from ..gateway_channel import clean_bound_instances
from ..paths import gateway_dir
from ..store_file_io import read_json_object as _read_json
from ..store_file_io import store_lock as _file_lock
from ..store_file_io import write_secure_json as _write_secure
from .records import DEVICE_STORE_CONTRACT, DEVICE_STORE_FILENAME, PAIRING_STORE_FILENAME, DeviceRecord

__layer__ = "stores"


# ── paths ────────────────────────────────────────────────────────────────────


def device_store_path(store_root: Path | str) -> Path:
    return gateway_dir(store_root) / DEVICE_STORE_FILENAME


def pairing_store_path(store_root: Path | str) -> Path:
    return gateway_dir(store_root) / PAIRING_STORE_FILENAME


def decode_client_scope(value: Any) -> str | None:
    from ..conversation_owner import ConversationOwnerError, client_scope

    try:
        return client_scope(value)
    except ConversationOwnerError:
        return None


def clean_name(value: Any) -> str:
    """Printable, single-line, bounded — the rule ``gateway_identity`` states.

    Not imported from there: that one is capped for a GREETING FRAME's budget
    and this one names a row in a device list. The rule happens to be the same
    today; tying them would mean a change to one silently retunes the other.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    text = "".join(ch for ch in text if ch.isprintable())
    return " ".join(text.split())[:64].strip()


def decode_device(row: Any) -> DeviceRecord | None:
    if not isinstance(row, dict):
        return None
    device_id = str(row.get("device_id") or "").strip()
    if not device_id:
        return None
    tier = str(row.get("tier") or "").strip()
    # A row whose tier this build does not know is read as the LEAST privileged
    # tier, never as the default. The alternative — treating an unrecognised
    # word as ``console`` because that is the common case — is how a typo or a
    # downgrade widens a door silently.
    tier = tier if tier in TIERS else TIER_READ
    return DeviceRecord(
        device_id=device_id,
        name=str(row.get("name") or device_id),
        tier=tier,
        created_at=str(row.get("created_at") or ""),
        last_seen=(str(row["last_seen"]) if row.get("last_seen") else None),
        revoked=bool(row.get("revoked")),
        revoked_at=(str(row["revoked_at"]) if row.get("revoked_at") else None),
        # Absent reads as ``None`` — "never expires" — so every row written by a
        # build that predates S2 keeps working exactly as it did. That is the
        # whole migration: there is no rewrite pass and no contract bump,
        # because the only new fact has a legal absent value.
        expires_at=(str(row["expires_at"]) if row.get("expires_at") else None),
        account_device_id=(
            str(row["account_device_id"]) if row.get("account_device_id") else None
        ),
        # Both absent on every row written before RL-23, and absent reads as
        # "nobody said" — the same migration story ``expires_at`` has: a new
        # fact with a legal empty value needs no rewrite pass and no contract
        # bump.
        revoked_reason=(
            str(row["revoked_reason"]) if row.get("revoked_reason") else None
        ),
        superseded_by=(str(row["superseded_by"]) if row.get("superseded_by") else None),
        # Absent reads ``device`` (every row before the rule); a word this build does not know
        # reads ``channel`` — the NARROWER kind — for the unknown-tier rule's reason.
        kind=_decode_kind(row.get("kind")),
        bound_instances=clean_bound_instances(row.get("bound_instances")),
        client_scope=decode_client_scope(row.get("client_scope")),
    )


def _decode_kind(value: Any) -> str:
    if value in (None, ""):
        return DEVICE_KIND_DEVICE
    return value if value in DEVICE_KINDS else DEVICE_KIND_CHANNEL


def read_devices(store_root: Path | str) -> dict[str, Any]:
    payload = _read_json(device_store_path(store_root))
    rows = payload.get("devices")
    return dict(rows) if isinstance(rows, dict) else {}


def write_devices(store_root: Path | str, rows: dict[str, Any]) -> None:
    _write_secure(
        device_store_path(store_root),
        {"contract": DEVICE_STORE_CONTRACT, "devices": rows},
    )


def read_pairing(store_root: Path | str) -> dict[str, Any]:
    payload = _read_json(pairing_store_path(store_root))
    payload.setdefault("pending", {})
    if not isinstance(payload["pending"], dict):
        payload["pending"] = {}
    return payload


def write_pairing(store_root: Path | str, state: dict[str, Any]) -> None:
    state["contract"] = DEVICE_STORE_CONTRACT
    _write_secure(pairing_store_path(store_root), state)


# The bodies live in ``store_file_io`` (one authority) — the JSON read, the
# atomic 0600 write, the cross-process lock, the UTC stamp and the ACL
# narrowing, including the "this IS the transport slice that introduces the
# exposure" rationale that used to sit on the ACL helper here. Stage 6's
# ``gateway_peers`` is the second importer and is why the last four moved: two
# credential stores in one directory that each restated the same write is the
# exact group ``test_duplicate_helper_bodies`` would have named next.
# ``read_pairing`` / ``write_pairing`` / ``store_lock`` are PUBLIC since the
# gateway_peers split (layout sheet §3): ``gateway_peers.ceremony`` spends all
# three, and a private name read from another module is a door nobody owns.


def store_lock(store_root: Path | str, *, timeout_seconds: float = 10.0):
    """This root's gateway-directory lock. ONE lock file, both ceremonies.

    ``devices.lock`` is shared with ``gateway_peers`` rather than split per
    store, and deliberately: both ceremonies read-modify-write the SAME
    ``pairing.json`` (one pending map, one lockout, one cap — see
    ``gateway_pairing_codes``), so two lock files would be two names for a
    mutual exclusion that has to be one. The filename is historical; the scope
    it protects is the directory.

    Since R-D27 it REFUSES at ``timeout_seconds`` — ``HarnessLockUnavailable``,
    on every platform — instead of proceeding unlocked, so each caller catches
    it beside the ``OSError`` it already turned into a typed ``StoreRefusal``.
    The two best-effort writers (:func:`note_device_seen` and
    ``gateway_peers._touch_cache``) catch ``Exception`` and were already covered.
    """

    return _file_lock(
        gateway_dir(store_root) / "devices.lock", timeout_seconds=timeout_seconds
    )
