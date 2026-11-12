"""The agents' half of a realm re-key (RT-REKEY-LOCAL-COPY-GETS-NEW-AGENTS).

Plan ``docs/agent-runtime-harness/planned/rejoin-fresh-realm-2026-11-12.md`` §6. An agent's id is the team's
identity and its chats are named after it, so the team's agents cannot follow the local copy: they PARK
(``persona_instances_parked/<old realm>/``, the row moved whole — never a retire, whose tombstone would stop a
re-join's pull bringing the agent back) and the local copy gets a new agent of the same persona for each, minted
through the door a first-time joiner's pull uses (``PersonaInstanceStore.replicate_instance``: the definition
copied, the runtime state born fresh, an empty chat). ``agent_runtime.realm_rekey`` owns the map, the journal
and the order; this module is its ``agents`` step and the restore a re-join runs before its pull.

What names an agent in the local copy — the desk (``office/<ws>/actors/``: actor key, file name, the agent
item's id), the flow graph it owns (``flow_graphs/runtime_<agent>.json``), a schedule, an open Work claim
(``persona:<agent>``) — is re-pointed by the generic content and rename steps through :func:`agent_forms` /
:func:`agent_name_forms`.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from . import paths
from .models import DELIBERATE_PLACEMENT_SUFFIX, PERSONA_INSTANCE_ID_PREFIX
from .office_models import actor_file_token
from .serde import safe_assignment_token

__layer__ = "lanes"
__all__ = [
    "PARKED_DIRNAME",
    "agent_forms",
    "agent_name_forms",
    "agents_of",
    "fresh_agent_id",
    "parked_agents_dir",
    "restore_parked_agents",
    "step_agents",
]

PARKED_DIRNAME = "persona_instances_parked"
#: The local half a new agent of the same persona keeps from the one it replaces: both are this machine's own
#: answers about the agent (a custom name, a local context-file path), not chat or run state.
_KEPT_LOCAL_FIELDS = ("display_name_custom", "slot_context_custom")
_GRAPH_PREFIX = "runtime_"


def parked_agents_dir(realm_id: str) -> Path:
    return paths.store_root() / PARKED_DIRNAME / paths.safe_path_token(realm_id)


def fresh_agent_id(old: str, persona_id: str) -> str:
    """A new deliberate-placement id for the same desk: ``personainst_qa_agent_2`` → ``personainst_qa_agent_<hex8>``."""
    stem = DELIBERATE_PLACEMENT_SUFFIX.sub("", old)
    if stem == old:  # an id minted before the placement shape was required
        stem = f"{PERSONA_INSTANCE_ID_PREFIX}{safe_assignment_token(persona_id) or 'persona'}"
    return f"{stem}_agent_{uuid.uuid4().hex[:8]}"


def agents_of(realm_id: str, workspace_ids: set[str]) -> dict[str, str]:
    """``{agent id: persona id}`` for every agent the realm holds. A persona's own channel
    (``personainst_<persona>``) is this install's and belongs to no realm: it never parks."""
    from .persona_assignments import PersonaInstanceStore
    from .persona_assignments.identity import is_canonical_persona_channel

    return {
        item.id: item.persona_id for item in PersonaInstanceStore().list_all()
        if not is_canonical_persona_channel(item) and (item.workspace_id in workspace_ids or item.realm_id == realm_id)
    }


def _placement(agent_id: str) -> str:
    return agent_id[len(PERSONA_INSTANCE_ID_PREFIX):] if agent_id.startswith(PERSONA_INSTANCE_ID_PREFIX) else agent_id


def agent_forms(agents: dict[str, str]) -> dict[str, str]:
    """Every whole token that names an agent: its id, its placement id (the scene item's id where the app
    minted it) and its flow graph's stored id (``runtime_<agent>``; ``runtime:<agent>`` splits on the colon)."""
    forms: dict[str, str] = {}
    for old, new in agents.items():
        forms.update({old: new, _placement(old): _placement(new), _GRAPH_PREFIX + old: _GRAPH_PREFIX + new})
    return forms


def agent_name_forms(agents: dict[str, str]) -> dict[str, str]:
    """File stems that name an agent and are not the id itself: a long actor key's capped file token."""
    return {actor_file_token(old): actor_file_token(new) for old, new in agents.items()}


def _read_row(path: Path):
    from .persona_assignments.store import _decode_stored_instance

    return _decode_stored_instance(json.loads(path.read_text(encoding="utf-8")))


def step_agents(root: Path, mapping: Any) -> None:
    """Mint the local copy's agents, then park the team's. Runs FIRST, before any id is rewritten: once the
    team's rows are out of ``persona_instances/`` the generic steps can treat that folder as the local copy's.
    Re-run after a kill it mints only what is missing and parks only what is still in place."""
    from .persona_assignments import PersonaInstanceStore
    from .persona_instance_sync.projection import project_persona_instance
    from .state_patches.persona_instance import emit_persona_instance_remove

    store = PersonaInstanceStore()
    parked_dir = parked_agents_dir(mapping.realm_old)
    parents: dict[str, list[str]] = {}
    for old, new in mapping.agents.items():
        live, parked = paths.persona_instance_path(old), parked_dir / paths.persona_instance_path(old).name
        source = live if live.exists() else parked
        if not source.exists():
            continue  # retired while the realm was local: nothing to park, no desk to re-seat
        team = _read_row(source)
        if live.exists() and store._has_live_binding(team):
            raise RuntimeError(f"realm re-key: {old} has a live run binding; the re-key runs only when idle")
        parents[new] = [mapping.agents.get(parent, parent) for parent in team.steered_by]
        if not paths.persona_instance_path(new).exists():
            body = project_persona_instance(team)
            body.pop("steered_by", None)  # edges are applied below, once every new agent exists
            body["id"] = new  # its realm and workspace are re-pointed with every other row, by the content step
            store.replicate_instance(body, realm_id=mapping.realm_new)
            kept = {name: getattr(team, name) for name in _KEPT_LOCAL_FIELDS if getattr(team, name, None)}
            if kept:
                store.patch_fields(new, **kept)
        if live.exists():
            parked_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(live), str(parked))
            emit_persona_instance_remove(store.event_log, team)
    for new, steered_by in parents.items():
        if steered_by:
            store.apply_replicated_steering(new, steered_by, realm_id=mapping.realm_new)


def restore_parked_agents(realm_id: str) -> list[str]:
    """Put the team's agents of ``realm_id`` (its id before the re-key) back, before a re-join's pull: the pull
    then finds them present and their chats re-attach by id. A row that is somehow live already is left as it
    is and its parked copy stays. Returns the ids restored."""
    from .persona_assignments import PersonaInstanceStore
    from .state_patches.persona_instance import emit_persona_instance_create

    store = PersonaInstanceStore()
    parked_dir = parked_agents_dir(realm_id)
    restored = []
    for parked in sorted(parked_dir.glob("*.json")) if parked_dir.is_dir() else []:
        live = paths.persona_instances_dir() / parked.name
        if live.exists():
            continue
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(parked), str(live))
        instance = _read_row(live)
        emit_persona_instance_create(store.event_log, instance)
        restored.append(instance.id)
    if parked_dir.is_dir() and not any(parked_dir.iterdir()):
        parked_dir.rmdir()
    return restored
