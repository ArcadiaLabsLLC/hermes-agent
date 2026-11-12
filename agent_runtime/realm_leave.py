"""A realm whose server you left, or were removed from, becomes a local realm
(RT-LEFT-SERVER-REALM-STAYS-LISTED).

The owner's rule (2026-11-12): "keep it incase you have llocal custom modifications, only it is now a
local realm". ``runtime.realm.revoked`` with a member-access reason (``MEMBER_ACCESS_REASONS``) calls
:func:`make_realm_local`:

* the realm record drops ``server_id`` and ``sync_manifest_ref`` (the team's repository address), so
  no sync verb can reach the team's copy again — a later publish or pull is a local realm's, against
  the ``local`` sync repo, never the server's;
* where it came from is kept in the install-local ``shared_from`` record
  (``realm_sync/revocation.py``), which the snapshot's realm row carries as ``shared_from``;
* the server's sync clone on this machine goes once no realm is bound to that server any more — it is
  the publish projection of the team's repository (its address, its fetch log), not the realm's
  data, which lives in the store and is not touched;
* the revocation mark and the cached sync state are cleared: both describe a bound realm, and the
  ``shared_from`` record is now the history. Kept, the mark would refuse a local realm's own sync
  ``realm_revoked`` and tell the client its access was revoked for a realm it now simply owns.

Nothing is sent anywhere: the team's copy is not changed by a member leaving. Archive then follows
the local rules (``realm_manage.archive_realm``). A re-grant (``realm_membership.adopt_realms``)
binds the SAME realm again by its id and drops the record. The drift baselines are set aside at the
leave (``keep_team_baselines``) and put back at the re-grant, so whatever the realm's own publishes
and pulls did while it was local, the next status reads the store against what this install and the
team last agreed on: what changed while local shows as drift and is kept by the next pull, as for
any member who edited offline — it is neither taken away nor sent without a publish.

Pinned by ``tests/agent_runtime/test_realm_leave.py``.
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from . import paths
from .locks import workspace_realm_assign_lock
from .realm_sync.revocation import (
    MEMBER_ACCESS_REASONS,
    RealmRevokedReason,
    clear_realm_revocation,
    keep_team_baselines,
    read_realm_revocation,
    read_realm_shared_from,
    write_realm_shared_from,
)
from .realm_sync.sidecar import realm_sync_sidecar_path
from .store import RealmStore
from .store_events import emit_store_event

__layer__ = "lanes"
__all__ = ["make_marked_realms_local", "make_realm_local"]


def make_realm_local(
    realm_id: str, reason: RealmRevokedReason, *, server_name: str | None = None
) -> tuple[dict[str, Any] | None, bool]:
    """Returns ``(shared_from, changed)``. ``changed`` is False — nothing written, no event — for a
    realm that is already local: a replayed ``realm.revoked`` answers the first record, and a realm
    that never had a server answers ``None``. Held under the workspace/realm assign lock, like
    archive, so a move or an archive never sees the realm half converted.

    The record is written BEFORE the realm, so a crash between the two leaves a bound realm with a
    record nobody reads (the snapshot shows it only for a server-less realm) and the replay finishes
    the job."""
    if reason not in MEMBER_ACCESS_REASONS:
        raise ValueError(f"{reason.value} is the git host's state, not a loss of the member's access")
    realms = RealmStore()
    with workspace_realm_assign_lock():
        realm = realms.get(realm_id)
        if not realm.server_id:
            return read_realm_shared_from(realm.id), False
        server_id = realm.server_id
        record = write_realm_shared_from(realm.id, server_id=server_id, server_name=server_name, reason=reason)
        keep_team_baselines(realm.id)
        realm.server_id = None
        realm.sync_manifest_ref = None
        realm = realms.save(realm, emit_event=False)
        _drop_server_clone(server_id, realms)
        realm_sync_sidecar_path(realm.id).unlink(missing_ok=True)
        clear_realm_revocation(realm)
        emit_store_event(
            realms.event_log,
            "realm.updated",
            {"realm_id": realm.id, "change": "became_local", "server_id": server_id},
            domain="store",
        )
    return record, True


def make_marked_realms_local() -> list[str]:
    """Convert every still-bound realm whose revocation mark is a member-access reason — a mark
    written before this rule existed. Returns the realm ids converted. Run after an adopt, which has
    just lifted the mark of every realm the member still holds."""
    converted = []
    for realm in RealmStore().list_all(include_archived=True):
        mark = read_realm_revocation(realm.id) if realm.server_id else None
        if mark is None or mark["host_state"]:
            continue
        if make_realm_local(realm.id, RealmRevokedReason(mark["reason"]))[1]:
            converted.append(realm.id)
    return converted


def _drop_server_clone(server_id: str, realms: RealmStore) -> None:
    """Remove the server's sync clone (``realm_sync/<server>``) once no realm is bound to that server.
    A repository pinned by a local-path ``sync_manifest_ref`` is the member's own checkout and is
    never under that root, so it is never touched. Best effort: a clone that cannot be removed whole
    loses its remotes instead, so no address stays configured in it."""
    if any(item.server_id == server_id for item in realms.list_all(include_archived=True)):
        return
    clone = paths.realm_sync_root() / paths.safe_path_token(server_id)
    if not (clone / ".git").exists():
        return
    try:
        _remove_tree(clone)
    except OSError:
        from .realm_sync.git import _git

        for name in _git(clone, "remote", check=False).split():
            _git(clone, "remote", "remove", name, check=False)


def _remove_tree(path: Path) -> None:
    def _writable(func, target, _exc) -> None:  # git object files are read-only on Windows
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_writable)
    else:  # pragma: no cover - 3.11
        shutil.rmtree(path, onerror=lambda f, t, e: _writable(f, t, e))
