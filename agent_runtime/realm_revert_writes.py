"""The store writes one decided realm revert makes, and the hash it realigns to.

``realm_revert`` decides (``classify_revert``) and accounts (``RevertRow``); this
module performs the write each decision names — restore, adopt, archive-local —
through each family's own store door, and reads back the content hash the
baseline is realigned to. Every function raises; ``realm_revert._revert_one``
turns a raise into a ``refused_store_error`` row, so nothing here reports.
"""

from __future__ import annotations

from . import board_models, office_models, paths
from .realm_sync import (
    DRIFT_FAMILY_BOARD,
    DRIFT_FAMILY_FLOW_GRAPH,
    DRIFT_FAMILY_OFFICE_ACTOR,
    DRIFT_FAMILY_OFFICE_SURFACE,
    DRIFT_FAMILY_PERSONA_DEFINITION,
    DRIFT_FAMILY_PERSONA_INSTANCE,
    DRIFT_FAMILY_SKILL,
    StoreDriftItem,
)

__layer__ = "lanes"

#: ``updated_by`` on every write this lane takes. The pull's arms stamp
#: ``realm_sync``; this one says which sync lane moved the row, so an operator
#: reading an actor's provenance can tell a peer's pull from their own revert.
REVERT_ACTOR_REF = "realm_sync_revert"


class _SkillWriteRefused(RuntimeError):
    """The promotion door refused a skill revert's write, with its typed code.

    Raised out of the write arms and caught in :func:`_revert_one` BEFORE the
    generic handler, so the row carries the door's own ``BLOCK_*`` code instead of
    the exception class name — an installer-owned package is a policy answer the
    operator can act on, not an unexpected failure.
    """

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _install_skill_from_inbox(item: StoreDriftItem, source_dir, *, realm_id: str | None) -> None:
    """Install the realm's copy of a skill package over the local canonical one.

    Goes through the ONE guarded promotion door
    (``skill_promotion.execute_promotion``), with ``adopt_divergent=True`` so a
    present canonical package is ARCHIVED before the install rather than
    overwritten — archive-never-delete, and the same arm the pull's ``updated``
    bucket and the operator's ``--take remote`` use. Nothing here is a second
    write path.

    ``move_source=False``: the inbox is the realm's mirror, not a duplicate to
    retire. A refusal (installer-owned package, or a canonical slot that moved
    under us) raises :class:`_SkillWriteRefused` so the row carries the door's own
    typed code.
    """

    from .skill_promotion import classify_promotion, execute_promotion

    plan = classify_promotion(item.item_key, source_dir)
    if plan.action == "refuse_invalid":
        raise _SkillWriteRefused("skill_plan_refused", plan.reason)
    result = execute_promotion(
        plan,
        source={"kind": "realm", "realm_id": realm_id or ""},
        adopt_divergent=True,
        move_source=False,
    )
    if result.action not in ("promoted", "noop"):
        raise _SkillWriteRefused(result.reason_code or "skill_promotion_refused", result.reason)


def _archive_local_skill(item: StoreDriftItem) -> None:
    """Archive a local-only skill package — the ``added`` arm.

    ``skill_promotion._archive_package`` MOVES the tree into
    ``shared/skills/.archive/<UTC ts>/``, which is the never-delete lane the
    promotion door and ``skills delete`` both use; ``hermes harness skills
    promote`` can bring it back from there. This lane mints NO realm-visible
    tombstone, exactly as the office/board ``added`` arms do not
    (``record_tombstone=False``): the operator is saying "my local copy is noise",
    not "delete this skill for the realm".
    """

    from agent_runtime.profile_home import get_shared_skills_dir

    from .skill_promotion import _archive_package

    package = get_shared_skills_dir().joinpath(*item.item_key.split("/"))
    if package.is_dir():
        _archive_package(package, item.item_key)


def _refuse_flow_graph(body):
    """The canvas family's admission door — ``parse_flow_graph_doc``, and only it.

    A ``Refusal`` in the shared shape so the row reads like every other family's,
    carrying the parser's own code. Nothing else is added: this is the exact door
    ``apply_flow_graph_pull`` holds, and a revert must write nothing a pull could
    not have written — nor refuse what a pull would have admitted.
    """

    from .flow_graph import FlowGraphDocError, parse_flow_graph_doc
    from .flow_graph_sync import REFUSAL_INVALID_REMOTE_DOCUMENT
    from .sync_admission import Refusal

    graph_id = str((body or {}).get("graph_id") or "") if isinstance(body, dict) else ""
    try:
        parse_flow_graph_doc(body)
    except FlowGraphDocError as exc:
        return Refusal(graph_id, REFUSAL_INVALID_REMOTE_DOCUMENT, str(exc))
    return None


