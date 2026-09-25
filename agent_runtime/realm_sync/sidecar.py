"""The files the sync verbs leave behind: the status sidecar, the manifest, timestamps, events.

``read_realm_sync_sidecar`` is the only realm-sync surface ``build_snapshot`` may
touch; everything here is a best-effort receipt that never fails a sync verb.
"""

from __future__ import annotations

import json
import logging
from datetime import timezone
from pathlib import Path
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from .. import paths
from ..events import EventLog
from ..models import Event, Realm
from ..store import WorkspaceStore
from .models import RealmSyncArtifact, _canonicalize_text_bytes, _safe_display_path
from .ledgers import _skill_tombstone_rows
from .git import _realm_subtree, _sync_state
from .artifacts import _distinct_skill_package_count, realm_agent_selection_state

logger = logging.getLogger(__name__)

__layer__ = "stores"
__all__ = [
    "_append_realm_sync_event",
    "_held_profile_artifacts",
    "_sync_result",
    "_timestamp_file",
    "_workspace_sync_statuses",
    "_write_sync_metadata",
    "_write_sync_sidecar",
    "_write_timestamp",
    "read_realm_sync_sidecar",
    "realm_sync_sidecar_path",
]


def _append_realm_sync_event(event_type: str, realm: Realm, *, changed: bool, artifacts: int) -> None:
    """Advance the EventLog watermark after a sync mutation so stream /
    read-model consumers refresh (event-less store/sidecar writes are
    invisible to them). Emitted for pull/publish only — NEVER for
    status, which itself runs off published events and would loop.
    Best effort: a broken event log must not fail the sync verb."""
    try:
        EventLog().append(
            Event(
                now(),
                event_type,
                None,
                None,
                None,
                {
                    "realm_id": realm.id,
                    "changed": changed,
                    "artifacts": artifacts,
                },
            )
        )
    except Exception:  # noqa: BLE001 — evidence channel, not the mutation
        pass


def realm_sync_sidecar_path(realm_id: str) -> Path:
    return paths.store_root() / "realm_sync_state" / f"{paths.safe_path_token(realm_id)}.json"


