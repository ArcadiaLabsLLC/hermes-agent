"""How a record that references a shipped agent reads, saves and shows.

A reference is a persona record with ``origin: "eternia"`` whose id is a shipped
id. The store keeps a full record (an older build loads it as an ordinary
persona, and its profile's ``SOUL.md`` stays as that build's fallback), but this
build never reads the definition from it: :func:`resolve_record` lays the build's
definition over it on every load, and :func:`shipped_soul_for_turn` hands the
turn the build's SOUL. A changed build therefore changes the next prompt with no
store write.

A local edit is allowed (owner 2026-11-19). It is a definition that differs from
the build's, or a profile ``SOUL.md`` no build shipped, on a record stamped with
the CURRENT version; it is kept and shown as ``locally_changed``. Once a newer
build ships, the stamp is stale and the edit is reset: the build's definition
wins on load, and the next save (or :func:`sync_shipped_agents`) persists it.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any

from ..models import AgentPersona
from .catalog import DEFINITION_FIELDS, ORIGIN_ETERNIA, ShippedAgent, normalized_soul_sha, shipped_agent

__layer__ = "stores"

__all__ = [
    "directory_fields",
    "is_locally_changed",
    "prepare_save",
    "reference_record",
    "resolve_record",
    "shipped_reference",
    "shipped_soul_for_turn",
    "sync_shipped_agents",
]

_LOG = logging.getLogger(__name__)


def shipped_reference(persona: Any) -> ShippedAgent | None:
    """The shipped agent ``persona`` references, or ``None`` for any other record."""

    if getattr(persona, "origin", None) != ORIGIN_ETERNIA:
        return None
    return shipped_agent(getattr(persona, "id", None))


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _definition(persona: AgentPersona) -> dict[str, Any]:
    return {name: _plain(getattr(persona, name)) for name in DEFINITION_FIELDS}


def _current(persona: AgentPersona, shipped: ShippedAgent) -> bool:
    return persona.bundled_version == shipped.version


def _profile_soul_path(shipped: ShippedAgent) -> Path | None:
    from hermes_cli.profiles import get_profile_dir

    profile = shipped.definition.get("hermes_profile")
    return Path(get_profile_dir(profile)) / "SOUL.md" if profile else None


def _soul_edited(shipped: ShippedAgent) -> bool:
    """The profile holds a SOUL no build shipped (an unmanaged SOUL is never "edited")."""

    if shipped.soul_file is None:
        return False
    path = _profile_soul_path(shipped)
    if path is None or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return normalized_soul_sha(text) not in shipped.known_soul_sha256()


def resolve_record(persona: AgentPersona) -> AgentPersona:
    """``persona`` with the build's definition, unless it carries a current local edit."""

    shipped = shipped_reference(persona)
    if shipped is None:
        return persona
    if _current(persona, shipped) and _definition(persona) != shipped.definition:
        return persona
    return replace(persona, **{name: _plain(value) for name, value in shipped.definition.items()})


def is_locally_changed(persona: AgentPersona) -> bool:
    shipped = shipped_reference(persona)
    if shipped is None or not _current(persona, shipped):
        return False
    return _definition(persona) != shipped.definition or _soul_edited(shipped)


def shipped_soul_for_turn(persona: AgentPersona) -> str | None:
    """The build's SOUL text for this turn, or ``None`` to read the profile's as usual."""

    shipped = shipped_reference(persona)
    if shipped is None or shipped.soul_file is None:
        return None
    if _current(persona, shipped) and _soul_edited(shipped):
        return None
    text = shipped.soul_text()
    return text.strip() if text is not None else None


def directory_fields(persona: AgentPersona | None) -> dict[str, Any]:
    """The additive directory / instance-detail keys (design § 5); absent means "no"."""

    if persona is None:
        return {}
    fields: dict[str, Any] = {"agent_name": persona.display_name}
    if shipped_reference(persona) is not None:
        fields["origin"] = ORIGIN_ETERNIA
        fields["locally_changed"] = is_locally_changed(persona)
    if persona.based_on:
        fields["based_on"] = dict(persona.based_on)
    return fields


def reference_record(shipped: ShippedAgent, settings: AgentPersona | None = None) -> AgentPersona:
    """A fresh reference to ``shipped``; ``settings`` donates the install settings it keeps."""

    base = settings or AgentPersona(shipped.id, shipped.name, str(shipped.definition["role"]), None, None, None)
    return replace(
        base,
        id=shipped.id,
        origin=ORIGIN_ETERNIA,
        bundled_version=shipped.version,
        based_on=None,
        **{name: _plain(value) for name, value in shipped.definition.items()},
    )


def _reset_stale_soul(shipped: ShippedAgent) -> None:
    path = _profile_soul_path(shipped)
    soul = shipped.soul_text()
    if soul is None or path is None or not path.parent.is_dir() or not _soul_edited(shipped):
        return
    path.write_text(soul, encoding="utf-8")


def prepare_save(persona: AgentPersona, stored_version: str | None) -> AgentPersona:
    """Stamp a reference with this build's version as it is written.

    A record last written under an older build has its local edit reset by the
    update: the SOUL file goes back to the build's text before the stamp moves,
    so the edit cannot come back as a change made under this build.
    """

    shipped = shipped_reference(persona)
    if shipped is None:
        return persona
    if stored_version != shipped.version:
        _reset_stale_soul(shipped)
    return replace(persona, bundled_version=shipped.version)


def sync_shipped_agents() -> list[str]:
    """Persist the update's reset on every reference written under an older build."""

    from ..store import AgentStore

    store = AgentStore()
    synced: list[str] = []
    for persona in store.list_all():
        shipped = shipped_reference(persona)
        if shipped is None or _current(persona, shipped):
            continue
        store.save(persona)
        synced.append(persona.id)
    if synced:
        _LOG.info("shipped agents updated to this build: %s", ", ".join(synced))
    return synced
