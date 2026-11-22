"""Fold the agent profile discovery found on a shipped agent's profile into the shipped agent.

Row ``RT-SHIPPED-BASE-LEAVES-A-SECOND-BASE-IN-AN-OLDER-NAMESPACE`` (review w1118a.44
D4). Profile discovery (``profile_persona_discovery``) promotes a named profile no
record owns to ``profile_<name>``. An install whose first directory read came before
the shipped Base was placed therefore holds ``profile_base`` over the ``base``
profile; placing the shipped ``base`` beside it, by ``persona sort-shipped`` or by a
realm pull, used to list Base twice, and the extra one could not be copied.

:func:`discovered_over` finds that persona only while the person has not edited it
(every definition field still what discovery wrote). :func:`fold_discovered` then
makes the shipped agent the one Base, deleting nothing:

* the persona's settings (model, provider, budgets) stay on the shipped reference,
  as the sort's rule says (``sort_existing``);
* each instance is re-pointed to the shipped agent, keeping its id, so its chats
  move with it. Its own channel (``personainst_profile_<name>``) is one of them: it
  used to be folded onto the shipped agent's hidden copy, which nothing mints any
  more (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT), so it stays an
  instance of the shipped agent under its own id, its chats with it;
* its record is moved out of the live roster into ``agents_archive/``.

A discovered persona the person edited is theirs and is left as it is (an edge case,
documented on the row, not worked).
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from typing import Any

from ..models import AgentPersona
from .catalog import DEFINITION_FIELDS, ShippedAgent
from .resolve import _definition_value, reference_record, shipped_reference

__layer__ = "stores"

__all__ = ["discovered_over", "fold_discovered"]

#: Profile discovery's own marker on a record it wrote.
_DISCOVERED_MARK = "auto_discovered_profile"


def _discovered_definition(profile: str) -> dict[str, Any]:
    """The definition profile discovery writes for ``profile`` (``reconcile_profile_personas``)."""

    display = " ".join(
        word[:1].upper() + word[1:] for word in profile.replace("-", "_").split("_") if word
    ) or profile
    return {
        "display_name": display,
        "role": "profile",
        "autonomy": "propose_only",
        "hermes_profile": profile,
        "skills": [],
        "system_prompt_path": "",
        "soul_overlay_path": None,
        "required_mcp_servers": [],
        "include_profile_memory": True,
        "include_core_context_files": False,
    }


def discovered_over(shipped: ShippedAgent, stored: dict[str, AgentPersona]) -> AgentPersona | None:
    """The unedited discovered persona over ``shipped``'s profile in ``stored``, if any."""

    profile = str(shipped.definition.get("hermes_profile") or "")
    record = stored.get(f"profile_{profile}") if profile else None
    if record is None or record.hermes_profile != profile:
        return None
    if not (record.readiness or {}).get(_DISCOVERED_MARK):
        return None
    if record.origin or record.based_on or record.character_assignment:
        return None
    mine = {name: _definition_value(getattr(record, name)) for name in DEFINITION_FIELDS}
    return record if mine == _discovered_definition(profile) else None


def _archive_record(persona_id: str) -> str:
    from hermes_time import now

    from .. import paths
    from ..locks import agent_record_write_lock

    source = paths.agent_path(persona_id)
    archive = paths.store_root() / "agents_archive" / f"{now().strftime('%Y%m%dT%H%M%SZ')}_shipped_fold"
    with agent_record_write_lock("persona", persona_id):
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(archive / source.name))
    return str(archive / source.name)


def fold_discovered(shipped: ShippedAgent, record: AgentPersona, store) -> dict[str, Any]:
    """Make ``shipped`` the one agent over ``record``'s profile; returns the fold's receipt."""

    from ..agent_duplicate import _repoint
    from ..persona_assignments import PersonaInstanceStore

    held = next((persona for persona in store.list_all() if persona.id == shipped.id), None)
    if held is not None and shipped_reference(held) is not None:
        reference = held  # already the shipped agent: its own settings stand
    else:
        reference = store.save(reference_record(shipped, settings=replace(record, readiness={})))
    instances = PersonaInstanceStore()
    moved = [_repoint(instance.id, reference) for instance in instances.scan_all().instances
             if instance.persona_id == record.id]
    return {
        "persona_id": record.id,
        "name": record.display_name,
        "instances_moved": sorted(moved),
        "record_archived": _archive_record(record.id),
    }
