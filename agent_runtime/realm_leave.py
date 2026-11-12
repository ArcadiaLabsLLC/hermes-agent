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
* each workspace's brain lets go of the team's shared task repository (``work_store.default_brain.
  detach_left_remote``): its remote and its declared slot ``brain`` go, its history stays, and Work written in
  the local copy is never pushed to the team;
* the revocation mark and the cached sync state are cleared: both describe a bound realm, and the
  ``shared_from`` record is now the history. Kept, the mark would refuse a local realm's own sync
  ``realm_revoked`` and tell the client its access was revoked for a realm it now simply owns.

Nothing is sent anywhere: the team's copy is not changed by a member leaving. Archive then follows
the local rules (``realm_manage.archive_realm``).

The leave also OWES A RE-KEY (``realm_rekey.owe_rekey``; owner 2026-11-12: "it should be rekeyd as
soon as you leave"): the local copy takes a realm id, workspace ids, board ids and agents of its own
the first moment nothing is running (``realm_rekey_triggers``; at once when the serve is idle), so
that a re-join can bring the server's realm back FRESH beside it — the team's ids, the team's
agents and their chats — instead of binding this realm again and merging. Nothing done while local
is published by a re-join; the local copy stays the member's, labelled by its ``shared_from`` record.

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
from .realm_rekey import owe_rekey
from .realm_sync.revocation import (
    MEMBER_ACCESS_REASONS,
    RealmRevokedReason,
    clear_realm_revocation,
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
    # Each workspace's brain stops pushing to the team's shared task repository (RT-LEFT-REALM-BRAIN-STILL-PUSHES-
    # TO-THE-TEAM): the copy's Work stays on this machine. Before the re-key, which then commits the copy's own ids
    # into a brain that is this machine's alone (``realm_rekey_git._commit_new_ids``).
    _detach_brains(realm.id)
    # Owed outside the assign lock (``owe_rekey`` takes it itself). The map is the realm as it is at THIS
    # moment: what the team's copy publishes. What the member adds from here on is theirs alone and keeps
    # its ids. A crash before this line leaves a local realm that owes nothing; a re-join owes it then
    # (``realm_rekey_triggers.make_way_for_rejoin``).
    owe_rekey(realm.id, reason=reason.value)
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


def _detach_brains(realm_id: str) -> None:
    from .clock import now_iso
    from .store import WorkspaceStore
    from .work_store.default_brain import detach_left_remote

    realm = RealmStore().get(realm_id)
    held = [item.id for item in WorkspaceStore().list_all(include_archived=True) if item.realm_id == realm_id]
    at = now_iso()
    for workspace_id in dict.fromkeys([*realm.workspace_ids, *held]):
        detach_left_remote(workspace_id, at=at)


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
