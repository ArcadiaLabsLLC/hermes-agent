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
from agent_runtime.agent_create_phases import timed_create_subphase
from agent_runtime.errors import PersonaInstancesUnreadable
from agent_runtime.events import EventLog
from agent_runtime.models import AgentPersona, Event, PersonaInstance
from agent_runtime.persona_assignments import (
    chat_binding as chat_binding_lane,
    profile_writes as profile_writes_lane,
    repair as repair_lane,
    replicate as replicate_lane,
    retire as retire_lane,
    steering as steering_lane,
)
from agent_runtime.persona_assignments.identity import (
    _durable_chat_root,
    _normalize_instance_source_persona,
    _profile_id_for_persona_or_template,
    canonical_persona_instance_id,
    persona_chat_session_id_for,
    persona_instance_id_for,
    persona_instance_id_for_placement,
)
from agent_runtime.persona_assignments.scan import (
    _note_unreadable_instance_row,
    PersonaInstanceScan,
)
from agent_runtime.persona_lifecycle import is_runtime_persona
from agent_runtime.serde import (
    from_jsonable,
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
    to_jsonable,
)
from agent_runtime.state_patches import emit_persona_instance_patch
from agent_runtime.states import WorkerSessionState

__layer__ = "stores"

__all__ = [
    "PersonaInstanceStore",
]


# S70 removed ``PersonaAssignmentSpec`` with the assignment MINT side (see the
# note above ``PersonaAssignmentStore``). The spec's one production consumer was
# ``create_or_resume``, whose one caller was the retired free-floating queue
# verb chain.


