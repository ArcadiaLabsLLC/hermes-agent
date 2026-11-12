"""A realm this install lost access to — the durable local mark.

The backend emits ``realm.revoked`` on ``personal:`` (durable, replayable)
with ``{realm_id, server_id, slug, reason}`` (backend 02 §4, EVENT_CATALOG).
Hermes holds no realtime subscription and no credential between calls, so the
launcher, which receives the event, records it here through
``runtime.realm.revoked``. The mark is what keeps the revocation from being a
moment: the realm record and every local file stay (local data is kept), the
snapshot's realm ``sync`` object carries ``revoked`` so a relaunched client
does not re-arm the realm's poll, and every credentialed sync verb refuses
``realm_revoked`` (not retryable) before it touches the network. ``status``
degrades to its local half, as it does for any refused authorization.

The mark is cleared by a re-grant: ``adopt_realms`` re-adopting the realm.

Since RT-LEFT-SERVER-REALM-STAYS-LISTED (owner 2026-11-12) the mark is what a
HOST-state loss leaves (``HOST_STATE_REASONS``: the binding is still there to
reconnect). A loss of the MEMBER's access (``MEMBER_ACCESS_REASONS``) no longer
leaves a bound realm that cannot sync: ``agent_runtime.realm_leave`` makes the
realm a local one and records where it came from in the ``shared_from`` record
below — a third install-local file, read by the snapshot only for a realm with
no ``server_id``. The record follows the local copy through its re-key and is
what labels it beside the server's realm after a re-join
(RT-REJOIN-PULLS-THE-SERVER-REALM-FRESH): a re-join never binds the local copy
again, so nothing here is "put back".

Stored at ``realm_sync_state/<realm>.revoked.json`` beside the status
sidecar — a separate file, because every status run rewrites the sidecar
whole. Install-local: nothing here is published.
"""

from __future__ import annotations

import json
from datetime import timezone, UTC
from enum import Enum
from pathlib import Path
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from .. import paths
from ..events import EventLog
from ..models import Event, Realm
from .models import RealmSyncError

__layer__ = "stores"
__all__ = [
    "BACKEND_REFUSAL_REASONS",
    "HOST_STATE_REASONS",
    "MEMBER_ACCESS_REASONS",
    "REALM_REVOKED_CODE",
    "RealmRevokedReason",
    "clear_realm_revocation",
    "mark_realm_revoked",
    "read_realm_revocation",
    "read_realm_shared_from",
    "realm_revocation_path",
    "realm_shared_from_path",
    "refuse_if_revoked",
    "write_realm_shared_from",
]

#: The ``RealmSyncError.code`` a revoked realm's sync verbs refuse with.
REALM_REVOKED_CODE = "realm_revoked"


class RealmRevokedReason(str, Enum):
    """Backend ``RealmRevokedReason`` (``realms/services.py``), verbatim, plus
    ``git_host_binding_lost``: no event carries it — it is the backend's
    permanent ``409 realms.git_host_binding_lost`` on the credential mint
    (App uninstalled, repo dropped), which the launcher records here exactly
    as it records ``git_host_unbound`` (``BACKEND_REFUSAL_REASONS``)."""

    MEMBERSHIP_LEFT = "membership_left"
    MEMBERSHIP_KICKED = "membership_kicked"
    MEMBERSHIP_BANNED = "membership_banned"
    TIMEOUT_STARTED = "timeout_started"
    ROLE_REVOKED = "role_revoked"
    GRANT_REMOVED = "grant_removed"
    REALM_DELETED = "realm_deleted"
    SERVER_DELETED = "server_deleted"
    # The realm's ownership moved to another member (backend
    # REALM-REVOKED-OWNERSHIP-TRANSFERRED); the member's access, not the host.
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    GIT_HOST_UNBOUND = "git_host_unbound"
    GIT_HOST_BINDING_LOST = "git_host_binding_lost"


#: Reasons that are the git HOST's state, not the member's: the launcher shows
#: the host state (reconnect via ``install_url``) instead of "access revoked".
#: No ``realm.granted`` follows a reconnect (``connect_github`` emits none), so
#: these are lifted by the next ADMITTED credential instead of a re-adopt: the
#: mint re-verifies the binding (``ensure_repo``, backend 02 §5 step 5) and
#: refuses with these same 409s while it is still gone.
HOST_STATE_REASONS = frozenset({RealmRevokedReason.GIT_HOST_UNBOUND, RealmRevokedReason.GIT_HOST_BINDING_LOST})

#: Every other reason: the MEMBER lost the realm (left, kicked, banned, timed
#: out, lost the role or the grant, ownership moved, the realm or its server
#: was deleted). The realm becomes a local one (``agent_runtime.realm_leave``).
#: All of them, not only the three ``membership_*`` ones: the backend emits
#: ``realm.revoked`` once, on the grant diff — a member who loses a role's realm
#: and LATER leaves the server gets no second event, so a realm left bound on
#: the first would stay bound for good. A re-grant adopts the server's realm
#: fresh, beside the local copy.
MEMBER_ACCESS_REASONS = frozenset(RealmRevokedReason) - HOST_STATE_REASONS

