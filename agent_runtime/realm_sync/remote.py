"""``harness realm sync remote set|clear``: point a server-less realm at a backup repository.

A local realm backs up the same way a ``local:`` credential's ``git_url`` makes it
(``git._adopt_local_remote``): the URL becomes the realm's ``sync_manifest_ref`` and
the shared local sync repo's ``origin``. A server realm's remote is the server's and
is never set here. RT-HARNESS-REALM-SET-BACKUP-REMOTE: before this verb a lane
hand-edited the realm JSON, and a ``file://`` URL there was read as a path.
"""

from __future__ import annotations

from typing import Any

from ..redaction import redact_url
from ..store import RealmStore
from .git import (
    _REPO_CONFIG,
    _adopt_local_remote,
    _ensure_sync_repo,
    _git,
    _looks_like_remote,
    _sync_repo_path,
)
from .models import RealmSyncError

__layer__ = "lanes"
__all__ = ["clear_realm_backup_remote", "set_realm_backup_remote"]


def _server_less(realm_id: str):
    realm = RealmStore().get(realm_id)
    if realm.server_id:
        raise RealmSyncError(
            "realm_server_bound",
            "A server realm syncs with its server's repository; only a local realm takes a backup remote.",
        )
    return realm


def _answer(realm, remote: str | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "realm_sync_remote",
        "id": realm.id,
        "remote": redact_url(remote) if remote else None,
    }


def set_realm_backup_remote(realm_id: str, url: str) -> dict[str, Any]:
    """Adopt ``url`` (``file://``, ``https://``, ``ssh://``, ``git@``) as the realm's backup remote."""

    realm = _server_less(realm_id)
    url = str(url or "").strip()
    if not _looks_like_remote(url):
        raise RealmSyncError(
            "invalid_remote", "A backup remote is a file://, https://, ssh:// or git@ repository URL."
        )
    repo = _ensure_sync_repo(realm)
    _adopt_local_remote(realm, repo, url, config=_REPO_CONFIG)
    return _answer(RealmStore().get(realm.id), url)


def clear_realm_backup_remote(realm_id: str) -> dict[str, Any]:
    """Undo ``set``: the realm forgets its remote; the shared repo's ``origin`` goes once no
    other local realm names it."""

    realm = _server_less(realm_id)
    url = str(realm.sync_manifest_ref or "")
    if not _looks_like_remote(url):
        return _answer(realm, None)  # no remote (or a pinned local path, which is not one)
    repo = _sync_repo_path(realm)
    realm.sync_manifest_ref = None
    RealmStore().save(realm, emit_event=False)
    still_named = any(
        not other.server_id and str(other.sync_manifest_ref or "") == url
        for other in RealmStore().list_all(include_archived=True)
    )
    if not still_named and (repo / ".git").exists():
        _git(repo, "remote", "remove", "origin", check=False)
    return _answer(realm, None)
