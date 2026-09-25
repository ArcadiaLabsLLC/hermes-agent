"""``apply_persona_instance_pull`` — the mint door — and its per-row helpers.

Map: ``agent_runtime/persona_instance_sync/__init__.py``.
"""

from __future__ import annotations

from typing import Any

from .contract import PROJECTION_RELATIVE_PATH, PersonaInstancePullSummary
from .projection import persona_instance_def_hash, project_persona_instance, refuse_persona_instance
from .sidecars import (
    _write_conflict_sidecar,
    instance_baseline_key,
    read_dropped_steering_ledger,
    read_persona_instance_baseline,
    read_remote_persona_instances,
    write_dropped_steering_ledger,
    write_persona_instance_baseline,
)

__layer__ = "stores"


def _refusal_row(instance_id: str, code: str, message: str) -> dict[str, str]:
    return {"key": instance_id, "code": code, "message": message}


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
    the alphabetical order of instance ids.

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
    from ..sync_merge import PullAction, classify_three_way_pull

    summary = PersonaInstancePullSummary()
    remote, source = read_remote_persona_instances(subtree)
    summary.source = source
    store = (
        PersonaInstanceStore(event_log=event_log)
        if event_log is not None
        else PersonaInstanceStore()
    )
    baseline = read_persona_instance_baseline(realm_id)
    dropped_ledger = read_dropped_steering_ledger(realm_id)

    # §5.2 FIRST, and independent of the projection. The trigger is the office
    # lane's own ``remote_removed`` archive, not anything in this document — a
    # peer can retire a desk in the same pull where their projection is absent,
    # unreadable, or unchanged, and the replica has to follow the desk in all
    # three cases.
    _retire_replicas_for_removed_desks(
        store, summary, baseline, realm_id=realm_id, desks_removed=desks_removed
    )

    if source is None:
        # Not published. Never a removal — no baselined row is touched, so an
        # older peer in the rotation cannot strand this machine's replicas.
        if summary.retired:
            write_persona_instance_baseline(realm_id, baseline)
        return summary
    if source == "unreadable":
        summary.refused.append(
            _refusal_row(
                PROJECTION_RELATIVE_PATH,
                "unreadable_projection",
                "the pulled instance projection exists and would not decode",
            )
        )
        if summary.retired:
            write_persona_instance_baseline(realm_id, baseline)
        return summary

    prefix = instance_baseline_key("")
    baselined_ids = {key[len(prefix):] for key in baseline if key.startswith(prefix)}
    written: list[tuple[str, dict[str, Any]]] = []
    #: ``{instance_id: [parent, ...]}`` — rows phase one classified ``kept_local``
    #: whose drift is fully explained by edges an earlier pull dropped. They
    #: re-enter phase two and their OUTCOME is decided there, because whether
    #: the parent has actually arrived is phase two's question, not phase one's.
    heal_pending: dict[str, list[str]] = {}
    # The resurrection guard, from TWO sources that answer the same question at
    # different ranges. The office ledger covers desks archived in any earlier
    # pass; ``summary.retired`` covers the ones THIS pass just archived, which
    # the ledger would also carry in production but which must not depend on
    # another store's state for a guarantee this function makes about itself. A
    # retire undone by phase one of the same pull would be incoherent.
    archived_keys = _locally_archived_actor_keys() | set(summary.retired)

    # --- phase one: the rows ------------------------------------------------
    for instance_id in sorted(set(remote) | baselined_ids):
        remote_body = remote.get(instance_id)
        key = instance_baseline_key(instance_id)

        if remote_body is not None:
            refusal = refuse_persona_instance(instance_id, remote_body)
            if refusal is not None:
                # Untouched, named, and the pull continues — the store never
                # learns this row existed.
                summary.refused.append(refusal.as_dict())
                continue

        local_hash, local_record, local_refusal = _local_projection_hash(store, instance_id)
        if local_refusal is not None:
            summary.refused.append(
                _refusal_row(instance_id, local_refusal, "local instance row will not decode")
            )
            continue

        if remote_body is None:
            # THE row that is not a delete. The realm stopped carrying a row
            # this baseline says it published, and that is exactly as consistent
            # with "the publisher's office scan came back short" as with "the
            # operator deleted it". Only the DESK's own removal is authored
            # intent (plan §5.2). Hold it, name it, and KEEP the baseline so a
            # repaired publish still converges.
            if local_hash is not None:
                summary.upstream_absent.append(instance_id)
            else:
                baseline.pop(key, None)
            continue

        remote_hash = persona_instance_def_hash(remote_body)
        decision = classify_three_way_pull(
            local_hash,
            remote_hash,
            baseline.get(key),
            # THE resurrection guard, and it is the office family's own ledger
            # rather than a second one: the actor key IS the instance id, so a
            # desk the operator archived here answers for its agent too. Without
            # it, a retire-follows-the-desk taken in one pull would be undone by
            # the very next pull, because the retired row reads as locally absent
            # while the realm still publishes it.
            locally_archived=instance_id in archived_keys,
        )
        if decision.reason in ("archived_local", "archive_vs_edit"):
            summary.desk_archived.append(instance_id)
            if decision.action == PullAction.CONFLICT:
                # The realm EDITED an agent whose desk is archived here. Nothing
                # is written, but the body is parked so the divergence is not
                # simply lost between two correct local states.
                _write_conflict_sidecar(
                    realm_id, instance_id, decision.reason, remote_body, local_hash, remote_hash
                )
            continue

        if decision.action == PullAction.NOOP:
            summary.converged.append(instance_id)
            written.append((instance_id, remote_body))
            baseline[key] = remote_hash
            continue
        if decision.action == PullAction.KEEP_LOCAL:
            # THE heal seam. A row whose local drift is exactly the edges an
            # earlier pull dropped is not an operator's edit at all — it is this
            # lane's own unfinished write, and re-entering phase two is what
            # finishes it. Everything else stays ``kept_local`` untouched.
            healable = _healable_dropped_parents(
                dropped_ledger, instance_id, remote_body, remote_hash, local_hash
            )
            if healable:
                heal_pending[instance_id] = healable
                written.append((instance_id, remote_body))
            else:
                summary.kept_local.append(instance_id)
            continue
        if decision.action == PullAction.CONFLICT:
            summary.held.append(instance_id)
            _write_conflict_sidecar(
                realm_id, instance_id, decision.reason, remote_body, local_hash, remote_hash
            )
            continue
        if decision.action == PullAction.ARCHIVE_LOCAL:
            # Unreachable while ``remote_body is not None`` — the classifier only
            # takes this arm on an absent remote — and stated rather than left to
            # fall through: this family has NO archive arm in the pull at all.
            # Retirement follows the DESK (H4/§5.2), never the absence.
            summary.upstream_absent.append(instance_id)
            continue

        # WRITE_REMOTE. ``converged`` here means both sides moved to the SAME
        # content and only the baseline needs to catch up — never a rewrite.
        if decision.reason == "converged":
            summary.converged.append(instance_id)
            written.append((instance_id, remote_body))
            baseline[key] = remote_hash
            continue
        try:
            store.replicate_instance(remote_body, realm_id=realm_id, adopt_existing=local_record)
        except Exception as exc:  # noqa: BLE001 — accounted; the pull continues
            summary.refused.append(_refusal_row(instance_id, "mint_failed", type(exc).__name__))
            continue
        if local_record is None:
            summary.replicated.append(instance_id)
        else:
            summary.adopted.append(instance_id)
        written.append((instance_id, remote_body))
        # THE baseline-alignment property (plan §3.3): keyed off the REMOTE hash,
        # never re-derived from the local write, so a fresh replica reads ZERO
        # drift immediately. Without it the very next `realm sync status` reports
        # the replica as an unpublished local addition and the revert lane offers
        # to archive correct state.
        baseline[key] = remote_hash

    # --- phase two: the authored steering edges -----------------------------
    #
    # Only rows this pass WROTE or found converged, plus the HEAL candidates
    # phase one re-entered. A ``held`` row must not have its graph rewritten by
    # the body it refused to adopt, and a ``kept_local`` row's steering is this
    # machine's own edit — unless the ledger says the drift IS a drop this lane
    # took, which is the one exception and it is decided in phase one.
    next_ledger: dict[str, dict[str, Any]] = {}
    for instance_id, remote_body in written:
        parents = [str(item) for item in (remote_body.get("steered_by") or [])]
        pending = heal_pending.get(instance_id)
        try:
            applied, dropped = store.apply_replicated_steering(
                instance_id, parents, realm_id=realm_id
            )
        except Exception as exc:  # noqa: BLE001 — accounted; a bad edge never fails a pull
            summary.steering_dropped.append(
                {"key": instance_id, "parent": "", "reason": type(exc).__name__}
            )
            if pending is not None:
                # The heal did not happen, so the row is what phase one would
                # have called it, and the ledger entry is carried forward
                # UNCHANGED — a store fault is not evidence that the edge was
                # re-applied or that its parent arrived.
                summary.kept_local.append(instance_id)
                next_ledger[instance_id] = dict(dropped_ledger[instance_id])
            continue
        for row in dropped:
            summary.steering_dropped.append({"key": instance_id, **row})
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
        if pending is None:
            continue
        healed = [parent for parent in pending if parent in applied]
        for parent in healed:
            summary.steering_healed.append({"key": instance_id, "parent": parent})
        if healed:
            # ``adopted`` and not ``converged``: a travelling field DID move
            # forward onto an existing row, and ``converged`` promises no write.
            summary.adopted.append(instance_id)
        else:
            # Nothing arrived. The row is exactly what phase one would have
            # called it, and the re-entry cost one store read.
            summary.kept_local.append(instance_id)

    write_persona_instance_baseline(realm_id, baseline)
    write_dropped_steering_ledger(realm_id, next_ledger)
    return summary
