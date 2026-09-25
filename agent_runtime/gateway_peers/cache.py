"""``peers_cache.json`` — what the NETWORK told us (S2c, R-IP12a).

The cache half of the peer stores: every cache writer and ``_touch_cache``,
the ONE write door they share (rule 13), and the readers (``read_peer_cache``,
``usable_peers``). No function here opens ``peers.json`` for writing.

The one cycle in the package is broken HERE: ``trust_store`` imports this
module at its top (``record_peer`` clears ``revoked_you``), so this module
takes its two ``trust_store`` names last, after every name above is bound,
and the package ``__init__`` imports this module before ``trust_store``.
"""

from __future__ import annotations

import threading as _threading
from pathlib import Path
from typing import Any

from ..gateway_identity import clean_display_name
from ..serve_gateway_auth import store_lock
from ..store_file_io import iso_stamp as _iso
from ..store_file_io import read_json_object as _read_json
from ..store_file_io import write_secure_json as _write_secure
from .models import (
    PEER_CACHE_CONTRACT,
    PEER_CACHE_ROSTER_CAP,
    PEER_CACHE_ROW_FIELDS,
    PEER_EVENT_REACHABILITY,
    PEER_EVENT_ROSTER,
    PEER_EVENT_UPDATED,
    REACHABILITY_REACHABLE,
    REACHABILITY_UNKNOWN,
    REACHABILITY_UNREACHABLE,
    PeerCacheRow,
    UsablePeer,
    _clean_fingerprint,
    clean_endpoints,
    peer_cache_path,
)

__layer__ = "stores"


def read_peer_cache(store_root: Path | str) -> dict[str, PeerCacheRow]:
    """Every cached peer row, keyed by install id. Never raises.

    Reads the revision as it goes (R-S2-8), so a process that has been handed a
    file somebody edited notices exactly once.
    """

    note_peer_store_read(store_root)
    rows = _read_cache_rows(store_root)
    decoded: dict[str, PeerCacheRow] = {}
    for peer_install_id, row in rows.items():
        cached = _decode_cache(peer_install_id, row)
        if cached is not None:
            decoded[cached.peer_install_id] = cached
    return decoded


def cache_peer_hello(
    store_root: Path | str,
    peer_install_id: str,
    *,
    display_name: Any = None,
    endpoints: Any = None,
    cert_fingerprint: Any = None,
    now: float | None = None,
) -> None:
    """Refresh what a peer says about itself, from a VERIFIED hello.

    Every hello, not only a join. Before this the name, addresses and
    fingerprint were pairing-time snapshots refreshed only by a re-``join``, so
    an install that moved networks became unreachable until an operator re-ran a
    ceremony they had no reason to suspect was needed.

    The fingerprint here is the ANNOUNCED one and never the pin: see
    :class:`PeerCacheRow`. A change is recorded as a rotation notice for an
    operator to act on.
    """

    changes: dict[str, Any] = {
        "last_hello_at": _iso(now),
        "reachability": REACHABILITY_REACHABLE,
        "unreachable_since": None,
    }
    cleaned_name = clean_display_name(display_name) or None
    if cleaned_name:
        changes["announced_display_name"] = cleaned_name
    cleaned_endpoints = clean_endpoints(endpoints)
    if cleaned_endpoints:
        changes["endpoints"] = [dict(endpoint) for endpoint in cleaned_endpoints]
    announced = _clean_fingerprint(cert_fingerprint)
    if announced:
        changes["cert_fingerprint"] = announced
        rotation = _rotation_notice(store_root, peer_install_id, announced, now=now)
        if rotation is not None:
            changes["fingerprint_rotation"] = rotation
    _touch_cache(store_root, peer_install_id, change="display_name", now=now, **changes)


