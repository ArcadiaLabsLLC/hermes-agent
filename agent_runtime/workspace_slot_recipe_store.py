"""The setup recipe's two doors: ``recipe.set`` writes the owner's part, ``recipe.show`` reads the checklist.

Plan ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §3.5 (row H10).
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
    write_document,
)

__layer__ = "stores"


def _revision(slot: dict[str, Any]) -> int:
    try:
        return int(((slot.get("recipe") or {}).get("revision")) or 0)
    except (TypeError, ValueError):
        return 0


def set_recipe(workspace_id: str, slot: str, steps: Any, *, base_revision: Any, issued_at: str, machine: str,
               persona_instance_id: str | None = None) -> dict[str, Any]:
    """Replace ``slot``'s owner steps; ``base_revision`` must be the revision the editor read."""

    document = load_document(workspace_id)
    live = live_slots(document)
    body = live.get(slot)
    if body is None:
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{workspace_id} declares no slot {slot!r}")
    current = _revision(body)
    if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision != current:
        raise SlotRefused(REASON_STALE_REVISION, f"the recipe is at revision {current}, the edit was made from {base_revision!r}")
    owner_steps = normalize_owner_steps(slot, body, steps, live)
    body["recipe"] = {"revision": current + 1, "steps": owner_steps, "edited_at": issued_at,
                      "edited_by": {"machine": machine, "persona_instance_id": persona_instance_id or None}}
    body["issued_at"] = issued_at
    write_document(workspace_id, document)
    return {"slot": slot, "revision": current + 1, "recipe": _slot_checklist(workspace_id, slot, body, _my_rows(document))}


def _my_rows(document: dict[str, Any]) -> dict[str, Any]:
    machine = known_machine_id()
    mine = ((document.get("machines") or {}).get(machine) or {}) if machine else {}
    return mine.get("slots") or {}


def _slot_checklist(workspace_id: str, name: str, slot: dict[str, Any], rows: dict[str, Any]) -> dict[str, Any]:
    """One slot's checklist; ``runs`` is the newest Clone / command run of each step on THIS machine."""

    from .workspace_slot_runs import latest_runs

    recipe = slot.get("recipe") or {}
    return {"revision": _revision(slot), "edited_at": recipe.get("edited_at"), "edited_by": recipe.get("edited_by"),
            **readiness(name, slot, rows.get(name)), "runs": latest_runs(workspace_id, name)}


def show_recipe(workspace_id: str) -> dict[str, Any]:
    """Every live slot's checklist on THIS machine (no probe; the last report is the input)."""

    document = load_document(workspace_id)
    machine = known_machine_id()
    mine = ((document.get("machines") or {}).get(machine) or {}) if machine else {}
    rows = mine.get("slots") or {}
    return {"workspace_id": workspace_id, "machine": machine, "reported_at": mine.get("reported_at") or None,
            "slots": {name: _slot_checklist(workspace_id, name, slot, rows) for name, slot in sorted(live_slots(document).items())}}


__all__ = ["set_recipe", "show_recipe"]
