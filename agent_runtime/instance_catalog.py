"""Client-neutral projection of the existing persona-instance directory.

Two per-instance use facts ride each entry, each derived from its one owner, never stored here:
``last_used_at`` (the newest chat turn's start, from the turn journal; ``None`` when it has none)
and ``in_running_group_chat`` (a seat in a room that has not ended, from the discussion run store;
``None`` when this process holds no discussion service and cannot say).
"""
from __future__ import annotations

from collections.abc import Callable

from . import paths
from .bundled_agents import directory_fields, sync_shipped_agents
from .config import ensure_persisted_personas, load_agent_runtime_config
from .gateway_identity import read_install_identity
from .mission_chat_turns import last_turn_started_by_instance
from .persona_assignments import PersonaInstanceStore, is_canonical_persona_channel
from .persona_lifecycle import is_independent_agent_persona, is_runtime_persona
from .profile_context import active_profile_name, resolve_persona_profile
from .profile_persona_discovery import reconcile_profile_personas

__layer__ = "stores"


class InstanceCatalogUnavailable(ValueError):
    """An incomplete roster must not masquerade as an empty directory."""


def prepare_instance_catalog(seated: Callable[[str], frozenset[str] | None] = lambda _install_id: None) -> dict:
    """Discover profiles and materialize canonical identities without starting work.

    *seated* answers an install's instances seated in a running room, or ``None`` when it cannot say;
    the RPC door passes the discussion run store's answer (a lane, above this store)."""
    install_id = read_install_identity(paths.store_root()).install_id
    if not install_id:
        raise InstanceCatalogUnavailable("installation_unavailable")
    store = PersonaInstanceStore()
    _read_instances(store)
    config = load_agent_runtime_config()
    reconcile_profile_personas(config)
    sync_shipped_agents()
    personas = {p.id: p for p in ensure_persisted_personas(config) if is_runtime_persona(p)}
    for persona in personas.values():
        # The bulk snapshot helper also resets work state; discovery must not.
        if not is_independent_agent_persona(persona):
            store.ensure_for_persona(persona)
    last_used = last_turn_started_by_instance()
    seated_ids = seated(install_id)
    return {"install_id": install_id, "instance_conversations": 1, "agents": [
        {**_project(instance, personas.get(instance.persona_id), install_id),
         "last_used_at": last_used.get(instance.id),
         "in_running_group_chat": None if seated_ids is None else instance.id in seated_ids}
        for instance in _read_instances(store)
    ]}


def _read_instances(store):
    scan = store.scan_all()
    if scan.unreadable:
        raise InstanceCatalogUnavailable("instance_roster_unreadable")
    return scan.instances


def _project(instance, persona, install_id: str) -> dict:
    binding = resolve_persona_profile(persona) if persona is not None else None
    ready = binding is not None and binding.readiness == "ready"
    return {
        "install_id": install_id,
        "instance_id": instance.id,
        "persona_id": instance.persona_id,
        "display_name": instance.display_name,
        "workspace_id": instance.workspace_id,
        "canonical": is_canonical_persona_channel(instance),
        "profile": (binding.hermes_profile or active_profile_name()) if binding else None,
        "profile_home": str(binding.profile_home) if binding and binding.profile_home else None,
        "available": ready,
        "reason": None if ready else (binding.readiness if binding else "persona_not_found"),
        **directory_fields(persona),
    }
