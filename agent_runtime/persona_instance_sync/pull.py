"""``apply_persona_instance_pull`` — the mint door — and its per-row helpers.

Map: ``agent_runtime/persona_instance_sync/__init__.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ..sync_admission import Refusal
from ..sync_merge import (
    REASON_ARCHIVE_VS_EDIT,
    REASON_ARCHIVED_LOCAL,
    REASON_CONVERGED,
    PullAction,
    classify_three_way_pull,
)
from .contract import PROJECTION_RELATIVE_PATH, PersonaInstancePullSummary
from .projection import persona_instance_def_hash, project_persona_instance, refuse_persona_instance
from ..store_conflicts import park_conflict_sidecar
from .sidecars import (
    instance_baseline_key,
    instance_conflict_path,
    read_dropped_steering_ledger,
    read_persona_instance_baseline,
    read_remote_persona_instances,
    write_dropped_steering_ledger,
    write_persona_instance_baseline,
)

__layer__ = "stores"


def _local_projection_hash(store, instance_id: str):
    """``(hash, record, refusal_code)`` for the LOCAL row.

    A row whose file EXISTS and will not decode is refused rather than reported
    absent. Absent is what drives the MINT arm, so folding a parse error into it
    would overwrite a row that might carry a live run binding — the same
    unreadable-is-not-absent rule ``apply_office_pull`` spends on its own local
    scan.
    """

    from .. import paths

    path = paths.persona_instance_path(instance_id)
    try:
        record = store.get(instance_id)
    except FileNotFoundError:
        return None, None, None
    except Exception:
        if path.exists():
            return None, None, "local_row_unreadable"
        return None, None, None
    return persona_instance_def_hash(project_persona_instance(record)), record, None


def _locally_archived_actor_keys() -> set[str]:
    """Every actor key this machine has archived, across every office surface.

    Read from the office store's own ``archived_actor_keys`` ledger — the SAME
    resurrection guard ``_reconcile_actors`` passes to the classifier — because
    the actor key IS the instance id for an instance-bound actor. Growing a
    second ledger for the same fact is how two authorities over one identity
    start disagreeing.

    A store that cannot be read yields an EMPTY set, which is the permissive
    direction, and that is the right one here: the alternative is refusing to
    replicate anything on a projection fault, and the resurrection this guards
    against is bounded (one desk comes back and the operator deletes it again),
    while the refusal would strand every agent in the realm.
    """

    try:
        from ..office_store import OfficeStore

        store = OfficeStore()
        keys: set[str] = set()
        for workspace_token in store.list_workspaces():
            try:
                surface = store.get_surface(workspace_token)
            except Exception:  # noqa: BLE001 — one unreadable surface is not the others'
                continue
            keys.update(str(key) for key in (surface.archived_actor_keys or []))
        return keys
    except Exception:  # noqa: BLE001 — see the docstring: permissive on a fault
        return set()


def _retire_replicas_for_removed_desks(
    store,
    summary: PersonaInstancePullSummary,
    baseline: dict[str, str],
    *,
    realm_id: str,
    desks_removed,
) -> None:
    """§5.2: the replica follows the DESK, never the absence.

    ``desks_removed`` is the actor keys the office lane ARCHIVED in this same
    pull — the ``remote_removed`` arm, which is authored intent that already
    propagated from the machine the operator clicked on. That is a different
    fact from an instance being missing from the projection, which is
    ``upstream_absent`` and never a delete: a desk's removal is a decision a
    peer made, while a row's absence is equally consistent with the publisher's
    own office scan having come back short.

    The actor key IS the canonical instance id for an instance-bound actor
    (``_canonical_actor_key``), so a key with no matching row is simply a
    persona-keyed desk and there is nothing to retire.
    """

    from .. import paths

    for actor_key in sorted({str(key) for key in (desks_removed or []) if key}):
        if not paths.persona_instance_path(actor_key).exists():
            continue
        try:
            store.retire_replica(actor_key, reason="remote_removed", realm_id=realm_id)
        except Exception as exc:  # noqa: BLE001 — accounted, never silent
            code = getattr(exc, "code", None) or type(exc).__name__
            summary.retire_held.append({"key": actor_key, "code": str(code)})
            # The baseline entry STAYS. Dropping it would tell the next pull
            # there is no baseline for a row that is still live, and a row with
            # no baseline reads as a local ADD — the failed archive would come
            # back as something to publish (``_reconcile_actors``' C2 lesson).
            continue
        summary.retired.append(actor_key)
        baseline.pop(instance_baseline_key(actor_key), None)


def _remote_body_without_edges(
    remote_body: dict[str, Any], parents: list[str]
) -> dict[str, Any]:
    """The remote body as it would look with ``parents`` never applied.

    ``project_persona_instance`` OMITS structurally-empty values, so a row whose
    every edge was dropped carries no ``steered_by`` key at all — dropping to
    ``[]`` instead would hash as a different body and the heal would never
    recognise its own handiwork.
    """

    body = dict(remote_body)
    unwanted = set(parents)
    remaining = [str(item) for item in (body.get("steered_by") or []) if str(item) not in unwanted]
    if remaining:
        body["steered_by"] = remaining
    else:
        body.pop("steered_by", None)
    return body


def _healable_dropped_parents(
    ledger: dict[str, dict[str, Any]],
    instance_id: str,
    remote_body: dict[str, Any],
    remote_hash: str,
    local_hash: str | None,
) -> list[str]:
    """The parents a ``kept_local`` row's local drift is FULLY explained by.

    This is the whole of "tell a dropped edge from an authored re-steer", and it
    asks two questions rather than trusting the ledger alone:

    * the realm has not moved since the drop (the recorded ``remote_hash`` is
      still the remote hash) — otherwise the ledger describes a body that no
      longer exists and the row's drift may be about something else entirely;
    * the local body is EXACTLY the remote body minus those edges. An operator
      who re-steered, renamed, or re-pointed the model changed the body
      somewhere the dropped edge cannot account for, and the answer is to leave
      it alone. That is the one thing ``kept_local`` exists to protect, and it
      is why re-running phase two for every ``kept_local`` row was rejected.

    Empty means "not a heal candidate", and the caller reports ``kept_local``
    exactly as it did before this existed.
    """

    entry = ledger.get(instance_id)
    if not entry or local_hash is None:
        return []
    if entry.get("remote_hash") != remote_hash:
        return []
    parents = [str(item) for item in (entry.get("parents") or [])]
    if not parents:
        return []
    expected = persona_instance_def_hash(_remote_body_without_edges(remote_body, parents))
    return parents if expected == local_hash else []

@dataclass(slots=True)
class _RowContext:
    """One pulled row as phase one decided it — the input every row handler reads."""

    instance_id: str
    key: str
    remote_body: dict[str, Any]
    remote_hash: str
    local_hash: str | None
    local_record: Any
    reason: str


@dataclass(slots=True)
class PullPass:
    """One run of the mint door. The locals every phase used to share are its fields.

    ``written`` is the rows phase two applies edges to (written or found
    converged, plus the heal candidates); ``heal_pending`` is
    ``{instance_id: [parent, ...]}`` — rows phase one classified ``kept_local``
    whose drift is fully explained by edges an earlier pull dropped. They
    re-enter phase two and their OUTCOME is decided there, because whether the
    parent has actually arrived is phase two's question, not phase one's.
    """

    realm_id: str
    store: Any
    summary: PersonaInstancePullSummary
    baseline: dict[str, str]
    ledger: dict[str, dict[str, Any]]
    archived_keys: set[str] = field(default_factory=set)
    written: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    heal_pending: dict[str, list[str]] = field(default_factory=dict)

    def retire_removed_desks(self, desks_removed) -> None:
        # §5.2 FIRST, and independent of the projection. The trigger is the office
        # lane's own ``remote_removed`` archive, not anything in this document — a
        # peer can retire a desk in the same pull where their projection is absent,
        # unreadable, or unchanged, and the replica has to follow the desk in all
        # three cases.
        _retire_replicas_for_removed_desks(
            self.store, self.summary, self.baseline, realm_id=self.realm_id, desks_removed=desks_removed
        )

    def phase_one(self, remote: dict[str, dict[str, Any]]) -> None:
        """The rows: admit, classify, and hand each to its action's handler."""

        prefix = instance_baseline_key("")
        baselined_ids = {key[len(prefix):] for key in self.baseline if key.startswith(prefix)}
        # The resurrection guard, from TWO sources that answer the same question at
        # different ranges. The office ledger covers desks archived in any earlier
        # pass; ``summary.retired`` covers the ones THIS pass just archived, which
        # the ledger would also carry in production but which must not depend on
        # another store's state for a guarantee this function makes about itself. A
        # retire undone by phase one of the same pull would be incoherent.
        self.archived_keys = _locally_archived_actor_keys() | set(self.summary.retired)
        for instance_id in sorted(set(remote) | baselined_ids):
            row = self._row_context(instance_id, remote.get(instance_id))
            if row is None:
                continue
            decision = classify_three_way_pull(
                row.local_hash,
                row.remote_hash,
                self.baseline.get(row.key),
                # THE resurrection guard, and it is the office family's own ledger
                # rather than a second one: the actor key IS the instance id, so a
                # desk the operator archived here answers for its agent too. Without
                # it, a retire-follows-the-desk taken in one pull would be undone by
                # the very next pull, because the retired row reads as locally absent
                # while the realm still publishes it.
                locally_archived=instance_id in self.archived_keys,
            )
            row.reason = decision.reason
            if decision.reason in (REASON_ARCHIVED_LOCAL, REASON_ARCHIVE_VS_EDIT):
                self.summary.desk_archived.append(instance_id)
                if decision.action == PullAction.CONFLICT:
                    # The realm EDITED an agent whose desk is archived here. Nothing
                    # is written, but the body is parked so the divergence is not
                    # simply lost between two correct local states.
                    self._park(row)
                continue
            _ROW_ACTIONS[decision.action](self, row)

    def _row_context(self, instance_id: str, remote_body: dict[str, Any] | None) -> _RowContext | None:
        """The row, or ``None`` when it was refused or is the upstream-absent arm."""

        if remote_body is not None:
            refusal = refuse_persona_instance(instance_id, remote_body)
            if refusal is not None:
                # Untouched, named, and the pull continues — the store never
                # learns this row existed.
                self.summary.refused.append(refusal.as_dict())
                return None
        local_hash, local_record, local_refusal = _local_projection_hash(self.store, instance_id)
        if local_refusal is not None:
            self.summary.refused.append(
                Refusal(instance_id, local_refusal, "local instance row will not decode").as_dict()
            )
            return None
        key = instance_baseline_key(instance_id)
        if remote_body is None:
            # THE row that is not a delete. The realm stopped carrying a row
            # this baseline says it published, and that is exactly as consistent
            # with "the publisher's office scan came back short" as with "the
            # operator deleted it". Only the DESK's own removal is authored
            # intent (plan §5.2). Hold it, name it, and KEEP the baseline so a
            # repaired publish still converges.
            if local_hash is not None:
                self.summary.upstream_absent.append(instance_id)
            else:
                self.baseline.pop(key, None)
            return None
        remote_hash = persona_instance_def_hash(remote_body)
        return _RowContext(instance_id, key, remote_body, remote_hash, local_hash, local_record, "")

    def _park(self, row: _RowContext) -> None:
        """Park the body a HOLD refused to adopt (store_conflicts' one pull-side writer)."""

        park_conflict_sidecar(
            instance_conflict_path(self.realm_id, row.instance_id),
            realm_id=self.realm_id,
            key_field="persona_instance_id",
            key=row.instance_id,
            kind=row.reason,
            remote_body=row.remote_body,
            local_hash=row.local_hash,
            remote_hash=row.remote_hash,
        )

    def _settle(self, row: _RowContext) -> None:
        self.written.append((row.instance_id, row.remote_body))
        self.baseline[row.key] = row.remote_hash

    def _row_converged(self, row: _RowContext) -> None:
        self.summary.converged.append(row.instance_id)
        self._settle(row)

    def _row_keep_or_heal(self, row: _RowContext) -> None:
        # THE heal seam. A row whose local drift is exactly the edges an
        # earlier pull dropped is not an operator's edit at all — it is this
        # lane's own unfinished write, and re-entering phase two is what
        # finishes it. Everything else stays ``kept_local`` untouched.
        healable = _healable_dropped_parents(
            self.ledger, row.instance_id, row.remote_body, row.remote_hash, row.local_hash
        )
        if healable:
            self.heal_pending[row.instance_id] = healable
            self.written.append((row.instance_id, row.remote_body))
        else:
            self.summary.kept_local.append(row.instance_id)

    def _row_hold(self, row: _RowContext) -> None:
        self.summary.held.append(row.instance_id)
        self._park(row)

    def _row_upstream_absent(self, row: _RowContext) -> None:
        # Unreachable while ``remote_body is not None`` — the classifier only
        # takes this arm on an absent remote — and stated rather than left to
        # fall through: this family has NO archive arm in the pull at all.
        # Retirement follows the DESK (H4/§5.2), never the absence.
        self.summary.upstream_absent.append(row.instance_id)

    def _row_write(self, row: _RowContext) -> None:
        # WRITE_REMOTE. ``converged`` here means both sides moved to the SAME
        # content and only the baseline needs to catch up — never a rewrite.
        if row.reason == REASON_CONVERGED:
            self._row_converged(row)
            return
        try:
            self.store.replicate_instance(row.remote_body, realm_id=self.realm_id, adopt_existing=row.local_record)
        except Exception as exc:  # noqa: BLE001 — accounted; the pull continues
            self.summary.refused.append(Refusal(row.instance_id, "mint_failed", type(exc).__name__).as_dict())
            return
        if row.local_record is None:
            self.summary.replicated.append(row.instance_id)
        else:
            self.summary.adopted.append(row.instance_id)
        # THE baseline-alignment property (plan §3.3): keyed off the REMOTE hash,
        # never re-derived from the local write, so a fresh replica reads ZERO
        # drift immediately. Without it the very next `realm sync status` reports
        # the replica as an unpublished local addition and the revert lane offers
        # to archive correct state.
        self._settle(row)

    def phase_two(self) -> dict[str, dict[str, Any]]:
        """The authored steering edges; returns the rebuilt dropped-edge ledger.

        Only rows this pass WROTE or found converged, plus the HEAL candidates
        phase one re-entered. A ``held`` row must not have its graph rewritten by
        the body it refused to adopt, and a ``kept_local`` row's steering is this
        machine's own edit — unless the ledger says the drift IS a drop this lane
        took, which is the one exception and it is decided in phase one.
        """

        next_ledger: dict[str, dict[str, Any]] = {}
        for instance_id, remote_body in self.written:
            parents = [str(item) for item in (remote_body.get("steered_by") or [])]
            pending = self.heal_pending.get(instance_id)
            try:
                applied, dropped = self.store.apply_replicated_steering(
                    instance_id, parents, realm_id=self.realm_id
                )
            except Exception as exc:  # noqa: BLE001 — accounted; a bad edge never fails a pull
                self.summary.steering_dropped.append(
                    {"key": instance_id, "parent": "", "reason": type(exc).__name__}
                )
                if pending is not None:
                    # The heal did not happen, so the row is what phase one would
                    # have called it, and the ledger entry is carried forward
                    # UNCHANGED — a store fault is not evidence that the edge was
                    # re-applied or that its parent arrived.
                    self.summary.kept_local.append(instance_id)
                    next_ledger[instance_id] = dict(self.ledger[instance_id])
                continue
            for row in dropped:
                self.summary.steering_dropped.append({"key": instance_id, **row})
            self._record_still_absent(next_ledger, instance_id, remote_body, dropped)
            if pending is not None:
                self._settle_heal(instance_id, pending, applied)
        return next_ledger

    @staticmethod
    def _record_still_absent(next_ledger, instance_id: str, remote_body: dict[str, Any], dropped) -> None:
        # Only ``parent_absent`` is recorded for a later heal. A self edge and a
        # cycle are refusals of the remote GRAPH — no parent is ever going to
        # arrive and make them valid — so re-entering phase two for them every
        # pull would re-report a verdict that cannot change.
        still_absent = sorted(
            {str(row.get("parent") or "") for row in dropped if row.get("reason") == "parent_absent"}
            - {""}
        )
        if still_absent:
            next_ledger[instance_id] = {
                "parents": still_absent,
                # The hash the drop was taken AGAINST, so a realm that moves the
                # body afterwards invalidates this entry by construction rather
                # than by an expiry rule.
                "remote_hash": persona_instance_def_hash(remote_body),
            }

    def _settle_heal(self, instance_id: str, pending: list[str], applied) -> None:
        healed = [parent for parent in pending if parent in applied]
        for parent in healed:
            self.summary.steering_healed.append({"key": instance_id, "parent": parent})
        if healed:
            # ``adopted`` and not ``converged``: a travelling field DID move
            # forward onto an existing row, and ``converged`` promises no write.
            self.summary.adopted.append(instance_id)
        else:
            # Nothing arrived. The row is exactly what phase one would have
            # called it, and the re-entry cost one store read.
            self.summary.kept_local.append(instance_id)

    def commit(self, next_ledger: dict[str, dict[str, Any]]) -> None:
        write_persona_instance_baseline(self.realm_id, self.baseline)
        write_dropped_steering_ledger(self.realm_id, next_ledger)


