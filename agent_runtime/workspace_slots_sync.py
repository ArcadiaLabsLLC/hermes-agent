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

**A peer's document is validated before it is merged** (:func:`held_document`), by the SAME
validators a local edit runs — ``normalize_declaration`` for a slot record, ``normalize_owner_step``
for each stored recipe step — one entry at a time:

* a slot whose NAME is not a root name, or whose declaration fails (a clone URL carrying userinfo,
  a malformed toolchain / context / recipe) is dropped WHOLE: the local record of that name, when
  there is one, stays as it was;
* a recipe STEP that fails (a credential-shaped argv / label / hint / url, a field a stored step
  never carries, a malformed command) is dropped ALONE: its slot and the slot's other steps merge;
* a document filed under another workspace's name is refused whole (``slot_document_misfiled``).

Each drop is a typed row in ``WorkspaceSlotsPullSummary.refused`` — ``{document, slot, step?,
reason}`` — and never carries the refused value: a name or id that is not a safe identifier is
named by a short digest instead. Because the dropped value never enters this machine's document,
this machine's next publish (a verbatim copy) cannot carry it back out.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .machine_roots import _ROOT_NAME_RE
from .workspace_slot_recipe import (
    REASON_DUPLICATE_STEP_ID,
    RecipeRefused,
    derived_by_id,
    normalize_owner_step,
)
from .workspace_slots import (
    REASON_INVALID_DECLARATION,
    REASON_INVALID_SLOT_NAME,
    SlotRefused,
    load_document_from,
    normalize_declaration,
    stamp_epoch,
    write_document,
)

__layer__ = "stores"

PUBLISHED_ROOT = "store/workspace_slots"

REASON_DOCUMENT_MALFORMED = "slot_document_malformed"
#: The document's ``workspace_id`` does not own the file name it was published under.
REASON_DOCUMENT_MISFILED = "slot_document_misfiled"

#: A label a refusal may print as-is: an identifier with no ``=``, no ``://``, no space — so no
#: assignment, no URL userinfo, no bearer value fits — optionally behind a derived-step prefix.
_SAFE_LABEL_RE = re.compile(r"^(?:(?:tool|env_key):)?[A-Za-z0-9_.+-]{1,64}$")


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


# ── a peer's document, validated entry by entry ──────────────────────────────


def _label(value: Any) -> str:
    """How a refusal names a slot or step: itself when a safe identifier, else a digest — never the value."""

    text = str(value if value is not None else "")
    if _SAFE_LABEL_RE.match(text):
        return text
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _held_recipe(name: str, body: dict[str, Any], recipe: Any, names: frozenset[str],
                 refused: list[dict[str, str]]) -> dict[str, Any]:
    """The slot's recipe with every step that fails the shared validator dropped (and accounted)."""

    recipe = {} if recipe is None else recipe
    if not isinstance(recipe, dict):
        raise SlotRefused(REASON_INVALID_DECLARATION, "recipe")
    revision, steps = recipe.get("revision", 0), recipe.get("steps")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0 or not isinstance(steps, (list, type(None))):
        raise SlotRefused(REASON_INVALID_DECLARATION, "recipe")
    derived = derived_by_id(name, body)
    kept: list[dict[str, Any]] = []
    for entry in steps or []:
        step_id = entry.get("id") if isinstance(entry, dict) else None
        try:
            step = normalize_owner_step(entry, name, derived, names, held=True)
            if any(other["id"] == step["id"] for other in kept):
                raise RecipeRefused(REASON_DUPLICATE_STEP_ID)
        except RecipeRefused as exc:
            refused.append({"slot": name, "step": _label(step_id), "reason": exc.reason})
            continue
        kept.append(step)
    edited_by = recipe.get("edited_by")
    return {"revision": revision, "steps": kept, "edited_at": _text_or_none(recipe.get("edited_at")),
            "edited_by": {"machine": _text_or_none(edited_by.get("machine")),
                          "persona_instance_id": _text_or_none(edited_by.get("persona_instance_id"))}
            if isinstance(edited_by, dict) else None}


def _held_slot(name: str, record: Any, names: frozenset[str], refused: list[dict[str, str]]) -> dict[str, Any]:
    """One peer slot record rebuilt from what the validators return, or :class:`SlotRefused`."""

    if not isinstance(record, dict):
        raise SlotRefused(REASON_INVALID_DECLARATION, "record")
    _, body = normalize_declaration({"name": name, "repo": record.get("repo"), "toolchain": record.get("toolchain"),
                                     "context": record.get("context")})
    return {**body, "recipe": _held_recipe(name, body, record.get("recipe"), names, refused),
            "declared_at": _text_or_none(record.get("declared_at")),
            "declared_by_machine": _text_or_none(record.get("declared_by_machine")),
            "issued_at": _text_or_none(record.get("issued_at")), "removed_at": _text_or_none(record.get("removed_at"))}


def held_document(remote: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """``(document, refused)``: a peer's slot document with every invalid slot and step dropped.

    ``refused`` rows are ``{slot, step?, reason}``. A step that fails drops alone; a slot whose
    name or declaration fails drops whole, its steps unlisted.
    """

    raw = remote.get("slots") or {}
    names = frozenset(name for name in raw if isinstance(name, str) and _ROOT_NAME_RE.match(name))
    slots: dict[str, Any] = {}
    refused: list[dict[str, str]] = []
    for name in sorted(raw, key=str):
        if name not in names:
            refused.append({"slot": _label(name), "reason": REASON_INVALID_SLOT_NAME})
            continue
        steps_refused: list[dict[str, str]] = []
        try:
            slots[name] = _held_slot(name, raw[name], names, steps_refused)
        except SlotRefused as exc:
            refused.append({"slot": name, "reason": exc.reason})
            continue
        refused.extend(steps_refused)
    return {**remote, "slots": slots}, refused


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
            summary.refused.append({"document": path.name, "reason": REASON_DOCUMENT_MALFORMED})
            continue
        owner = remote.get("workspace_id")
        if not isinstance(owner, str) or not owner or paths.workspace_slots_path(owner).name != path.name:
            summary.refused.append({"document": path.name, "reason": REASON_DOCUMENT_MISFILED})
            continue
        remote, refused = held_document(remote)
        summary.refused.extend({"document": path.name, **row} for row in refused)
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
