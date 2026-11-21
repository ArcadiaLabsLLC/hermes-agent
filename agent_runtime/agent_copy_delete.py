"""Delete an agent copy you made, in one step: it leaves every agent list.

Row ``RT-AN-INDEPENDENT-COPY-CANNOT-BE-DELETED`` (seen 2026-11-20 by w1118a-phoneN):
``persona instance retire`` archived a copy's instance and kept its chats, but the
copy's definition (``agents/<id>.json``) and its profile home stayed, and no door
removed either, so every reader of the roster still listed the copy. Review
w1118a.47 D5 ruled one door:

* it deletes a COPY — an independent agent (a persona minted for its own
  ``agent-<digest>`` profile, ``persona_lifecycle.is_independent_agent_persona``)
  or a duplicate (``based_on``) — stored in this install and declared by no config;
* it refuses a shipped agent (``shipped_agent``), any other persona
  (``not_a_copy``), an agent a realm holds (``held_by_realm``: a realm's agent
  selection lists it, or a shared realm's workspace roster or desk has it — unselect
  or remove it there first), and an agent with a live run (``instance_active``);
* every instance of the copy is retired as ``retire`` retires one — the row and its
  desks archived, its chats kept — its own channel included (the persona it is the
  channel of is going);
* its definition is moved to ``agents_archive/<ts>_delete/`` and its profile is
  moved to ``profiles/.retired-independent-agents/`` only when that profile is the
  copy's OWN: made for it (the independent create's owner marker, or a duplicate's)
  and bound by no other persona or live instance. A profile another agent uses
  stays, and the answer says why (``profile_kept``).

Nothing is erased: every move is archive-never-delete, as retire and the failed
create's ``_archive_unbound_identity`` are. A retry after a lost answer re-reads the
receipt and answers ``already_deleted: true``.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_cli.profiles import get_profile_dir
from hermes_time import now
from utils import atomic_json_write

from . import paths
from .agent_duplicate import AGENT_NAME_LOCK
from .bundled_agents import shipped_reference
from .bundled_agents.realm import is_shipped_id, shipped_profile_tokens
from .config import load_agent_runtime_config
from .config.persona_records import persona_records_from_config
from .config.roster import ensure_persisted_personas
from .locks import agent_create_lock, agent_record_write_lock
from .models import AgentPersona, PersonaInstance
from .persona_assignments import PersonaInstanceStore
from .persona_assignments.independent import _OWNER_FILE
from .persona_lifecycle import is_agent_copy
from .profile_context import active_profile_name
from .request_actor import request_actor
from .store import RealmStore, WorkspaceStore

__layer__ = "stores"

__all__ = ["AgentDeleteRefused", "COPY_OWNER_FILE", "delete_agent_copy"]

#: The marker a copy's own profile carries (the independent create writes it; the
#: duplicate verb writes it since this row). Shared with ``independent.py``.
COPY_OWNER_FILE = _OWNER_FILE

_RECEIPT = "delete-receipt.json"
_PROFILE_ARCHIVE = ".retired-independent-agents"


class AgentDeleteRefused(ValueError):
    """A typed refusal; ``reason`` is the wire string, ``data`` rides beside it."""

    def __init__(self, reason: str, message: str, **data: Any):
        super().__init__(message)
        self.reason = reason
        self.data = data


@dataclass(slots=True)
class _Plan:
    persona: AgentPersona
    instances: list[PersonaInstance]
    profile_kept: str | None
    others: list[str] = field(default_factory=list)


def _archive_root() -> Path:
    return paths.store_root() / "agents_archive"


def _receipt_for(persona_id: str) -> dict[str, Any] | None:
    """The receipt of an earlier delete of ``persona_id``, newest first."""

    token = paths.safe_path_token(persona_id)
    for receipt in sorted(_archive_root().glob(f"*_delete/{token}/{_RECEIPT}"), reverse=True):
        try:
            return json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def _is_copy(persona: AgentPersona) -> bool:
    return is_agent_copy(persona)


def _realm_hold(persona: AgentPersona, instances: list[PersonaInstance]) -> dict[str, str] | None:
    """Where a realm holds ``persona``, or ``None``. Local only: a realm's agent is never deleted here."""

    realms = RealmStore().list_all()
    for realm in realms:
        # Only a selection the realm publishes holds it; a ``workspace``-mode list is dormant
        # and already reports an id it cannot find as ``missing``.
        if realm.agent_publish_mode == "selected" and persona.id in (realm.agent_selection or []):
            return {"realm_id": realm.id, "held_by": "agent_selection"}
    shared = {realm.id for realm in realms if realm.server_id}
    if not shared:
        return None
    shared_workspaces = {ws.id: ws for ws in WorkspaceStore().list_all() if ws.realm_id in shared}
    for workspace in shared_workspaces.values():
        if persona.id in (workspace.agent_ids or []):
            return {"realm_id": str(workspace.realm_id), "held_by": "workspace_roster", "workspace_id": workspace.id}
    for instance in instances:
        if instance.realm_id in shared or instance.workspace_id in shared_workspaces:
            realm_id = instance.realm_id if instance.realm_id in shared else shared_workspaces[instance.workspace_id].realm_id
            return {"realm_id": str(realm_id), "held_by": "realm_desk", "persona_instance_id": instance.id}
    return None