#: Phase one's routing (rule 12): the classifier's action -> the row handler.
#: The desk-archived reasons are decided BEFORE this table (they override the
#: action), and ``WRITE_REMOTE`` splits ``converged`` from a real write inside
#: its own handler.
_ROW_ACTIONS: Mapping[PullAction, Callable[[PullPass, _RowContext], None]] = {
    PullAction.NOOP: PullPass._row_converged,
    PullAction.KEEP_LOCAL: PullPass._row_keep_or_heal,
    PullAction.CONFLICT: PullPass._row_hold,
    PullAction.ARCHIVE_LOCAL: PullPass._row_upstream_absent,
    PullAction.WRITE_REMOTE: PullPass._row_write,
}


def apply_persona_instance_pull(
    realm_id: str,
    subtree,
    *,
    event_log: Any = None,
    desks_removed=(),
) -> PersonaInstancePullSummary:
    """THE mint door: a pulled desk that has no agent here gets one.

    Runs inside ``pull_realm_sync`` AFTER the persona-definition and
    profile-file lanes (the mint reads the definition to derive ``role`` and
    ``profile_id``, and a mint from a definition that has not landed yet builds
    the wrong agent) and BEFORE the workspace-tombstone lane (so a replica is
    never minted into a workspace the same pull is about to archive).

    Two phases, per plan §3.4. Phase one writes every row with ``steered_by``
    empty; phase two applies the edges, because an edge may name a parent this
    same pass has not minted yet. Without the split the outcome would depend on
    the alphabetical order of instance ids. :class:`PullPass` holds the state
    the phases share; :data:`_ROW_ACTIONS` routes phase one's rows.

    **The dropped-edge HEAL (2026-09-02), which is a third thing phase one
    does.** An edge whose parent is absent is dropped and accounted, and the row
    is then locally divergent from a remote body the baseline still holds the
    hash of — so every later pull classified it ``kept_local`` and phase two
    never re-ran for it. The edge was gone for good even on a realm that
    published the parent one pull later. Phase one now consults the durable
    drop ledger (:func:`read_dropped_steering_ledger`) on exactly the
    ``kept_local`` rows and re-enters phase two for the ones whose local body is
    still EXACTLY "remote minus the dropped edge" against the SAME remote hash
    the drop was taken against. Anything else — an operator's own re-steer, a
    renamed display name, a moved model override — is left alone, because that
    divergence is what ``kept_local`` exists to protect and re-running phase two
    for all of it was considered and rejected.

    Every write goes through ``PersonaInstanceStore.replicate_instance`` — a
    store door, never a raw file write — so the delta patch, the §1.3
    derivations and the event all happen in one place. A pull that GIVES you an
    agent reaches the same live consumers as one that takes one away.
    """

    from ..persona_assignments import PersonaInstanceStore

    summary = PersonaInstancePullSummary()
    remote, source = read_remote_persona_instances(subtree)
    summary.source = source
    store = PersonaInstanceStore(event_log=event_log) if event_log is not None else PersonaInstanceStore()
    run = PullPass(
        realm_id, store, summary, read_persona_instance_baseline(realm_id), read_dropped_steering_ledger(realm_id)
    )
    run.retire_removed_desks(desks_removed)
    if source is None or source == "unreadable":
        # Not published — never a removal: no baselined row is touched, so an
        # older peer in the rotation cannot strand this machine's replicas. An
        # unreadable projection is refused by name and touches nothing either.
        if source == "unreadable":
            summary.refused.append(
                Refusal(
                    PROJECTION_RELATIVE_PATH,
                    "unreadable_projection",
                    "the pulled instance projection exists and would not decode",
                ).as_dict()
            )
        if summary.retired:
            write_persona_instance_baseline(realm_id, run.baseline)
        return summary
    run.phase_one(remote)
    run.commit(run.phase_two())
    return summary
