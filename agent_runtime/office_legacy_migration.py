"""One-shot startup cleanups of old office schema on disk — delete and report.

The owner's standing rule (2026-09-18): old schema is deleted and the count
reported, never kept alive by a compatibility path. Each step below is one such
deletion, run once per store: its report is written to
``<store>/migrations/<marker>`` and the marker's presence makes the next start a
single stat. Same shape as ``persona_toolsets_migration``.

Every rewrite happens under the workspace's ``office_lock``. A workspace whose
lock or files fail is reported in ``errors`` and the marker is NOT written, so
the next start retries; a failure never raises out of plugin load.

``STEPS`` is the table: ``(marker name, step function)``. A step takes the
store root and returns its report dict.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import atomic_json_write

__layer__ = "stores"

__all__ = [
    "STEPS",
    "is_legacy_desk_item",
    "run_office_legacy_migrations_once",
    "strip_item_minted_kind",
    "sweep_legacy_desks",
]

logger = logging.getLogger(__name__)

#: The retired ``OfficeItem`` key (RT-OFFICEITEM-MINTED-KIND): stamped by every
#: upsert since H-H12, read by nothing since the desk-litter census was deleted.
RETIRED_ITEM_KEY = "minted_kind"


def _actor_files(store_root: Path) -> list[tuple[str, Path]]:
    """Every live and archived actor file, with the workspace token it sits under."""

    office = Path(store_root) / "office"
    found: list[tuple[str, Path]] = []
    if not office.is_dir():
        return found
    for workspace in sorted(entry for entry in office.iterdir() if entry.is_dir()):
        for sub in ("actors", "archive"):
            directory = workspace / sub
            if directory.is_dir():
                found.extend((workspace.name, path) for path in sorted(directory.glob("*.json")))
    return found


def strip_item_minted_kind(store_root: Path) -> dict[str, Any]:
    """Remove ``minted_kind`` from every item of every actor file; count it."""

    from .locks import office_lock

    stripped_items = 0
    files: list[str] = []
    errors: list[dict[str, str]] = []
    by_workspace: dict[str, list[Path]] = {}
    for workspace, path in _actor_files(store_root):
        by_workspace.setdefault(workspace, []).append(path)
    for workspace, paths in by_workspace.items():
        try:
            with office_lock(workspace):
                for path in paths:
                    row = json.loads(path.read_text(encoding="utf-8"))
                    items = row.get("items") if isinstance(row, dict) else None
                    if not isinstance(items, list):
                        continue
                    count = sum(
                        1 for item in items if isinstance(item, dict) and RETIRED_ITEM_KEY in item
                    )
                    if not count:
                        continue
                    for item in items:
                        if isinstance(item, dict):
                            item.pop(RETIRED_ITEM_KEY, None)
                    # The store's own writer shape (``office_store.files``).
                    atomic_json_write(path, row, indent=2, sort_keys=True)
                    stripped_items += count
                    files.append(f"{workspace}/{path.parent.name}/{path.name}")
        except Exception as exc:  # noqa: BLE001 - reported, retried next start
            errors.append({"workspace": workspace, "error": type(exc).__name__})
            logger.warning("office_minted_kind_strip_failed workspace=%s error=%s", workspace, type(exc).__name__)
    if stripped_items:
        logger.warning("office_minted_kind_stripped items=%d files=%d", stripped_items, len(files))
    return {"stripped_items": stripped_items, "files": files, "errors": errors}


def is_legacy_desk_item(item: Any) -> bool:
    """A desk addressed by a PERSONA — written by the per-persona-desk era.

    The launcher's rule (``missionOfficeIsLegacyDeskAddress``, owner ruling 5,
    2026-09-18), spelled once on this side: a generic desk is self-addressed
    (its ``persona_id`` IS its ``item_id``), so a desk filed under anything else
    is legacy. Blank on either side is not legacy.
    """

    if not isinstance(item, dict) or str(item.get("kind") or "").strip() != "desk":
        return False
    item_id = str(item.get("item_id") or "").strip()
    persona_id = str(item.get("persona_id") or "").strip()
    return bool(item_id and persona_id and item_id != persona_id)


def sweep_legacy_desks(store_root: Path) -> dict[str, Any]:
    """Drop every legacy desk from every LIVE actor file (RT-DROPPED-LEGACY-DESK-LEAVES).

    The launcher drops these at its load chokepoint, but that is a read: an
    actor whose only item was a legacy desk was never rewritten, so its file
    stayed. An actor that keeps other items is rewritten without the desks
    (revision + 1); an actor left with none is archived through
    ``OfficeStore.remove_actor``, the office's one delete. Archived copies are
    left to the archive retention.
    """

    from hermes_time import now

    from .locks import office_lock
    from .office_store import OfficeStore
    from .serde import to_jsonable

    dropped = 0
    rewritten: list[str] = []
    emptied: list[tuple[str, str]] = []
    errors: list[dict[str, str]] = []
    by_workspace: dict[str, list[Path]] = {}
    for workspace, path in _actor_files(store_root):
        if path.parent.name == "actors":
            by_workspace.setdefault(workspace, []).append(path)
    for workspace, paths in by_workspace.items():
        try:
            with office_lock(workspace):
                for path in paths:
                    row = json.loads(path.read_text(encoding="utf-8"))
                    items = row.get("items") if isinstance(row, dict) else None
                    if not isinstance(items, list):
                        continue
                    kept = [item for item in items if not is_legacy_desk_item(item)]
                    if len(kept) == len(items):
                        continue
                    dropped += len(items) - len(kept)
                    if not kept:
                        emptied.append((str(row.get("workspace_id") or workspace), str(row.get("actor_key") or "")))
                        continue
                    row["items"] = kept
                    row["revision"] = int(row.get("revision") or 0) + 1
                    row["updated_at"] = to_jsonable(now())
                    row["updated_by"] = "legacy_desk_sweep"
                    atomic_json_write(path, row, indent=2, sort_keys=True)
                    rewritten.append(f"{workspace}/{path.name}")
        except Exception as exc:  # noqa: BLE001 - reported, retried next start
            errors.append({"workspace": workspace, "error": type(exc).__name__})
            logger.warning("office_legacy_desk_sweep_failed workspace=%s error=%s", workspace, type(exc).__name__)
    archived: list[str] = []
    store = OfficeStore()
    for workspace_id, actor_key in emptied:
        try:
            store.remove_actor(
                workspace_id, actor_key, reason="legacy_desk_sweep", updated_by="legacy_desk_sweep"
            )
            archived.append(f"{workspace_id}/{actor_key}")
        except Exception as exc:  # noqa: BLE001 - reported, retried next start
            errors.append({"workspace": workspace_id, "actor_key": actor_key, "error": type(exc).__name__})
    if dropped:
        logger.warning(
            "office_legacy_desks_dropped desks=%d rewritten=%d archived=%d",
            dropped,
            len(rewritten),
            len(archived),
        )
    return {
        "dropped_desks": dropped,
        "rewritten_actors": rewritten,
        "archived_actors": archived,
        "errors": errors,
    }


STEPS: tuple[tuple[str, Callable[[Path], dict[str, Any]]], ...] = (
    ("office_item_minted_kind.json", strip_item_minted_kind),
    ("office_legacy_desks.json", sweep_legacy_desks),
)


def run_office_legacy_migrations_once() -> dict[str, dict[str, Any]]:
    """Run every step whose marker is absent for the active store; return the
    reports of the steps that ran (an empty dict when all had already run)."""

    from . import paths

    store_root = paths.store_root()
    ran: dict[str, dict[str, Any]] = {}
    if not store_root.is_dir():  # never create a store for a home that has none
        return ran
    for marker_name, step in STEPS:
        marker = store_root / "migrations" / marker_name
        if marker.exists():
            continue
        report = {
            "schema": "hermes.agent_runtime.office_legacy_migration/v1",
            "ran_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            **step(store_root),
        }
        ran[marker_name] = report
        if not report.get("errors"):
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ran
