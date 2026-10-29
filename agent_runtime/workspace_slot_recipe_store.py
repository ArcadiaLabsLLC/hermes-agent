"""The setup recipe's two doors: ``recipe.set`` writes the owner's part, ``recipe.show`` reads the checklist.

Plan ``docs/agent-runtime-harness/archive/build-running-work-2026-10-04.md`` §3.5 (row H10).
The recipe lives INSIDE the slot record (``slots.<name>.recipe``) of the slot document, so it
travels with the declaration as one decision (``workspace_slots_sync``); the policy that reads
it — derived steps, owner steps, readiness — is ``workspace_slot_recipe``.

* **set** replaces one slot's OWNER steps (annotations + ``command`` steps) and advances
  ``recipe.revision``. It is optimistic: the caller names the revision it edited from, and a
  recipe that moved since (another editor, a re-declaration, a peer's edit pulled in) is
  refused ``stale_revision`` — the higher revision always wins, locally as in the realm merge.
* **show** is read-only and probe-free: every live slot's materialised steps, each with its
  state on THIS machine read from this machine's last report (``machines.<me>``), and the
  ``ready`` answer. A machine that never reported, or a probe the report does not carry,
  reads ``unknown`` — never ready.
"""

from __future__ import annotations

from typing import Any

from .workspace_slot_recipe import normalize_owner_steps, readiness
from .workspace_slots import (
    REASON_SLOT_NOT_DECLARED,
    REASON_STALE_REVISION,
    SlotRefused,
    known_machine_id,
    live_slots,
    load_document,
    resolve_slot,
    write_document,
)

__layer__ = "stores"


def _revision(slot: dict[str, Any]) -> int:
    try:
        return int(((slot.get("recipe") or {}).get("revision")) or 0)
    except (TypeError, ValueError):
        return 0


def apply_recipe(slot: str, body: dict[str, Any], live: dict[str, dict[str, Any]], steps: Any, *, base_revision: Any,
                 issued_at: str, machine: str, persona_instance_id: str | None = None) -> int:
    """Replace ``body``'s owner steps in place (``stale_revision`` unless ``base_revision`` is current); the new revision.

    The one recipe edit, shared by a workspace document's write here and a Project record's
    (``project_store.ProjectStore.set_recipe``, the record's single writer).
    """

    current = _revision(body)
    if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision != current:
        raise SlotRefused(REASON_STALE_REVISION, f"the recipe is at revision {current}, the edit was made from {base_revision!r}")
    owner_steps = normalize_owner_steps(slot, body, steps, live)
    body["recipe"] = {"revision": current + 1, "steps": owner_steps, "edited_at": issued_at,
                      "edited_by": {"machine": machine, "persona_instance_id": persona_instance_id or None}}
    body["issued_at"] = issued_at
    return current + 1


def set_recipe(workspace_id: str | None, slot: str, steps: Any, *, base_revision: Any, issued_at: str, machine: str,
               persona_instance_id: str | None = None, project_id: str | None = None,
               credentials: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replace ``slot``'s owner steps where it is declared — the workspace's own document or its Project's record.

    ``base_revision`` must be the revision the editor read. A workspace-keyed edit of a slot a
    Project declares (a migrated workspace) lands in that Project's record, so no edit is ever
    written into a document frozen at ``migrated_to``.
    """

    resolved = resolve_slot(workspace_id, slot, project_id=project_id)
    if resolved is None:
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{project_id or workspace_id} declares no slot {slot!r}")
    edit = {"base_revision": base_revision, "issued_at": issued_at, "machine": machine,
            "persona_instance_id": persona_instance_id}
    if resolved.project_id:
        from .project_store import ProjectStore, load_project

        revision = ProjectStore(credentials).set_recipe(resolved.project_id, resolved.slot, steps, **edit)
        document = load_project(resolved.project_id)
    else:
        document = load_document(str(workspace_id))
        revision = apply_recipe(resolved.slot, live_slots(document)[resolved.slot], live_slots(document), steps, **edit)
        write_document(str(workspace_id), document)
    body = live_slots(document)[resolved.slot]
    return {"slot": resolved.slot, "project_id": resolved.project_id, "revision": revision,
            "recipe": _slot_checklist(workspace_id, resolved.slot, body, _my_rows(document),
                                      project_id=resolved.project_id)}


def _my_rows(document: dict[str, Any]) -> dict[str, Any]:
    machine = known_machine_id()
    mine = ((document.get("machines") or {}).get(machine) or {}) if machine else {}
    return mine.get("slots") or {}


def _slot_checklist(workspace_id: str | None, name: str, slot: dict[str, Any], rows: dict[str, Any], *,
                    project_id: str | None = None) -> dict[str, Any]:
    """One slot's checklist; ``runs`` is the newest Clone / command run of each step on THIS machine."""

    from .workspace_slot_runs import latest_runs

    recipe = slot.get("recipe") or {}
    return {"revision": _revision(slot), "edited_at": recipe.get("edited_at"), "edited_by": recipe.get("edited_by"),
            **readiness(name, slot, rows.get(name)), "runs": latest_runs(workspace_id, name, project_id=project_id)}


def _reported(document: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    machine = known_machine_id()
    return machine, (((document.get("machines") or {}).get(machine) or {}) if machine else {})


def show_recipe(workspace_id: str) -> dict[str, Any]:
    """Every live slot the workspace sees, with its checklist on THIS machine (no probe; the last report is the input).

    The slots are ``persona_slots.visible_slots``' — the workspace's own document's and each assigned
    Project's, keyed ``<project>/<slot>`` for a Project's — and each reads its owner's record and report.
    """

    from .persona_slots import visible_slots

    machine, mine = _reported(load_document(workspace_id))
    slots = {key: _slot_checklist(workspace_id, seen.name, seen.record, _my_rows(seen.document),
                                  project_id=seen.project_id)
             for key, seen in sorted(visible_slots(workspace_id).items())}
    return {"workspace_id": workspace_id, "machine": machine, "reported_at": mine.get("reported_at") or None,
            "slots": slots}


def show_project_recipe(project_id: str) -> dict[str, Any]:
    """``recipe.show`` for a Project: every live slot its record declares, with its checklist on THIS machine."""

    from .project_store import load_project, valid_project_id

    record = load_project(valid_project_id(project_id))
    machine, mine = _reported(record)
    rows = mine.get("slots") or {}
    return {"project_id": project_id, "machine": machine, "reported_at": mine.get("reported_at") or None,
            "slots": {name: _slot_checklist(None, name, slot, rows, project_id=project_id)
                      for name, slot in sorted(live_slots(record).items())}}


__all__ = ["apply_recipe", "set_recipe", "show_project_recipe", "show_recipe"]
