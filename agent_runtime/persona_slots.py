"""A persona instance's repo-slot ASSIGNMENT, and the context its turns load from it (build plan §3.3).

The authority is the instance record (``assigned_slots``, ``primary_slot``,
``slots_issued_at``); the launcher's Agent Console edits it through
``runtime.persona.instance.slots.set`` (owner correction 2026-10-04) — the workspace side
declares and fills slots and never assigns agents.

* **A subset, never "all".** Every assigned name is a live slot the instance's workspace
  declares (``slot_not_in_workspace``); empty means NONE. A slot may sit in several
  instances' lists at once (OWNER 2026-10-04 example): ``set`` touches one record, so
  assigning a slot to the frontend agent never takes it from the backend agent. A slot the
  workspace removes is dropped from every assignment in the same write
  (:func:`drop_removed_slots`), and a primary that left is cleared.
* **ONE primary** (OWNER 2026-10-04 full-stack): the default working directory. Unset
  means the first assigned, and :func:`resolve_primary` says which it used —
  ``explicit | first_assigned | none`` — so a default is never mistaken for a choice.
  Instructions load for ALL assigned slots, never only the primary.
* **The context**: for each assigned slot BOUND here, each of the declaration's
  ``context.files`` (default ``CLAUDE.md`` AND ``AGENTS.md``) loads through the per-file
  loader (128 KB each, no total cap) as its OWN section headed by the slot name
  (``## launcher — CLAUDE.md``). Receipts list every assigned slot and every file —
  an unbound slot (``slot_unbound_here``, naming the machines that bind it) and a missing
  file (``missing``) included.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

__layer__ = "stores"

REASON_SLOT_NOT_IN_WORKSPACE = "slot_not_in_workspace"
REASON_PRIMARY_NOT_ASSIGNED = "primary_not_assigned"
REASON_INSTANCE_HAS_NO_WORKSPACE = "instance_has_no_workspace"
REASON_INSTANCE_NOT_FOUND = "instance_not_found"
REASON_STALE_REVISION = "stale_revision"
REASON_INVALID_REQUEST = "invalid_request"

PRIMARY_SOURCE_EXPLICIT = "explicit"
PRIMARY_SOURCE_FIRST_ASSIGNED = "first_assigned"
PRIMARY_SOURCE_NONE = "none"

#: The receipt the one-release ``--agents-file`` alias gets under an assignment (call 4e).
SUPERSEDED_BY_ASSIGNMENT = "superseded_by_assignment"


class SlotAssignmentRefused(ValueError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def resolve_primary(instance: Any) -> tuple[str | None, str]:
    """``(primary slot, primary_source)`` for an instance record."""

    assigned = list(getattr(instance, "assigned_slots", None) or [])
    primary = getattr(instance, "primary_slot", None)
    if primary and primary in assigned:
        return primary, PRIMARY_SOURCE_EXPLICIT
    if assigned:
        return assigned[0], PRIMARY_SOURCE_FIRST_ASSIGNED
    return None, PRIMARY_SOURCE_NONE


def _store():
    from .persona_assignments import PersonaInstanceStore

    return PersonaInstanceStore()


def _slot_instance(instance_id: str):
    try:
        return _store().get(instance_id)
    except (FileNotFoundError, KeyError) as exc:
        raise SlotAssignmentRefused(REASON_INSTANCE_NOT_FOUND, instance_id) from exc


def set_instance_slots(instance_id: str, slots: Any, primary: Any = None, *, issued_at: str) -> dict[str, Any]:
    """REPLACE one instance's assignment and primary; refusals are typed."""

    from .workspace_slots import live_slots, load_document, stamp_epoch

    if not isinstance(slots, list) or not all(isinstance(name, str) and name for name in slots):
        raise SlotAssignmentRefused(REASON_INVALID_REQUEST, "slots must be a list of slot names")
    issued = stamp_epoch(issued_at)
    if issued is None:
        raise SlotAssignmentRefused(REASON_INVALID_REQUEST, "issued_at must be an ISO-8601 stamp")
    instance = _slot_instance(instance_id)
    if not instance.workspace_id:
        raise SlotAssignmentRefused(REASON_INSTANCE_HAS_NO_WORKSPACE, "the canonical persona channel has no assignment")
    declared = live_slots(load_document(instance.workspace_id))
    unknown = [name for name in slots if name not in declared]
    if unknown:
        raise SlotAssignmentRefused(REASON_SLOT_NOT_IN_WORKSPACE, ", ".join(unknown))
    if primary is not None and primary not in slots:
        raise SlotAssignmentRefused(REASON_PRIMARY_NOT_ASSIGNED, str(primary))
    held = instance.slots_issued_at
    if held is not None and issued < held.timestamp():
        raise SlotAssignmentRefused(REASON_STALE_REVISION, "a newer assignment already landed")
    instance.assigned_slots = list(dict.fromkeys(slots))
    instance.primary_slot = primary or None
    instance.slots_issued_at = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    _store().update(instance)
    return show_instance_slots(instance_id)