#: Backend refusal ``error.code`` on the credential mint -> the mark it is.
#: Both are permanent (no ``Retry-After``): never ``sync_remote_unreachable``,
#: which is the retryable ``503 realm.sync.git_unavailable``'s word.
BACKEND_REFUSAL_REASONS: dict[str, RealmRevokedReason] = {
    "realms.git_host_unbound": RealmRevokedReason.GIT_HOST_UNBOUND,
    "realms.git_host_binding_lost": RealmRevokedReason.GIT_HOST_BINDING_LOST,
}


def realm_revocation_path(realm_id: str) -> Path:
    return paths.store_root() / "realm_sync_state" / f"{paths.safe_path_token(realm_id)}.revoked.json"


def read_realm_revocation(realm_id: str) -> dict[str, Any] | None:
    """``{reason, revoked_at, host_state}`` or ``None``. A pure file read —
    ``build_snapshot`` reads it through ``read_realm_sync_sidecar``."""
    try:
        raw = json.loads(realm_revocation_path(realm_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        reason = RealmRevokedReason(raw.get("reason"))
    except ValueError:
        return None
    return {
        "reason": reason.value,
        "revoked_at": raw.get("revoked_at"),
        "host_state": reason in HOST_STATE_REASONS,
    }


def realm_shared_from_path(realm_id: str) -> Path:
    return paths.store_root() / "realm_sync_state" / f"{paths.safe_path_token(realm_id)}.shared_from.json"


def read_realm_shared_from(realm_id: str) -> dict[str, Any] | None:
    """``{server_id, server_name, reason, left_at}`` — the server a now-local
    realm was shared from — or ``None``. A pure file read (the snapshot's)."""
    try:
        raw = json.loads(realm_shared_from_path(realm_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("server_id"), str) or not raw["server_id"]:
        return None
    name = raw.get("server_name")
    return {
        "server_id": raw["server_id"],
        "server_name": name if isinstance(name, str) and name else None,
        "reason": raw.get("reason"),
        "left_at": raw.get("left_at"),
    }


def write_realm_shared_from(
    realm_id: str, *, server_id: str, server_name: str | None, reason: RealmRevokedReason
) -> dict[str, Any]:
    """Record where a realm came from. Holds ids, a display name and a reason
    only — never a URL, a token or a credential. No event: its caller's
    ``became_local`` event is the one that advances the watermark."""
    payload = {
        "schema_version": 1,
        "realm_id": realm_id,
        "server_id": server_id,
        "server_name": server_name or None,
        "reason": reason.value,
        "left_at": now().astimezone(UTC).isoformat(),
    }
    atomic_json_write(realm_shared_from_path(realm_id), payload)
    return read_realm_shared_from(realm_id) or {}


def mark_realm_revoked(realm: Realm, reason: RealmRevokedReason) -> dict[str, Any]:
    """Write the mark (idempotent: a repeat keeps the first ``revoked_at`` for
    the same reason) and advance the event watermark."""
    existing = read_realm_revocation(realm.id)
    if existing is not None and existing["reason"] == reason.value:
        return existing
    payload = {
        "schema_version": 1,
        "realm_id": realm.id,
        "reason": reason.value,
        "revoked_at": now().astimezone(UTC).isoformat(),
    }
    atomic_json_write(realm_revocation_path(realm.id), payload)
    _append_event(realm, "revoked")
    return read_realm_revocation(realm.id) or {}


def clear_realm_revocation(realm: Realm) -> bool:
    """Remove the mark (a re-grant). Returns whether one was there."""
    path = realm_revocation_path(realm.id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    _append_event(realm, "revocation_cleared")
    return True


def refuse_if_revoked(realm: Realm, *, credential_admitted: bool = False) -> None:
    """Raise ``realm_revoked`` (not retryable) for a marked realm. A host-state
    mark is lifted instead when the call carries a credential minted for this
    realm (``HOST_STATE_REASONS``)."""
    mark = read_realm_revocation(realm.id)
    if mark is None:
        return
    if mark["host_state"] and credential_admitted:
        clear_realm_revocation(realm)
        return
    raise RealmSyncError(
        REALM_REVOKED_CODE,
        "Access to this realm was revoked; local data is kept. A re-grant re-adopts it.",
        retryable=False,
        safe_details={"revoked_reason": mark["reason"], "host_state": mark["host_state"]},
    )


def _append_event(realm: Realm, change: str) -> None:
    """Advance the EventLog watermark (the registered ``realm.updated``
    contract) so the snapshot picks the mark up. Best effort: a broken event
    log never fails the mark."""
    try:
        EventLog().append(Event(now(), "realm.updated", None, None, None, {"realm_id": realm.id, "change": change}))
    except Exception:  # evidence channel, not the mutation
        pass
