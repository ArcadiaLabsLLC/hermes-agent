"""``PersonaInstanceStore`` — the persona-instance roster store (one JSON row per
instance under ``paths.persona_instances_dir()``), moved here whole.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from agent_runtime import paths
from agent_runtime.character_assignment import CharacterAssignmentChange, CharacterAssignmentReplication, preserve_character_assignment
from agent_runtime.locks import agent_record_write_lock
from agent_runtime.agent_create_phases import timed_create_subphase
from agent_runtime.config.roster import ensure_persisted_personas
from agent_runtime.errors import PersonaInstancesUnreadable
from agent_runtime.events import EventLog
from agent_runtime.models import Event, PersonaInstance
from agent_runtime.persona_assignments import (
    chat_binding as chat_binding_lane,
    profile_writes as profile_writes_lane,
    repair as repair_lane,
    replicate as replicate_lane,
    retire as retire_lane,
    steering as steering_lane,
)
from agent_runtime.persona_assignments.chat_binding import _durable_chat_root
from agent_runtime.persona_assignments.identity import (
    _normalize_instance_source_persona,
    _profile_id_for_persona_or_template,
    canonical_persona_instance_id,
    persona_chat_session_id_for,
    persona_instance_id_for_placement,
)
from agent_runtime.persona_assignments.scan import (
    PersonaInstanceScan,
)
from agent_runtime.serde import (
    from_jsonable,
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
    to_jsonable,
)
from agent_runtime.state_patches.models import PERSONA_INSTANCE_FOLDED_STORE_FIELDS
from agent_runtime.state_patches.persona_instance import emit_persona_instance_patch

__layer__ = "stores"

__all__ = [
    "PersonaInstanceStore",
]


# S70 removed ``PersonaAssignmentSpec`` with the assignment MINT side (the rest
# of the store went at RT-FULL-PERSONAASSIGNMENTSTORE, 2026-10-25). The spec's one production consumer was
# ``create_or_resume``, whose one caller was the retired free-floating queue
# verb chain.


def _decode_stored_instance(raw: dict[str, Any]) -> PersonaInstance:
    """THE decode of one stored row; ``get`` and ``scan_all`` both go through it.

    A retired meaning is dropped here, once, so no reader carries a branch for it.

    A hidden copy ``personainst_<persona>`` used to decode with no workspace whatever
    its row held (RT-GLOBAL-SINGLETON-CANONICAL). Nothing mints one any more, and the
    hidden-copy migration (``persona_instance_adoption``) adopts, archives or holds
    every one it finds, clearing a stale pointer as it goes, so a row decodes as it
    is stored (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT).
    """
    from agent_runtime.persona_instance_sync.contract import stored_instance_body

    # A row written by an edition that stored the Project spelling (RT-WS-RECALL-RENAME-S2-FIELD).
    instance = from_jsonable(PersonaInstance, stored_instance_body(raw))
    if instance.mode == "task_bound":
        # ``task_bound`` is stored-only: nothing writes it, so no reader branches on it
        # (RT-TASK-BOUND-MISSION-LANES). A STEER-shaped row (its task IS its goal, a
        # correlation id) drops the task too. A MISSION-shaped row (a task that is not
        # its goal) keeps ``current_task_id`` so the archive record is whole; phase 0
        # reads the RAW row for its shape and archives it, at every serve boot.
        if (instance.current_task_id or None) == (instance.goal_id or None):
            instance.current_task_id = None
        instance.mode = "configured"
    return instance


class PersonaInstanceStore:
    def __init__(self, event_log: EventLog | None = None, *, preparation_epoch=None):
        self.event_log = event_log or EventLog()
        self.preparation_epoch = preparation_epoch

    # S-DUP4 removed ``create_free_floating`` (and its only helper,
    # ``_free_floating_identity``). It was production-callerless — the
    # free-floating queue verb chain that used to call it left with the mission
    # lane — and its only remaining callers were test suites that needed a pair
    # of cheap instance rows. The mint moved to
    # ``tests/agent_runtime/persona_instance_mint.py::mint_free_floating``;
    # the tombstone row is in ``tests/agent_runtime/test_tombstone_registry.py``.
    # ``mode="free_floating"`` itself is NOT retired: it is still read here
    # (``_CHAT_MODES``), in ``operator_channels``, ``persona_chat_history`` and
    # ``persona_instance_identity``, and rows carrying it exist on disk.

    # RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT removed ``ensure_for_persona`` /
    # ``ensure_for_personas``: they minted a hidden copy ``personainst_<persona>`` of every agent on
    # discovery, prewarm, every snapshot build, status, the peer roster, every send and the CLI, so a
    # read wrote the rows it read (a named ``never_converged`` trigger of the snapshot cache). An
    # agent's template is its persona; every live agent is a placed instance (plan
    # ``agent-template-vs-canonical-instance-2026-11-21``). Readers list the store; a profile rebind
    # cascades through ``persona_profile_binding``; a persona's name was synced only onto the hidden
    # copy, never onto a placement, so nothing replaces that half.

    def get(self, persona_instance_id: str) -> PersonaInstance:
        path = paths.persona_instance_path(persona_instance_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # The literal file wins (canonical ids are read verbatim — zero
            # behaviour change). Only when it is missing do we resolve the same
            # id-scheme drift the identity module already defines, so a caller
            # that hands us a legacy/actor-token id (the Launcher graph save, a
            # replayed spec, a CLI verb) reaches the real row instead of a hard
            # "not found". Re-raise the original error for a genuinely absent id.
            resolved = self._resolve_stored_instance_id(persona_instance_id)
            if resolved is None:
                raise
            raw = json.loads(paths.persona_instance_path(resolved).read_text(encoding="utf-8"))
        return _decode_stored_instance(raw)

    def _resolve_stored_instance_id(self, raw_id: str) -> str | None:
        """Resolve a caller-supplied id to the id of the row actually on disk.

        Tolerates exactly the drift :mod:`persona_instance_identity` already
        knows how to collapse: structural actor-token drift
        (``persona_personainst_x`` -> ``personainst_x`` /
        ``persona:<persona>`` -> canonical channel, via
        :func:`canonical_persona_instance_id`) and the durable
        legacy->canonical alias registry (the operator-hash schemes the store
        reconciler records). Returns a stored id whose file exists, or ``None``
        so the caller raises on a genuinely missing row. Read-only: it never
        mints or rewrites a row — the reconciler remains the durable cleanup.
        """
        candidates: list[str] = []

        def _add(candidate: str | None) -> None:
            if candidate and candidate != raw_id and candidate not in candidates:
                candidates.append(candidate)

        structural = canonical_persona_instance_id(raw_id)
        _add(structural)
        try:
            from ..persona_instance_identity import load_persona_instance_aliases

            aliases = load_persona_instance_aliases()
        except Exception:
            aliases = {}
        _add(aliases.get(raw_id))
        if structural:
            _add(aliases.get(structural))
        for candidate in candidates:
            if paths.persona_instance_path(candidate).exists():
                return candidate
        return None

    #: The instance model-override tier, in one place. ``update_profile`` stamps
    #: all five together (``model_override_issued_at`` is the tier's CLOCK) and
    #: emits ``persona_instance.profile_updated`` + ``state.patched``; the realm
    #: replica door carries all five and emits too.
    _MODEL_LANE_FIELDS: tuple[str, ...] = (
        "provider",
        "model",
        "api_mode",
        "reasoning_effort",
        "model_override_issued_at",
    )

    def update(self, instance: PersonaInstance) -> PersonaInstance:
        """Write a whole row back — WITHOUT moving the model tier from under it.

        ``update`` is a whole-row write, and its callers hold rows for a while:
        the chat turn loaded the instance at admission and wrote it back at
        settle, minutes later. A ``set-model`` landing in between (2026-10-01,
        ``personainst_dev_agent_8b319ebf``: set at 19:43:01Z inside a turn that
        started 19:40:41Z and settled 19:54:36Z) was silently reverted by that
        settle — eventless, because ``update`` emits nothing — and every chat
        after it ran the old model until the owner re-picked.

        So the tier's clock decides: when the row ON DISK carries a newer
        ``model_override_issued_at`` than the copy being written, the disk's
        five fields win and the stale copy's are dropped with a WARNING. A copy
        whose clock matches (or is newer) writes as before, and a model-tier
        field it does move ships a ``state.patched`` so no change to the tier
        is ever invisible to the read model.
        """

        instance.updated_at = now()
        moved = self._reconcile_model_lane_with_disk(instance)
        self._keep_newer_slot_assignment(instance)
        self._write(instance)
        if moved:
            self._emit_state_patch(instance, {name: getattr(instance, name) for name in moved})
        return self.get(instance.id)

    def patch_fields(self, persona_instance_id: str, **fields: Any) -> PersonaInstance:
        """Re-read the row and write ONLY ``fields`` onto it.

        The door for a caller that owns a few fields of a row it loaded long
        ago (the chat turn's ``skill_manifest_hash`` and its return-to-idle):
        everything else is taken from the row as it is NOW, so a concurrent
        rename, skills edit or model pick is never reverted by a turn that
        merely finished.
        """

        instance = self.get(persona_instance_id)
        moved: list[str] = []
        for name, value in fields.items():
            if not hasattr(instance, name):
                raise AttributeError(f"PersonaInstance has no field {name!r}")
            if getattr(instance, name) != value:
                moved.append(name)
            setattr(instance, name, value)
        written = self.update(instance)
        # Every folded field this write moved ships in one ``state.patched``, so a seat moved to a
        # copy (``agent_duplicate._repoint``) or renamed by a shipped update
        # (``bundled_agents.resolve``) reads under its new agent at once. ``update`` already
        # announces the model tier it moved.
        announced = [name for name in moved
                     if name in PERSONA_INSTANCE_FOLDED_STORE_FIELDS and name not in self._MODEL_LANE_FIELDS]
        if announced:
            self._emit_state_patch(written, {name: getattr(written, name) for name in announced})
        return written

    #: The repo-slot assignment (build plan §3.3) and its clock, ``slots_issued_at``.
    _SLOT_LANE_FIELDS: tuple[str, ...] = ("assigned_slots", "primary_slot", "slots_issued_at",
                                          "recall_shared_workspaces", "slot_context_files",
                                          "slot_context_custom")

    def _keep_newer_slot_assignment(self, instance: PersonaInstance) -> None:
        """A whole-row copy older than the stored slot assignment takes the stored one.

        The model lane's rule for the model lane's reason: a chat turn writes back a
        row it loaded at admission, and a ``slots.set`` landing mid-turn must not be
        reverted by that settle.
        """

        from agent_runtime.persona_assignments.profile import _as_utc

        try:
            stored = _decode_stored_instance(
                json.loads(paths.persona_instance_path(instance.id).read_text(encoding="utf-8"))
            )
        except Exception:  # absent/unreadable: no baseline to defend
            return
        stored_clock, copy_clock = stored.slots_issued_at, instance.slots_issued_at
        if stored_clock is not None and (copy_clock is None or _as_utc(copy_clock) < _as_utc(stored_clock)):
            for name in self._SLOT_LANE_FIELDS:
                setattr(instance, name, getattr(stored, name))

    def _reconcile_model_lane_with_disk(self, instance: PersonaInstance) -> list[str]:
        """Settle the model tier against the stored row; return the tier fields this write MOVES.

        A stale copy (its clock older than the disk's) takes the disk's tier and
        moves nothing. A missing or unreadable row is not a baseline: the write
        proceeds as it always did and reports nothing moved.
        """

        from agent_runtime.persona_assignments.profile import _as_utc

        try:
            stored = from_jsonable(
                PersonaInstance,
                json.loads(paths.persona_instance_path(instance.id).read_text(encoding="utf-8")),
            )
        except Exception:  # absent/unreadable: no baseline to defend
            return []
        stored_clock = stored.model_override_issued_at
        copy_clock = instance.model_override_issued_at
        stale = stored_clock is not None and (
            copy_clock is None or _as_utc(copy_clock) < _as_utc(stored_clock)
        )
        if stale:
            dropped = [
                name
                for name in self._MODEL_LANE_FIELDS
                if getattr(instance, name) != getattr(stored, name)
            ]
            for name in self._MODEL_LANE_FIELDS:
                setattr(instance, name, getattr(stored, name))
            if dropped:
                logging.getLogger(__name__).warning(
                    "persona_instance_stale_model_write_dropped instance=%s fields=%s "
                    "stored_issued_at=%s copy_issued_at=%s — a whole-row write held a "
                    "copy older than the stored model override; the stored override "
                    "was kept",
                    instance.id,
                    ",".join(dropped),
                    stored_clock,
                    copy_clock,
                )
            return []
        return [
            name
            for name in self._MODEL_LANE_FIELDS
            if name != "model_override_issued_at" and getattr(instance, name) != getattr(stored, name)
        ]

    #: The STORE fields ``open_chat`` may move, in one place, named.
    #:
    #: They were an anonymous pair of positional tuples until 2026-08-16, which
    #: was enough while their only consumer was the idempotence test
    #: (``before == after`` → observation, not mutation). The office
    #: fold-promotion plan gave them a second consumer that needs the NAMES: the
    #: paired ``state.patched`` must say WHICH fields moved, so the launcher
    #: folds a field subset instead of taking a full core. Two parallel literal
    #: tuples plus a third list of names is the shape that silently drifts, so
    #: there is one authority and the tuples are built from it.
    #:
    #: ``chat_head_home`` (and ``chat_head_kind`` beside it) is deliberately in
    #: the list even though it projects to
    #: no wire field: it must still count as a mutation for the idempotence gate
    #: above, and ``_PERSONA_INSTANCE_STORE_TO_WIRE`` drops it at the projection
    #: (an unmapped store field yields itself, and it is not in the wire row).
    _OPEN_CHAT_TRACKED_STORE_FIELDS: tuple[str, ...] = (
        "display_name",
        "profile_id",
        "workspace_id",
        "realm_id",
        "mode",
        "default_chat_session_id",
        "session_id",
        "chat_head_home",
        "chat_head_kind",
    )

    def add_instance(
        self,
        *,
        persona_id: str,
        placement_id: str,
        display_name: str | None = None,
        default_display_name: str | None = None,
        session_id: str | None = None,
        workspace_id: str | None = None,
        realm_id: str | None = None,
        client_scope: str | None = None,
        correlation_id: str | None = None,
    ) -> PersonaInstance:
        # ``correlation_id``: the placing gesture's token, handed to
        # ``open_chat`` (correlation-id plan P2) — the argv
        # ``persona instance open-chat --add-instance`` door's half of the join.
        normalized_persona = _normalize_instance_source_persona(persona_id)
        normalized_placement = safe_assignment_token(placement_id)
        if not normalized_placement:
            raise ValueError("placement_id is required for an additional persona instance")
        # ONE id shape and one rule (owner ruling 2026-10-15,
        # RT-AGENT-CREATE-REFUSES-UNMARKED): every placement door already asked
        # this, but the store took any token, and that is how the unmarked
        # ``personainst_chara_a2_7b31d0e4`` ghost was minted. The doors keep
        # their typed refusals; this is the floor none of them can skip.
        from agent_runtime.models import (
            PLACEMENT_ID_NOT_DISCRIMINABLE_REASON,
            looks_like_deliberate_placement,
            placement_id_not_discriminable_message,
        )

        if not looks_like_deliberate_placement(normalized_placement):
            raise ValueError(
                f"{PLACEMENT_ID_NOT_DISCRIMINABLE_REASON}: "
                + placement_id_not_discriminable_message(normalized_placement)
            )
        instance_id = persona_instance_id_for_placement(normalized_placement)
        try:
            existing = self.get(instance_id)
        except Exception:
            existing = None
        if existing is not None and existing.persona_id != normalized_persona:
            raise ValueError(f"placement already belongs to {existing.persona_id}: {normalized_placement}")
        normalized_session = safe_assignment_text(session_id, limit=200) if session_id is not None else None
        if normalized_session and self._session_owned_by_other_instance(normalized_session, instance_id):
            normalized_session = None
        display_name = self._numbered_seat_name(display_name, normalized_persona, instance_id)
        default_display_name = self._numbered_seat_name(default_display_name, normalized_persona, instance_id)
        # Reproduce ``open_chat``'s naming rule HERE so the chat title this mint
        # writes is the one the argv lane's post-hoc ensure would have written:
        # explicit name wins, an existing instance keeps its own, and the
        # persona default only lands on a row that has no name yet.
        bound_display_name = (
            safe_assignment_text(display_name, limit=120)
            or (
                safe_assignment_text(getattr(existing, "display_name", None), limit=120)
                if existing is not None
                else ""
            )
            or safe_assignment_text(default_display_name, limit=120)
        )
        root = normalized_session or persona_chat_session_id_for(instance_id)
        # See ``create_operator_chat``: every refusal this bind can raise is
        # decidable without writing, so it is decided before the root is made
        # durable rather than after.
        with timed_create_subphase("bindable_ms"):
            self.assert_bindable(
                persona_id=normalized_persona,
                session_id=root,
                persona_instance_id=instance_id,
            )
        # ``display_name`` is the operator's AUTHORITATIVE placement name and
        # always wins; ``default_display_name`` is the persona's honest default,
        # stamped only when the instance has no name yet — never enough to clobber
        # an existing distinct placement name on a re-open (open_chat enforces).
        return self.open_chat(
            persona_id=normalized_persona,
            persona_instance_id=instance_id,
            session_id=_durable_chat_root(
                root,
                persona_id=normalized_persona,
                display_name=bound_display_name,
                client_scope=client_scope,
            ),
            display_name=display_name,
            default_display_name=default_display_name,
            profile_id=_profile_id_for_persona_or_template(normalized_persona, ensure_persisted_personas),
            workspace_id=workspace_id,
            realm_id=realm_id,
            correlation_id=correlation_id,
        )

    def _numbered_seat_name(self, display_name: str | None, persona_id: str, instance_id: str) -> str | None:
        """The name a placed seat wears: ``display_name`` — numbered by THE seat rule
        (``numbered_instance_name``: ``Neko Mission Lead · 2``) when another placed
        instance of the agent, in any workspace, already wears it.

        Row Eternia ``MC-OLD-PLACEMENT-PATH-NAMES-A-SECOND-SEAT-WITH-PARENTHESES``
        (owner 2026-11-19: "numbered per agent across every workspace"; the runtime
        owns instance names): the argv ``--add-instance`` doors stored the caller's
        name verbatim, so Eternia counted ``(2)`` itself there. Every placing door
        passes here, so none keeps a rule of its own. The seat being written is not
        counted, so a retry keeps its number; an unreadable store numbers nothing.
        """

        name = safe_assignment_text(display_name, limit=120)
        if not name:
            return display_name
        from agent_runtime.agent_create.request import numbered_instance_name

        try:
            others = [
                instance.display_name
                for instance in self.list_all()
                if instance.persona_id == persona_id
                and instance.id != instance_id
                and instance.workspace_id
                and instance.display_name
            ]
        except Exception:
            return name
        # A name no other seat wears is the caller's own and is kept verbatim (a new
        # agent's name, a deliberate seat label); only a clash is numbered.
        key = " ".join(name.split()).casefold()
        if all(" ".join(other.split()).casefold() != key for other in others):
            return name
        return numbered_instance_name(name, others) or name

    def _session_owned_by_other_instance(self, session_id: str, instance_id: str) -> bool:
        """Is this chat session already the default of a DIFFERENT instance?

        A uniqueness guard, so it answers by searching, so its negative is worth
        exactly what its enumeration is worth: an instance row that will not
        decode is an owner this loop cannot see, the guard answers ``False``, and
        a second binding lands on a session that already had one — the class-key
        fence's blind spot, one subsystem over. Refuses rather than answering
        ``False`` it cannot support.
        """
        scan = self.scan_all()
        if scan.unreadable:
            raise PersonaInstancesUnreadable(
                f"cannot establish sole ownership of chat session {session_id}: "
                f"{scan.unreadable} persona instance row(s) will not decode; "
                "repair or remove them before binding"
            )
        for instance in scan.instances:
            if instance.id != instance_id and instance.default_chat_session_id == session_id:
                return True
        return False

    # S56 removed ``update_from_worker`` and ``_goal_id_for_worker`` with the
    # worker session store. They were the only way a persona instance could ever
    # be stamped ``mode="task_bound"`` from a worker row, and the only writer of
    # ``PersonaInstance.active_worker_session_id`` (a field that went with them).

    def scan_all(self) -> PersonaInstanceScan:
        """Every instance this root HAS, plus how many rows did not decode.

        THE chokepoint. ``list_all`` is the thin list view over it, so the many
        callers that only want rows keep their signature while the ones that
        must not describe a short answer as complete — the steering repair, the
        backlink release, the session-uniqueness guard — can ask the fuller
        question. Forking those readers is the failure this shape forbids.
        """

        directory = paths.persona_instances_dir()
        if not directory.exists():
            return PersonaInstanceScan([], 0)
        instances: list[PersonaInstance] = []
        unreadable = 0
        for path in sorted(directory.glob("*.json")):
            try:
                instances.append(_decode_stored_instance(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                unreadable += 1
                continue
        return PersonaInstanceScan(sorted(instances, key=lambda item: item.id), unreadable)

    def list_all(self) -> list[PersonaInstance]:
        return self.scan_all().instances

    def _has_live_binding(self, instance: PersonaInstance) -> bool:
        # S56 removed the worker arm: the store it read is gone and no instance
        # can carry ``active_worker_session_id`` any more. The run arm is the
        # whole check.
        run_id = safe_optional_token(instance.active_run_id)
        if run_id:
            try:
                from ..store import ACTIVE_RUN_STATES, RunStore

                run = RunStore().get(run_id)
                if run.state in ACTIVE_RUN_STATES:
                    return True
            except Exception:
                pass
        return False

    def _write(self, instance: PersonaInstance, *, character_change: CharacterAssignmentChange | CharacterAssignmentReplication | None = None, repair_unreadable: bool = False) -> PersonaInstance:
        if self.preparation_epoch is not None:
            self.preparation_epoch.invalidate()
        path = paths.persona_instance_path(instance.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with agent_record_write_lock("instance", instance.id):
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                stored = {}
            except json.JSONDecodeError:
                # Only the existing, once-per-row repair door may replace
                # corrupt JSON. Ordinary saves must not erase unknown data.
                if not repair_unreadable:
                    raise
                stored = {}
            if isinstance(character_change, CharacterAssignmentChange):
                # A character-only edit never writes a stale chat/profile row.
                instance = _decode_stored_instance(stored)
            elif isinstance(character_change, CharacterAssignmentReplication) and stored:
                from agent_runtime.persona_instance_sync.contract import PERSONA_INSTANCE_TRAVEL_FIELDS
                fresh = _decode_stored_instance(stored)
                for name in PERSONA_INSTANCE_TRAVEL_FIELDS - {"id", "persona_id", "steered_by"}:
                    setattr(fresh, name, getattr(instance, name))
                fresh.updated_at = instance.updated_at
                instance = fresh
            elif not stored and character_change is None and instance.character_assignment is None:
                # New identities can inherit a migrated persona immediately.
                # Existing rows with legacy placement choices stay untouched.
                from agent_runtime.config.roster import ensure_persisted_personas
                persona = next((p for p in ensure_persisted_personas() if p.id == instance.persona_id), None)
                if persona is not None and persona.character_assignment is not None:
                    instance.character_assignment = CharacterAssignmentChange(
                        0, "inherit", None, "initial-persona-inheritance",
                    ).apply(None)
            preserve_character_assignment(instance, stored, character_change)
            atomic_json_write(path, to_jsonable(instance), indent=2, sort_keys=True)
        return instance

    def set_character_assignment(self, instance_id: str, change: CharacterAssignmentChange) -> PersonaInstance:
        instance = self.get(instance_id)
        instance = self._write(instance, character_change=change)
        self._emit_state_patch(instance, {"character_assignment": instance.character_assignment})
        return instance

    def _event(self, event_type: str, instance: PersonaInstance, payload: dict[str, Any]) -> None:
        self.event_log.append(Event(ts=now(), type=event_type, task_id=instance.current_task_id, run_id=instance.active_run_id, persona_id=instance.persona_id, payload={**payload, "persona_instance_id": instance.id}))

    @staticmethod
    def _profile_patch_snapshot(instance: PersonaInstance) -> dict[str, Any]:
        """Operator-editable runtime fields watched for S6 field-patch diffs.

        Lists are copied so a before/after comparison is not fooled by in-place
        mutation of the same underlying object.

        ``skill_overrides`` keeps its ``None`` rather than collapsing to ``[]``,
        because this dict's ONLY job is the ``!=`` that decides whether a field
        moved, and those two values are the tri-state's two different answers
        ("no skills" versus "follow the template"). Collapsed, the
        ``--inherit-skills`` write diffed to nothing and shipped no
        ``state.patched`` field at all, so a connected launcher went on
        rendering the agent as customized until its next full snapshot."""

        return {
            "display_name": instance.display_name,
            "current_chat_goal": instance.current_chat_goal,
            "goal_id": instance.goal_id,
            "current_task_id": instance.current_task_id,
            "skill_overrides": (
                list(instance.skill_overrides) if instance.skill_overrides is not None else None
            ),
            "provider": instance.provider,
            "model": instance.model,
            "api_mode": instance.api_mode,
            "reasoning_effort": instance.reasoning_effort,
        }

    def _emit_state_patch(self, instance: PersonaInstance, changed: dict[str, Any]) -> None:
        """Emit an ``upsert`` ``state.patched`` entry for a persona-instance
        field change (S7-A producer; live unless ``read_model.delta_patches`` is
        explicitly off — it ships on). The store field NAMES that changed drive a WIRE-LEVEL projection
        (see :func:`emit_persona_instance_patch`) so the derived wire fields the
        launcher reads (``effective_model`` / ``skills`` / the display-name
        mirror / …) ship recomputed, not stale."""

        emit_persona_instance_patch(self.event_log, instance, list(changed.keys()))

    # ── lanes (composition): each binding makes a lane function a method, so
    # ``store.<name>(...)`` — and a test patching the class attribute — resolves
    # exactly as it did when the body lived here.

    # replicate
    replicate_instance = replicate_lane.replicate_instance
    _replica_row = replicate_lane._replica_row
    retire_replica = replicate_lane.retire_replica
    apply_replicated_steering = replicate_lane.apply_replicated_steering

    # steering
    steer = steering_lane.steer
    set_parents = steering_lane.set_parents
    add_parent = steering_lane.add_parent
    remove_parent = steering_lane.remove_parent
    detach_parents = steering_lane.detach_parents
    clear_parents = steering_lane.clear_parents
    _release_parent_references = steering_lane._release_parent_references
    _apply_steer_edges = steering_lane._apply_steer_edges
    _commit_steer = steering_lane._commit_steer
    _validate_no_steering_cycle = steering_lane._validate_no_steering_cycle

    # repair
    repair_non_instance_steering = repair_lane.repair_non_instance_steering
    repair_missing_steering_references = repair_lane.repair_missing_steering_references
    repair_missing_chat_session_bindings = repair_lane.repair_missing_chat_session_bindings
    retire_task_bound_rows = repair_lane.retire_task_bound_rows

    # chat_binding
    clear_chat_session_binding = chat_binding_lane.clear_chat_session_binding
    assert_bindable = chat_binding_lane.assert_bindable
    open_chat = chat_binding_lane.open_chat
    rollback_chat_root_bind = chat_binding_lane.rollback_chat_root_bind
    create_operator_chat = chat_binding_lane.create_operator_chat

    # profile_writes
    update_profile = profile_writes_lane.update_profile
    set_backing_profile = profile_writes_lane.set_backing_profile

    # retire
    _archive_office_placements = retire_lane._archive_office_placements
    retire = retire_lane.retire
    _write_retire_receipt = retire_lane._write_retire_receipt
    read_retire_receipt = retire_lane.read_retire_receipt
    _archive_instance_row = retire_lane._archive_instance_row
    retired_instance_ids = retire_lane.retired_instance_ids
    retired_instance_archive_path = retire_lane.retired_instance_archive_path
    retired_instance_row = retire_lane.retired_instance_row
