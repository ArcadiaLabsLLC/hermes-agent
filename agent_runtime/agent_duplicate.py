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

import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from hermes_cli.profiles import get_profile_dir
from hermes_cli.profiles_initialization import finish_profile_layout

from . import yaml_io
from .bundled_agents import SHIPPED_AGENTS, shipped_soul_for_turn
from .config import ensure_persisted_personas
from .locks import agent_create_lock
from .models import AgentPersona
from .persona_assignments import PersonaInstanceStore, is_canonical_persona_channel
from .persona_assignments.independent import _portable_model_defaults
from .store import AgentStore

__layer__ = "stores"

__all__ = ["AgentDuplicateRefused", "DuplicateResult", "duplicate_agent", "name_is_taken"]

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
    profile = slug.replace("_", "-")
    home = get_profile_dir(profile)
    return profile if not (home.exists() or home.is_symlink()) else f"{profile}-{uuid.uuid4().hex[:8]}"


def _copy_entry(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.exists():
        return
    if source.is_dir():
        shutil.copytree(source, target, symlinks=False, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)


def _stage_profile(home: Path, source_home: Path | None, soul: str | None) -> None:
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=home.parent, prefix=f".{home.name}-") as temp:
        stage = Path(temp) / "profile"
        stage.mkdir()
        if source_home is not None and source_home.is_dir() and not source_home.is_symlink():
            for entry in _AGENT_FILES:
                _copy_entry(source_home / entry, stage / entry)
        model = _portable_model_defaults(source_home) if source_home is not None else {}
        (stage / "config.yaml").write_text(yaml_io.dump({"model": model} if model else {}), encoding="utf-8")
        finish_profile_layout(stage, no_skills=False, clone_all=False, description=None, soul=soul)
        os.rename(stage, home)


def _source(persona_id: str, roster: list[AgentPersona]) -> AgentPersona:
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
    PersonaInstanceStore().patch_fields(
        instance_id, persona_id=copy.id, profile_id=copy.hermes_profile,
        display_name=copy.display_name, role=copy.role,
    )
    return instance_id


def duplicate_agent(persona_id: str, name: str, *, instance_id: str | None = None) -> DuplicateResult:
    """Copy ``persona_id`` as a new agent called ``name``; optionally move ``instance_id`` to it."""

    name = " ".join(str(name or "").split())
    if not name:
        raise AgentDuplicateRefused("agent_name_required", "Give the copy a name.")
    with agent_create_lock("agent-duplicate"):
        roster = ensure_persisted_personas()
        source = _source(persona_id, roster)
        if name_is_taken(name, roster):
            raise AgentDuplicateRefused("agent_name_taken", f"An agent is already called {name}.", name=name)
        if instance_id:
            _check_instance(instance_id, source)
        slug = _slug(name)
        profile = _free_profile(slug)
        source_home = Path(get_profile_dir(source.hermes_profile)) if source.hermes_profile else None
        soul = shipped_soul_for_turn(source)
        _stage_profile(get_profile_dir(profile), source_home, soul)
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
