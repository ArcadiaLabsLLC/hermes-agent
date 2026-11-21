"""Duplicate an agent under a new name, in one step, memory included.

Owner rulings 2026-11-19 (row ``RT-BUNDLED-AGENT-DUPLICATE-IN-ONE-STEP``): changing
a shipped agent is allowed but reset on update, so the duplicate is the easy way
to keep a change; a copy is a FULL duplicate, memory included; its name is one no
other agent has — ``agent_name_taken`` otherwise, and the runtime never invents a
suffix for a name. The copy records ``based_on`` and is an ordinary agent of the
install: it does not follow the original's updates.

The copy gets its own profile home holding the original's agent files — SOUL (the
text the original speaks with, so a shipped agent's copy starts from the build's
SOUL), memory, persona prompts, skills, core context files and portable model
defaults — and never its sign-in, sessions, logs or caches. Given an instance,
the verb re-points it at the copy: the instance keeps its id, so every chat it
holds keeps opening. The persona's own canonical instance is never re-pointed
(its id IS the original's channel; the copy gets its own).
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from hermes_cli.profiles import get_profile_dir
from hermes_constants import get_hermes_home

from .agent_profile_create import create_agent_profile, free_profile_name
from .bundled_agents import SHIPPED_AGENTS, shipped_soul_for_turn
from .config import ensure_persisted_personas
from .locks import agent_create_lock
from .models import AgentPersona
from .persona_assignments import PersonaInstanceStore, is_canonical_persona_channel
from .persona_assignments.independent import _carried_model_config
from .seat_follow import follow_seat
from .store import AgentStore

__layer__ = "stores"

__all__ = ["AGENT_NAME_LOCK", "AgentDuplicateRefused", "DuplicateResult", "duplicate_agent", "name_is_taken"]

#: The one lock a new agent's name is checked and taken under — by a duplicate
#: here and by ``runtime.agent.create``'s mint — so two makers cannot both take
#: one free name.
AGENT_NAME_LOCK = "agent-name"

#: The profile entries that ARE the agent and travel with a duplicate. Sign-in
#: (``auth.json``, ``.env``), sessions, logs and caches are the install's, not the
#: agent's, and are deliberately absent.
_AGENT_FILES = (
    "SOUL.md", "memories", "personas", "skills", "skins",
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "assets",
)


class AgentDuplicateRefused(ValueError):
    """A typed refusal; ``reason`` is the wire string."""

    def __init__(self, reason: str, message: str, **data: object):
        super().__init__(message)
        self.reason = reason
        self.data = data


@dataclass(frozen=True, slots=True)
class DuplicateResult:
    persona: AgentPersona
    instance_id: str | None

    def to_wire(self) -> dict:
        return {
            "persona_id": self.persona.id,
            "agent_name": self.persona.display_name,
            "based_on": dict(self.persona.based_on or {}),
            "profile": self.persona.hermes_profile,
            "instance_id": self.instance_id,
        }


def _name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def name_is_taken(name: str, roster: list[AgentPersona] | None = None) -> bool:
    """``name`` equals, ignoring case and spacing, a shipped agent's or any agent's name."""

    key = _name_key(name)
    names = [agent.name for agent in SHIPPED_AGENTS]
    names += [persona.display_name for persona in (roster if roster is not None else ensure_persisted_personas())]
    return any(_name_key(existing) == key for existing in names)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")[:48] or "agent"


def _free_id(slug: str, roster: list[AgentPersona]) -> str:
    taken = {persona.id for persona in roster} | {agent.id for agent in SHIPPED_AGENTS}
    return slug if slug not in taken else f"{slug}_{uuid.uuid4().hex[:8]}"


def _free_profile(slug: str) -> str:
    return free_profile_name(slug.replace("_", "-"))


def _copy_entry(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.exists():
        return
    if source.is_dir():
        shutil.copytree(source, target, symlinks=False, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)


def _stage_duplicate_profile(
    profile: str, source_home: Path | None, model_home: Path, soul: str | None, source_id: str,
) -> None:
    """The copy's home, made by the one profile creator (``agent_profile_create``), then
    filled with the source's agent files. A given ``soul`` (the shipped one) wins over the
    source's ``SOUL.md``, as ``finish_profile_layout(soul=…)`` did after the old copy."""

    def populate(stage: Path) -> None:
        if source_home is None or not source_home.is_dir() or source_home.is_symlink():
            return
        for entry in _AGENT_FILES:
            if entry == "SOUL.md" and soul is not None:
                continue
            _copy_entry(source_home / entry, stage / entry)

    # The copy's own profile carries the owner marker the independent create writes, so
    # ``agent_copy_delete`` may remove it with the copy (RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED).
    create_agent_profile(
        profile, owner=f"duplicate\n{source_id}", config=_carried_model_config(model_home), soul=soul,
        populate=populate,
    )