def _restore_from_upstream(
    item: StoreDriftItem, entity, *, office_store, board_store, realm_id: str | None = None
) -> None:
    """The un-archive door, then the upstream content on top of it.

    Two writes and not one, deliberately. The archive copy holds THIS machine's
    last local bytes, and only the store's own restore verb clears the
    resurrection-guard ledger entry that made the row invisible; adopting the
    upstream copy straight over a live-but-tombstoned key would leave a desk
    that the next pull's classifier still reads as archived. When the restored
    content already equals upstream's, the second write is skipped — the
    idempotence this lane promises is not paid for with a revision bump per
    call.

    A key that is in the resurrection-guard ledger with NO archive copy behind
    it falls through to the adopt arm alone, which leaves the ledger entry
    standing. No writer in this runtime produces that state (the archive copy is
    written BEFORE the ledger entry, and ``remove_actor`` itself reports
    not-found in it), so it is not machinery this lane grows a second door for —
    but it is why the ledger check is spelled as "is there an archive copy" and
    not "is this key archived".
    """

    if item.family == DRIFT_FAMILY_FLOW_GRAPH:
        # A canvas has no un-archive verb either, and for a stronger reason than
        # the instance family's: ``FlowGraphStore.archive`` MOVES the file into
        # ``flow_graphs_stale/`` and leaves no ledger entry behind, so there is
        # no resurrection guard to clear and "restore" and "adopt" are the same
        # write. The stale copy stays where archive-never-delete put it — a
        # second copy of a drawing the projection can rebuild is not worth a
        # second verb, and the operator's own last local bytes are exactly what
        # ``flow_graphs_stale/`` is for.
        _adopt_from_upstream(
            item, entity, office_store=office_store, board_store=board_store, realm_id=realm_id
        )
        return
    if item.family == DRIFT_FAMILY_PERSONA_INSTANCE:
        # A replicated AGENT has no un-archive verb of its own and does not need
        # one: the store door mints a row for an id with no live file, deriving
        # this machine's §1.3 half exactly as the pull would. So "restore" and
        # "adopt" are the same write for this family, and the archived copy on
        # disk stays where archive-never-delete put it — a second copy of a row
        # the projection can rebuild is not worth a second verb.
        _adopt_from_upstream(
            item, entity, office_store=office_store, board_store=board_store, realm_id=realm_id
        )
        return
    if item.family == DRIFT_FAMILY_OFFICE_ACTOR:
        if paths.office_archived_actor_path(item.container, item.item_key).exists():
            restored = office_store.restore_actor(
                item.container, item.item_key, updated_by=REVERT_ACTOR_REF
            )
            if office_models.office_content_hash(restored) == office_models.office_content_hash(entity):
                return
        _adopt_from_upstream(item, entity, office_store=office_store, board_store=board_store)
        return
    if paths.board_archived_card_path(item.container, item.item_key).exists():
        restored = board_store.restore_card(
            item.item_key, board_id=item.container, updated_by=REVERT_ACTOR_REF
        )
        if board_models.board_content_hash(restored) == board_models.board_content_hash(entity):
            return
    _adopt_from_upstream(item, entity, office_store=office_store, board_store=board_store)


def _adopt_from_upstream(
    item: StoreDriftItem, entity, *, office_store, board_store, realm_id: str | None = None
) -> None:
    """Write the subtree artifact over the local row — the pull's adopt arms,
    unchanged.

    "Unchanged" is the whole contract of this function, and it is why the board
    families moved when their pull arm did. They went through
    ``atomic_json_write`` for as long as ``board_sync.apply_board_pull`` did —
    the office store grew evented ``adopt_remote_*`` verbs in the actor-lifecycle
    wave (H1) and the board store did not, so this lane matched its family's pull
    arm rather than inventing a third spelling. The board store now has
    ``adopt_remote_board`` / ``adopt_remote_card`` and the pull routes through
    them, so this lane does too: four families, four store doors, and a revert
    that still writes nothing a pull could not have written.
    """

    if item.family == DRIFT_FAMILY_FLOW_GRAPH:
        # ``set_doc`` is the pull's own arm, so the document is validated by
        # ``parse_flow_graph_doc`` on the way in and never written raw.
        # ``requested_by`` says which lane moved it, the way ``REVERT_ACTOR_REF``
        # does for the stores that take an ``updated_by``.
        from .flow_graph import FlowGraphStore, parse_flow_graph_doc

        FlowGraphStore().set_doc(parse_flow_graph_doc(entity), requested_by=REVERT_ACTOR_REF)
        return
    if item.family == DRIFT_FAMILY_PERSONA_INSTANCE:
        # Through the SAME store door the pull writes replicas with, so a revert
        # writes nothing a pull could not have written — including the delta
        # patch and the ``persona_instance.replicated`` receipt. ``entity`` here
        # is the projected BODY (a dict), not a record: this family's upstream
        # artifact is one document for the whole realm.
        from .persona_assignments import PersonaInstanceStore

        store = PersonaInstanceStore()
        try:
            existing = store.get(item.item_key)
        except Exception:
            existing = None
        store.replicate_instance(entity, realm_id=str(realm_id or ""), adopt_existing=existing)
        return
    if item.family == DRIFT_FAMILY_OFFICE_ACTOR:
        entity.workspace_id = item.container
        entity.state = "active"
        office_store.adopt_remote_actor(entity, updated_by=REVERT_ACTOR_REF)
        return
    if item.family == DRIFT_FAMILY_OFFICE_SURFACE:
        entity.workspace_id = item.container
        office_store.adopt_remote_surface(entity, updated_by=REVERT_ACTOR_REF)
        return
    if item.family == DRIFT_FAMILY_BOARD:
        entity.board_id = item.container
        board_store.adopt_remote_board(entity, updated_by=REVERT_ACTOR_REF)
        return
    entity.state = "active"
    board_store.adopt_remote_card(
        entity, board_id=item.container, updated_by=REVERT_ACTOR_REF
    )