class PersonaInstanceStore:
    def __init__(self, event_log: EventLog | None = None):
        self.event_log = event_log or EventLog()

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

    def ensure_for_persona(self, persona: AgentPersona) -> PersonaInstance:
        """Materialize the canonical row for ``persona``, minting a missing one.

        TWO FAILURE SHAPES BEHIND ONE ``except``, SPLIT BY IC-3 (2026-08-22).

        This used to catch bare ``Exception`` and mint, which is right for a row
        that is not there and wrong for a row that is there and will not decode.
        Every build calls this for every persona
        (``snapshot.build_snapshot`` -> :meth:`ensure_for_personas`), so an
        unreadable row produced a file write AND a ``persona_instance.created``
        event on EVERY PASS, silently, forever. Measured consequence: that write
        moves an input the read-model cache's pre-build key already recorded, so
        the persisted key could never describe the store the next process stat'd
        — one of the named triggers behind the ``snapshot_core_cache
        never_converged`` receipt.

        * **COLD (the row is not there)** — ``FileNotFoundError``, after
          :meth:`get`'s id-drift resolution has failed to find one either. Mint,
          write, emit. UNCHANGED, deliberately: this is the ordinary cold-store
          and new-persona path and every suite pins it.
        * **UNREADABLE (the row is there and will not decode)** — anything else:
          malformed JSON, a payload :func:`from_jsonable` refuses, a permission
          error, a flaky share. Re-mint ONCE per process per row, with a WARNING
          naming the file and the error, because a corrupt row that repairs
          itself on the next build is the behaviour every caller already depends
          on. The SECOND time the same row will not decode in this process, the
          re-mint provably did not take — the store is rejecting the write, or
          something is corrupting the row behind us — and a third, fourth and
          thousandth mint would only keep hiding it. So that arm logs at ERROR
          and returns the row it WOULD have written, without touching the disk
          and without emitting a create event. The projection still sees a row;
          the store is left alone; the defect is on the log instead of in the
          fingerprint.

        The once-per-process memo is keyed on the row's PATH, not on the instance
        id: the id is stable across stores, and a memo keyed on it would let one
        test's or one profile's corrupt row silence another store's first
        legitimate repair.
        """

        instance_id = persona_instance_id_for(persona.id)
        try:
            existing = self.get(instance_id)
        except FileNotFoundError:
            return self._mint_instance(persona, instance_id)
        except Exception as exc:
            row_path = paths.persona_instance_path(instance_id)
            if _note_unreadable_instance_row(row_path):
                logging.getLogger(__name__).warning(
                    "persona_instance_row_unreadable path=%s instance=%s error=%s — "
                    "re-minting it once; a row that will not decode again after "
                    "this is a real defect and will be reported instead of "
                    "re-minted",
                    row_path,
                    instance_id,
                    exc,
                )
                return self._mint_instance(persona, instance_id)
            logging.getLogger(__name__).error(
                "persona_instance_row_unreadable path=%s instance=%s error=%s "
                "repeat=true — the re-mint did not take, so this build is NOT "
                "writing another row or emitting another persona_instance.created. "
                "Repair or remove the file; every build until then serves an "
                "in-memory row for this persona.",
                row_path,
                instance_id,
                exc,
            )
            return self._instance_row(persona, instance_id)
        changed = False
        if existing.display_name != persona.display_name:
            existing.display_name = persona.display_name
            changed = True
        if existing.profile_id != persona.hermes_profile:
            existing.profile_id = persona.hermes_profile
            changed = True
        if changed:
            existing.updated_at = now()
            self._write(existing)
        return self.get(instance_id)

    def _instance_row(self, persona: AgentPersona, instance_id: str) -> PersonaInstance:
        """The canonical row for a persona, as a VALUE — nothing is written here.

        Split out of the mint so the repeat-unreadable arm can answer with a row
        without also producing the durable write and the create event that arm
        exists to stop.
        """

        return PersonaInstance(
            id=instance_id,
            persona_id=persona.id,
            role=str(persona.role),
            display_name=persona.display_name,
            profile_id=persona.hermes_profile,
            runtime_root=str(paths.store_root()),
            state=WorkerSessionState.IDLE,
            updated_at=now(),
        )

    def _mint_instance(self, persona: AgentPersona, instance_id: str) -> PersonaInstance:
        """Write the canonical row and announce it — the cold path, unchanged."""

        instance = self._instance_row(persona, instance_id)
        self._write(instance)
        self._event("persona_instance.created", instance, {})
        return instance

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
        return from_jsonable(PersonaInstance, raw)

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

    def update(self, instance: PersonaInstance) -> PersonaInstance:
        instance.updated_at = now()
        self._write(instance)
        return self.get(instance.id)

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
    #: ``chat_head_home`` is deliberately in the list even though it projects to
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
    ) -> PersonaInstance:
        normalized_persona = _normalize_instance_source_persona(persona_id)
        normalized_placement = safe_assignment_token(placement_id)
        if not normalized_placement:
            raise ValueError("placement_id is required for an additional persona instance")
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
            ),
            display_name=display_name,
            default_display_name=default_display_name,
            profile_id=_profile_id_for_persona_or_template(normalized_persona),
            kill_active=False,
            workspace_id=workspace_id,
            realm_id=realm_id,
        )

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
                instances.append(from_jsonable(PersonaInstance, json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                unreadable += 1
                continue
        return PersonaInstanceScan(sorted(instances, key=lambda item: item.id), unreadable)

    def list_all(self) -> list[PersonaInstance]:
        return self.scan_all().instances

    def ensure_for_personas(self, personas: list[AgentPersona]) -> list[PersonaInstance]:
        """Materialize an instance for every configured persona and settle any
        instance still carrying a stale execution binding.

        S56 renamed this from ``derive_from_workers(personas, workers)``. The
        ``workers`` half is gone: ``build_snapshot`` had been passing a
        ``workers = []`` literal for two waves, so the "a live worker carries
        this persona's binding" branch could not be taken on the live tree, and
        the worker session store it read has since been deleted. What remains —
        the ensure pass plus the configured/idle reset — is exactly what ran
        before, now unconditionally rather than for "every persona with no live
        worker" (which was every persona).

        ``chat`` / ``free_floating`` instances are still skipped: an operator
        chat binding is not stale execution state.
        """
        personas = [persona for persona in personas if is_runtime_persona(persona)]
        for persona in personas:
            self.ensure_for_persona(persona)
        for persona in personas:
            instance = self.ensure_for_persona(persona)
            if instance.mode in {"chat", "free_floating"}:
                continue
            # S70 (contract 54): the two receipt-id disjuncts that used to widen
            # this predicate are gone with the fields. They were always falsy —
            # nothing had written either since the worker/goal lanes died — so
            # the set of instances this resets is unchanged.
            if (
                instance.state != WorkerSessionState.IDLE
                or instance.current_assignment_id
                or instance.current_task_id
                or instance.active_run_id
            ):
                instance.state = WorkerSessionState.IDLE
                instance.mode = "configured"
                instance.current_assignment_id = None
                instance.current_task_id = None
                instance.goal_id = None
                instance.spawned_by = None
                instance.steered_by = []
                instance.active_run_id = None
                instance.token_budget_used = 0
                instance.last_heartbeat_at = None
                self.update(instance)
        return self.list_all()

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

    def _write(self, instance: PersonaInstance) -> None:
        path = paths.persona_instance_path(instance.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, to_jsonable(instance), indent=2, sort_keys=True)

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
