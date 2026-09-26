"""``peers.json`` — what THIS install decided (the TRUST half, R-IP14).

The one derivation (``peer_secret_verifier`` / ``peer_proof``) and its
constant-time check, the reads, the three credential writers
(``record_peer``, ``revoke_peer``, ``note_peer_seen``) beside ``_write_peers``,
their ONE write door (rule 13), the external-write revision memo and
``_emit_peer_event``, the store's event emitter.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from typing import Any, Callable

from ..gateway_identity import clean_display_name
from ..serve_gateway_auth import StoreRefusal, store_lock
from ..store_file_io import HarnessLockUnavailable
from ..clock import iso_stamp as _iso
from ..store_file_io import os_error_reason as _os_reason
from ..store_file_io import read_json_object as _read_json
from ..store_file_io import write_secure_json as _write_secure
from .cache import _clear_revoked_you, _touch_cache
from .models import (
    PEER_AUTH_BAD_PROOF,
    PEER_AUTH_EXPIRED,
    PEER_AUTH_MALFORMED,
    PEER_AUTH_OK,
    PEER_AUTH_REVOKED,
    PEER_AUTH_UNKNOWN,
    PEER_EVENT_RECORDED,
    PEER_EVENT_REVOKED,
    PEER_EVENT_UPDATED,
    PEER_PROOF_CONTRACT,
    PEER_STORE_CONTRACT,
    REACHABILITY_REACHABLE,
    PeerAuth,
    PeerRecord,
    _clean_fingerprint,
    clean_endpoints,
    peer_cache_path,
    peer_store_path,
)

__layer__ = "stores"

#: Who hears a peer event besides the EventLog, called at the SAME site the
#: event is appended. The serve's push lane registers
#: ``serve_gateway_peers_rpc.publish_peer_event`` here when it loads; a CLI
#: ``peers join`` process registers nothing and notifies no one. A list rather
#: than an import because a credential store must not depend on the serve's RPC
#: surface (lane L1 inverted the deferred store -> lane import this replaces).
_peer_event_listeners: list[Callable[..., None]] = []


def add_peer_event_listener(listener: Callable[..., None]) -> None:
    """Register *listener* for ``(event_type, payload, *, store_root)``; idempotent."""

    if listener not in _peer_event_listeners:
        _peer_event_listeners.append(listener)


# ── the derivation ───────────────────────────────────────────────────────────


def peer_secret_verifier(secret: str) -> str:
    """``sha256(secret)`` as lowercase hex — what BOTH installs store.

    ONE derivation, called by the redeeming side to compute what to store, by
    the joining side to compute the same thing, and by either side's client half
    to compute the HMAC key. A second copy of this line is how two ends start
    disagreeing about what a credential is — and here there are genuinely two
    ends holding the same secret, so the risk is not hypothetical.
    """

    return hashlib.sha256(str(secret).encode("utf-8")).hexdigest()


def peer_proof(verifier: str, nonce: str, *, port: int, peer_install_id: str) -> str:
    """The answer to a peer challenge, as lowercase hex. ONE derivation, both ends.

    ``HMAC-SHA256(key=verifier, msg="pwv<contract>|<port>|<peer_install_id>|<nonce>")``
    where ``verifier`` is ``sha256(secret)`` — the value BOTH installs store and
    the value both use as the key. The device lane needs two spellings of this
    (the phone holds a token and digests it; the install holds only the digest);
    a peer edge needs one, because the plaintext secret is discarded by both
    sides the moment the pairing frame has been read. Writing it twice here
    would be two ways to describe one symmetric key, which is how the two ends
    of an edge start disagreeing about what the credential is.

    ``peer_install_id`` is the DIALER's own install id — the name it is asking
    to be recognised under — never the id of the install it is dialling. That
    asymmetry is what lets one symmetric secret serve an edge in both
    directions: A dialling B proves as A against B's row for A, and B dialling A
    proves as B against A's row for B, with the same key and different messages.

    The three bindings are ``device_proof``'s, for its reasons, with the middle
    one carrying extra weight here. The **nonce** is fresh per connection, so a
    captured transcript is not replayable. The **port** is what each end knows
    from its OWN socket, so an impostor relaying a live challenge to the real
    service gets an answer that does not verify there. The **install id** is
    what stops a proof minted for one direction being replayed in the other:
    without it, A's proof to B and B's proof to A over the same nonce would be
    the same bytes, and a relay that bounced one back would authenticate.

    The ``pwv`` prefix — against ``device_proof``'s ``gwv`` — is the last
    guard: even if a device token and a peer secret ever collided, a device
    proof would not verify as a peer proof and the reverse.

    The key is never the message, so the proof discloses nothing about the
    credential. It does not travel, in either direction.
    """

    message = f"pwv{PEER_PROOF_CONTRACT}|{int(port)}|{str(peer_install_id)}|{nonce}"
    return hmac.new(
        str(verifier).encode("ascii"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# ── peer store: reads ────────────────────────────────────────────────────────


def list_peers(store_root: Path | str) -> list[PeerRecord]:
    """Every paired install, revoked ones included, oldest first.

    Revoked rows are KEPT and shown, for ``list_devices``' reason: a revocation
    that deleted the row would make "never paired" and "thrown out" the same
    answer, and the second is the one an operator auditing a decommissioned
    machine needs.
    """

    rows = _read_peers(store_root)
    records = [record for record in (_decode_peer(row) for row in rows.values()) if record]
    records.sort(key=lambda record: (record.approved_at, record.peer_install_id))
    return records


def lookup_peer(store_root: Path | str, peer_install_id: str) -> PeerRecord | None:
    """One peer by install id, or ``None``. Never raises; never returns a secret."""

    peer_install_id = str(peer_install_id or "").strip()
    if not peer_install_id:
        return None
    row = _read_peers(store_root).get(peer_install_id)
    return _decode_peer(row) if isinstance(row, dict) else None


def verify_peer_proof(
    store_root: Path | str,
    peer_install_id: Any,
    presented: Any,
    nonce: str,
    *,
    port: int,
) -> PeerAuth:
    """Constant-time check of a peer hello's proof. Fails CLOSED, always.

    Every missing input is a refusal rather than a degrade: no store, an unknown
    id, a revoked row, an empty nonce, a non-string proof. "Nothing configured,
    let everyone in" is the failure mode that turns a hardening into a bypass,
    and this function is reachable by an unauthenticated peer on a listener
    bound beyond loopback.

    The outcomes are DISTINGUISHED here and deliberately COLLAPSED on the wire:
    the socket lane answers every one of them with the same typed rejection, and
    with the same reason a DEVICE failure gets — so a peer cannot use the reason
    to learn whether an install id is paired, nor even which of the two
    ceremonies it just failed.
    """

    peer_install_id = str(peer_install_id or "").strip()
    if not peer_install_id or len(peer_install_id) > 128:
        return PeerAuth(outcome=PEER_AUTH_MALFORMED)
    if not isinstance(presented, str) or not presented.strip():
        return PeerAuth(outcome=PEER_AUTH_MALFORMED, peer_install_id=peer_install_id)
    if not nonce:
        return PeerAuth(outcome=PEER_AUTH_MALFORMED, peer_install_id=peer_install_id)
    row = _read_peers(store_root).get(peer_install_id)
    if not isinstance(row, dict):
        return PeerAuth(outcome=PEER_AUTH_UNKNOWN, peer_install_id=peer_install_id)
    record = _decode_peer(row)
    if record is None:
        return PeerAuth(outcome=PEER_AUTH_UNKNOWN, peer_install_id=peer_install_id)
    verifier = str(row.get("secret_verifier") or "").strip()
    if not verifier:
        return PeerAuth(outcome=PEER_AUTH_UNKNOWN, peer_install_id=peer_install_id)
    expected = peer_proof(
        verifier, nonce, port=port, peer_install_id=peer_install_id
    )
    # BYTES, never str: ``hmac.compare_digest`` RAISES TypeError when either str
    # operand is non-ASCII, and ``presented`` is attacker-controlled on a path no
    # credential is needed to reach. Both sibling verifiers carry this note and
    # the same fix; one accented character used to unwind out of the loopback
    # handshake entirely.
    if not hmac.compare_digest(
        presented.strip().lower().encode("utf-8", "replace"), expected.encode("ascii")
    ):
        return PeerAuth(outcome=PEER_AUTH_BAD_PROOF, peer_install_id=peer_install_id)
    # Revocation is checked AFTER the proof, for ``verify_device_proof``'s
    # reason: checking it first would let an unauthenticated peer probe which
    # install ids are revoked (and, by difference, which are live) while holding
    # no credential at all.
    if record.revoked:
        return PeerAuth(
            outcome=PEER_AUTH_REVOKED, peer_install_id=peer_install_id, record=record
        )
    # Expiry sits beside revocation, AFTER the proof, for the same anti-probing
    # reason and in the same order: a row that is both reports ``peer_revoked``,
    # because a decision an operator made outranks a clock. Distinguished here,
    # collapsed on the wire.
    if record.expired:
        return PeerAuth(
            outcome=PEER_AUTH_EXPIRED, peer_install_id=peer_install_id, record=record
        )
    return PeerAuth(
        outcome=PEER_AUTH_OK, peer_install_id=peer_install_id, record=record
    )


# ── peer store: writes ───────────────────────────────────────────────────────


def note_peer_seen(
    store_root: Path | str, peer_install_id: str, *, now: float | None = None
) -> None:
    """A verified hello landed. Stamps the CACHE, never the trust file.

    S2c moved this write, and the move is the point of the sidecar (R-IP12a).
    Before it, the one thing the NETWORK wrote into a credential store was this
    stamp — a cache fact in a trust file, which is exactly the confusion the
    frozensets were added to make visible. Now every field the far install is
    the authority for lives in ``peers_cache.json`` and ``peers.json`` is trust
    only, so "can the network change this?" is answered by which FILE a fact is
    in rather than by remembering a list.

    Best effort, and never in the handshake's way: a peer whose proof verified
    has authenticated whether or not this write lands.
    """

    # ONE hello, ONE clock read. `_iso(None)` reads the wall clock, so calling
    # it twice stamped two fields that describe the SAME event from two
    # instants: on Linux they landed 7 microseconds apart and the contract test
    # asserting `last_hello_at == last_seen` was red on every CI runner, while
    # Windows' coarser clock made them equal and hid it. Resolve first, write
    # both.
    stamp = _iso(now)
    _touch_cache(
        store_root,
        peer_install_id,
        change="last_seen",
        now=now,
        last_seen=stamp,
        last_hello_at=stamp,
        reachability=REACHABILITY_REACHABLE,
        unreachable_since=None,
    )


def revoke_peer(
    store_root: Path | str,
    peer_install_id: str,
    *,
    announced: bool = False,
    correlation: Any = None,
    now: float | None = None,
) -> PeerRecord | StoreRefusal:
    """Refuse this peer at THIS install's door. Idempotent; the row is kept.

    One-sided by design, and the CLI ack says so. See the module docstring: a
    revocation that reached across the wire would be one install writing into
    another's credential store, which is the authority R5 says an install never
    has over another.
    """

    peer_install_id = str(peer_install_id or "").strip()
    if not peer_install_id:
        return StoreRefusal("invalid_peer_id", "a peer install id is required")
    try:
        with store_lock(store_root):
            rows = _read_peers(store_root)
            row = rows.get(peer_install_id)
            if not isinstance(row, dict):
                return StoreRefusal(
                    "unknown_peer",
                    f"no install {peer_install_id!r} is paired with this root",
                )
            if not row.get("revoked"):
                row["revoked"] = True
                row["revoked_at"] = _iso(now)
                _write_peers(store_root, rows)
                _note_write(store_root)
            record = _decode_peer(row)
            if record is None:  # pragma: no cover - a row we just wrote
                return StoreRefusal("store_corrupt", "the peer row will not decode")
    except (OSError, HarnessLockUnavailable) as exc:
        return StoreRefusal(_os_reason(exc), str(exc))
    _emit_peer_event(
        PEER_EVENT_REVOKED,
        {
            # Whether the far side was TOLD, not merely whether we tried. An
            # operator reading this line later needs to know if the other
            # install learned at the time or will learn at its next dial.
            "peer_install_id": peer_install_id,
            "announced": bool(announced),
            **({"grant_id": str(correlation)} if correlation else {}),
        },
        store_root=store_root,
    )
    return record


def record_peer(
    store_root: Path | str,
    *,
    peer_install_id: str,
    secret: str,
    display_name: Any = None,
    endpoints: Any = None,
    cert_fingerprint: Any = None,
    expires_at: Any = None,
    correlation: Any = None,
    now: float | None = None,
) -> PeerRecord | StoreRefusal:
    """Write the OTHER half of the edge, on the joining install.

    Called by ``harness gateway peers join`` with what came back on the
    ``hello_ok``: the remote install's id and display name, the secret it just
    minted, and the endpoint plus fingerprint the operator pasted in — the same
    values the dialer used, so what is stored is what was proven to work rather
    than what was advertised.

    Takes the secret as an ARGUMENT rather than minting one, and that is the
    whole difference between this function and :func:`redeem_peer_code`. A peer
    edge has exactly one secret; the side that did not mint it must store the
    one it was given or the two rows describe different credentials.
    
    ``expires_at`` travels the same way and for the same reason: it is read off
    ``hello_ok.peered`` (the redeeming side computed it) rather than recomputed
    here. A joining install that derived its own would put a second authority on
    one fact, and the two ends of an edge would lapse minutes — or, with a
    skewed clock, days — apart.
    """

    peer_install_id = str(peer_install_id or "").strip()
    if not peer_install_id or len(peer_install_id) > 128:
        return StoreRefusal("invalid_peer_id", "a peer install id is required")
    if not str(secret or "").strip():
        return StoreRefusal(
            "invalid_secret", "the remote install returned no peer secret"
        )
    stamp = now if now is not None else time.time()
    try:
        with store_lock(store_root):
            rows = _read_peers(store_root)
            rows[peer_install_id] = peer_row(
                peer_install_id=peer_install_id,
                display_name=clean_display_name(display_name) or peer_install_id,
                endpoints=clean_endpoints(endpoints),
                cert_fingerprint=_clean_fingerprint(cert_fingerprint),
                secret=str(secret).strip(),
                stamp=stamp,
                expires_at=(str(expires_at).strip() or None) if expires_at else None,
            )
            _write_peers(store_root, rows)
            _note_write(store_root)
            record = _decode_peer(rows[peer_install_id])
            if record is None:  # pragma: no cover - a row we just wrote
                return StoreRefusal("store_corrupt", "the peer row will not decode")
    except (OSError, HarnessLockUnavailable) as exc:
        return StoreRefusal(_os_reason(exc), str(exc))
    _clear_revoked_you(store_root, peer_install_id, now=stamp)
    # Emitted OUTSIDE the lock: an EventLog append is another store's write, and
    # holding this directory's lock across it would make two unrelated stores
    # share one contention story.
    _emit_peer_event(
        PEER_EVENT_RECORDED,
        {
            "peer_install_id": peer_install_id,
            "source": "join",
            **({"grant_id": str(correlation)} if correlation else {}),
        },
        store_root=store_root,
    )
    return record


def peer_row(
    *,
    peer_install_id: str,
    display_name: str,
    endpoints: tuple[dict[str, Any], ...],
    cert_fingerprint: str | None,
    secret: str,
    stamp: float,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """One stored row. The ONE place a peer row's shape is written.

    Both write paths (redeem on A, record on B) go through here, so the two
    halves of an edge cannot end up with differently-shaped rows — which is the
    kind of divergence that only shows up months later, on the side nobody
    tested.

    Its keys are exactly :data:`PEER_ROW_TRUST_FIELDS` ∪
    :data:`PEER_ROW_CACHE_FIELDS`, asserted in
    ``tests/agent_runtime/test_gateway_peers_store.py``. A field added here
    without being classified fails that test, which is the point: R-IP14's rule
    is that a fact has one authority and every other copy is a labelled cache,
    and the label has to be machine-readable for S2c's sidecar to be a move
    rather than a re-derivation.
    """

    return {
        "peer_install_id": peer_install_id,
        "display_name": display_name,
        "endpoints": [dict(endpoint) for endpoint in endpoints],
        "cert_fingerprint": cert_fingerprint,
        "secret_verifier": peer_secret_verifier(secret),
        "approved_at": _iso(stamp),
        "revoked": False,
        "revoked_at": None,
        "expires_at": expires_at,
    }


def _decode_peer(row: Any) -> PeerRecord | None:
    if not isinstance(row, dict):
        return None
    peer_install_id = str(row.get("peer_install_id") or "").strip()
    if not peer_install_id:
        return None
    return PeerRecord(
        peer_install_id=peer_install_id,
        display_name=str(row.get("display_name") or peer_install_id),
        endpoints=clean_endpoints(row.get("endpoints")),
        cert_fingerprint=_clean_fingerprint(row.get("cert_fingerprint")),
        approved_at=str(row.get("approved_at") or ""),
        # LEGACY ONLY. S2c moved this fact to ``peers_cache.json``; ``peer_row`` no
        # longer writes it and :func:`note_peer_seen` no longer touches this
        # file. A row written by a pre-S2c build still carries a value and it is
        # still shown, because deleting a fact an operator can already see is a
        # worse migration than reading one nothing writes. New rows answer
        # ``None`` here and the live stamp is ``cache.last_seen``.
        last_seen=(str(row["last_seen"]) if row.get("last_seen") else None),
        revoked=bool(row.get("revoked")),
        revoked_at=(str(row["revoked_at"]) if row.get("revoked_at") else None),
        # Absent reads as "never expires", so every row a pre-S2 build wrote
        # keeps working untouched. There is no migration pass because the only
        # new fact has a legal absent value.
        expires_at=(str(row["expires_at"]) if row.get("expires_at") else None),
    )


def _read_peers(store_root: Path | str) -> dict[str, Any]:
    payload = _read_json(peer_store_path(store_root))
    rows = payload.get("peers")
    return dict(rows) if isinstance(rows, dict) else {}


def _write_peers(store_root: Path | str, rows: dict[str, Any]) -> None:
    _write_secure(
        peer_store_path(store_root),
        {"contract": PEER_STORE_CONTRACT, "peers": rows},
    )


# ── the revision memo (R-S2-8) ───────────────────────────────────────────────
#
# Every write door below emits its own event from its OWN process, which is the
# ``realm_sync`` precedent already working: a CLI ``peers join`` beside a running
# serve advances the EventLog watermark and the serve's stream picks it up with
# no restart and no check. So the revision memo has exactly ONE job left — a
# write that emitted NOTHING. An editor on ``peers.json``; a binary that predates
# S2c. It is a stat taken on reads that were happening anyway, never a timer.

#: Per-process, keyed by the resolved store root. Not a cache of CONTENT — the
#: files are re-read every time — only of "what revision had this process seen".
_LAST_SEEN_REVISION: dict[str, tuple[int, int]] = {}


def peer_store_revision(store_root: Path | str) -> tuple[int, int]:
    """``(trust_mtime_ns, cache_mtime_ns)``; ``0`` for a file that is absent.

    Modification time and not a hash, deliberately: this question is asked on
    every gateway hello and every peer call, and hashing two files on that path
    would put I/O proportional to store size on the handshake. An mtime that did
    not move for a write is a filesystem this repo has bigger problems with.
    """

    def _mtime(path: Path) -> int:
        try:
            return int(path.stat().st_mtime_ns)
        except OSError:
            return 0

    return _mtime(peer_store_path(store_root)), _mtime(peer_cache_path(store_root))


def note_peer_store_read(store_root: Path | str) -> None:
    """Record the revision this process is reading, and emit once if it is new.

    A FRESH process seeds on its first read and emits nothing: it has no
    baseline, so "this changed" is not a claim it can make. A long-lived process
    — the serve, which reads on every hello, every ``peer.*`` call and every
    connections frame — is therefore the one that notices, which is exactly the
    process a stream consumer is attached to.
    """

    key = str(Path(store_root))
    revision = peer_store_revision(store_root)
    previous = _LAST_SEEN_REVISION.get(key)
    _LAST_SEEN_REVISION[key] = revision
    if previous is None or previous == revision:
        return
    store = "trust" if previous[0] != revision[0] else "cache"
    _emit_peer_event(
        PEER_EVENT_UPDATED,
        {
            "store": store,
            "change": "external_write",
            "store_revision": list(revision),
        },
        store_root=store_root,
    )


def _note_write(store_root: Path | str) -> None:
    """Adopt the revision THIS process just wrote, so it never reports itself."""

    _LAST_SEEN_REVISION[str(Path(store_root))] = peer_store_revision(store_root)


def _emit_peer_event(
    event_type: str, payload: dict[str, Any], *, store_root: Path | str | None = None
) -> None:
    """Append one ``gateway.peer.*`` event from THIS process. Best effort.

    ``store_root`` is the root that was actually WRITTEN, threaded from the
    caller rather than re-derived. Every function in this module takes its root
    as an INPUT for the reason the module docstring gives — several roots
    coexist on this machine and Stage 6's whole subject is two of them at once —
    and the S2d push lane inherits that: a notification that resolved its own
    root could describe a different store from the one the write landed in,
    which is the same class of bug the input rule exists to prevent. The
    EventLog append is unaffected (it is per-process, not per-root); this is for
    the fan-out below it.

    The ``realm_sync._append_realm_sync_event`` precedent, and its reason: the
    stream/read-model pipeline is watermark-gated on the EventLog, so a store
    write that emits nothing is invisible to every consumer until an unrelated
    event happens to advance the offset. Emitting from the writing process — a
    CLI ``peers join``, the serve's own authenticator — is what makes a join
    beside a running serve visible with no restart.

    **Never a secret, an endpoint or a roster body.** Ids and counts only: the
    payload cap is 4096 bytes and an event log is a place facts go to be read
    later by people who were not there. What the row holds is in the row.
    """

    from hermes_time import now

    from ..events import EventLog
    from ..models import Event

    try:
        EventLog().append(Event(now(), event_type, None, None, None, dict(payload)))
    except Exception:  # noqa: BLE001 — an evidence channel, never the mutation
        pass

    # S2d. The SAME call site feeds the launcher's push lane, because the
    # launcher's hermes stream carries no events at all (its hydrate core and
    # fold entities have no room for one) and canon 03 invariant 6 routes new
    # server→client push over JSON-RPC notifications instead. Emitting both
    # from here is what stops the two lanes disagreeing about WHEN something
    # changed: one write, one process, one moment.
    #
    # Through the listener list and guarded: this is a credential store, and it
    # must not take a hard dependency on the serve's RPC surface — a CLI
    # ``peers join`` runs this function in a process where nobody is subscribed
    # to anything.
    for listener in tuple(_peer_event_listeners):
        try:
            listener(event_type, dict(payload), store_root=store_root)
        except Exception:  # noqa: BLE001 — a notification is never the mutation
            pass