def _profile_verdict(persona: AgentPersona, roster: list[AgentPersona], live: list[PersonaInstance]) -> tuple[str | None, list[str]]:
    """``(None, [])`` when the profile is the copy's own to remove, else why it stays and who uses it."""

    profile = persona.hermes_profile
    if not profile or profile == "default":
        return "no_own_profile", []
    if paths.safe_path_token(profile) in shipped_profile_tokens() or profile == active_profile_name():
        return "not_its_own", []
    home = Path(get_profile_dir(profile))
    marker = home / COPY_OWNER_FILE
    if home.is_symlink() or not home.is_dir() or marker.is_symlink() or not marker.is_file():
        return "not_its_own", []
    # MUTATION: return (None, []) here, dropping the in-use check, and
    # test_a_profile_another_agent_uses_stays reddens.
    others = sorted(
        {p.id for p in roster if p.id != persona.id and p.hermes_profile == profile}
        | {i.persona_id for i in live if i.persona_id != persona.id and i.profile_id == profile}
    )
    return ("in_use", others) if others else (None, [])


def _delete_plan(persona_id: str) -> _Plan:
    cfg = load_agent_runtime_config()
    roster = ensure_persisted_personas(cfg)
    persona = next((p for p in roster if p.id == persona_id), None)
    if persona is None:
        raise AgentDeleteRefused("persona_not_found", "That agent does not exist.", persona_id=persona_id)
    # MUTATION: drop this guard and test_a_shipped_agent_is_refused reddens.
    if is_shipped_id(persona.id) or shipped_reference(persona) is not None:
        raise AgentDeleteRefused(
            "shipped_agent", f"{persona.display_name} ships with Eternia and cannot be deleted.", persona_id=persona_id,
        )
    declared = {p.id for p in persona_records_from_config(cfg)}
    # MUTATION: drop ``not _is_copy(persona)`` and test_an_agent_that_is_not_a_copy_is_refused reddens.
    if persona_id in declared or not paths.agent_path(persona_id).is_file() or not _is_copy(persona):
        raise AgentDeleteRefused(
            "not_a_copy", f"{persona.display_name} is not a copy you made; only a copy can be deleted.",
            persona_id=persona_id,
        )
    scan = PersonaInstanceStore().scan_all()
    if scan.unreadable:
        raise AgentDeleteRefused(
            "instances_unreadable", "Some agent records could not be read; nothing was deleted.", persona_id=persona_id,
        )
    mine = [i for i in scan.instances if i.persona_id == persona_id]
    hold = _realm_hold(persona, mine)
    # MUTATION: drop this guard and test_an_agent_a_realm_selection_holds_is_refused reddens.
    if hold is not None:
        raise AgentDeleteRefused(
            "held_by_realm",
            f"A realm holds {persona.display_name}; remove it from the realm's agents first.",
            persona_id=persona_id, **hold,
        )
    store = PersonaInstanceStore()
    busy = next((i for i in mine if store._has_live_binding(i)), None)
    if busy is not None:
        raise AgentDeleteRefused(
            "instance_active", f"{persona.display_name} is working; stop its run first.",
            persona_id=persona_id, persona_instance_id=busy.id,
        )
    kept, others = _profile_verdict(persona, roster, [i for i in scan.instances if i.persona_id != persona_id])
    return _Plan(persona, mine, kept, others)


