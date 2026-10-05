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
  key). This machine's own key is authored HERE ONLY: a peer's copy of ``machines.<me>`` is
  this machine's report echoed back and is ignored on pull, never merged over the local row,
  whatever its ``reported_at``. Another machine's key resolves to the newer ``reported_at``.

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
* a document filed under another workspace's name is refused whole (``slot_document_misfiled``);
* another machine's report (``machines.<id>``) is shape-checked against what
  ``workspace_slots_probe.report`` writes — statuses from its vocabularies, versions as versions,
  keys as identifiers, unknowns through ``UnknownsIndex`` (kind checked, evidence re-redacted) —
  and carried as that machine's, never re-stamped: a malformed entry drops whole, a malformed
  slot ROW drops alone (``invalid_machine_report``);
* a STAMP past this machine's clock plus ``STAMP_SKEW_SECONDS`` is not believed
  (``stamp_in_future``): a slot record or machine entry carrying one drops whole, a document
  ``issued_at`` carrying one is not merged — so a broken or forged peer clock cannot outrank every
  honest write made until then, nor wedge a local ``declare`` as ``stale_revision``.

Each drop is a typed row in ``WorkspaceSlotsPullSummary.refused`` — ``{document, slot | machine
| field, step?, reason}`` — and never carries the refused value: a name or id that is not a safe
identifier is named by a short digest instead, and a stamp is never printed. Because the dropped value never enters this machine's document,
this machine's next publish (a verbatim copy) cannot carry it back out.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .builds.unknowns import UnknownsIndex
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
    known_machine_id,
    load_document_from,
    normalize_declaration,
    stamp_epoch,
    stamp_horizon,
    stamp_in_future,
    write_document,
)
from .workspace_slots_probe import (
    CHECKOUT_MATCHES,
    CHECKOUT_NOT_A_REPO,
    CHECKOUT_REMOTE_MISMATCH,
    PROBE_MISSING,
    PROBE_SET,
    PROBE_UNKNOWN,
    STATUS_NEEDS_SETUP,
    STATUS_NOT_CLONED,
    STATUS_PATH_MISSING,
    STATUS_READY,
    STATUS_UNKNOWN,
)

__layer__ = "stores"

PUBLISHED_ROOT = "store/workspace_slots"

REASON_DOCUMENT_MALFORMED = "slot_document_malformed"
#: The document's ``workspace_id`` does not own the file name it was published under.
REASON_DOCUMENT_MISFILED = "slot_document_misfiled"

#: A peer's report row or machine entry that is not the shape ``workspace_slots_probe.report`` writes.
REASON_INVALID_MACHINE_REPORT = "invalid_machine_report"
#: A peer stamp past this machine's clock plus ``STAMP_SKEW_SECONDS``.
REASON_STAMP_IN_FUTURE = "stamp_in_future"

#: The report vocabularies (``workspace_slots_probe``): a peer row speaks only these words.
_ROW_STATUSES = frozenset({STATUS_READY, STATUS_NEEDS_SETUP, STATUS_NOT_CLONED, STATUS_PATH_MISSING, STATUS_UNKNOWN})
_CHECKOUTS = frozenset({CHECKOUT_MATCHES, CHECKOUT_REMOTE_MISMATCH, CHECKOUT_NOT_A_REPO, PROBE_UNKNOWN})
_PROBES = frozenset({PROBE_SET, PROBE_MISSING, PROBE_UNKNOWN})
_ROW_KEYS = frozenset({"status", "bound", "checkout", "tools", "env_keys", "dotenv", "unknowns", "adopted_existing_root"})
_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")

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


def _held_slot(name: str, record: Any, names: frozenset[str], refused: list[dict[str, str]],
               now: float) -> dict[str, Any]:
    """One peer slot record rebuilt from what the validators return, or :class:`SlotRefused`."""

    if not isinstance(record, dict):
        raise SlotRefused(REASON_INVALID_DECLARATION, "record")
    _, body = normalize_declaration({"name": name, "repo": record.get("repo"), "toolchain": record.get("toolchain"),
                                     "context": record.get("context")})
    held = {**body, "recipe": _held_recipe(name, body, record.get("recipe"), names, refused),
            "declared_at": _text_or_none(record.get("declared_at")),
            "declared_by_machine": _text_or_none(record.get("declared_by_machine")),
            "issued_at": _text_or_none(record.get("issued_at")), "removed_at": _text_or_none(record.get("removed_at"))}
    stamps = (held["declared_at"], held["issued_at"], held["removed_at"], held["recipe"]["edited_at"])
    if any(stamp_in_future(stamp, now=now) for stamp in stamps):
        raise SlotRefused(REASON_STAMP_IN_FUTURE, "a slot stamp runs past this machine's clock")
    return held


# ── another machine's report, shape-checked against what ``report`` writes ───


class _ReportRefused(Exception):
    def __init__(self, reason: str = REASON_INVALID_MACHINE_REPORT) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse() -> Any:
    raise _ReportRefused()


def _statuses(value: Any) -> dict[str, str]:
    """A ``{key: set|missing|unknown}`` map with identifier keys, else :class:`_ReportRefused`."""

    if not isinstance(value, dict) or not all(isinstance(k, str) and _KEY_RE.match(k) and v in _PROBES
                                               for k, v in value.items()):
        raise _ReportRefused()
    return dict(value)