def _archive_local_only(item: StoreDriftItem, *, office_store, board_store) -> None:
    """THE ruling, spelled once: a revert archives through the
    ``record_tombstone=False`` lane on both stores, so no realm-visible ledger
    entry is minted. See the module docstring (§AX7)."""

    if item.family == DRIFT_FAMILY_FLOW_GRAPH:
        # A drawing the realm does not have. ``archive`` MOVES it into
        # ``flow_graphs_stale/`` — the same door owner-liveness reaping uses —
        # so archive-never-delete holds and the operator's map is recoverable by
        # hand. ``record_tombstone=False`` is structural here rather than a
        # parameter: a graph carries no realm-visible ledger at all, so there is
        # nowhere for this lane to mint one.
        from .flow_graph import FlowGraphStore

        store = FlowGraphStore()
        store.archive(item.item_key, store.stale_dir())
        return
    if item.family == DRIFT_FAMILY_PERSONA_INSTANCE:
        # A locally-authored agent the realm does not have. The instance record
        # carries NO realm-visible ledger at all, so ``record_tombstone=False``
        # is structural here rather than a parameter: ``retire_replica`` archives
        # the row and deliberately runs no office half, which is the only place
        # this lane could have minted a ledger entry.
        from .persona_assignments import PersonaInstanceStore

        PersonaInstanceStore().retire_replica(item.item_key, reason="revert_local_only")
        return
    if item.family == DRIFT_FAMILY_OFFICE_ACTOR:
        office_store.remove_actor(
            item.container,
            item.item_key,
            reason="revert_local_only",
            updated_by=REVERT_ACTOR_REF,
            record_tombstone=False,
        )
        return
    board_store.archive_card(
        item.item_key,
        board_id=item.container,
        reason="revert_local_only",
        updated_by=REVERT_ACTOR_REF,
        record_tombstone=False,
    )


def _current_content_hash(item: StoreDriftItem, *, office_store, board_store) -> str:
    """The baseline is realigned from the STORE's post-write content, not from
    the upstream artifact's hash.

    The two are not always equal and the difference is the honest part:
    ``adopt_remote_surface`` UNIONS the resurrection-guard ledger (C1), so a
    surface holding a local-only tombstone the realm has not seen re-hashes
    away from upstream. Recording the store's own content says "this is what I
    would publish", which is what a baseline means; recording the remote's would
    make the sheet read in-sync for content this install does not hold.
    """

    if item.family == DRIFT_FAMILY_PERSONA_DEFINITION:
        from .persona_config_sync import local_persona_bodies, persona_def_hash

        # What a publish would now ship for this persona — the same body the
        # drift walk hashes, so a reverted row reads ``local == baseline``.
        return persona_def_hash(local_persona_bodies([item.item_key])[item.item_key])
    if item.family == DRIFT_FAMILY_SKILL:
        from agent_runtime.profile_home import get_shared_skills_dir

        from .skill_promotion import skill_package_sync_hash

        # The canonical package as it stands after the install, hashed with the
        # SYNC hash — the same hash the pull, the publish baseline and the resolve
        # verb record, so a reverted row reads ``local == baseline`` on the very
        # next status instead of ``changed`` over an EOL difference.
        return skill_package_sync_hash(
            get_shared_skills_dir().joinpath(*item.item_key.split("/"))
        )
    if item.family == DRIFT_FAMILY_FLOW_GRAPH:
        from .flow_graph import FlowGraphStore
        from .flow_graph_sync import flow_graph_def_hash, project_flow_graph

        return flow_graph_def_hash(
            project_flow_graph(FlowGraphStore().get(item.item_key), dropped=[])
        )
    if item.family == DRIFT_FAMILY_PERSONA_INSTANCE:
        from .persona_assignments import PersonaInstanceStore
        from .persona_instance_sync import persona_instance_def_hash, project_persona_instance

        return persona_instance_def_hash(
            project_persona_instance(PersonaInstanceStore().get(item.item_key))
        )
    if item.family == DRIFT_FAMILY_OFFICE_ACTOR:
        return office_models.office_content_hash(office_store.get_actor(item.container, item.item_key))
    if item.family == DRIFT_FAMILY_OFFICE_SURFACE:
        return office_models.office_content_hash(office_store.get_surface(item.container))
    if item.family == DRIFT_FAMILY_BOARD:
        return board_models.board_content_hash(board_store.get(item.container))
    return board_models.board_content_hash(board_store.get_card(item.item_key, board_id=item.container))