def _retire_all(plan: _Plan, correlation_id: str | None, actor: str) -> list[dict[str, Any]]:
    store = PersonaInstanceStore()
    retired = []
    for instance in plan.instances:
        # WHO deleted it, not the verb's name (RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT).
        # MUTATION: pass requested_by="runtime.agent.delete" again and test_a_delete_records_who_deleted_it reddens.
        result = store.retire(instance.id, reason="agent deleted", requested_by=actor, correlation_id=correlation_id)
        retired.append({key: result.get(key) for key in
                        ("persona_instance_id", "archive_path", "archived_actor_keys", "office_archive_failures")})
    return retired


def delete_agent_copy(
    persona_id: str, *, correlation_id: str | None = None, requested_by: str | None = None,
) -> dict[str, Any]:
    """Delete the copy ``persona_id``; the answer names everything it moved and what it kept.

    ``requested_by`` is who asked (``agent_runtime.request_actor``; ``unknown`` when nobody is named), on
    every retired instance's record and the delete's own receipt."""

    actor = request_actor(requested_by)
    with agent_create_lock(AGENT_NAME_LOCK):
        try:
            plan = _delete_plan(persona_id)
        except AgentDeleteRefused as exc:
            receipt = _receipt_for(persona_id) if exc.reason == "persona_not_found" else None
            if receipt is not None:
                return {**receipt, "already_deleted": True}
            raise
        persona = plan.persona
        retired = _retire_all(plan, correlation_id, actor)
        batch = _archive_root() / f"{now().strftime('%Y%m%dT%H%M%SZ')}_delete" / paths.safe_path_token(persona_id)
        batch.mkdir(parents=True, exist_ok=True)
        definition = batch / "persona.json"
        with agent_record_write_lock("persona", persona_id):
            os.replace(paths.agent_path(persona_id), definition)
        profile_archive = None
        if plan.profile_kept is None:
            home = Path(get_profile_dir(persona.hermes_profile))
            target = home.parent / _PROFILE_ARCHIVE / uuid.uuid4().hex
            target.mkdir(parents=True)
            # MUTATION: skip this move and test_a_delete_removes_the_copy_from_every_list reddens.
            os.replace(home, target / "profile")
            profile_archive = str(target / "profile")
        receipt = {
            "persona_id": persona_id,
            "agent_name": persona.display_name,
            "profile": persona.hermes_profile,
            "retired_instances": retired,
            "definition_archive": str(definition),
            "profile_archive": profile_archive,
            "profile_kept": plan.profile_kept,
            "profile_used_by": plan.others,
            "chats_kept": True,
            "requested_by": actor,
            "already_deleted": False,
        }
        if correlation_id:
            receipt["correlation_id"] = correlation_id
        atomic_json_write(batch / _RECEIPT, receipt)
    from .events import EventLog
    from .state_patches.persona import emit_persona_updated

    # The persona authority moved: the same cue ``AgentStore.save`` gives, so every
    # roster-fed section re-reads and finds the copy gone. Its pair is a refresh:
    # the departure takes the full core it always did.
    emit_persona_updated(EventLog(), persona_id=persona_id, display_name=persona.display_name)
    return receipt
