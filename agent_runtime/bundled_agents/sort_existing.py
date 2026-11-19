"""Sort the records an install already holds under a shipped agent's id.

Row ``RT-BUNDLED-AGENTS-EXISTING-RECORDS-SORTED`` (owner 2026-11-19): an install
made before shipped agents lived in the build holds Base / Neko as ordinary
records. Each one is sorted ONCE, by an explicit run (dry run first), never on
boot:

* ``adopt`` — the record's definition and SOUL match the build: it becomes a
  reference. Its id, instances and chats are untouched.
* ``copy`` — it differs: it is duplicated, memory and SOUL included, under a new
  name (default ``"<shipped name> Beta"``, owner 2026-11-19 for his Neko; never a
  suffix — a taken name refuses that record), the duplicate records ``based_on``,
  every placement instance moves to it with its chats, and the original id
  becomes the shipped reference beside it. The agent's own channel (the
  canonical instance, whose id IS the original's) stays with the shipped agent;
  its chats stay openable there (owner 2026-11-19: an instance opens its
  persona's old chats).
* ``place`` — the install holds no record under the id: the shipped reference is
  added (owner: "also place the shipped Neko in the owner's namespace").

Settings (model, provider, reasoning mode, budgets) are never a difference and
stay on the reference. Nothing is deleted.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..models import AgentPersona
from .catalog import SHIPPED_AGENTS, ShippedAgent
from .resolve import _definition, _soul_edited, reference_record, shipped_reference

__layer__ = "stores"

__all__ = ["apply_sort", "plan_sort"]


def _differences(record: AgentPersona, shipped: ShippedAgent) -> list[str]:
    mine = _definition(record)
    fields = [name for name, value in shipped.definition.items() if mine.get(name) != value]
    return [*fields, "soul"] if _soul_edited(shipped) else fields


def _instances_of(persona_id: str) -> tuple[list[str], list[str]]:
    """(placement instance ids, canonical instance ids) of ``persona_id``."""

    from ..persona_assignments import PersonaInstanceStore, is_canonical_persona_channel

    placed, canonical = [], []
    for instance in PersonaInstanceStore().scan_all().instances:
        if instance.persona_id == persona_id:
            (canonical if is_canonical_persona_channel(instance) else placed).append(instance.id)
    return sorted(placed), sorted(canonical)


def _entry(shipped: ShippedAgent, record: AgentPersona | None, names: dict[str, str], roster) -> dict[str, Any]:
    from ..agent_duplicate import name_is_taken

    entry: dict[str, Any] = {"persona_id": shipped.id, "shipped_name": shipped.name}
    if record is None:
        return {**entry, "action": "place"}
    if shipped_reference(record) is not None:
        return {**entry, "action": "none", "why": "already a reference"}
    differences = _differences(record, shipped)
    placed, canonical = _instances_of(shipped.id)
    if not differences:
        return {**entry, "action": "adopt", "instances_kept": placed + canonical}
    copy_name = names.get(shipped.id) or f"{shipped.name} Beta"
    entry.update(
        action="copy", differences=differences, current_name=record.display_name, copy_name=copy_name,
        instances_moved=placed, instances_kept=canonical,
    )
    if name_is_taken(copy_name, roster):
        entry["refused"] = "agent_name_taken"
    return entry


def plan_sort(names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """What :func:`apply_sort` would do, read only."""

    from ..config import ensure_persisted_personas
    from ..store import AgentStore

    roster = ensure_persisted_personas()
    stored = {persona.id: persona for persona in AgentStore().list_all()}
    return [_entry(shipped, stored.get(shipped.id), names or {}, roster) for shipped in SHIPPED_AGENTS]


def _place(shipped: ShippedAgent, store) -> None:
    from hermes_cli.profiles import get_profile_dir

    from ..fresh_install_seed import stage_shipped_profile

    soul = shipped.soul_text()
    home = get_profile_dir(shipped.definition["hermes_profile"])
    if soul is not None and not (home.exists() or home.is_symlink()):
        stage_shipped_profile(home, soul, shipped.id)
    store.save(reference_record(shipped))


def _copy(entry: dict[str, Any], shipped: ShippedAgent, record: AgentPersona, store) -> dict[str, Any]:
    from ..agent_duplicate import _repoint, duplicate_agent

    copy = duplicate_agent(shipped.id, entry["copy_name"]).persona
    for instance_id in entry["instances_moved"]:
        _repoint(instance_id, copy)
    store.save(reference_record(shipped, settings=record))
    return {**entry, "copy_id": copy.id, "copy_profile": copy.hermes_profile}


def apply_sort(names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Carry out :func:`plan_sort`; returns the receipt (the plan, with what was made)."""

    from ..store import AgentStore

    store = AgentStore()
    stored = {persona.id: persona for persona in store.list_all()}
    receipt: list[dict[str, Any]] = []
    for entry in plan_sort(names):
        shipped = next(agent for agent in SHIPPED_AGENTS if agent.id == entry["persona_id"])
        action = entry["action"] if "refused" not in entry else "none"
        if action == "adopt":
            store.save(replace(stored[shipped.id], origin="eternia"))
        elif action == "place":
            _place(shipped, store)
        elif action == "copy":
            entry = _copy(entry, shipped, stored[shipped.id], store)
        receipt.append({**entry, "applied": action != "none"})
    return receipt