def note_dial_result(
    store_root: Path | str,
    peer_install_id: str,
    *,
    ok: bool,
    error: Any = None,
    now: float | None = None,
) -> None:
    """Record what happened when we tried to reach this peer.

    ``unreachable_since`` is set on the FIRST failure and left alone on the
    ones after it, so "down for twelve minutes" is answerable. A field that was
    restamped on every retry would only ever say "down since the last attempt",
    which is a number nobody can act on.
    """

    if ok:
        _touch_cache(
            store_root,
            peer_install_id,
            change="reachability",
            now=now,
            reachability=REACHABILITY_REACHABLE,
            unreachable_since=None,
        )
        return
    existing = _decode_cache(
        peer_install_id, _read_cache_rows(store_root).get(str(peer_install_id).strip())
    )
    since = (
        existing.unreachable_since
        if existing is not None
        and existing.reachability == REACHABILITY_UNREACHABLE
        and existing.unreachable_since
        else _iso(now)
    )
    _touch_cache(
        store_root,
        peer_install_id,
        change="reachability",
        now=now,
        error=str(error or "")[:200] or None,
        reachability=REACHABILITY_UNREACHABLE,
        unreachable_since=since,
    )


def cache_peer_roster(
    store_root: Path | str,
    peer_install_id: str,
    *,
    workspace_id: Any = None,
    rows: Any = None,
    now: float | None = None,
) -> None:
    """Keep the roster a peer just handed us, so the HUD never has to dial.

    Bounded at :data:`PEER_CACHE_ROSTER_CAP` and stamped with when it was
    fetched, because a roster with no ``fetched_at`` is a claim about the
    present made from an unknown past — and the HUD renders an age from it.
    """

    kept = []
    for row in list(rows or ())[:PEER_CACHE_ROSTER_CAP]:
        if isinstance(row, dict):
            kept.append(dict(row))
    # ONE fetch, ONE clock read — the event and the row report the same
    # `fetched_at` because they report the same fetch. See `note_peer_seen`.
    fetched_at = _iso(now)
    _touch_cache(
        store_root,
        peer_install_id,
        change="roster",
        now=now,
        event_type=PEER_EVENT_ROSTER,
        event_payload={"count": len(kept)},
        event_detail={
            "workspace_id": str(workspace_id or "") or None,
            "fetched_at": fetched_at,
        },
        roster={
            "fetched_at": fetched_at,
            "workspace_id": str(workspace_id or "") or None,
            "rows": kept,
        },
    )


def apply_peer_announce(
    store_root: Path | str,
    caller_peer_install_id: str,
    payload: Any,
    *,
    now: float | None = None,
) -> list[str]:
    """Apply one ``peer.announce`` to the CALLER's own cache row. Returns the fields written.

    **The row written is the CALLER's, and there is no parameter that could say
    otherwise** (R-S2-9). The install id is taken positionally from what the
    transport proved; a payload that names a different install is refused by the
    handler before reaching here, and one that names its own is simply ignored.
    That is ``normalize_peer_chat_execute``'s posture, and its reason: the field
    a peer could type does not exist.

    Three things this cannot do, and each is a property of the code rather than
    a rule: it cannot write a credential (it opens only the cache file), it
    cannot clear ``revoked_you`` or ``revoked`` (both are cleared by a trust
    write alone), and it cannot move the dial pin (an announced fingerprint
    becomes a rotation NOTICE beside the pin, never the pin).
    """

    caller = str(caller_peer_install_id or "").strip()
    if not caller or not isinstance(payload, dict):
        return []

    # ONE announce, ONE clock read: `revoked_you_at` below records the same
    # message arriving, not a later one. See `note_peer_seen`.
    announced_at = _iso(now)
    changes: dict[str, Any] = {"last_announce_at": announced_at}
    written: list[str] = []

    name = clean_display_name(payload.get("display_name")) or None
    if name:
        changes["announced_display_name"] = name
        written.append("announced_display_name")

    endpoints = clean_endpoints(payload.get("endpoints"))
    if endpoints:
        changes["endpoints"] = [dict(endpoint) for endpoint in endpoints]
        written.append("endpoints")

    announced = _clean_fingerprint(payload.get("cert_fingerprint"))
    if announced:
        changes["cert_fingerprint"] = announced
        written.append("cert_fingerprint")
        rotation = _rotation_notice(store_root, caller, announced, now=now)
        if rotation is not None:
            changes["fingerprint_rotation"] = rotation
            written.append("fingerprint_rotation")

    if payload.get("roster_changed") is True:
        # DROPPED, not refreshed: this edge carries a notification, never a
        # roster body. Fetching one here would make an inbound announce trigger
        # an outbound dial, which is a loop with two installs in it.
        changes["roster"] = None
        written.append("roster")

    if payload.get("revoked_you") is True:
        changes["revoked_you"] = True
        changes["revoked_you_at"] = announced_at
        written.extend(["revoked_you", "revoked_you_at"])

    correlation = str(payload.get("correlation_id") or "").strip()[:64]
    if correlation:
        changes["correlation"] = correlation

    _touch_cache(
        store_root,
        caller,
        change="display_name" if name else "endpoints",
        now=now,
        **changes,
    )
    return written


