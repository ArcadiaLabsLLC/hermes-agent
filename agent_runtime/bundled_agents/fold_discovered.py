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
* each placement instance is re-pointed to the shipped agent, keeping its id, so its
  chats move with it;
* its own channel (``personainst_profile_<name>``) is folded onto the shipped
  agent's channel the way the store reconciler folds a legacy id
  (``persona_instance_identity``): the row is archived and a durable alias names the
  shipped channel, so its old chats open, and send, there;
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


def _fold_channel_onto(store, instance, canonical_id: str) -> None:
    """Fold a persona's own channel onto another's, as the reconciler's phase 1 folds a legacy id.

    The row is archived (never deleted) and a durable alias names ``canonical_id``, so
    the old id, and the chats minted under it, resolve there for history, open and send
    (``persona_chat_session._persona_chat_session_owner``).
    """

    from hermes_time import now

    from .. import paths
    from ..persona_instance_identity import _archive_row, _save_persona_instance_aliases, load_persona_instance_aliases

    _archive_row(instance.id, paths.persona_instances_archive_dir() / f"{now().strftime('%Y%m%dT%H%M%SZ')}_fold")
    aliases = load_persona_instance_aliases()
    aliases[instance.id] = canonical_id
    _save_persona_instance_aliases(aliases)
    store._event(  # store maintenance, as the reconciler's fold
        "persona_instance.reconciled", instance, {"from_id": instance.id, "to_id": canonical_id, "action": "folded"},
    )


def fold_discovered(shipped: ShippedAgent, record: AgentPersona, store) -> dict[str, Any]:
    """Make ``shipped`` the one agent over ``record``'s profile; returns the fold's receipt."""

    from ..agent_duplicate import _repoint
    from ..persona_assignments import PersonaInstanceStore, is_canonical_persona_channel

    held = next((persona for persona in store.list_all() if persona.id == shipped.id), None)
    if held is not None and shipped_reference(held) is not None:
        reference = held  # already the shipped agent: its own settings stand
    else:
        reference = store.save(reference_record(shipped, settings=replace(record, readiness={})))
    instances = PersonaInstanceStore()
    channel = instances.ensure_for_persona(reference)
    moved: list[str] = []
    folded: list[str] = []
    for instance in instances.scan_all().instances:
        if instance.persona_id != record.id:
            continue
        if is_canonical_persona_channel(instance):
            _fold_channel_onto(instances, instance, channel.id)
            folded.append(instance.id)
        else:
            moved.append(_repoint(instance.id, reference))
    return {
        "persona_id": record.id,
        "name": record.display_name,
        "instances_moved": sorted(moved),
        "channels_folded": {instance_id: channel.id for instance_id in sorted(folded)},
        "record_archived": _archive_record(record.id),
    }
