"""``PersonaInstanceStore`` — the persona-instance roster store (one JSON row per
instance under ``paths.persona_instances_dir()``), moved here whole.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from hermes_time import now
from utils import atomic_json_write

from agent_runtime import paths
from agent_runtime.agent_create_phases import timed_create_subphase
from agent_runtime.errors import PersonaInstancesUnreadable
from agent_runtime.events import EventLog
from agent_runtime.models import (
    AgentPersona,
    Event,
    looks_like_persona_instance_id,
    PERSONA_INSTANCE_ID_PREFIX,
    PersonaInstance,
)
from agent_runtime.persona_lifecycle import is_runtime_persona
from agent_runtime.serde import from_jsonable, to_jsonable
from agent_runtime.state_patches import (
    emit_persona_instance_create,
    emit_persona_instance_patch,
    emit_persona_instance_remove,
)
from agent_runtime.states import WorkerSessionState
from agent_runtime.persona_assignments.errors import (
    PersonaInstanceRetireError,
    RetiredPersonaInstanceError,
    StaleModelOverrideWrite,
)
from agent_runtime.persona_assignments.identity import (
    _coerce_travel_value,
    _display_name_for_template,
    _durable_chat_root,
    _MISSING_TRAVEL_FIELD,
    _normalize_instance_source_persona,
    _profile_id_for_persona_or_template,
    _role_for_persona_or_template,
    canonical_chat_instance_id,
    canonical_persona_instance_id,
    chat_session_is_foreign_to_instance,
    chat_session_owner_instance_id,
    is_canonical_persona_channel,
    persona_chat_session_id_for,
    persona_instance_id_for,
    persona_instance_id_for_placement,
)
from agent_runtime.persona_assignments.profile import (
    _as_utc,
    _normalize_reasoning_effort_override,
    _safe_model_override_text,
)
from agent_runtime.persona_assignments.retire import (
    _retired_persona_instance_archive_path,
    retire_receipt_path,
    retired_persona_instance_ids,
)
from agent_runtime.persona_assignments.scan import (
    _note_unreadable_instance_row,
    _session_presence_probe,
    PersonaInstanceScan,
    PersonaScanRefusal,
)
from agent_runtime.persona_assignments.tokens import (
    _dedupe_tokens,
    _safe_skill_overrides,
    safe_assignment_text,
    safe_assignment_token,
    safe_optional_token,
)
from agent_runtime.persona_assignments.vocabulary import (
    _BINDING_REPAIR_REASON,
    _CHAT_MODES,
)

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

    def replicate_instance(
        self,
        body: dict[str, Any],
        *,
        realm_id: str,
        adopt_existing: PersonaInstance | None = None,
    ) -> PersonaInstance:
        """THE door a realm pull writes a replicated agent through.

        A replication mint is a **THIRD intent class** (plan §3.5). It is not
        AUTHORED — no operator clicked on this machine, so it must not produce
        the receipts an authored create produces — and it is not DIAGNOSTIC — it
        is not a repair of a local projection against a local truth, but the
        arrival of a peer's authored fact. So it gets its own verb here and its
        own event type (``persona_instance.replicated``), rather than reusing
        ``_mint_instance``: ``persona_instance.created`` means "this machine
        authored an agent" to every consumer that reads it, and one pull would
        otherwise look like N creates in the log an operator greps.

        Why a STORE DOOR and not a raw ``persona_instances/`` write in the
        applier. Three facts are store-level and all three would be lost:

        * the DELTA PATCH. This is the one place not to repeat a mistake made
          one lane over three days ago — ``apply_board_pull`` writes cards with
          raw atomic writes, so a pull that GIVES you a card reaches no live
          consumer while one that ARCHIVES a card emits (open queue row). A
          replicated instance that needs an app restart to appear has not been
          replicated as far as the operator is concerned.
        * the §1.3 DERIVATIONS. ``role`` / ``profile_id`` / ``runtime_root`` /
          ``state`` / the durable chat root are this machine's answers, and an
          applier deriving them would be a second authority over what a
          persona-instance row means.
        * the EVENT-then-patch ordering the rest of this store keeps.

        ``adopt_existing`` is the ADOPT arm: the row is already here and only
        the travelling surface moves. Every §1.2 field on it is preserved
        BY CONSTRUCTION — the arm copies the existing record and writes only
        allowlisted keys onto it — so this door cannot express "adopt a live
        binding" even by mistake.

        No tombstone is minted here, ever: nothing is being deleted. No office
        write happens here either — the desk arrived through its own lane, and
        writing it again would be a second authority over one row.
        """

        from ..persona_instance_sync import (
            PERSONA_INSTANCE_ALLOWED_KEYS,
            cleared_travel_value,
        )

        instance_id = str(body["id"])
        persona_id = str(body["persona_id"])
        if adopt_existing is not None:
            instance = replace(adopt_existing)
            created = False
        else:
            instance = self._replica_row(instance_id, persona_id, body)
            created = True

        # The travelling SURFACE, wholesale. A key the publisher cleared clears
        # here too — a locally stale override that outlived the upstream write
        # removing it is the same clobber class the record split exists to end.
        # ``steered_by`` is deliberately NOT applied here: the edges are phase
        # two (plan §3.4), because an edge may name a parent this pass has not
        # minted yet.
        for name in sorted(PERSONA_INSTANCE_ALLOWED_KEYS - {"id", "persona_id", "steered_by"}):
            value = body.get(name, _MISSING_TRAVEL_FIELD)
            if value is _MISSING_TRAVEL_FIELD:
                value = cleared_travel_value(name)
            setattr(instance, name, _coerce_travel_value(name, value))
        instance.updated_at = now()

        self._write(instance)
        if created:
            emit_persona_instance_create(self.event_log, instance)
        else:
            emit_persona_instance_patch(
                self.event_log,
                instance,
                [*sorted(PERSONA_INSTANCE_ALLOWED_KEYS - {"id", "persona_id"}), "updated_at"],
            )
        # ``source``/``realm_id`` on the payload: the ``updated_by="realm_sync"``
        # precedent, so an operator reading the log can tell a peer's arrival
        # from their own click without joining against anything.
        self._event(
            "persona_instance.replicated",
            instance,
            {
                "source": "realm_sync",
                "realm_id": str(realm_id),
                "action": "replicated" if created else "adopted",
            },
        )
        return instance

    def _replica_row(self, instance_id: str, persona_id: str, body: dict[str, Any]) -> PersonaInstance:
        """A brand-new replica's LOCAL half — plan §1.3, derived, never carried.

        ``role`` and ``profile_id`` come from the persona definition that
        arrived in the SAME pull (the applier runs after
        ``apply_persona_config_pull`` for exactly this reason); travelling them
        would let a stale copy shadow the definition beside it. The chat root is
        minted fresh AND MADE DURABLE before the bind — a pointer that travelled
        would resolve to a SessionDB row the receiver does not have, which is
        precisely the ``unknown_chat_session`` defect ``_durable_chat_root`` was
        written to retire. A failure there RAISES, so the applier refuses this
        row and keeps pulling rather than binding a root it did not persist.
        """

        display_name = safe_assignment_text(body.get("display_name"), limit=120)
        return PersonaInstance(
            id=instance_id,
            persona_id=persona_id,
            role=str(_role_for_persona_or_template(persona_id) or ""),
            display_name=display_name,
            profile_id=_profile_id_for_persona_or_template(persona_id),
            runtime_root=str(paths.store_root()),
            state=WorkerSessionState.IDLE,
            default_chat_session_id=_durable_chat_root(
                persona_chat_session_id_for(instance_id),
                persona_id=persona_id,
                display_name=display_name,
            ),
            updated_at=now(),
        )

    def retire_replica(
        self,
        persona_instance_id: str,
        *,
        reason: str = "remote_removed",
        realm_id: str | None = None,
    ) -> dict[str, Any]:
        """Archive a replicated row when its DESK left — plan §5.2, nothing else.

        Two things this deliberately does NOT do, and both are the point:

        * **It runs no office half.** :meth:`retire` calls
          ``_archive_office_placements``, which archives through
          ``remove_actor``'s DEFAULT ``record_tombstone=True`` — a realm-visible
          ledger entry. Here the authored tombstone already exists upstream, and
          the pull's own office lane has already archived the local desk that
          triggered this, so minting a second one is the duplicate-authority
          defect §5.2 forbids. That is what "``record_tombstone=False``
          semantics" MEANS for this family: a persona-instance row has no
          realm-visible ledger of its own, so withholding the office write is
          the whole of it.
        * **It mints no tombstone of any kind.** Nothing in the replication lane
          ever does. The row MOVES to the archive (archive-never-delete) and the
          projection stops listing it, exactly as :meth:`retire` does.

        Refuses typed — never silently — on the two guards :meth:`retire`
        carries: a canonical channel (which never replicates at all, so reaching
        this door with one is a caller bug worth naming) and a LIVE run binding.
        A working agent is never archived; the pull accounts it as held and
        re-decides next pass, the "keep the baseline, retry" repair
        ``_reconcile_actors`` already uses one lane over.
        """

        instance = self.get(persona_instance_id)
        if is_canonical_persona_channel(instance):
            raise PersonaInstanceRetireError(
                "canonical_persona_channel",
                f"{instance.id} is a canonical persona channel and never replicates",
                persona_instance_id=instance.id,
                detail={"persona_id": instance.persona_id},
            )
        if self._has_live_binding(instance):
            raise PersonaInstanceRetireError(
                "instance_active",
                f"{instance.id} has a live run binding; never archive a working agent",
                persona_instance_id=instance.id,
                detail={"active_run_id": safe_optional_token(instance.active_run_id)},
            )

        archive_dir = (
            paths.persona_instances_archive_dir()
            / f"{now().strftime('%Y%m%dT%H%M%SZ')}_replica_retire"
        )
        archived_path = self._archive_instance_row(instance, archive_dir)
        if archived_path is None:
            raise PersonaInstanceRetireError(
                "not_found",
                f"persona instance row is not on disk: {instance.id}",
                persona_instance_id=instance.id,
            )
        payload: dict[str, Any] = {
            "reason": safe_assignment_text(reason, limit=240) or "remote_removed",
            "persona_id": instance.persona_id,
            "mode": instance.mode,
            "archive_dir": str(archive_dir),
            "source": "realm_sync",
        }
        if realm_id:
            payload["realm_id"] = str(realm_id)
        self._event("persona_instance.retired", instance, payload)
        emit_persona_instance_remove(self.event_log, instance)
        return {
            "persona_instance_id": instance.id,
            "persona_id": instance.persona_id,
            "archive_path": str(archived_path),
            "archive_dir": str(archive_dir),
        }

    def apply_replicated_steering(
        self, persona_instance_id: str, parents: list[str], *, realm_id: str
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Phase TWO of the mint (plan §3.4): the authored steering edges.

        Returns ``(applied, dropped)``. An edge whose target is still absent
        after phase one is DROPPED with a typed row, never silently — the target
        may be a row this realm never published, or one whose own admission was
        refused. ``_validate_no_steering_cycle`` runs per edge, so a hostile or
        corrupt remote graph cannot install a cycle even though every edge in it
        passed the content door.
        """

        applied: list[str] = []
        dropped: list[dict[str, str]] = []
        for parent in _dedupe_tokens(parents):
            if parent == persona_instance_id:
                dropped.append({"parent": parent, "reason": "self_edge"})
                continue
            if not paths.persona_instance_path(parent).exists():
                dropped.append({"parent": parent, "reason": "parent_absent"})
                continue
            try:
                self._validate_no_steering_cycle(persona_instance_id, parent)
            except Exception as exc:  # noqa: BLE001 — accounted, never silent
                dropped.append({"parent": parent, "reason": type(exc).__name__})
                continue
            applied.append(parent)
        try:
            instance = self.get(persona_instance_id)
        except Exception as exc:  # noqa: BLE001 — the row went away under us
            dropped.append({"parent": "", "reason": type(exc).__name__})
            return [], dropped
        if list(instance.steered_by) == applied:
            return applied, dropped
        instance.steered_by = applied
        instance.updated_at = now()
        self._write(instance)
        emit_persona_instance_patch(self.event_log, instance, ["steered_by", "updated_at"])
        self._event(
            "persona_instance.replicated",
            instance,
            {
                "source": "realm_sync",
                "realm_id": str(realm_id),
                "action": "steered",
                "steered_by": list(applied),
            },
        )
        return applied, dropped

    def steer(
        self,
        persona_instance_id: str,
        *,
        parent_instance_id: str | None,
        goal_id: str | None = None,
        detach: bool = False,
    ) -> PersonaInstance:
        """Back-compat single-parent re-route (Stage 77).

        Preserves the original ``--parent`` semantics EXACTLY: replace the whole
        steering set with the one given parent, or clear it on ``detach``. New
        multi-parent callers use :meth:`set_parents` / :meth:`add_parent` /
        :meth:`remove_parent` / :meth:`detach_parents`. This is a re-route (a
        STEER verb, ungated per 76D.3), never a create/kill.
        """
        if detach:
            return self.detach_parents(persona_instance_id)
        normalized_parent = safe_optional_token(parent_instance_id)
        if not normalized_parent:
            raise ValueError("parent_instance_id is required unless detach is set")
        return self.set_parents(persona_instance_id, [normalized_parent], goal_id=goal_id)

    def set_parents(
        self,
        persona_instance_id: str,
        parent_instance_ids: list[str],
        *,
        goal_id: str | None = None,
    ) -> PersonaInstance:
        """Declaratively REPLACE a child's steering-parent set (fan-in).

        The Launcher graph-save reconciler asserts the desired set per child
        with this; it is idempotent (re-asserting the same set is a no-op) and
        the single write path for the persisted living-graph wiring. An empty
        set detaches the child (standalone owner).
        """
        normalized = _dedupe_tokens(parent_instance_ids)
        if not normalized:
            return self.detach_parents(persona_instance_id)
        return self._apply_steer_edges(persona_instance_id, normalized, goal_id=goal_id)

    def add_parent(
        self,
        persona_instance_id: str,
        parent_instance_id: str,
        *,
        goal_id: str | None = None,
    ) -> PersonaInstance:
        """Idempotently ADD one parent to a child's steering set (set-union)."""
        normalized_parent = safe_optional_token(parent_instance_id)
        if not normalized_parent:
            raise ValueError("parent_instance_id is required")
        instance = self.get(persona_instance_id)
        desired = list(instance.steered_by)
        if normalized_parent not in desired:
            desired.append(normalized_parent)
        return self._apply_steer_edges(persona_instance_id, desired, goal_id=goal_id, _instance=instance)

    def remove_parent(self, persona_instance_id: str, parent_instance_id: str) -> PersonaInstance:
        """Remove ONE parent from a child's steering set (detach-one).

        Removing the last parent detaches the child (standalone owner).
        """
        normalized_parent = safe_optional_token(parent_instance_id)
        instance = self.get(persona_instance_id)
        desired = [pid for pid in instance.steered_by if pid != normalized_parent]
        if not desired:
            return self.detach_parents(persona_instance_id)
        return self._apply_steer_edges(persona_instance_id, desired, goal_id=instance.goal_id, _instance=instance)

    def detach_parents(self, persona_instance_id: str) -> PersonaInstance:
        """Clear a child's entire steering set (detach-all) → standalone owner."""
        instance = self.get(persona_instance_id)
        removed = list(instance.steered_by)
        updates: dict[str, Any] = {
            "steered_by": [],
            "spawned_by": None,
            "goal_id": None,
            "current_task_id": None,
        }
        if instance.mode == "task_bound":
            updates["mode"] = "configured"
        self._commit_steer(instance, updates, added=[], removed=removed, detached=True)
        return self.get(instance.id)

    def clear_parents(self, persona_instance_id: str) -> PersonaInstance:
        """Clear a child's steering set WITHOUT leaving its mission.

        The flow-doc reconcile's "drawn standalone" verb: an operator's chart
        states who steers whom — never goal membership. [detach_parents] above
        is a different statement ("leave the mission": it also strips goal_id /
        current_task_id and task-bound mode), and using it for a chart ingest
        would unbind a root agent from its live goal. Same single write path
        ([_commit_steer]) and event as every other steer mutation."""

        instance = self.get(persona_instance_id)
        removed = list(instance.steered_by)
        self._commit_steer(
            instance,
            {"steered_by": [], "spawned_by": None},
            added=[],
            removed=removed,
            detached=True,
        )
        return self.get(instance.id)

    def repair_non_instance_steering(
        self,
        persona_instance_id: str | None = None,
        *,
        apply: bool = True,
    ) -> dict[str, Any]:
        """Strip non-instance principals out of steering fields (evented, dry-run aware).

        A steering-parent SET (``steered_by``) and its mirror (``spawned_by``)
        may hold ONLY persona-instance ids. A legacy mint seeded the operator
        principal into them (``steered_by=["operator"]`` / ``spawned_by=
        "operator"``), which the HUD then rendered as a phantom "steered by
        operator" edge. This removes the non-instance entries surgically:

        - ``steered_by`` keeps only its instance-shaped parents;
        - a NON-instance ``spawned_by`` is re-pointed at the surviving primary
          parent (``steered_by[0]``) when one remains, else cleared — restoring
          the mirror invariant. An already instance-shaped ``spawned_by`` is left
          untouched (the ``__post_init__`` backfill self-heals it into a bare
          ``steered_by``), so a valid parent is never destroyed.

        Everything else on the row (mode, goal, session) is untouched — this is a
        steering repair, not a detach. Honors dry-run: with ``apply=False``
        nothing is written and no event is emitted (the on-disk row stays
        byte-identical); with ``apply=True`` each repaired row goes through the
        single steer write path (``_commit_steer`` → one
        ``persona_instance.steered`` event + state patch).
        ``persona_instance_id`` targets one row; ``None`` scans every row.
        """
        targets = (
            [self.get(persona_instance_id)]
            if persona_instance_id
            else self.list_all()
        )
        repairs: list[dict[str, Any]] = []
        for instance in targets:
            steered_before = list(instance.steered_by)
            kept = [p for p in steered_before if looks_like_persona_instance_id(p)]
            bogus_steered = [p for p in steered_before if not looks_like_persona_instance_id(p)]
            spawned = instance.spawned_by
            bogus_spawn = (
                spawned
                if (spawned and not looks_like_persona_instance_id(spawned))
                else None
            )
            if not bogus_steered and bogus_spawn is None:
                continue
            updates: dict[str, Any] = {"steered_by": kept}
            # Only rewrite the mirror when it is itself bogus; re-point it at the
            # surviving primary, or clear it when no instance parent remains.
            desired_spawn = spawned
            if bogus_spawn is not None:
                desired_spawn = kept[0] if kept else None
                updates["spawned_by"] = desired_spawn
            record = {
                "persona_instance_id": instance.id,
                "steered_by_before": steered_before,
                "steered_by_after": kept,
                "spawned_by_before": spawned,
                "spawned_by_after": desired_spawn,
                "removed_steered_by": bogus_steered,
                "removed_spawned_by": bogus_spawn,
            }
            repairs.append(record)
            if not apply:
                continue
            self._commit_steer(
                instance,
                updates,
                added=[],
                removed=bogus_steered,
                detached=not kept,
            )
        return {
            "applied": bool(apply),
            "dry_run": not apply,
            "repaired": repairs,
            "repaired_count": len(repairs),
        }

    def repair_missing_steering_references(
        self,
        *,
        apply: bool = True,
    ) -> dict[str, Any]:
        """Remove steering parents that no longer resolve to a live instance.

        JSON shape validation cannot catch a syntactically valid id whose row
        has been retired or reaped. This is the referential-integrity repair:
        it preserves every live parent and all child context, rewrites the
        ``spawned_by`` mirror, and emits the ordinary steering event when
        applied. Dry-run is side-effect free.

        REFUSES, whole, when any instance row will not decode. ``live_ids`` is
        this repair's entire notion of what exists, and it is derived by
        SUBTRACTION: a parent id absent from it is stripped from its child as
        dangling. An unreadable row is absent from it for a reason that has
        nothing to do with the parent being gone — so under the short list every
        child edge naming that row is destroyed, and the strip is a delete-shaped
        write minted out of a parse error. There is no partial answer available
        here the way there is for a per-workspace office publish: one unreadable
        row poisons the membership question for EVERY child at once, because the
        set is what the predicate tests against. So the refusal is the whole
        sweep, it writes nothing, and it says how many rows it could not read.
        """
        scan = self.scan_all()
        refusal = PersonaScanRefusal.for_scan("persona_instances", scan.unreadable)
        if refusal is not None:
            return {
                "applied": False,
                "dry_run": not apply,
                "refused": refusal.as_dict(),
                "repaired": [],
                "repaired_count": 0,
            }
        instances = scan.instances
        live_ids = {instance.id for instance in instances}
        repairs: list[dict[str, Any]] = []
        for instance in instances:
            before = list(instance.steered_by)
            kept = [parent for parent in before if parent in live_ids]
            missing = [parent for parent in before if parent not in live_ids]
            spawned_before = instance.spawned_by
            spawned_missing = bool(
                spawned_before
                and looks_like_persona_instance_id(spawned_before)
                and spawned_before not in live_ids
            )
            if not missing and not spawned_missing:
                continue
            spawned_after = kept[0] if kept else None
            repairs.append(
                {
                    "persona_instance_id": instance.id,
                    "steered_by_before": before,
                    "steered_by_after": kept,
                    "spawned_by_before": spawned_before,
                    "spawned_by_after": spawned_after,
                    "missing_parent_ids": sorted(set(missing + ([spawned_before] if spawned_missing else []))),
                }
            )
            if not apply:
                continue
            self._commit_steer(
                instance,
                {"steered_by": kept, "spawned_by": spawned_after},
                added=[],
                removed=missing,
                detached=not kept,
            )
        return {
            "applied": bool(apply),
            "dry_run": not apply,
            # Additive and uniform across both arms, so a consumer reads one
            # shape: ``None`` is the positive statement "the whole store was
            # readable", never the absence of an answer.
            "refused": None,
            "repaired": repairs,
            "repaired_count": len(repairs),
        }

    def clear_chat_session_binding(
        self,
        instance: PersonaInstance,
        *,
        session_id: str,
        reason: str,
    ) -> dict[str, Any] | None:
        """THE write path that unbinds one instance from a chat session.

        Nulls only the pointers that actually reference ``session_id``, demotes a
        conversational mode back to ``configured`` once the instance is left with
        no chat, persists once, and emits ``persona_instance.chat_binding_cleared``
        (store mutations always emit an event). Returns the repair record, or
        ``None`` when the instance never pointed at that session.

        Every STALE-binding clear — the operator ``persona chat delete`` verb and
        the ``repair_missing_chat_session_bindings`` reconcile sweep — goes
        through here, so a binding whose session is gone can never be reaped
        silently by one path and loudly by another.

        Why that claim is narrower than it used to be
        ---------------------------------------------
        It used to say "every unbind", and since ``b912cce88a`` that was false:
        :meth:`rollback_chat_root_bind` also nulls chat pointers, and it emits no
        ``chat_binding_cleared``. The sentence was corrected rather than made true
        by routing the retraction through here, because the retraction cannot
        become a call to this method without losing three properties it needs:

        * **It restores, it does not clear.** A retraction puts the row's PREVIOUS
          pointer back (a later mint failing must not orphan the conversation the
          instance already had). This method only ever nulls, and only the fields
          that match one ``session_id``.
        * **It must not raise.** It runs inside the failure handler of a lane that
          already holds a typed error; this method lets ``update`` propagate, and a
          rollback that masks its caller's cause is worse than the litter it sweeps.
        * **It must move the read model, and it is the ONLY thing that can.**
          The retraction emits ``emit_persona_instance_patch`` and appends
          nothing else — ``update`` is eventless — so with the patch removed the
          row write is invisible to the stream entirely, while the ``chat_opened``
          the failed bind already appended IS covered
          (:data:`patch_coverage.LIVE_COVERED_DOMAIN_EVENT_TYPES`) and can promote
          its batch to a patch frame. A connected client would fold the BIND and
          never hear the unbind. This method's event is uncovered and demotes the
          whole batch instead (see below), so routing the retraction through here
          would trade a false docstring for a genuinely stale client.

        Why this method emits NO ``state.patched``, measured rather than assumed
        ---------------------------------------------------------------------
        Not "because it emits a domain event" — the retraction's argument above
        is not the mirror image of that, and the sibling emits one too. The
        reason is what reaches the WIRE, and it was captured from a run:

        * ``persona_instance.chat_binding_cleared`` is deliberately absent from
          :data:`patch_coverage.COVERED_DOMAIN_EVENT_TYPES`. One uncovered event
          makes the whole coalesced batch uncoverable
          (:func:`patch_coverage.batch_is_patch_coverable`), so every frame
          carrying a clear ships with a full ``core`` attached and the client
          re-hydrates IN THAT SAME FRAME. There is no staleness window to close,
          and a ``state.patched`` emitted here would be a producer whose rows are
          discarded before the ``patches`` list is ever assembled — including
          when ``read_model.delta_patches`` is off, where the lane is a full core
          by design. This path is flag-independent; the retraction is not.
        * The demote is LOAD-BEARING, not an oversight waiting to be optimised.
          A clear also empties the instance's ``persona_chat_history`` row (the
          projection keys chat rows by ``default_chat_session_id``; drop the
          pointer and the row leaves the section outright), and there is no
          ``persona_chat_history`` patch entity for that to ride. Covering this
          event to make a patch reachable would therefore silently drop the
          chat-row departure from every connected client — the exact failure the
          ``persona_instance.chat_opened`` note in ``patch_coverage`` says the
          producer and the coverage entry must land together to avoid.

        Both halves are pinned as behaviour in ``test_persona_assignments.py``
        (the clear's batch demotes; covering it would drop a chat-history row),
        so this is a checkable claim rather than an assurance.

        The two paths are therefore both legitimate and both accounted for, and
        the count is fenced: ``test_persona_assignments.py`` walks this module's
        AST and fails if a THIRD function ever writes ``default_chat_session_id``
        or ``session_id`` on an instance.
        """

        target = safe_assignment_text(session_id, limit=200)
        if not target:
            return None
        cleared: list[str] = []
        if safe_assignment_text(instance.default_chat_session_id, limit=200) == target:
            instance.default_chat_session_id = None
            cleared.append("default_chat_session_id")
        if safe_assignment_text(instance.session_id, limit=200) == target:
            instance.session_id = None
            cleared.append("session_id")
        if not cleared:
            return None
        mode_before = instance.mode
        if (
            not instance.default_chat_session_id
            and not instance.session_id
            and (instance.mode or "").lower() in _CHAT_MODES
        ):
            instance.mode = "configured"
        updated = self.update(instance)
        payload = {
            "persona_id": updated.persona_id,
            "session_id": target,
            "cleared_fields": cleared,
            "mode_before": mode_before,
            "mode_after": updated.mode,
            "reason": reason,
        }
        self._event("persona_instance.chat_binding_cleared", updated, payload)
        return {"persona_instance_id": updated.id, **payload}

    def repair_missing_chat_session_bindings(
        self,
        *,
        apply: bool = True,
        session_db: Any | None = None,
    ) -> dict[str, Any]:
        """Clear chat-session bindings whose session SessionDB no longer has.

        A persona instance can outlive its chat: the operator deletes the
        conversation through a path that does not own the instance store (the
        generic ``hermes sessions delete``, a gateway/web delete, a scrub), and
        the pointer is left dangling. The snapshot's persona-chat projection is
        READ-ONLY, so it can only hide the row and account a ``session_not_in_db``
        drop — one permanent parity anomaly per orphan, forever. This is the
        write-path repair that retires them.

        Fail-safe by construction:

        * a binding is cleared ONLY on a positive "absent" answer from a
          positively-enumerating SessionDB; an unavailable, unreadable or empty
          database repairs nothing at all (see :func:`_session_presence_probe`),
          because a blind read must never reap a live pointer;
        * ``task_bound`` instances are skipped entirely — a mission turn runs in
          a session that lives in the run/event stream and is legitimately absent
          from the operator SessionDB;
        * an instance with a live worker/run binding is held;
        * ``apply=False`` is a pure report: no writes, no events.
        """

        probe, skip_reason = _session_presence_probe(session_db)
        if probe is None:
            return {
                "applied": False,
                "dry_run": not apply,
                "skipped": skip_reason,
                "repaired": [],
                "repaired_count": 0,
                "held": [],
                "held_count": 0,
            }

        repairs: list[dict[str, Any]] = []
        held: list[dict[str, Any]] = []
        for instance in self.list_all():
            pointers = {
                safe_assignment_text(instance.default_chat_session_id, limit=200),
                safe_assignment_text(instance.session_id, limit=200),
            }
            # Legacy rows may persist either pointer as an empty string. That is
            # already the absence of a binding, not a session id to probe. Keep
            # dry-run and apply on the same candidate set: before this filter a
            # dry-run reported a repair for ``""`` while apply delegated to
            # ``clear_chat_session_binding``, which correctly rejected the empty
            # target and wrote nothing.
            pointers = {pointer for pointer in pointers if pointer}
            if not pointers:
                continue
            if (instance.mode or "").lower() == "task_bound" or safe_optional_token(
                instance.current_task_id
            ):
                # Mission sessions live in the run/event stream, not SessionDB.
                continue
            missing = sorted(session_id for session_id in pointers if probe(session_id) == "absent")
            if not missing:
                continue
            if self._has_live_binding(instance):
                held.extend(
                    {
                        "persona_instance_id": instance.id,
                        "persona_id": instance.persona_id,
                        "session_id": session_id,
                        "reason": "active-binding",
                    }
                    for session_id in missing
                )
                continue
            for session_id in missing:
                if not apply:
                    repairs.append(
                        {
                            "persona_instance_id": instance.id,
                            "persona_id": instance.persona_id,
                            "session_id": session_id,
                            "cleared_fields": [
                                field_name
                                for field_name, value in (
                                    ("default_chat_session_id", instance.default_chat_session_id),
                                    ("session_id", instance.session_id),
                                )
                                if safe_assignment_text(value, limit=200) == session_id
                            ],
                            "reason": _BINDING_REPAIR_REASON,
                        }
                    )
                    continue
                record = self.clear_chat_session_binding(
                    instance,
                    session_id=session_id,
                    reason=_BINDING_REPAIR_REASON,
                )
                if record is not None:
                    repairs.append(record)
        return {
            "applied": bool(apply),
            "dry_run": not apply,
            "repaired": repairs,
            "repaired_count": len(repairs),
            "held": held,
            "held_count": len(held),
        }

    def _release_parent_references(self, parent_instance_id: str) -> list[str]:
        """Transactionally release every child backlink before owner removal.

        REFUSES when any instance row will not decode, because "every" is the
        whole promise. This runs immediately before the owner's row leaves the
        live directory; a child whose file could not be read keeps a backlink to
        an id that is about to stop resolving, and nothing downstream will ever
        revisit it — the owner is gone, so no later sweep can rediscover what the
        edge pointed at. Refusing costs the operator a retire they must repair
        the store to complete; proceeding costs a dangling edge nobody can
        reconstruct.

        THE chokepoint for this fact. The one write path that removes an owner
        (:meth:`retire`, via :meth:`_archive_instance_row`) reaches it, and it
        runs BEFORE that path moves the file, so a refusal leaves the store
        exactly as it found it. It stays a chokepoint rather than an inline step
        inside that caller because the NEXT owner-removing path must arrive here
        too: the unlinking ``_delete`` that used to be the second caller was
        reaped at ML-16 with zero callers repo-wide, and whatever replaces it
        must not re-derive this rule.
        """
        scan = self.scan_all()
        if scan.unreadable:
            raise PersonaInstancesUnreadable(
                f"cannot release child backlinks for {parent_instance_id}: "
                f"{scan.unreadable} persona instance row(s) will not decode; "
                "repair or remove them before removing an owner"
            )
        released: list[str] = []
        for child in scan.instances:
            if child.id == parent_instance_id or parent_instance_id not in child.steered_by:
                continue
            kept = [parent for parent in child.steered_by if parent != parent_instance_id]
            if kept:
                self._apply_steer_edges(
                    child.id,
                    kept,
                    goal_id=child.goal_id,
                    _instance=child,
                )
            else:
                # Owner retirement changes graph topology, not the child's
                # mission membership. Preserve goal/task/mode context.
                self.clear_parents(child.id)
            released.append(child.id)
        return released

    def _apply_steer_edges(
        self,
        persona_instance_id: str,
        parent_instance_ids: list[str],
        *,
        goal_id: str | None,
        _instance: PersonaInstance | None = None,
    ) -> PersonaInstance:
        instance = _instance or self.get(persona_instance_id)
        # Resolve every parent to the id of the row actually on disk BEFORE
        # persisting, so id-scheme drift (e.g. persona_personainst_x) can never
        # enter the stored steering set. Storing a drifted parent id would make
        # the next snapshot re-emit the drift, and the Launcher graph edge (which
        # matches parents by canonical instance id) would silently fail to
        # resolve. Dedupe on the CANONICAL id so a drifted and a canonical
        # spelling of one parent collapse to a single edge. The child id is
        # already canonical here — `instance.id` is the resolved row.
        normalized: list[str] = []
        seen: set[str] = set()
        for parent in parent_instance_ids or []:
            token = safe_optional_token(parent)
            if not token:
                continue
            # Defense in depth for the steering invariant: a steering parent is a
            # persona-INSTANCE id, never a principal. Reject a non-instance-shaped
            # token loudly with the reason, BEFORE the store lookup, so no future
            # caller (a replayed spec, a mangled graph edge) can reintroduce the
            # "steered by operator" class of bug — and so the failure names the
            # category error ("not an instance id") rather than a misleading
            # "not found". Actor-token drift (persona_personainst_x) is first
            # collapsed to its canonical instance shape, which the store lookup
            # below then resolves to the real row.
            shaped = canonical_persona_instance_id(token) or token
            if not looks_like_persona_instance_id(shaped):
                raise ValueError(
                    "steering parent must be a persona-instance id "
                    f"({PERSONA_INSTANCE_ID_PREFIX}*), not a non-instance principal: {token!r}"
                )
            try:
                parent_instance = self.get(token)
            except Exception as exc:
                raise ValueError(f"parent persona instance not found: {token}") from exc
            canonical_parent = parent_instance.id
            if canonical_parent == instance.id:
                raise ValueError("a persona instance cannot steer itself")
            if canonical_parent in seen:
                continue
            seen.add(canonical_parent)
            self._validate_no_steering_cycle(instance.id, canonical_parent)
            normalized.append(canonical_parent)
        if not normalized:
            return self.detach_parents(instance.id)
        before = list(instance.steered_by)
        resolved_goal = safe_optional_token(goal_id) if goal_id is not None else instance.goal_id
        updates: dict[str, Any] = {
            "steered_by": normalized,
            # Denormalized legacy mirror: the primary (first) parent, for old
            # readers still keyed on the scalar. Single writer, single source.
            "spawned_by": normalized[0],
            "goal_id": resolved_goal,
        }
        if resolved_goal:
            updates["mode"] = "task_bound"
            updates["current_task_id"] = resolved_goal
        added = [pid for pid in normalized if pid not in before]
        removed = [pid for pid in before if pid not in normalized]
        self._commit_steer(instance, updates, added=added, removed=removed, detached=False)
        return self.get(instance.id)

    def _commit_steer(
        self,
        instance: PersonaInstance,
        updates: dict[str, Any],
        *,
        added: list[str],
        removed: list[str],
        detached: bool,
    ) -> None:
        changed_fields: dict[str, Any] = {}
        for attr, value in updates.items():
            if getattr(instance, attr) != value:
                setattr(instance, attr, value)
                changed_fields[attr] = value
        if not changed_fields:
            return
        instance.updated_at = now()
        self._write(instance)
        self._event(
            "persona_instance.steered",
            instance,
            {
                "goal_id": instance.goal_id,
                "spawned_by": instance.spawned_by,
                "steered_by": list(instance.steered_by),
                "added": added,
                "removed": removed,
                "detached": bool(detached),
            },
        )
        # S6 producer: the flagship field-patch case. ``changed_fields`` is the
        # exact set this steer mutation wrote (steered_by/spawned_by, plus
        # goal_id/mode/current_task_id when the re-route changed them). Live
        # unless read_model.delta_patches is explicitly off (it ships on).
        self._emit_state_patch(instance, changed_fields)

    def update_profile(
        self,
        persona_instance_id: str,
        *,
        display_name: str | None = None,
        current_chat_goal: str | None = None,
        goal_id: str | None = None,
        skills: list[str] | None = None,
        clear_skills: bool = False,
        inherit_skills: bool = False,
        provider: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
        reasoning_effort: str | None = None,
        clear_model_override: bool = False,
        model_issued_at: datetime | None = None,
        requested_by: str | None = None,
    ) -> PersonaInstance:
        """Persist operator-editable runtime profile overrides.

        These fields belong to the durable persona instance, not the backing
        Hermes profile template. Editing ``Alice Agent`` therefore updates the
        live ``personainst_*`` record while leaving the lower ``alice`` profile
        untouched for future default instances.

        ``provider``/``model``/``api_mode`` form the instance model-override
        tier (None = inherit the backing persona live; see
        ``models.apply_instance_model_overrides``). ``clear_model_override``
        resets all three. A ``model_issued_at`` older than the last applied
        model write raises :class:`StaleModelOverrideWrite` instead of
        clobbering the newer value.

        **The skills lane is a TRI-state, and all three values are reachable
        from here** (operator ruling 2026-09-03). ``skill_overrides`` has meant
        three different things since the tier shipped, but only two of them had
        a door:

        =====================  ==========================================
        ``skill_overrides``    what the resolver does
        =====================  ==========================================
        a non-empty list       use exactly this set
        ``[]``                 use NO skills — an explicit, pinned empty
        ``None``               FOLLOW THE TEMPLATE, live, forever after
        =====================  ==========================================

        ``skills=`` writes the first, ``clear_skills`` writes the second, and
        until this arm existed nothing wrote the third — so one Save at "this
        agent" scope pinned that agent off its persona permanently, and the
        template tier made that worse in proportion to its use: "fix the persona
        and let the existing agents follow" silently skipped every agent the
        Skills sheet had ever touched. ``inherit_skills`` is the missing arm.

        It is a SEPARATE argument rather than a third value on ``clear_skills``
        or a ``skills=None`` sentinel, and that is the ruling rather than a
        taste call. ``skills=None`` already means "the caller expressed no
        opinion" throughout this method and every one of its callers
        (``hermes_cli.flag_binding.list_flag_or_absent`` exists to keep it that
        way, after an empty-list collapse silently erased skill sets), so
        overloading it would put the tri-state's third value on the one spelling
        that must keep meaning "untouched". The three are therefore mutually
        exclusive and a caller that asks for two gets a ``ValueError`` rather
        than a precedence rule nobody can see in the argv.
        """
        if inherit_skills and (clear_skills or skills is not None):
            raise ValueError("inherit_skills conflicts with skills/clear_skills")
        instance = self.get(persona_instance_id)
        before_patch_fields = self._profile_patch_snapshot(instance)
        changed = False
        model_lane_touched = clear_model_override or any(
            value is not None for value in (provider, model, api_mode, reasoning_effort)
        )
        if clear_model_override and any(value is not None for value in (provider, model, api_mode, reasoning_effort)):
            raise ValueError("clear_model_override conflicts with provider/model/api_mode/reasoning_effort values")
        if model_lane_touched:
            if model_issued_at is not None and instance.model_override_issued_at is not None:
                issued = _as_utc(model_issued_at)
                applied = _as_utc(instance.model_override_issued_at)
                if issued <= applied:
                    raise StaleModelOverrideWrite(instance, issued_at=issued, applied_issued_at=applied)
            if clear_model_override:
                if (
                    instance.model is not None
                    or instance.provider is not None
                    or instance.api_mode is not None
                    or instance.reasoning_effort is not None
                ):
                    instance.model = None
                    instance.provider = None
                    instance.api_mode = None
                    instance.reasoning_effort = None
                    changed = True
            else:
                for field_name, raw in (("provider", provider), ("model", model), ("api_mode", api_mode)):
                    if raw is None:
                        continue
                    value = _safe_model_override_text(raw, field_name=field_name)
                    if getattr(instance, field_name) != value:
                        setattr(instance, field_name, value)
                        changed = True
                # Reasoning effort rides the model lane but is a validated enum
                # (or "none"/empty-clear), not free text — normalize separately.
                if reasoning_effort is not None:
                    new_reasoning = _normalize_reasoning_effort_override(reasoning_effort)
                    if instance.reasoning_effort != new_reasoning:
                        instance.reasoning_effort = new_reasoning
                        changed = True
            if changed:
                instance.model_override_issued_at = _as_utc(model_issued_at) if model_issued_at is not None else now()
        if display_name is not None:
            value = safe_assignment_text(display_name, limit=120)
            if not value:
                raise ValueError("display_name must not be empty")
            if instance.display_name != value:
                instance.display_name = value
                changed = True
        if current_chat_goal is not None:
            value = safe_assignment_text(current_chat_goal, limit=500) or None
            if instance.current_chat_goal != value:
                instance.current_chat_goal = value
                changed = True
        if goal_id is not None:
            value = safe_optional_token(goal_id)
            if instance.goal_id != value:
                instance.goal_id = value
                changed = True
            if value and instance.current_task_id != value:
                instance.current_task_id = value
                changed = True
        if skills is not None or clear_skills or inherit_skills:
            # ``None`` is the third value, not the absence of one — see the
            # tri-state table above. The comparison is deliberately ``!=`` on
            # the raw attribute so ``[] -> None`` registers as a change: those
            # two resolve to different skill sets the moment the template holds
            # anything, and reading them as equal would make the inherit door a
            # silent no-op for exactly the agents that need it.
            value = None if inherit_skills else ([] if clear_skills else _safe_skill_overrides(skills or []))
            if instance.skill_overrides != value:
                instance.skill_overrides = value
                changed = True
        if changed:
            instance.updated_at = now()
            self._write(instance)
            payload: dict[str, Any] = {
                "display_name": instance.display_name,
                "current_chat_goal": instance.current_chat_goal,
                "goal_id": instance.goal_id,
                # ``None`` travels as ``None``: the event's reader cannot tell
                # "pinned to no skills" from "follows the template" if the two
                # are spelled the same, and after ``--inherit-skills`` both
                # states are reachable through this one verb.
                "skill_overrides": (
                    list(instance.skill_overrides) if instance.skill_overrides is not None else None
                ),
                "provider": instance.provider,
                "model": instance.model,
                "api_mode": instance.api_mode,
                "reasoning_effort": instance.reasoning_effort,
            }
            if requested_by:
                payload["requested_by"] = str(requested_by)[:80]
            self._event("persona_instance.profile_updated", instance, payload)
            # S6 producer: the persona-instance profile/model write funnel. Emit
            # only the operator-editable fields this call actually changed. Live
            # unless read_model.delta_patches is explicitly off (it ships on).
            after_patch_fields = self._profile_patch_snapshot(instance)
            self._emit_state_patch(
                instance,
                {
                    field_name: after_patch_fields[field_name]
                    for field_name in after_patch_fields
                    if after_patch_fields[field_name] != before_patch_fields.get(field_name)
                },
            )
        return self.get(instance.id)

    def set_backing_profile(self, persona_instance_id: str, profile_id: str | None) -> PersonaInstance:
        """Re-point one instance's ``profile_id`` at a new backing Hermes profile.

        Deliberately NOT part of :meth:`update_profile`: everything that method
        writes is an operator-editable RUNTIME override that belongs to the
        instance. ``profile_id`` is not — it is a PROJECTION of the owning
        persona's ``hermes_profile``. Folding it into ``update_profile`` would
        create a second, instance-local rebind authority competing with the
        persona record.

        The ONE sanctioned caller is
        :func:`agent_runtime.persona_profile_binding.rebind_persona_profile`,
        which moves the persona authority and cascades every instance row in the
        same operation, refuses while any instance is in flight, and emits the
        single typed ``persona.profile_rebound`` event that accounts for every
        row this method touched. That is why no event is appended here: the
        operation's event names each moved row, and it is deliberately an
        UNCOVERED type (see ``patch_coverage``) so the batch degrades to a full
        core rather than shipping a patch frame that folds nothing.
        """

        instance = self.get(persona_instance_id)
        value = safe_optional_token(profile_id)
        if instance.profile_id == value:
            return instance
        instance.profile_id = value
        instance.updated_at = now()
        self._write(instance)
        return self.get(instance.id)

    def _validate_no_steering_cycle(self, persona_instance_id: str, parent_instance_id: str) -> None:
        # Multi-parent DAG walk: adding parent → child must not let the child
        # reach itself through the steering graph. We only reject when the child
        # is reachable from the new parent (a real cycle); a diamond (two parents
        # sharing an ancestor) is fine, so we track a visited set separately from
        # the cycle test rather than raising on any re-visit.
        #
        # The walk ADMITS the edge by exhausting the frontier without finding
        # the child, so every node it fails to open is a subgraph it silently
        # declares cycle-free. A row that will not decode therefore hides any
        # cycle BEHIND it and the edge is admitted into a graph that now has one.
        # An ABSENT ancestor is not that condition: ``get`` re-raises
        # ``FileNotFoundError`` for an id with no row, which is a dangling
        # reference the steering repair exists to strip, and it really does end
        # the walk — nothing is reachable through a node that is not there. A row
        # that EXISTS and will not decode is the unknowable case, and it refuses.
        visited: set[str] = set()
        unreadable = 0
        frontier = _dedupe_tokens([parent_instance_id])
        while frontier:
            cursor = frontier.pop()
            if cursor == persona_instance_id:
                raise ValueError("steering edge would create a cycle")
            if cursor in visited:
                continue
            visited.add(cursor)
            try:
                parent = self.get(cursor)
            except FileNotFoundError:
                continue
            except Exception:
                unreadable += 1
                continue
            frontier.extend(_dedupe_tokens(list(parent.steered_by)))
        if unreadable:
            raise PersonaInstancesUnreadable(
                f"cannot prove the steering edge {parent_instance_id} -> {persona_instance_id} "
                f"is acyclic: {unreadable} ancestor row(s) will not decode; "
                "repair or remove them before steering"
            )

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

    def _archive_office_placements(
        self, instance: PersonaInstance, *, correlation_id: str | None = None
    ) -> dict[str, Any]:
        """Archive office actors when a live placement is retired, and SAY what happened.

        The office half stays best-effort — placement retirement is
        authoritative with or without the office projection, and a retire that
        raised because a desk file was locked would leave the operator unable to
        retire at all — but "best-effort" used to also mean "unsaid": this method
        returned ``None`` and swallowed every fault, so the two-lane removal the
        launcher performs (retire the row, remove the actor) had no receipt
        joining its halves and a half-state (row archived, desk still on the
        canvas) was invisible to everyone including the caller that caused it.
        Placement plan D7: the outcome LEAVES, and :meth:`retire` puts it on the
        ack.

        Shape is the store's own (``archived``, ``failed``, ``archived_actor_keys``,
        ``failures``). A fault in the projection ITSELF — the import, the store
        construction, the workspace listing — is not one actor's, so it is
        reported with ``actor_key: None``: naming an actor there would be a
        guess, and the whole point of this return value is that it stops
        guessing.

        ``correlation_id`` is the retiring GESTURE's token and it travels no
        further than the office writes: the row archive above already carries
        its own ``persona_instance.retired`` event, and the office half is the
        part that was landing in a second, unjoinable correlation space.
        """

        try:
            from ..office_store import OfficeStore

            return OfficeStore(event_log=self.event_log).archive_actors_for_instance(
                instance.id,
                reason="instance_reaped",
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001 - the retire is authoritative regardless
            logging.getLogger(__name__).warning(
                "office placement archive failed for %s", instance.id, exc_info=True
            )
            return {
                "archived": 0,
                "failed": 1,
                "archived_actor_keys": [],
                "failures": [
                    {
                        "actor_key": None,
                        "workspace_id": instance.workspace_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                ],
            }

    def retire(
        self,
        persona_instance_id: str,
        *,
        reason: str = "placement removed",
        requested_by: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Instance end-of-life: archive a placement-backed (or otherwise
        deliberate) persona-instance ROW and emit an EventLog event.

        The operator ruling is that a deliberate placement IS the instance:
        deleting the placement ends the instance's life. This is the sanctioned
        verb for that transition — the row file MOVES to
        ``persona_instances_archive/<ts>_retire/`` (archive-never-delete), an
        evented mutation (no silent row move). Chat sessions and turn stores
        stay untouched on disk (history is never destroyed); the projection
        simply stops listing the row because ``list_all`` only globs the live
        dir, so every instance-fed surface (snapshot, roster, chat history,
        flow node dropdown) drops it on the next frame.

        The returned dict carries the OFFICE half beside the row's own fields:
        ``archived_actor_keys`` (every actor this retire took off the level) and
        ``office_archive_failures`` (every one it could not, with its error).
        Both are ADDITIVE and neither is authoritative over the row archive —
        the office projection may be unavailable and the retirement still
        stands — but they are no longer DISCARDED, which is what let a
        half-state (row archived, desk still on the canvas) exist with nothing
        able to detect it. ``agent_retire.perform_agent_retire`` is the service
        that puts them on an operator ack (placement plan D7).

        They are also PERSISTED, beside the tombstone, so a client that lost the
        ack can still be told what the office half did
        (:meth:`_write_retire_receipt`, H-H5). ``retire_receipt_path`` says
        where — ``None``, with ``retire_receipt_error`` beside it, when nothing
        could be written.

        Refuses with a typed :class:`PersonaInstanceRetireError` (never a silent
        no-op) when the row is the canonical persona/profile channel
        (``canonical_persona_channel`` — the global-singleton retirement is the
        queued workspace-scoping redesign), or when a live run/worker still
        resolves (``instance_active`` — never archive a working agent). The two
        ASSIGNMENT guards this method used to carry left with AX2; the class
        docstring above carries the argument."""
        try:
            instance = self.get(persona_instance_id)
        except Exception as exc:
            raise PersonaInstanceRetireError(
                "not_found",
                f"persona instance not found: {persona_instance_id}",
                persona_instance_id=safe_assignment_token(persona_instance_id) or str(persona_instance_id),
            ) from exc

        if is_canonical_persona_channel(instance):
            raise PersonaInstanceRetireError(
                "canonical_persona_channel",
                (
                    f"{instance.id} is the canonical persona channel for "
                    f"{instance.persona_id!r}; the global-singleton channel cannot be "
                    "retired here (that is the queued workspace-scoping redesign) — "
                    "retire a placement-backed instance instead"
                ),
                persona_instance_id=instance.id,
                detail={"persona_id": instance.persona_id},
            )

        if self._has_live_binding(instance):
            raise PersonaInstanceRetireError(
                "instance_active",
                f"{instance.id} has a live run binding; never retire a working agent",
                persona_instance_id=instance.id,
                detail={
                    "active_run_id": safe_optional_token(instance.active_run_id),
                },
            )

        archive_dir = paths.persona_instances_archive_dir() / f"{now().strftime('%Y%m%dT%H%M%SZ')}_retire"
        archived_path = self._archive_instance_row(instance, archive_dir)
        if archived_path is None:
            raise PersonaInstanceRetireError(
                "not_found",
                f"persona instance row is not on disk: {instance.id}",
                persona_instance_id=instance.id,
            )
        safe_reason = safe_assignment_text(reason, limit=240) or "placement removed"
        normalized_requested_by = str(requested_by)[:80] if requested_by else None
        payload: dict[str, Any] = {
            "reason": safe_reason,
            "persona_id": instance.persona_id,
            "mode": instance.mode,
            "archive_dir": str(archive_dir),
        }
        if normalized_requested_by:
            payload["requested_by"] = normalized_requested_by
        self._event("persona_instance.retired", instance, payload)
        # S7-A producer: the retired row leaves the active frame, so the launcher
        # deletes the keyed row (never renders it as a live idle agent). Live
        # unless read_model.delta_patches is explicitly off (it ships on).
        emit_persona_instance_remove(self.event_log, instance)
        # Prune-lane hook (mirrors close_for_task / the janitor): a retired
        # instance must not leave a phantom office desk. Best-effort; office
        # archival never fails the retire.
        #
        # The gesture's token rides INTO the office half (S8b). Before it, a
        # removal gesture's two verbs lived in two correlation spaces: the
        # create/office writes stamped `correlation_id` on their patches and
        # the retire's office removes stamped nothing, so one grep over the two
        # logs could not join the halves of a single operator action — the
        # exact defect EG-2.3 built the token to retire.
        office = self._archive_office_placements(
            instance, correlation_id=correlation_id
        )
        result = {
            "persona_instance_id": instance.id,
            "persona_id": instance.persona_id,
            "display_name": instance.display_name,
            "mode": instance.mode,
            "reason": safe_reason,
            "requested_by": normalized_requested_by,
            "archive_path": str(archived_path),
            "archive_dir": str(archive_dir),
            # The office half, ADDITIVE and never authoritative over the row
            # archive above it: which actors this retire took off the canvas, and
            # which it could not. Empty failures is the claim "every bound actor
            # archived" — a claim this method could not make while the prune's
            # outcome was discarded (plan D7).
            "archived_actor_keys": list(office.get("archived_actor_keys") or []),
            "office_archive_failures": list(office.get("failures") or []),
        }
        return {**result, **self._write_retire_receipt(archive_dir, result)}

    def _write_retire_receipt(
        self, archive_dir: Path, result: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist THIS retire's outcome beside its tombstone (H-H5).

        The office half is the part of a retire that only ever existed on the
        ack. ``archived_actor_keys`` survived a lost ack because the archive can
        be re-read; ``office_archive_failures`` did not, so a replay answered the
        positive-claim shape — the empty list — for a first attempt that had
        actually failed to take a desk off the canvas, and the operator whose ack
        went missing was told the opposite of what happened. The create has had a
        receipt for this reason since S4; this is the retire's.

        BEST-EFFORT AND SAID, never best-effort and silent. The retirement is
        already durable when this runs — refusing it because a receipt would not
        write would fail a retire that has succeeded — but a failed write is
        reported on the ack (``retire_receipt_path: None`` plus
        ``retire_receipt_error``), because "a best-effort lane discarded its
        outcome" is the exact class this repo has already paid for three times
        and the fourth instance is not going to be one written by the fix for the
        third.

        ``retire_receipt_path`` is present on every fresh ack, ``None`` when
        nothing was written — one shape, so a client never reads an absent key as
        "yes, it was recorded".
        """

        path = retire_receipt_path(archive_dir, result["persona_instance_id"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_write(
                path,
                {
                    # The wall clock this retire ran at. Not derivable from the
                    # batch directory name by a reader that should not have to
                    # parse a path to learn a time.
                    "retired_at": now().isoformat(timespec="microseconds").replace(
                        "+00:00", "Z"
                    ),
                    **result,
                },
                indent=2,
                sort_keys=True,
            )
        except Exception as exc:  # noqa: BLE001 - the retirement is already durable
            logging.getLogger(__name__).warning(
                "retire receipt write failed for %s",
                result["persona_instance_id"],
                exc_info=True,
            )
            return {
                "retire_receipt_path": None,
                "retire_receipt_error": f"{type(exc).__name__}: {exc}",
            }
        return {"retire_receipt_path": str(path)}

    def read_retire_receipt(
        self, persona_instance_id: str | None
    ) -> dict[str, Any] | None:
        """The recorded outcome of the retire that archived this id, or ``None``.

        ``None`` for every answer that is not a receipt: no tombstone, a retire
        from before receipts existed, an unreadable file. NEVER RAISES — every
        caller is on a lane whose whole point is to answer a client that already
        lost its ack, and a traceback there would cost the answer as well as the
        receipt.

        The absence is INFORMATION, not a gap to paper over: it says the first
        attempt's per-actor failures are unrecoverable, which is exactly what was
        true of every retire before H-H5 and is what the replay reports instead
        of inventing an empty list.
        """

        tombstone = self.retired_instance_archive_path(persona_instance_id)
        if tombstone is None:
            return None
        instance_id = safe_assignment_token(persona_instance_id)
        if not instance_id:
            return None
        try:
            raw = json.loads(
                retire_receipt_path(tombstone.parent, instance_id).read_text(
                    encoding="utf-8"
                )
            )
        except Exception:  # noqa: BLE001 - absent, unreadable, or not JSON
            return None
        return raw if isinstance(raw, dict) else None

    def _archive_instance_row(self, instance: PersonaInstance, archive_dir) -> Any:
        """Move the instance's row file into ``archive_dir`` (archive-never-delete).
        Returns the archived path, or ``None`` when the live row is already gone."""
        source = paths.persona_instance_path(instance.id)
        if not source.exists():
            return None
        self._release_parent_references(instance.id)
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / source.name
        shutil.move(str(source), str(target))
        return target

    def update(self, instance: PersonaInstance) -> PersonaInstance:
        instance.updated_at = now()
        self._write(instance)
        return self.get(instance.id)

    def retired_instance_ids(self) -> frozenset[str]:
        """Every retired instance id, in one archive listing — the bulk reader's
        door to :func:`retired_persona_instance_ids` (see it for the contract and
        for why the LIVE half of the predicate is the caller's to supply)."""
        return retired_persona_instance_ids()

    def retired_instance_archive_path(
        self,
        persona_instance_id: str | None,
        *,
        persona_id: str | None = None,
    ) -> Path | None:
        """The retirement tombstone for *persona_instance_id*, or ``None``.

        THE read-only retirement predicate. Retirement is not a flag on a row —
        it is the ABSENCE of a live row PLUS the presence of a ``*_retire``
        archive — so every caller that needs the answer has to compose those two
        facts. Composing them inline at each site is how a second, subtly
        different retirement rule gets born (one that reads a reconcile/prune
        archive as a tombstone, say, and makes a legitimate future mint
        impossible), so the composition lives here and :meth:`open_chat` — the
        write chokepoint that refuses a retired placement — asks this same
        method instead of re-deriving it.

        It exists because ``open_chat`` answers the question only by RAISING,
        and by then a caller like ``PersonaChatMintReceiptStore.mint`` has
        already created a titled session row. A refusal decidable without
        writing anything must be decidable WITHOUT writing anything.

        Never creates, mutates, or resurrects a row. Pass ``persona_id`` to
        resolve a caller-supplied (or omitted) instance id through the same
        :func:`canonical_chat_instance_id` derivation ``open_chat`` uses;
        without it the id is taken as already canonical.

        NEVER RAISES for a storage failure. Both callers ask this before their
        first durable write, and the mint's caller handles exactly one typed
        error (:class:`RetiredPersonaInstanceError`) — so an ``OSError`` from a
        flaky/UNC store root escaping here would reach the operator as the
        untyped traceback this predicate exists to retire. A probe that cannot
        read the archive cannot PROVE retirement, so it reports ``None`` (the
        pre-flight's posture, now shared by construction) and logs; the write
        chokepoint ``open_chat`` still refuses a retired target, so failing open
        costs the litter, never the guarantee.
        """
        instance_id = (
            canonical_chat_instance_id(persona_id, persona_instance_id)
            if persona_id
            else safe_assignment_token(persona_instance_id)
        )
        if not instance_id:
            return None
        try:
            self.get(instance_id)
        except Exception:
            pass
        else:
            # A live row always wins: the archive is history, and an id carried by a
            # live placement is live — never a tombstone.
            return None
        try:
            return _retired_persona_instance_archive_path(instance_id)
        except OSError:
            # The tombstone probe is filesystem I/O (``exists`` / ``iterdir`` /
            # ``is_file``) over the archive root. Loud in the log, quiet in the
            # answer: a caller must not be handed a refusal the store never
            # actually proved, nor a traceback from a lane that has a typed
            # refusal contract.
            logging.getLogger(__name__).warning(
                "retirement tombstone probe failed for %s; "
                "treating the target as NOT retired",
                instance_id,
                exc_info=True,
            )
            return None

    def assert_bindable(
        self,
        *,
        persona_id: str,
        session_id: str | None = None,
        persona_instance_id: str | None = None,
    ) -> str:
        """Everything :meth:`open_chat` refuses, asserted WITHOUT writing anything.

        Returns the canonical instance id the bind would target, so a caller that
        needs to act before the bind derives that id ONCE, here, rather than
        re-deriving it and drifting.

        This exists because ``open_chat`` answers "may this bind happen?" only by
        RAISING at the end of whatever the caller already did. For
        :meth:`PersonaChatMintReceiptStore.mint` that end came after a session row
        had been created, meta written and a title set — so a dispatch to a target
        that could never be served left a permanent titled thread in Mission
        Control, and the refusal arrived one durable write too late. A refusal
        decidable without writing must be decidable WITHOUT writing, and it must be
        the SAME refusal: one derivation, one spelling of the target id, one
        retirement rule (:meth:`retired_instance_archive_path`).

        ``session_id`` is optional so a caller can ask "is this instance bindable
        at all?" before it has minted a root; when present it is checked for the
        sibling-steal the bind refuses. ``open_chat`` calls this first and is the
        write chokepoint, so this costs one extra row read on the bind path and
        buys the pre-flight callers an answer they can trust.
        """

        normalized_persona = _normalize_instance_source_persona(persona_id)
        if not normalized_persona:
            raise ValueError("persona_id is required")
        normalized_instance = (
            canonical_persona_instance_id(persona_instance_id, persona_id=normalized_persona)
            if persona_instance_id
            else None
        )
        instance_id = normalized_instance or persona_instance_id_for(normalized_persona)
        # A chat session encodes the instance it was minted for; binding one
        # instance's session onto ANOTHER instance's pointer is the sibling steal
        # that overwrote ``personainst_qa``'s default-chat pointer with a
        # placement sibling's session (live 2026-07-18: the console's open-chat of
        # a sibling bound its session onto the canonical primary, then a
        # bare-persona relay adopted the poisoned pointer — both instances folded
        # onto ONE operator channel). Refuse loudly at the write chokepoint every
        # send/open flows through — the existing ``_session_owned_by_other_instance``
        # guard only covered ``add_instance``. Legacy/opaque ``persona_chat_*``
        # sessions (no encoded owner) and the instance's own sessions bind freely.
        normalized_session = safe_assignment_text(session_id, limit=200)
        if normalized_session and chat_session_is_foreign_to_instance(
            normalized_session, instance_id
        ):
            owner = chat_session_owner_instance_id(normalized_session)
            raise ValueError(
                f"chat session {normalized_session!r} belongs to instance {owner!r}; "
                f"it cannot be bound onto {instance_id!r} — open that instance's own "
                "chat lane instead of adopting a sibling's session"
            )
        # ONE retirement rule, composed in one place (absence of a live row PLUS a
        # ``*_retire`` tombstone) and asked here by every caller that needs it.
        retired_archive = self.retired_instance_archive_path(instance_id)
        if retired_archive is not None:
            raise RetiredPersonaInstanceError(instance_id, archive_path=retired_archive)
        return instance_id

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

    def open_chat(
        self,
        *,
        persona_id: str,
        session_id: str,
        persona_instance_id: str | None = None,
        display_name: str | None = None,
        default_display_name: str | None = None,
        profile_id: str | None = None,
        kill_active: bool = False,
        workspace_id: str | None = None,
        realm_id: str | None = None,
    ) -> PersonaInstance:
        """Bind a persona instance to a durable chat session without running a turn.

        Persona instances are intentionally chat-shaped: selecting an old chat can
        re-open the same live persona instance history by rebinding the instance
        to the stored session id, while the normal send/resume path owns the actual
        LLM execution. A placement retired through :meth:`retire` is the explicit
        exception: its archived row is an end-of-life tombstone, so the preserved
        chat stays history-only and cannot recreate a live roster row. This helper
        is a state transition only; it never fabricates a task, worker, run, or
        transcript.
        """
        normalized_persona = _normalize_instance_source_persona(persona_id)
        normalized_session = safe_assignment_text(session_id, limit=200)
        if not normalized_persona:
            raise ValueError("persona_id is required")
        if not normalized_session:
            raise ValueError("session_id is required")

        # The bind's refusals — sibling steal and retirement — live in ONE
        # read-only seam so a pre-flight caller and the bind itself cannot
        # disagree about who this is or whether it may be bound.
        instance_id = self.assert_bindable(
            persona_id=persona_id,
            session_id=normalized_session,
            persona_instance_id=persona_instance_id,
        )
        from ..auxiliary_chat import is_auxiliary_chat

        if is_auxiliary_chat(instance_id, normalized_session):
            # assert_bindable above still enforces retirement and ownership.
            # An auxiliary open is never allowed to create/repoint an instance.
            return self.get(instance_id)
        safe_display_name = safe_assignment_text(display_name, limit=120) if display_name is not None else None
        safe_default_display_name = (
            safe_assignment_text(default_display_name, limit=120) if default_display_name is not None else None
        )
        safe_profile_id = safe_assignment_token(profile_id) if profile_id is not None else None
        created = False
        try:
            instance = self.get(instance_id)
        except Exception:
            ts = now()
            role = "profile" if normalized_persona.startswith("profile:") else normalized_persona
            instance = PersonaInstance(
                id=instance_id,
                persona_id=normalized_persona,
                role=role,
                display_name=safe_display_name or safe_default_display_name or _display_name_for_template(normalized_persona.split(":", 1)[1] if normalized_persona.startswith("profile:") else normalized_persona),
                profile_id=safe_profile_id or (normalized_persona.split(":", 1)[1] if normalized_persona.startswith("profile:") else None),
                runtime_root=str(paths.store_root()),
                state=WorkerSessionState.IDLE,
                updated_at=ts,
            )
            created = True
        else:
            # Worker/run ownership is orthogonal to operator chat ownership.
            # Opening another chat root must not cancel or rebind live work.
            pass

        before = None if created else tuple(
            getattr(instance, field) for field in self._OPEN_CHAT_TRACKED_STORE_FIELDS
        )

        # An explicit ``display_name`` is AUTHORITATIVE — an operator naming this
        # chat (create_operator_chat) or a deliberate placement (add_instance,
        # "QA Agent (2)"); it always applies. A ``default_display_name`` is the
        # persona DEFAULT the SEND PATH stamps and must NEVER rename an existing
        # instance: applying it unconditionally clobbered a placement name —
        # ``personainst_qa_agent_2`` read "QA Agent" instead of "QA Agent (2)"
        # (the "(2)" is LOAD-BEARING: the launcher conversational fold keys on
        # persona+displayName, so the clobber folds a sibling onto the primary's
        # channel). Stamp the default only when the instance has NO name yet.
        # The one rename path stays ``persona.instance.update_profile``.
        if safe_display_name:
            instance.display_name = safe_display_name
        elif safe_default_display_name and not safe_assignment_text(
            getattr(instance, "display_name", None), limit=120
        ):
            instance.display_name = safe_default_display_name
        if safe_profile_id:
            instance.profile_id = safe_profile_id
        elif normalized_persona.startswith("profile:") and not instance.profile_id:
            instance.profile_id = normalized_persona.split(":", 1)[1]
        # Scope-provenance pointers: a provided workspace/realm is the caller's
        # authoritative placement-scope claim (the launcher stamps its active
        # scope when minting a placement) and applies on create AND re-open; an
        # omitted one never clears an existing pointer (plain chat re-opens
        # don't know scope and must not erase it).
        safe_workspace_id = safe_assignment_token(workspace_id) if workspace_id is not None else None
        safe_realm_id = safe_assignment_token(realm_id) if realm_id is not None else None
        if safe_workspace_id:
            instance.workspace_id = safe_workspace_id
        if safe_realm_id:
            instance.realm_id = safe_realm_id
        instance.mode = "chat"
        instance.default_chat_session_id = normalized_session
        # Read-compatible mirror for v1 consumers. Worker writers never touch
        # this field; default_chat_session_id is the sole new authority.
        instance.session_id = normalized_session
        # Stamp WHERE the bound conversation's transcript lives — the
        # INSTANCE_RECORDED rung of ``chat_session_scope``. The send path
        # re-enters this chokepoint every turn, so the stamp is re-affirmed
        # per turn for free. Only an AUTHORITATIVE scope may stamp: recording
        # a degraded ambient guess would launder the very guess the rung
        # exists to retire, so an ambient bind leaves the field as it was
        # (``None`` = explicitly UNRECORDED for readers). A re-stamp to a
        # DIFFERENT authoritative head is deliberate and AUDITED, not silent:
        # it changes the before/after tuple, so the row is rewritten and the
        # ``chat_opened`` event below carries both the new and previous head.
        previous_chat_head = instance.chat_head_home
        from ..chat_session_scope import resolve_process_chat_scope

        # PROCESS ladder, deliberately — this is the site that WRITES the
        # INSTANCE_RECORDED rung, and ``normalized_session`` is in hand
        # right here, so omitting it would otherwise read as an oversight.
        # A writer that consulted its own rung would re-affirm a stale head
        # forever: the record would always agree with itself and the
        # pointer beneath it could never correct it.
        scope = resolve_process_chat_scope()
        if scope.authoritative:
            instance.chat_head_home = str(scope.head_home)
        after = tuple(
            getattr(instance, field) for field in self._OPEN_CHAT_TRACKED_STORE_FIELDS
        )
        if not created and before == after:
            # Idempotent re-open is an observation, not a mutation. Rewriting the
            # row would advance directory fingerprints and emitting
            # persona_instance.chat_opened would force a full-core stream delta.
            # One first-turn path legitimately reaches this chokepoint multiple
            # times; no-op calls must stay invisible to the event/read model.
            return instance
        event_payload: dict[str, Any] = {"session_id": normalized_session}
        if instance.chat_head_home:
            event_payload["chat_head_home"] = instance.chat_head_home
        if previous_chat_head and previous_chat_head != instance.chat_head_home:
            event_payload["previous_chat_head_home"] = previous_chat_head
        with timed_create_subphase("instance_write_ms"):
            updated = self.update(instance)
        # S7-A producer: the PAIR ``persona_instance.chat_opened`` never had.
        #
        # Covering that event without this would be a silent data drop, not a
        # missed optimisation: ``open_chat`` writes real wire-visible state —
        # ``mode``, ``workspace_id``, ``realm_id``, ``profile_id``,
        # ``display_name`` and the ``default_chat_session_id`` trio, all present
        # in ``persona_instance_summary`` — and emitted no ``state.patched`` at
        # all, so a promoted batch would have advanced every connected client's
        # watermark past a row it never received.
        #
        # Two cases, split at ``created``:
        #
        # * RE-OPEN (``created=False``): the row exists on every client, so the
        #   diffed field subset folds as a merge. ``updated_at`` always rides,
        #   which is what keeps the pair from ever being EMPTY — a bind that
        #   moved only ``chat_head_home`` (no wire field) would otherwise emit
        #   nothing and leave the covered event riding alone.
        # * CREATE (``created=True``): a COMPLETE-row ``upsert`` stamped
        #   ``created: true``, gated behind the ``persona_instance_create``
        #   capability token so an un-updated launcher keeps receiving today's
        #   wire byte-for-byte (see ``emit_persona_instance_create``).
        #
        #   This arm emitted an ``op: refresh`` until D3 landed (plan §10.3,
        #   2026-08-16), and that one row was the entire cost of the operator's
        #   "add an agent" gesture: one unfoldable row demotes the whole batch,
        #   so it took the perfectly foldable ``office_actor created:true``
        #   upsert beside it down too and paid a full ``build_snapshot()`` —
        #   6.3–6.6 s of a measured 6.94 s gesture. The refresh's stated
        #   justification was that "a full persona-instance row cannot be assumed
        #   to fit the 4 KB cap", which was an assumption, not a measurement, and
        #   it outlived the R2 residue slimming that made it false. Measured on
        #   the live roster: worst assembled payload 3,133 bytes of 4,096. The
        #   emitter re-checks that per row and still degrades to ``refresh`` for
        #   any row that does not fit LOSSLESSLY, so the pre-D3 behaviour remains
        #   the floor rather than the norm.
        if created:
            with timed_create_subphase("create_patch_ms"):
                emit_persona_instance_create(self.event_log, updated)
        else:
            moved = [
                field
                for field, was, is_now in zip(
                    self._OPEN_CHAT_TRACKED_STORE_FIELDS, before or (), after
                )
                if was != is_now
            ]
            emit_persona_instance_patch(
                self.event_log, updated, [*moved, "updated_at"]
            )
        with timed_create_subphase("event_append_ms"):
            self._event("persona_instance.chat_opened", updated, event_payload)
        return updated

    def rollback_chat_root_bind(
        self,
        *,
        persona_instance_id: str,
        root_session_id: str,
        previous: PersonaInstance | None,
    ) -> bool:
        """Undo an :meth:`open_chat` bind whose transcript row never landed.

        The EARLY-BIND ordering in
        :meth:`PersonaChatMintReceiptStore.mint` is deliberate — the bind is the
        step that proves the target still live, so it must precede the first
        SESSION-visible write (see the comment there; a retire landing mid-lane
        would otherwise leave a titled thread for a dead placement). The cost of
        that ordering is a window: if the ``create_session`` immediately after
        the bind FAILS, the pointer is already on the instance and names a root
        with no transcript row — the phantom
        :mod:`agent_runtime.persona_chat_durability` exists to make impossible,
        permanently undeliverable because
        :func:`resolve_default_chat_session_id_for_instance` re-offers a
        chat-shaped own-instance pointer forever without asking whether it
        resolves.

        This closes that window from the other side: the ordering stays, and the
        bind is RETRACTED when the write it was guarding could not be made.

        *previous* is the row as it stood BEFORE the bind, or ``None`` when the
        bind created it. Restoring ``None`` clears both pointer fields, which is
        the self-healing state — the resolver answers "no thread yet" and the
        next mint makes a fresh, durable root. The legacy ``session_id`` mirror
        is moved WITH the authority: ``PersonaInstance.__post_init__``
        re-derives ``default_chat_session_id`` from a ``persona_chat_*``
        ``session_id``, so clearing only the authority would resurrect the
        phantom on the next read. ``mode`` moves with them for the same reason —
        ``open_chat`` stamps ``chat`` as part of the bind, and a row left in that
        mode with no chat pointer is the very half-state
        :meth:`clear_chat_session_binding` demotes.

        Deliberately NOT routed through :meth:`clear_chat_session_binding`; see
        the "why the two paths stay separate" note in that method's docstring.

        Retracts on IDENTITY, never on mere presence: if the live pointer no
        longer names *root_session_id*, some other lane bound this instance
        after ours did, and its pointer is not ours to revert. Returns whether a
        retraction was written.
        """

        instance_id = safe_assignment_token(persona_instance_id)
        root = safe_assignment_text(root_session_id, limit=200)
        if not instance_id or not root:
            return False
        try:
            live = self.get(instance_id)
        except Exception:
            # No row to retract (or the store is unreadable). Either way this
            # must not raise: it runs inside the failure handler of a lane that
            # already has a typed error to report, and a rollback that masks the
            # original cause is worse than the litter it cleans.
            return False
        if safe_assignment_text(
            getattr(live, "default_chat_session_id", None), limit=200
        ) != root:
            return False
        restored_default = getattr(previous, "default_chat_session_id", None) if previous else None
        restored_legacy = getattr(previous, "session_id", None) if previous else None
        live.default_chat_session_id = restored_default
        live.session_id = restored_legacy
        # ``mode`` is restored WITH the pointers, because ``open_chat`` sets it
        # (``instance.mode = "chat"``) in the same breath as the bind this is
        # retracting. Reverting the pointers alone left the row in precisely the
        # state :meth:`clear_chat_session_binding` exists to demote away from —
        # ``mode == "chat"`` with no chat to be in — and that is not a cosmetic
        # inconsistency: ``persona_instance_summary`` ships ``mode`` on the wire,
        # the launcher decodes ``chat`` to ``MissionAgentInstanceMode.chatHistory``
        # (``mission_agent_instance.dart``), and its persona-best election ranks
        # ``chatHistory`` ABOVE ``configuredIdle``
        # (``mission_instance_resolution.dart``). A retracted fresh mint would
        # out-rank a genuinely idle sibling on the strength of a conversation
        # that was never written.
        #
        # ``previous.mode`` rather than a flat demotion, because this method
        # restores — it does not clear. A row that already had a working thread
        # keeps ``chat`` alongside the pointer being put back; a row the bind
        # CREATED has no previous mode, so it takes the store default
        # (``PersonaInstance.mode = "configured"``), which is the same value
        # ``clear_chat_session_binding`` demotes to.
        #
        # It rides the SAME staleness contract the pointers already ride, and no
        # stronger one: the identity guard above proves nothing re-bound the
        # POINTER since ``previous`` was read, not that nothing touched ``mode``.
        # A concurrent mode-only write inside that window would be reverted —
        # which is exactly what already happens to a concurrent pointer write
        # that kept our root, so this is the method's existing posture applied to
        # the field the bind set, not a new risk introduced beside it.
        live.mode = getattr(previous, "mode", None) or "configured"
        try:
            updated = self.update(live)
        except Exception:
            logging.getLogger(__name__).warning(
                "could not retract the chat-root bind for %s; "
                "its default chat pointer may name an unwritten transcript",
                instance_id,
                exc_info=True,
            )
            return False
        # The bind emitted a create/patch onto the read model; the retraction
        # must emit its counterpart or every connected client keeps showing the
        # phantom pointer the store no longer holds.
        emit_persona_instance_patch(
            self.event_log,
            updated,
            ["mode", "session_id", "default_chat_session_id", "updated_at"],
        )
        return True

    def create_operator_chat(
        self,
        *,
        persona_id: str,
        display_name: str,
        session_id: str | None = None,
        kill_active: bool = False,
    ) -> PersonaInstance:
        normalized_persona = _normalize_instance_source_persona(persona_id)
        instance_id = persona_instance_id_for(normalized_persona)
        root = session_id or persona_chat_session_id_for(instance_id)
        # Refusals FIRST, durable writes second — the ordering
        # ``PersonaChatMintReceiptStore.mint`` already learned. Persisting the
        # root before the bind is checked would leave a titled Mission Control
        # thread behind every retirement/sibling-steal refusal; ``open_chat``
        # re-asserts this, so the pre-flight only moves the answer earlier.
        self.assert_bindable(
            persona_id=normalized_persona,
            session_id=root,
            persona_instance_id=instance_id,
        )
        return self.open_chat(
            persona_id=normalized_persona,
            persona_instance_id=instance_id,
            session_id=_durable_chat_root(
                root,
                persona_id=normalized_persona,
                # An explicit ``display_name`` is authoritative in ``open_chat``,
                # so this is exactly the title the argv lane's post-hoc ensure
                # would have written — and that ensure never overwrites an
                # existing title, so the two lanes agree by construction.
                display_name=display_name,
            ),
            display_name=display_name,
            profile_id=_profile_id_for_persona_or_template(normalized_persona),
            kill_active=kill_active,
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