def read_realm_sync_sidecar(realm_id: str) -> dict[str, Any] | None:
    """Read the cached sync state written by the sync verbs.

    Pure file read — this is the ONLY realm-sync surface ``build_snapshot`` may
    touch (Decision 7: zero git calls / artifact resolution in the snapshot).
    Returns ``None`` when no sidecar exists (launcher renders "not checked").
    """
    try:
        raw = json.loads(realm_sync_sidecar_path(realm_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return {
        "state": raw.get("state"),
        "ahead": raw.get("ahead"),
        "behind": raw.get("behind"),
        "skills_drift": raw.get("skills_drift") or [],
        "skill_publish_mode": raw.get("skill_publish_mode") or "all",
        "skill_selection": raw.get("skill_selection") or [],
        # Additive + absent-tolerant, like ``profile_artifacts_held`` below: a
        # sidecar written before the skill-delete ledger existed reports none.
        "skill_tombstones": raw.get("skill_tombstones") or [],
        "skills_published": raw.get("skills_published") or 0,
        "agent_publish_mode": raw.get("agent_publish_mode") or "workspace",
        "agent_selection": raw.get("agent_selection") or [],
        "agents_published": raw.get("agents_published") or 0,
        "conflicts": raw.get("conflicts") or [],
        "last_pull": raw.get("last_pull"),
        "last_publish": raw.get("last_publish"),
        "artifacts": raw.get("artifacts"),
        "checked_at": raw.get("checked_at"),
        "workspace_statuses": raw.get("workspace_statuses") or [],
        # Additive + absent-tolerant: a sidecar written before the profile-file
        # lane existed simply reports no holds.
        "profile_artifacts_held": raw.get("profile_artifacts_held") or [],
    }


def _held_profile_artifacts(realm: Realm, repo: Path) -> list[str]:
    """Profile-file entity keys currently HELD for this realm.

    A classify-only (``dry_run``) pass through the ONE applier — never a second
    decision table, and never a write from the status path.
    """

    from ..profile_artifact_sync import apply_profile_artifact_pull

    try:
        summary = apply_profile_artifact_pull(realm.id, _realm_subtree(repo, realm.id), dry_run=True)
    except Exception:  # noqa: BLE001 — status must never fail over an evidence field
        logger.exception("held profile-artifact classification failed for realm %s", realm.id)
        return []
    return sorted(set(summary.held))


def _write_sync_sidecar(
    realm: Realm,
    *,
    repo: Path,
    git: dict[str, Any],
    skills_drift: list[str],
    artifacts: list[RealmSyncArtifact],
    profile_artifacts_held: list[str] | None = None,
) -> None:
    agent_state = realm_agent_selection_state(realm.id)
    payload = {
        "schema_version": 2,
        "realm_id": realm.id,
        "state": _sync_state(git),
        "ahead": git["ahead"],
        "behind": git["behind"],
        "skills_drift": skills_drift,
        "skill_publish_mode": realm.skill_publish_mode,
        "skill_selection": sorted(realm.skill_selection or []),
        "skill_tombstones": _skill_tombstone_rows(realm),
        "skills_published": _distinct_skill_package_count(artifacts),
        "agent_publish_mode": agent_state["mode"],
        "agent_selection": agent_state["selection"],
        "agents_published": len(agent_state["published"]),
        "conflicts": git["conflicts"],
        "last_pull": _timestamp_file(repo, "last_pull.txt"),
        "last_publish": _timestamp_file(repo, "last_publish.txt"),
        "artifacts": len(artifacts),
        "checked_at": now().astimezone(timezone.utc).isoformat(),
        "workspace_statuses": _workspace_sync_statuses(realm, repo),
        "profile_artifacts_held": list(profile_artifacts_held or []),
    }
    try:
        atomic_json_write(realm_sync_sidecar_path(realm.id), payload)
    except OSError:
        return  # the sidecar is a best-effort snapshot cache; never fail the sync verb over it


def _write_sync_metadata(subtree: Path, *, realm: Realm, artifacts: list[RealmSyncArtifact]) -> None:
    manifest = {
        "schema_version": 1,
        "kind": "realm_sync_manifest",
        "realm_id": realm.id,
        "server_id": realm.server_id,
        "generated_at": now().isoformat(),
        "artifacts": [artifact.row() for artifact in artifacts],
    }
    (subtree / "manifest.json").write_bytes(
        _canonicalize_text_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
    )


def _sync_result(realm: Realm, action: str, state: str, artifacts: list[RealmSyncArtifact], *, repo: Path, git: dict[str, Any], changed: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": realm.id,
        "kind": "realm_sync",
        "action": action,
        "state": state,
        "ahead": git["ahead"],
        "behind": git["behind"],
        "conflicts": git["conflicts"],
        "changed": bool(changed),
        "artifacts": [artifact.row() for artifact in artifacts],
        "artifact_count": len(artifacts),
        "secrets_excluded": [],
        "sync_repo": _safe_display_path(repo),
        "updated_at": now(),
        "workspace_statuses": _workspace_sync_statuses(realm, repo),
    }


def _workspace_sync_statuses(realm: Realm, repo: Path) -> list[dict[str, str]]:
    """Return honest per-workspace publication truth for this realm.

    Local realms are device-owned. A server-bound workspace is published only
    when its current store file byte-matches the file in the checked-out realm
    subtree; a missing or changed remote artifact is unpublished. Transient
    syncing is deliberately a launcher phase, never persisted here.
    """
    workspace_store = WorkspaceStore()
    workspace_ids = set(realm.workspace_ids or [])
    for workspace in workspace_store.list_all(include_archived=True):
        if workspace.realm_id == realm.id:
            workspace_ids.add(workspace.id)
    rows: list[dict[str, str]] = []
    subtree = _realm_subtree(repo, realm.id) / "store" / "workspaces"
    for workspace_id in sorted(workspace_ids):
        local = paths.workspace_path(workspace_id)
        if not local.exists():
            continue
        if not realm.server_id:
            state = "local"
        else:
            published = subtree / f"{paths.safe_path_token(workspace_id)}.json"
            try:
                # Canonical compare: the published file is LF while the local
                # store file is CRLF on Windows — byte-equality would falsely
                # report a just-published workspace as "unpublished".
                matches = published.exists() and _canonicalize_text_bytes(published.read_bytes()) == _canonicalize_text_bytes(local.read_bytes())
            except OSError:
                matches = False
            state = "published" if matches else "unpublished"
        rows.append({"workspace_id": workspace_id, "state": state})
    return rows


def _timestamp_file(repo: Path, name: str) -> str | None:
    try:
        return (repo / ".git" / "hermes" / name).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_timestamp(repo: Path, name: str) -> None:
    path = repo / ".git" / "hermes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now().isoformat(), encoding="utf-8")
