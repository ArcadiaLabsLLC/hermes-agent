"""The WORKSPACE_SLOTS realm-sync family: the slot document, merged key-wise at three depths.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §3.1 (call 4d:
key-wise, never whole-document HOLD — a HOLD would block a realm's detection over a rename).

* **Slot names union.** A name only one side holds is kept. A name both sides hold resolves
  to ONE side's record: the newer ``recipe.revision``, then the newer ``issued_at``. Removal
  is a TOMBSTONE (``removed_at`` + the removal's ``issued_at``), so a stale peer that still
  holds the slot live loses to the newer removal instead of resurrecting it.
* **Inside a slot**, ``repo`` / ``toolchain`` / ``context`` / ``recipe`` travel together as
  the winning record — a declaration is one decision, never spliced from two.
* **``machines`` by machine id**: disjoint by construction (each machine writes only its own
  key); the same id on both sides is this machine's report echoed back, and the newer
  ``reported_at`` wins.

Publish copies the document verbatim; this applier is the only writer on pull (the generic
overwrite loop never touches ``store/workspace_slots/``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .workspace_slots import load_document_from, stamp_epoch, write_document

__layer__ = "stores"

PUBLISHED_ROOT = "store/workspace_slots"


def _slot_rank(slot: dict[str, Any]) -> tuple[int, float]:
    recipe = slot.get("recipe") if isinstance(slot.get("recipe"), dict) else {}
    try:
        revision = int(recipe.get("revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    return revision, stamp_epoch(slot.get("issued_at")) or 0.0


def _newer(a: dict[str, Any] | None, b: dict[str, Any] | None, rank) -> dict[str, Any] | None:
    if a is None or b is None:
        return a if b is None else b
    return b if rank(b) > rank(a) else a


def _report_rank(entry: dict[str, Any]) -> float:
    return stamp_epoch(entry.get("reported_at")) or 0.0


def merge_documents(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """The key-wise merge of two slot documents (pure)."""

    slots: dict[str, Any] = {}
    local_slots, remote_slots = local.get("slots") or {}, remote.get("slots") or {}
    for name in sorted(set(local_slots) | set(remote_slots)):
        slots[name] = _newer(local_slots.get(name), remote_slots.get(name), _slot_rank)
    machines: dict[str, Any] = {}
    local_machines, remote_machines = local.get("machines") or {}, remote.get("machines") or {}
    for machine in sorted(set(local_machines) | set(remote_machines)):
        machines[machine] = _newer(local_machines.get(machine), remote_machines.get(machine), _report_rank)
    issued = max((local.get("issued_at") or "", remote.get("issued_at") or ""), key=lambda s: stamp_epoch(s) or 0.0)
    return {
        "schema_version": local.get("schema_version") or remote.get("schema_version"),
        "workspace_id": local.get("workspace_id") or remote.get("workspace_id"),
        "issued_at": issued,
        "slots": slots,
        "machines": machines,
    }


@dataclass
class WorkspaceSlotsPullSummary:
    """One pull's accounting for the family, emitted unconditionally (``source: null`` = nothing published)."""

    source: int | None = None
    merged: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.merged)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "merged": list(self.merged), "unchanged": list(self.unchanged),
                "refused": list(self.refused)}


def apply_workspace_slots_pull(realm_id: str, subtree: Path) -> WorkspaceSlotsPullSummary:
    """Merge every published slot document into this machine's copy."""

    summary = WorkspaceSlotsPullSummary()
    published = Path(subtree) / PUBLISHED_ROOT
    if not published.is_dir():
        return summary
    files = sorted(published.glob("*.json"))
    summary.source = len(files)
    for path in files:
        remote = load_document_from(path)
        if not isinstance(remote.get("slots"), dict):
            summary.refused.append({"document": path.name, "reason": "slot_document_malformed"})
            continue
        local_path = paths.workspace_slots_dir() / path.name
        local = load_document_from(local_path) if local_path.is_file() else {}
        merged = merge_documents(local, remote)
        if json.dumps(merged, sort_keys=True) == json.dumps(local, sort_keys=True):
            summary.unchanged.append(path.stem)
            continue
        workspace_id = str(merged.get("workspace_id") or path.stem)
        write_document(workspace_id, merged)
        summary.merged.append(path.stem)
        _drop_newly_removed(workspace_id, local, merged)
    return summary


def _drop_newly_removed(workspace_id: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    """A peer's tombstone that won the merge leaves every local assignment too (§3.3)."""

    from .persona_slots import drop_removed_slots

    was_live = {name for name, slot in (before.get("slots") or {}).items() if not (slot or {}).get("removed_at")}
    now_removed = {name for name, slot in (after.get("slots") or {}).items() if (slot or {}).get("removed_at")}
    drop_removed_slots(workspace_id, frozenset(was_live & now_removed))


def publish_artifacts(workspaces: list[Any]) -> list[Any]:
    """One artifact per workspace of the realm that has a slot document (copied verbatim)."""

    from .realm_sync.families import SyncFamily
    from .realm_sync.models import RealmSyncArtifact

    artifacts = []
    for workspace in workspaces:
        source = paths.workspace_slots_path(workspace.id)
        if source.is_file():
            artifacts.append(RealmSyncArtifact(kind=SyncFamily.WORKSPACE_SLOTS, source=source,
                                               relative_path=f"{PUBLISHED_ROOT}/{source.name}", destination=source))
    return artifacts