# ── the predicate every reader shares ────────────────────────────────────────


def usable_peers(store_root: Path | str) -> list[UsablePeer]:
    """The peers an address could actually reach, oldest edge first.

    THE predicate (R-S2-16). Three conditions, and each is a different way for
    an edge to be dead:

    * ``revoked`` — this operator threw the peer out.
    * ``expired`` — the credential lapsed (S2).
    * ``cache.revoked_you`` — the FAR operator threw us out and said so
      (S2c's announce). Learning this from the cache is the whole point of the
      push edge: before it, a revoke on the far side was discovered as the next
      send's refusal, minutes or hours later, by an agent that had already
      written the message.

    ``ref`` is computed across the whole usable set rather than per row, because
    "is this name unique" is a question about the SET. A row that answered it
    alone would hand out a display name that the resolver then refuses as
    ambiguous — a spelling the system itself printed and will not accept.
    """

    records = [record for record in list_peers(store_root)]
    cache = read_peer_cache(store_root)
    live = [
        record
        for record in records
        if not record.revoked
        and not record.expired
        and not (
            (cache.get(record.peer_install_id) or PeerCacheRow("")).revoked_you
        )
    ]
    names: dict[str, int] = {}
    for record in live:
        folded = (record.display_name or "").casefold()
        names[folded] = names.get(folded, 0) + 1
    rows: list[UsablePeer] = []
    for record in live:
        folded = (record.display_name or "").casefold()
        unique = bool(record.display_name) and names.get(folded, 0) == 1
        rows.append(
            UsablePeer(
                record=record,
                cache=cache.get(record.peer_install_id),
                ref=record.display_name if unique else record.peer_install_id,
            )
        )
    return rows

#: **In-process mutual exclusion for the cache's read-modify-write**, on top of
#: the cross-process file lock and not instead of it.
#:
#: ``store_file_io.store_lock`` used to fall through WITHOUT the lock rather
#: than raising when it could not be taken, and this lock was the answer to the
#: lost update that let through. R-D27 closed the fall-through — the store lock
#: now refuses at its deadline — and this lock is MORE necessary, not less: the
#: cross-process lock is not reentrant, so two threads of ONE serve process
#: contending on it no longer lose an update, they spend the whole budget and
#: one of them refuses. The CACHE is where that would bite: its writers are a
#: handshake on the listener thread, a dial from a tool and an announce fan-out
#: on a background thread, all inside one process and all merging into one row.
#: Serialising them HERE means they queue in memory and reach the file lock one
#: at a time, so the second writer waits microseconds instead of racing a ten
#: second refusal — and a boot-time announce racing the first hello still cannot
#: drop the field the other writer had just set.
#:
#: A module-level lock is the whole fix because every write goes through
#: :func:`_touch_cache`. Held only across the read-modify-write, never across an
#: event append or a dial.
_CACHE_WRITE_LOCK = _threading.Lock()


# ── cache internals ──────────────────────────────────────────────────────────