def _duplicate_source(persona_id: str, roster: list[AgentPersona]) -> AgentPersona:
    source = next((persona for persona in roster if persona.id == persona_id), None)
    if source is None:
        raise AgentDuplicateRefused("persona_not_found", "That agent does not exist.", persona_id=persona_id)
    return source


def _check_instance(instance_id: str, source: AgentPersona) -> None:
    instance = PersonaInstanceStore().get(instance_id)
    if instance.persona_id != source.id:
        raise AgentDuplicateRefused(
            "instance_not_of_agent", "That instance belongs to another agent.", instance_id=instance_id,
        )
    if is_canonical_persona_channel(instance):
        raise AgentDuplicateRefused(
            "canonical_instance_stays",
            "An agent's own channel stays with it; the copy has its own.",
            instance_id=instance_id,
        )


def _repoint(instance_id: str, copy: AgentPersona) -> str:
    store = PersonaInstanceStore()
    moved_from = store.get(instance_id).persona_id
    store.patch_fields(
        instance_id, persona_id=copy.id, profile_id=copy.hermes_profile,
        display_name=copy.display_name, role=copy.role,
    )
    # The seat's office desk and its chats move with it (``seat_follow``).
    follow_seat(instance_id, moved_from=moved_from)
    return instance_id


def duplicate_agent(persona_id: str, name: str, *, instance_id: str | None = None) -> DuplicateResult:
    """Copy ``persona_id`` as a new agent called ``name``; optionally move ``instance_id`` to it."""

    name = " ".join(str(name or "").split())
    if not name:
        raise AgentDuplicateRefused("agent_name_required", "Give the copy a name.")
    with agent_create_lock(AGENT_NAME_LOCK):
        roster = ensure_persisted_personas()
        source = _duplicate_source(persona_id, roster)
        if name_is_taken(name, roster):
            raise AgentDuplicateRefused("agent_name_taken", f"An agent is already called {name}.", name=name)
        if instance_id:
            _check_instance(instance_id, source)
        slug = _slug(name)
        profile = _free_profile(slug)
        source_home = Path(get_profile_dir(source.hermes_profile)) if source.hermes_profile else None
        # A source on the main profile answers through the head home's model, so the copy
        # carries that model block — and none of the head home's own entries (memory,
        # sign-in), as ``independent.py::_profile_source`` falls back to the head home.
        model_home = source_home if source_home is not None else Path(get_hermes_home())
        soul = shipped_soul_for_turn(source)
        _stage_duplicate_profile(profile, source_home, model_home, soul, source.id)
        copy = AgentStore().save(replace(
            source,
            id=_free_id(slug, roster),
            display_name=name,
            hermes_profile=profile,
            origin=None,
            bundled_version=None,
            based_on={"id": source.id, "name": source.display_name},
            readiness={},
            model_override_issued_at=None,
            skills_override_issued_at=None,
            character_assignment=None,
        ))
        moved = _repoint(instance_id, copy) if instance_id else None
    return DuplicateResult(copy, moved)
