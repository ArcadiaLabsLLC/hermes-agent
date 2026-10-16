"""The workspace LEVEL family's revert arm — its row in ``realm_revert._FAMILY_ARMS``.

Plan: ``docs/agent-runtime-harness/planned/realm-level-revert-arm-2026-10-15.md`` S2
(owner-approved 2026-10-15). Every write goes through ``level_sync.LevelStore``, the
family's one door, so a revert writes nothing a pull could not have written:

* RESTORE / ADOPT write the last-pulled subtree's bytes VERBATIM (the pull's adopt);
* ARCHIVE_LOCAL (a level the realm never carried) copies the local bytes into
  ``<realm sync root>/<realm>/level_conflicts/archive/`` and then clears the store
  file — recoverable, never a bare delete (ruling 3). The archive is a SUBFOLDER on
  purpose: the status ``levels.held`` list is the top level of ``level_conflicts``,
  and an archived level is not a hold.

The admission door is the pull's own, ``validate_level_document``, which
``read_remote_levels`` already ran: a remote level that will not validate comes back
UNREADABLE from the upstream reader, never absent, so it is refused before any arm.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths

__layer__ = "lanes"


def read_level_upstream(subtree: Path) -> tuple[dict[str, bytes], set[str]]:
    """``(levels by workspace token, tokens whose published file will not read)``."""

    from .level_sync import read_remote_levels

    levels, refused = read_remote_levels(subtree)
    return levels, {str(row.get("key")) for row in refused}


def refuse_level_door(_item_key: str, _entity: Any) -> None:
    """No second door: the pull's (``validate_level_document``) ran in the reader."""

    return None


def level_archive_path(realm_id: str, workspace_token: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        paths.realm_sync_root()
        / paths.safe_path_token(realm_id)
        / "level_conflicts"
        / "archive"
        / f"{paths.safe_path_token(workspace_token)}.{stamp}.json"
    )


def apply_level(item: Any, entity: Any, action: Any, *, realm_id: str | None, **_stores: Any) -> None:
    """The one store write a decided level revert makes. Raises; the caller accounts."""

    from utils import atomic_write_bytes

    from .level_sync import LevelStore
    from .realm_revert import RevertAction

    store = LevelStore()
    token = item.item_key
    if action is not RevertAction.ARCHIVE_LOCAL:
        store.write(token, entity)
        return
    if not realm_id:
        raise ValueError("a level archive needs its realm")
    local = store.read(token)
    if local is not None:
        archive = level_archive_path(realm_id, token)
        archive.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(archive, local)
    store.clear(token)


def level_content_hash(item: Any) -> str:
    """The store's post-write bytes, hashed as the drift walk and the publish hash them."""

    from .level_sync import LevelStore, level_document_hash

    raw = LevelStore().read(item.item_key)
    if raw is None:
        raise FileNotFoundError(item.item_key)
    return level_document_hash(raw)