def _held_tools(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise _ReportRefused()
    held = {}
    for name, tool in value.items():
        version = tool.get("version") if isinstance(tool, dict) else None
        if (not isinstance(name, str) or not _KEY_RE.match(name) or not isinstance(tool, dict)
                or set(tool) - {"status", "version"} or tool.get("status") not in _PROBES
                or not (version is None or (isinstance(version, str) and _VERSION_RE.match(version)))):
            raise _ReportRefused()
        held[name] = {"status": tool["status"], "version": version}
    return held


def _held_dotenv(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"present", "keys"} or not isinstance(value["present"], bool):
        raise _ReportRefused()
    return {"present": value["present"], "keys": _statuses(value["keys"])}


def _held_unknowns(value: Any, now: float) -> list[dict[str, Any]]:
    """The row's unknowns through the ONE unknowns index: kind checked, evidence re-redacted and bounded."""

    if not isinstance(value, list):
        raise _ReportRefused()
    index = UnknownsIndex()
    if index.extend_wire(value):
        raise _ReportRefused()
    held = index.wire()
    if any(entry["seen_at"] > stamp_horizon(now) for entry in held):
        raise _ReportRefused(REASON_STAMP_IN_FUTURE)
    return held


#: Each optional part of a report row and its check; a part the row does not carry stays absent.
_ROW_PARTS = {
    "checkout": lambda value, now: value if value in _CHECKOUTS else _refuse(),
    "tools": lambda value, now: _held_tools(value),
    "env_keys": lambda value, now: _statuses(value),
    "dotenv": lambda value, now: _held_dotenv(value),
    "unknowns": _held_unknowns,
    "adopted_existing_root": lambda value, now: value if isinstance(value, bool) else _refuse(),
}


def _held_report_row(row: Any, now: float) -> dict[str, Any]:
    """One slot row of another machine's report, rebuilt part by part, or :class:`_ReportRefused`."""

    if (not isinstance(row, dict) or set(row) - _ROW_KEYS or row.get("status") not in _ROW_STATUSES
            or not isinstance(row.get("bound"), bool)):
        raise _ReportRefused()
    held = {"status": row["status"], "bound": row["bound"]}
    for part, check in _ROW_PARTS.items():
        if part in row:
            held[part] = check(row[part], now)
    return held


def _held_machine(entry: Any, now: float, refused: list[dict[str, str]], label: str) -> dict[str, Any]:
    """Another machine's whole entry, ``{reported_at, slots}``, or :class:`_ReportRefused`."""

    if (not isinstance(entry, dict) or set(entry) != {"reported_at", "slots"} or not isinstance(entry["slots"], dict)
            or not isinstance(entry["reported_at"], str) or stamp_epoch(entry["reported_at"]) is None):
        raise _ReportRefused()
    if stamp_in_future(entry["reported_at"], now=now):
        raise _ReportRefused(REASON_STAMP_IN_FUTURE)
    slots = {}
    for name in sorted(entry["slots"], key=str):
        try:
            if not isinstance(name, str) or not _ROOT_NAME_RE.match(name):
                raise _ReportRefused()
            slots[name] = _held_report_row(entry["slots"][name], now)
        except _ReportRefused as exc:
            refused.append({"machine": label, "slot": _label(name), "reason": exc.reason})
    return {"reported_at": entry["reported_at"], "slots": slots}


def _held_machines(raw: Any, *, me: str | None, now: float, refused: list[dict[str, str]]) -> dict[str, Any]:
    """Every OTHER machine's entry, held; ``machines.<me>`` is this machine's to write and is skipped."""

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        refused.append({"field": "machines", "reason": REASON_INVALID_MACHINE_REPORT})
        return {}
    machines = {}
    for machine in sorted(raw, key=str):
        if me is not None and machine == me:
            continue  # this machine's own report echoed back: authored here only, never pulled over ours
        label = _label(machine)
        try:
            if label != machine or ":" in machine:
                raise _ReportRefused()
            machines[machine] = _held_machine(raw[machine], now, refused, label)
        except _ReportRefused as exc:
            refused.append({"machine": label, "reason": exc.reason})
    return machines


def held_document(remote: dict[str, Any], *, me: str | None = None,
                  now: float | None = None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """``(document, refused)``: a peer's slot document with every invalid entry dropped.

    ``refused`` rows are ``{slot | machine | field, step?, reason}``. A step that fails drops
    alone; a slot whose name, declaration or stamps fail drops whole, its steps unlisted; another
    machine's entry drops whole, a row of it alone. ``machines.<me>`` is never taken from a peer,
    and a document ``issued_at`` past this machine's horizon is not merged.
    """

    now = time.time() if now is None else now
    refused: list[dict[str, str]] = []
    issued = remote.get("issued_at")
    if stamp_in_future(issued, now=now):
        refused.append({"field": "issued_at", "reason": REASON_STAMP_IN_FUTURE})
        issued = ""
    machines = _held_machines(remote.get("machines"), me=me, now=now, refused=refused)
    raw = remote.get("slots") or {}
    names = frozenset(name for name in raw if isinstance(name, str) and _ROOT_NAME_RE.match(name))
    slots: dict[str, Any] = {}
    for name in sorted(raw, key=str):
        if name not in names:
            refused.append({"slot": _label(name), "reason": REASON_INVALID_SLOT_NAME})
            continue
        steps_refused: list[dict[str, str]] = []
        try:
            slots[name] = _held_slot(name, raw[name], names, steps_refused, now)
        except SlotRefused as exc:
            refused.append({"slot": name, "reason": exc.reason})
            continue
        refused.extend(steps_refused)
    return {**remote, "issued_at": issued, "slots": slots, "machines": machines}, refused


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


def apply_workspace_slots_pull(realm_id: str, subtree: Path, *, now: float | None = None) -> WorkspaceSlotsPullSummary:
    """Merge every published slot document into this machine's copy (``now``: this machine's clock)."""

    summary = WorkspaceSlotsPullSummary()
    me, now = known_machine_id(), time.time() if now is None else now
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
        remote, refused = held_document(remote, me=me, now=now)
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
