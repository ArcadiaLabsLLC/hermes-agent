"""Idempotent, local-only promotion of named Hermes profiles to Personas.

Discovery never starts an agent, changes the selected Hermes executable, or
changes a previously authored Persona. A profile with any existing owner is
already represented; an unrelated row occupying the deterministic id is a
conflict, not permission to overwrite it.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from .models import AgentPersona
from .personas import AutonomyLevel, PROFILE_ROLE_SENTINEL

__layer__ = "stores"

if TYPE_CHECKING:
    from .config import AgentRuntimeConfig
    from .store import AgentStore

_LOG = logging.getLogger(__name__)
_DISCOVERY_LOCK = threading.Lock()


def reconcile_profile_personas(
    cfg: AgentRuntimeConfig | None = None,
    *,
    store: AgentStore | None = None,
) -> list[AgentPersona]:
    """Create one proposal-only Persona for each *unowned* named profile.

    Existing config-defined and stored bindings win, including multiple owners.
    Failed discovery is never interpreted as an empty authoritative roster.
    This is an explicit write operation, not part of the config/store merge.
    """
    from agent_runtime.profile_home import available_profile_template_summaries
    from hermes_cli.profiles import list_profile_names
    from hermes_constants import named_profile_has_servable_identity
    from .config import load_agent_runtime_config, persona_records_from_config
    from .store import AgentStore

    with _DISCOVERY_LOCK:
        store = store or AgentStore()
        # Template summaries alone include tombstoned/marker-less ghost dirs;
        # only the CLI's live identity roster may authorize a persisted row.
        live_names = set(list_profile_names()) - {"default"}
        profiles = [
            profile for profile in available_profile_template_summaries()
            if profile.name in live_names
            and named_profile_has_servable_identity(profile.path)
        ]
        if not profiles:
            return []
        cfg = cfg or load_agent_runtime_config()
        stored = {persona.id: persona for persona in store.list_all()}
        catalog = {persona.id: persona for persona in persona_records_from_config(cfg)}
        roster = {**catalog, **stored}
        owned = {
            str(persona.hermes_profile).strip()
            for persona in roster.values()
            if persona.hermes_profile
        }
        created: list[AgentPersona] = []
        for profile in profiles:
            name = str(profile.name).strip()
            if not name or name in owned:
                continue
            persona_id = f"profile_{name}"
            if persona_id in roster:
                _LOG.warning(
                    "Profile %s cannot be auto-promoted: Persona id %s is occupied",
                    name, persona_id,
                )
                continue
            display = " ".join(
                word[:1].upper() + word[1:]
                for word in name.replace("-", "_").split("_") if word
            ) or name
            persona = AgentPersona(
                id=persona_id,
                display_name=display,
                role=PROFILE_ROLE_SENTINEL,
                model=None,
                provider=None,
                api_mode=None,
                toolsets=[],
                autonomy=AutonomyLevel.PROPOSE_ONLY.value,
                hermes_profile=name,
                include_profile_memory=True,
                readiness={"auto_discovered_profile": True},
            )
            store.save(persona)
            created.append(persona)
            roster[persona_id] = persona
            owned.add(name)
        return created
