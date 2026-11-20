from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__layer__ = "policy"


# Retired definitions remain part of the administrative catalog, but they are
# not runtime personas and must never acquire a live PersonaInstance.  Keep the
# vocabulary here so every materialization/readiness surface makes the same
# decision without importing the much larger personas module.
MOTHBALLED_ROLE_TOKENS: frozenset[str] = frozenset({"pm"})
MOTHBALLED_PERSONA_IDS: frozenset[str] = frozenset({"pm"})
DISABLED_ROLE_TOKENS: frozenset[str] = frozenset({"disabled"})
_INDEPENDENT_PROFILE_ID = re.compile(r"agent-([a-f0-9]{24})")


def independent_profile_persona_id(profile: str | None) -> str | None:
    """The persona reserved for an automatically provisioned agent profile."""
    match = _INDEPENDENT_PROFILE_ID.fullmatch(profile or "")
    return f"agent_{match[1]}" if match else None


def is_independent_agent_persona(persona: Any) -> bool:
    """An authored agent already has an instance, identified by its create intent."""
    return independent_profile_persona_id(persona.hermes_profile) == persona.id


def is_agent_copy(persona: Any) -> bool:
    """A copy the person made of an agent: an independent copy (its ``agent_<digest>`` persona on its own
    ``agent-<digest>`` profile) or a duplicate (a persona recording ``based_on``). Read off the persona's own
    record. Its profile is that agent's home, never a template to place (rows
    ``RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE``,
    ``RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE``, reviews w1118a.52 D3 and w1118a.53 D10),
    and it is what ``runtime.agent.delete`` may delete (``agent_copy_delete``)."""
    return is_independent_agent_persona(persona) or bool(getattr(persona, "based_on", None))


def is_runtime_persona(persona: Any) -> bool:
    """Return whether a persona definition participates in the live runtime.

    Disabled and explicitly mothballed definitions remain discoverable through
    management commands.  Unknown/custom roles stay active by default.
    """

    def value(name: str) -> Any:
        return persona.get(name) if isinstance(persona, Mapping) else getattr(persona, name, "")

    persona_id = str(value("persona_id") or value("id") or "").strip().lower()
    role = str(value("role") or "").strip().lower()
    return (
        role not in DISABLED_ROLE_TOKENS
        and role not in MOTHBALLED_ROLE_TOKENS
        and persona_id not in MOTHBALLED_PERSONA_IDS
    )