def show_instance_slots(instance_id: str) -> dict[str, Any]:
    """``{workspace_id, slots: [{name, bound_here, path, status}], primary_slot, primary_source}``."""

    from .workspace_slots import bound_path, live_slots, load_document

    instance = _slot_instance(instance_id)
    declared = live_slots(load_document(instance.workspace_id)) if instance.workspace_id else {}
    rows = []
    for name in instance.assigned_slots or []:
        path = bound_path(name) if name in declared else None
        bound = bool(path and path.is_dir())
        status = "bound" if bound else ("unbound_here" if name in declared else "not_declared")
        rows.append({"name": name, "bound_here": bound, "path": str(path) if bound else None, "status": status})
    primary, source = resolve_primary(instance)
    return {"persona_instance_id": instance.id, "workspace_id": instance.workspace_id, "slots": rows,
            "primary_slot": primary, "primary_source": source}


def drop_removed_slots(workspace_id: str, removed: set[str] | frozenset[str]) -> list[str]:
    """Drop ``removed`` slot names from every instance of ``workspace_id``; returns the ids touched."""

    if not removed:
        return []
    store = _store()
    touched = []
    for instance in store.list_all():
        if instance.workspace_id != workspace_id or not set(instance.assigned_slots or []) & set(removed):
            continue
        store.patch_fields(
            instance.id,
            assigned_slots=[name for name in instance.assigned_slots if name not in removed],
            primary_slot=None if instance.primary_slot in removed else instance.primary_slot,
        )
        touched.append(instance.id)
    return touched


# ── the context a turn loads ─────────────────────────────────────────────────


@dataclass(frozen=True)
class SlotContextSection:
    slot: str
    file: str
    content: str

    @property
    def heading(self) -> str:
        return f"## {self.slot} — {self.file}"


@dataclass(frozen=True)
class SlotContext:
    """The assigned slots' context for one turn: sections, receipts, and the primary."""

    sections: tuple[SlotContextSection, ...] = ()
    receipts: tuple[dict[str, Any], ...] = ()
    primary_slot: str | None = None
    primary_source: str = PRIMARY_SOURCE_NONE
    primary_path: str | None = None
    bound: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    workspace_id: str = ""

    @property
    def bindings(self) -> tuple[Any, ...]:
        """The bound assigned slots as overlay bindings (the turn's env scope, §3.3)."""

        from .workspace_slot_overlay import SlotBinding

        return tuple(SlotBinding(self.workspace_id, slot, path) for slot, path in self.bound)

    @property
    def content(self) -> str:
        return "\n\n".join(f"{section.heading}\n\n{section.content.strip()}" for section in self.sections)


def _file_receipt(slot: str, file: str, loaded: Any) -> dict[str, Any]:
    receipt = dict(getattr(loaded, "receipt", None) or {})
    receipt.pop("preview", None)
    receipt.update(slot=slot, file=file, label=f"{slot}/{file}", kind="workspace_context")
    return receipt


def _unbound_receipt(slot: str, document: dict[str, Any]) -> dict[str, Any]:
    from .workspace_slots import binding_machines

    machines = binding_machines(document, slot)
    return {"slot": slot, "label": slot, "kind": "workspace_context", "included": False, "status": "slot_unbound_here",
            "evidence": "bound on " + (", ".join(machines) if machines else "no reporting machine")}


def load_slot_context(instance: Any) -> SlotContext | None:
    """The turn's slot context, or None when the instance has no assignment (EMPTY ⇒ nothing, never all)."""

    from .prompt_observability.workspace_agents import load_workspace_agents_context
    from .workspace_slots import DEFAULT_CONTEXT_FILES, bound_path, live_slots, load_document

    assigned = list(getattr(instance, "assigned_slots", None) or [])
    workspace_id = getattr(instance, "workspace_id", None)
    if not assigned or not workspace_id:
        return None
    document = load_document(workspace_id)
    declared = live_slots(document)
    sections: list[SlotContextSection] = []
    receipts: list[dict[str, Any]] = []
    bound: list[tuple[str, str]] = []
    for slot in assigned:
        path = bound_path(slot) if slot in declared else None
        if path is None or not path.is_dir():
            receipts.append(_unbound_receipt(slot, document) if slot in declared else
                            {"slot": slot, "label": slot, "kind": "workspace_context", "included": False,
                             "status": "slot_not_declared"})
            continue
        bound.append((slot, str(path)))
        files = (declared[slot].get("context") or {}).get("files") or list(DEFAULT_CONTEXT_FILES)
        for file in files:
            loaded = load_workspace_agents_context(str(Path(path) / file), allowed_names=None)
            receipts.append(_file_receipt(slot, file, loaded))
            if getattr(loaded, "content", None):
                sections.append(SlotContextSection(slot, file, loaded.content))
    primary, source = resolve_primary(instance)
    primary_path = dict(bound).get(primary) if primary else None
    return SlotContext(tuple(sections), tuple(receipts), primary, source, primary_path, tuple(bound), workspace_id)
