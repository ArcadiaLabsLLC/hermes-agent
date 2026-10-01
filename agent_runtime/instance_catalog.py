"""Client-neutral projection of the existing persona-instance directory."""
from __future__ import annotations

from . import paths
from .config import ensure_persisted_personas, load_agent_runtime_config
from .gateway_identity import read_install_identity
from .persona_assignments import PersonaInstanceStore, is_canonical_persona_channel
from .persona_lifecycle import is_runtime_persona
from .profile_context import active_profile_name, resolve_persona_profile
from .profile_persona_discovery import reconcile_profile_personas

__layer__ = "stores"


class InstanceCatalogUnavailable(ValueError):
    """An incomplete roster must not masquerade as an empty directory."""


def prepare_instance_catalog() -> dict:
    """Discover profiles and materialize canonical identities without starting work."""
    install_id = read_install_identity(paths.store_root()).install_id
    if not install_id:
        raise InstanceCatalogUnavailable("installation_unavailable")
    store = PersonaInstanceStore()
    _read_instances(store)
    config = load_agent_runtime_config()
    reconcile_profile_personas(config)
    personas = {p.id: p for p in ensure_persisted_personas(config) if is_runtime_persona(p)}
    for persona in personas.values():
        # The bulk snapshot helper also resets work state; discovery must not.
        store.ensure_for_persona(persona)
    return {"install_id": install_id, "agents": [
        _project(instance, personas.get(instance.persona_id), install_id)
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
    }
