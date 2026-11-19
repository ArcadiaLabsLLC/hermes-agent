"""How a realm carries a shipped agent: a pointer, never the agent itself.

Design § 3 "Realms and namespaces" (owner 2026-11-19, row
``RT-REALM-SHARES-A-SHIPPED-AGENT-BY-REFERENCE``): every member's build already
holds Base Agent and Neko Mission Lead, so a realm publish sends, for a
shipped agent, only the reference — its id with :data:`REFERENCE_BODY` in the
persona projection, the version as accounting — and the seats placed in the
realm. No SOUL, prompt or memory file travels for it. A pull never writes a
definition or a profile file over a shipped id: an older owner's published
definition for one is ignored and accounted. Each member reads their own
build's version (no pinning, owner answer 6).

Callers: ``realm_sync.artifacts`` (publish: no profile files),
``persona_config_sync`` (the projection body, the pull, the adopt door) and
``profile_artifact_sync`` (the pull's profile-file lane).
"""

from __future__ import annotations

from typing import Any

from .catalog import ORIGIN_ETERNIA, SHIPPED_AGENTS, shipped_agent
from .resolve import shipped_reference

__layer__ = "stores"

__all__ = [
    "REFERENCE_BODY",
    "WITHHELD_REASON",
    "is_reference_body",
    "is_shipped_id",
    "place_if_missing",
    "reference_body",
    "shipped_profile_tokens",
    "withheld_row",
]

#: The whole published persona body of a shipped agent. Version-free on purpose:
#: a body is hashed for drift, and members on different builds must not read each
#: other's reference as a change. The version travels beside it as accounting.
REFERENCE_BODY: dict[str, str] = {"origin": ORIGIN_ETERNIA}

#: The ``withheld`` reason a publish gives for a shipped agent's profile files.
WITHHELD_REASON = "shipped_with_eternia"


def is_shipped_id(persona_id: Any) -> bool:
    """This build ships an agent under ``persona_id``; the build owns its definition."""

    return shipped_agent(persona_id) is not None


def reference_body(record: Any) -> dict[str, str] | None:
    """The body a realm publishes for ``record``, or ``None`` when it is not a reference."""

    return dict(REFERENCE_BODY) if shipped_reference(record) is not None else None


def is_reference_body(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("origin") == ORIGIN_ETERNIA


def withheld_row(persona_id: str) -> dict[str, str]:
    return {
        "persona_id": persona_id,
        "kind": "shipped_agent",
        "reason": WITHHELD_REASON,
        "message": "ships with Eternia; every member's build holds it, so only the reference travels",
    }


def shipped_profile_tokens() -> frozenset[str]:
    """The profile homes shipped agents live in; a pull writes no file into them."""

    from ..paths import safe_path_token

    return frozenset(
        safe_path_token(str(agent.definition["hermes_profile"]))
        for agent in SHIPPED_AGENTS
        if agent.definition.get("hermes_profile")
    )


def place_if_missing(persona_id: str, *, dry_run: bool) -> bool:
    """Add the shipped reference when this install has no agent under ``persona_id``.

    A realm's seats may sit at a shipped agent the member's install never held
    (Neko is seeded on fresh installs only). Returns whether one was (or, dry,
    would be) added.
    """

    from ..config import ensure_persisted_personas
    from ..store import AgentStore
    from .sort_existing import place_shipped

    shipped = shipped_agent(persona_id)
    if shipped is None or any(persona.id == persona_id for persona in ensure_persisted_personas()):
        return False
    if not dry_run:
        place_shipped(shipped, AgentStore())
    return True