def _cache_row(peer_install_id: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """One stored cache row. The ONE place its shape is written.

    Its keys are exactly :data:`PEER_CACHE_ROW_FIELDS`, asserted in
    ``test_gateway_peers_store.py`` — so a field added here without being
    classified fails, which is the trust row's rule applied to the other half of
    the split.

    ``fields`` is a DICT and not ``**kwargs``, and that is a bug fix wearing a
    signature. The caller merges the row it read with the fields it is changing
    and passes the result; a splat made ``peer_install_id`` — which is a key in
    every stored row — collide with the positional parameter, so the first write
    to a fresh row succeeded (nothing to merge) and every write after it raised
    ``TypeError`` into :func:`_touch_cache`'s best-effort ``except`` and
    silently did nothing. A dict cannot collide, and the id stays positional
    because it is the one field a caller must not be able to change by merging.
    """

    row: dict[str, Any] = {
        "peer_install_id": peer_install_id,
        "announced_display_name": None,
        "endpoints": [],
        "cert_fingerprint": None,
        "last_seen": None,
        "last_hello_at": None,
        "reachability": REACHABILITY_UNKNOWN,
        "unreachable_since": None,
        "roster": None,
        "revoked_you": False,
        "revoked_you_at": None,
        "fingerprint_rotation": None,
        "last_announce_at": None,
        "correlation": None,
    }
    for key, value in (fields or {}).items():
        if key in PEER_CACHE_ROW_FIELDS:
            row[key] = value
    # Always the id the CALLER named, never one a merged row carried: a cache
    # row that could rename itself through a merge would be a row addressed by
    # one install and stored under another.
    row["peer_install_id"] = peer_install_id
    return row


def _decode_cache(peer_install_id: Any, row: Any) -> PeerCacheRow | None:
    if not isinstance(row, dict):
        return None
    resolved = str(row.get("peer_install_id") or peer_install_id or "").strip()
    if not resolved:
        return None
    reachability = str(row.get("reachability") or REACHABILITY_UNKNOWN)
    if reachability not in {
        REACHABILITY_UNKNOWN,
        REACHABILITY_REACHABLE,
        REACHABILITY_UNREACHABLE,
    }:
        # A word this build does not know reads as ``unknown``, never as
        # ``reachable``: the safe direction for a reachability claim is "we do
        # not know", because the other one is a dial an operator was promised.
        reachability = REACHABILITY_UNKNOWN
    return PeerCacheRow(
        peer_install_id=resolved,
        announced_display_name=(
            str(row["announced_display_name"])
            if row.get("announced_display_name")
            else None
        ),
        endpoints=clean_endpoints(row.get("endpoints")),
        cert_fingerprint=_clean_fingerprint(row.get("cert_fingerprint")),
        last_seen=(str(row["last_seen"]) if row.get("last_seen") else None),
        last_hello_at=(str(row["last_hello_at"]) if row.get("last_hello_at") else None),
        reachability=reachability,
        unreachable_since=(
            str(row["unreachable_since"]) if row.get("unreachable_since") else None
        ),
        roster=row["roster"] if isinstance(row.get("roster"), dict) else None,
        revoked_you=bool(row.get("revoked_you")),
        revoked_you_at=(
            str(row["revoked_you_at"]) if row.get("revoked_you_at") else None
        ),
        fingerprint_rotation=(
            row["fingerprint_rotation"]
            if isinstance(row.get("fingerprint_rotation"), dict)
            else None
        ),
        last_announce_at=(
            str(row["last_announce_at"]) if row.get("last_announce_at") else None
        ),
        correlation=(str(row["correlation"]) if row.get("correlation") else None),
    )


def _read_cache_rows(store_root: Path | str) -> dict[str, Any]:
    payload = _read_json(peer_cache_path(store_root))
    rows = payload.get("peers")
    return dict(rows) if isinstance(rows, dict) else {}


def _write_peer_cache(store_root: Path | str, rows: dict[str, Any]) -> None:
    _write_secure(
        peer_cache_path(store_root),
        {"contract": PEER_CACHE_CONTRACT, "peers": rows},
    )


def _clear_revoked_you(
    store_root: Path | str, peer_install_id: str, *, now: float | None = None
) -> None:
    """The ONE exit from ``revoked_you`` (R-S2-9), taken by a TRUST write.

    ``revoked_you`` is one-way against the wire — an announce may set it and no
    announce may clear it — because an install that could announce itself back
    into an edge would have granted itself access an operator refused. But a
    one-way flag with no exit at all would mean a re-pair produced an edge that
    every reader still treated as dead.

    So the exit is exactly the ceremony that re-establishes trust: the far
    operator paired again, which is the same authority that could revoke. Called
    from :func:`redeem_peer_code` and :func:`record_peer` — the two functions
    that write a credential — and from nowhere else, so "cleared by a trust
    write" is a property of the call graph rather than a comment.

    A no-op when there is no cache row: nothing to clear is not a failure.
    """

    rows = _read_cache_rows(store_root)
    existing = rows.get(str(peer_install_id).strip())
    if not isinstance(existing, dict) or not existing.get("revoked_you"):
        return
    _touch_cache(
        store_root,
        peer_install_id,
        change="display_name",
        now=now,
        revoked_you=False,
        revoked_you_at=None,
    )


def _rotation_notice(
    store_root: Path | str,
    peer_install_id: str,
    announced: str,
    *,
    now: float | None,
) -> dict[str, Any] | None:
    """A fingerprint that disagrees with the PIN, as a notice. Never applied.

    ``None`` when it agrees, or when there is no pin to disagree with. The
    notice is what an operator reads to decide whether to re-pair; applying it
    would let a peer nominate the certificate it is authenticated against, which
    is the one thing pinning exists to prevent.
    """

    record = lookup_peer(store_root, peer_install_id)
    pin = record.cert_fingerprint if record is not None else None
    if not pin or pin == announced:
        return None
    return {"announced_at": _iso(now), "new_fingerprint": announced}


def _touch_cache(
    store_root: Path | str,
    peer_install_id: Any,
    *,
    change: str,
    now: float | None = None,
    event_type: str | None = None,
    event_payload: dict[str, Any] | None = None,
    event_detail: dict[str, Any] | None = None,
    error: Any = None,
    **fields: Any,
) -> None:
    """Merge *fields* into one cache row, write, and emit. Never raises.

    The ONE write door for the sidecar, which is what makes "no cache writer can
    change a trust field" checkable rather than promised: there is exactly one
    function that opens this file for writing, and it opens no other.

    Best effort throughout. Every caller is on a path where the bookkeeping is
    not the work — a verified hello, a completed dial, an accepted announce —
    and a store that will not write must not be the thing that fails an
    authentication.
    """

    resolved = str(peer_install_id or "").strip()
    if not resolved:
        return
    previous_reachability = None
    try:
        with _CACHE_WRITE_LOCK, store_lock(store_root):
            rows = _read_cache_rows(store_root)
            existing = rows.get(resolved)
            previous = _decode_cache(resolved, existing)
            previous_reachability = (
                previous.reachability if previous is not None else None
            )
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(fields)
            rows[resolved] = _cache_row(resolved, merged)
            _write_peer_cache(store_root, rows)
            _note_write(store_root)
    except Exception:
        return

    if event_type is not None:
        payload = {"peer_install_id": resolved, **(event_payload or {})}
        payload.update({k: v for k, v in (event_detail or {}).items() if v is not None})
        _emit_peer_event(event_type, payload, store_root=store_root)
        return

    reachability = fields.get("reachability")
    if reachability is not None and reachability != previous_reachability:
        # Emitted on a CHANGE OF WORD only. A peer that answers every thirty
        # seconds would otherwise write one event per hello for a fact that did
        # not move, which is the shape that makes an event log unreadable.
        detail = {
            "peer_install_id": resolved,
            "reachability": reachability,
            "unreachable_since": fields.get("unreachable_since"),
        }
        if error:
            detail["error"] = str(error)[:200]
        _emit_peer_event(PEER_EVENT_REACHABILITY, detail, store_root=store_root)
        return

    _emit_peer_event(
        PEER_EVENT_UPDATED,
        {"store": "cache", "change": change, "peer_install_id": resolved},
        store_root=store_root,
    )


def unusable_reason(record: Any, cache: Any) -> str:
    """The resolver's own vocabulary, so one condition has one word everywhere."""

    from ..gateway_targets import (
        REASON_PEER_EXPIRED,
        REASON_PEER_REVOKED,
        REASON_PEER_REVOKED_YOU,
    )

    if record.revoked:
        return REASON_PEER_REVOKED
    if record.expired:
        return REASON_PEER_EXPIRED
    if cache is not None and cache.revoked_you:
        return REASON_PEER_REVOKED_YOU
    return ""


# The cycle break (sheet §1.1): imported last, after every name above is bound,
# because the sibling imports this module at its top.
from .trust_store import (  # noqa: E402
    _emit_peer_event,
    _note_write,
    list_peers,
    lookup_peer,
    note_peer_store_read,
)
