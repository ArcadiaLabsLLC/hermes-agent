"""Per-item revert-to-upstream for realm store drift — the second exit from
"unpublished changes" (``hermes harness realm sync revert``).

Plan: ``docs/mission_control/planned/realm-sync-local-changes-resolution.md``
(launcher repo), Stage H. Until this module existed the ONLY exit the product
offered an operator holding local store drift was **Publish** — pull
deliberately never clobbers local state (correct), so an operator whose local
changes are noise had no exit at all. Measured 2026-08-31 on the operator's
store: office drift ``offices_changed 1, actors_removed 1``, the one item a
baseline actor the census had archived locally and nobody ever meant to
publish.

Three rulings shape every line below.

* **A revert is DIAGNOSTIC intent, not authored deletion** (the actor-lifecycle
  wave's authored-vs-diagnostic ruling, §AX7). The operator is saying "my local
  unpublished state is noise; upstream is truth" — NOT "delete this
  realm-wide". So the ``added`` arm archives through the
  ``record_tombstone=False`` lane on BOTH stores, and **no revert ever mints a
  realm-visible tombstone**. That is a guarantee, pinned by
  ``tests/agent_runtime/test_realm_revert.py``.
* **Local-only.** No git, no network, no credential, no remote. This
  reconciles the local store against the local sync-repo subtree — the
  LAST-PULLED upstream picture. A fresher upstream is what Pull is for, and the
  verb refuses ``sync_repo_missing`` rather than inventing one.
* **Archive-never-delete stands.** Reverting a locally-added row archives it;
  nothing is unlinked, and ``actor-restore`` / ``board card restore`` still
  reach it.

The write arms are the PULL lane's arms, not new ones: ``adopt_remote_actor`` /
``adopt_remote_surface`` / ``adopt_remote_board`` / ``adopt_remote_card`` /
``restore_actor`` / ``restore_card`` / ``archive_card`` / ``remove_actor``,
— and, since the SKILL family joined on 2026-09-12, the ONE guarded promotion
door (``skill_promotion.execute_promotion`` with ``adopt_divergent=True``, and
``_archive_package`` for the local-only arm),
and — since the replicated persona-INSTANCE family joined on 2026-08-31 —
``replicate_instance`` / ``retire_replica``, and since the replicated CANVAS
family joined on 2026-09-05, ``FlowGraphStore.set_doc`` / ``.archive``, plus the
same admission door every pulled payload passes. A revert writes nothing a pull
could not have written.
(The two board adopt verbs arrived on 2026-09-02 with the pull arm that grew
them; until then both lanes wrote board rows with a raw ``atomic_json_write``
and emitted nothing, which is why the sentence above was true and the module's
own "a live subscriber that never heard" note below was not.)

The instance family's ``added`` arm needs no ``record_tombstone=False``
parameter, and that is not an omission: a persona-instance record carries no
realm-visible ledger at all, so the only place this lane could mint one is the
office half — and ``retire_replica`` deliberately does not run it. The canvas
family's arm is the same shape for the same reason, one step simpler:
``FlowGraphStore.archive`` moves the file into ``flow_graphs_stale/`` and writes
no ledger anywhere, so archive-never-delete holds with no parameter at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from . import paths
from .realm_sync import (
    DRIFT_FAMILY_BOARD,
    DRIFT_FAMILY_BOARD_CARD,
    DRIFT_FAMILY_FLOW_GRAPH,
    DRIFT_FAMILY_OFFICE_ACTOR,
    DRIFT_FAMILY_OFFICE_SURFACE,
    DRIFT_FAMILY_PERSONA_DEFINITION,
    DRIFT_FAMILY_PERSONA_INSTANCE,
    DRIFT_FAMILY_SKILL,
    DRIFT_KIND_ADDED,
    DRIFT_KIND_CHANGED,
    DRIFT_KIND_REMOVED,
    RealmSyncError,
    StoreDriftItem,
    _append_realm_sync_event,
    _board_store_drift,
    _office_store_drift,
    _realm_subtree,
    _safe_display_path,
    _sync_repo_path,
    _workspaces_for_realm,
    store_drift_items,
)
from .serde import to_jsonable
from .realm_revert_writes import (  # noqa: F401 — REVERT_ACTOR_REF is re-exported
    REVERT_ACTOR_REF,
    _SkillWriteRefused,
    _adopt_from_upstream,
    _archive_local_only,
    _archive_local_skill,
    _current_content_hash,
    _install_skill_from_inbox,
    _refuse_flow_graph,
    _restore_from_upstream,
)
from .store import RealmStore

__layer__ = "lanes"

#: The event a completed revert appends. It advances the EventLog watermark the
#: same way ``realm.sync.pulled`` / ``realm.sync.published`` do, because a
#: revert rewrites store state through the same door and a live office
#: subscriber that never heard would render rows the store no longer has.
REVERT_EVENT_TYPE = "realm.sync.reverted"


# --- outcomes (the typed vocabulary the launcher renders per row) ----------

#: A baseline row that was archived/absent locally is live again, from the
#: subtree artifact.
OUTCOME_RESTORED = "restored_from_upstream"
#: A locally-edited row's content was overwritten with the subtree artifact's.
OUTCOME_REVERTED = "reverted_to_upstream"
#: A local-only row was archived through the ``record_tombstone=False`` lane.
OUTCOME_ARCHIVED_LOCAL_ONLY = "archived_local_only"
#: The baseline claimed an artifact the subtree does not have. Accounted, never
#: silent: the stale entry is dropped so the item stops counting.
OUTCOME_BASELINE_DROPPED = "baseline_entry_dropped"
#: There is no upstream copy to revert TO and this family has no local-only
#: archive lane (a board def / office surface cannot be "archived locally").
REFUSED_NO_UPSTREAM = "refused_no_upstream"
#: The requested item is not in this realm's current drift set — a typo, or an
#: item some earlier pass already resolved.
REFUSED_UNKNOWN_ITEM = "refused_unknown_item"
#: The subtree artifact exists and would not decode. Never treated as absence:
#: absence is what drives the baseline-drop and archive arms, so a parse error
#: read as absence is a delete-shaped decision taken on a read failure.
REFUSED_UNREADABLE_UPSTREAM = "refused_unreadable_upstream"
#: The subtree payload would not pass ``sync_admission`` — the same door the
#: pull holds against secret-shaped and machine-shaped content.
REFUSED_ADMISSION = "refused_admission"
#: The store refused the write. The item is untouched and the pass continues.
REFUSED_STORE_ERROR = "refused_store_error"

APPLIED_OUTCOMES = frozenset(
    {OUTCOME_RESTORED, OUTCOME_REVERTED, OUTCOME_ARCHIVED_LOCAL_ONLY, OUTCOME_BASELINE_DROPPED}
)

#: Families whose row IS the container definition. They have no local-only
#: archive lane, which is the one place their transition table differs.
CONTAINER_FAMILIES = frozenset({DRIFT_FAMILY_BOARD, DRIFT_FAMILY_OFFICE_SURFACE})
#: Families with no local-only archive lane: the containers above, plus the
#: persona DEFINITION — a persona is referenced by placements, instances and
#: assignments, and a revert never deletes one (the pull's ``retained`` rule).
NO_LOCAL_ARCHIVE_FAMILIES = CONTAINER_FAMILIES | frozenset({DRIFT_FAMILY_PERSONA_DEFINITION})
FAMILIES = frozenset(
    {
        DRIFT_FAMILY_BOARD,
        DRIFT_FAMILY_BOARD_CARD,
        DRIFT_FAMILY_OFFICE_SURFACE,
        DRIFT_FAMILY_OFFICE_ACTOR,
        DRIFT_FAMILY_PERSONA_INSTANCE,
        DRIFT_FAMILY_FLOW_GRAPH,
        DRIFT_FAMILY_SKILL,
        DRIFT_FAMILY_PERSONA_DEFINITION,
    }
)

#: Rows before containers, and the CANVAS after the agents it binds. A restored
#: actor leaves its workspace's resurrection-guard ledger, which CHANGES the
#: surface hash — so the surface arm (and the baseline realignment that follows
#: it) must run after the rows it is downstream of, or a ``--all`` pass realigns
#: the surface against a picture one write out of date.
#:
#: The canvas sits LAST for the pull lane's reason, not the surface's: a canvas
#: binds nodes to instance ids, owner-liveness reaping archives a drawing whose
#: owner is gone, and a canvas restored before its owner instance looks exactly
#: like that. ``apply_flow_graph_pull`` runs after ``apply_persona_instance_pull``
#: for this, and a ``--all`` revert that carried both would otherwise restore
#: them in family-name order — ``flow_graph`` before ``persona_instance``.
#: The SKILL family sits in the ROW band (0) and needs nothing from the others:
#: its upstream is the per-realm inbox mirror and its container is the machine's
#: shared skills root, so no other family's write can change what a skill row
#: reverts to, and no skill write changes another family's hash.
_PROCESS_ORDER = {
    DRIFT_FAMILY_OFFICE_ACTOR: 0,
    DRIFT_FAMILY_BOARD_CARD: 0,
    DRIFT_FAMILY_PERSONA_INSTANCE: 0,
    DRIFT_FAMILY_SKILL: 0,
    DRIFT_FAMILY_PERSONA_DEFINITION: 0,
    DRIFT_FAMILY_OFFICE_SURFACE: 1,
    DRIFT_FAMILY_BOARD: 1,
    DRIFT_FAMILY_FLOW_GRAPH: 2,
}


class RevertAction(str, Enum):
    RESTORE = "restore"  # baseline row, gone locally → live again from upstream
    ADOPT = "adopt"  # local row overwritten with the upstream artifact
    ARCHIVE_LOCAL = "archive_local"  # local-only row → archived, NO tombstone
    DROP_BASELINE = "drop_baseline"  # stale baseline entry with no artifact behind it
    REFUSE = "refuse"  # nothing to revert to, and nothing safe to do


@dataclass(frozen=True, slots=True)
class RevertDecision:
    action: RevertAction
    outcome: str


def classify_revert(*, family: str, kind: str, upstream_present: bool) -> RevertDecision:
    """THE transition table, pure and total over (family × kind × upstream).

    ``upstream_present`` is "the last-pulled subtree holds a decodable artifact
    for this row" — the only fact about upstream this decision needs. The
    unreadable case never reaches here: a subtree artifact that exists and will
    not decode is refused by the caller rather than folded into ``False``,
    because ``False`` is what drives the two delete-shaped arms below.
    """

    if kind == DRIFT_KIND_REMOVED:
        # Baseline says the realm has this row; locally it is archived or gone.
        return (
            RevertDecision(RevertAction.RESTORE, OUTCOME_RESTORED)
            if upstream_present
            else RevertDecision(RevertAction.DROP_BASELINE, OUTCOME_BASELINE_DROPPED)
        )
    if kind == DRIFT_KIND_CHANGED:
        return (
            RevertDecision(RevertAction.ADOPT, OUTCOME_REVERTED)
            if upstream_present
            else RevertDecision(RevertAction.DROP_BASELINE, OUTCOME_BASELINE_DROPPED)
        )
    if kind == DRIFT_KIND_ADDED:
        # No baseline entry — but "no baseline entry" is a statement about what
        # THIS install last published, not about what the realm holds. When the
        # subtree does have the row, reverting to upstream means adopting it,
        # not deleting it; only a row upstream genuinely lacks is local-only.
        if upstream_present:
            return RevertDecision(RevertAction.ADOPT, OUTCOME_REVERTED)
        if family in NO_LOCAL_ARCHIVE_FAMILIES:
            return RevertDecision(RevertAction.REFUSE, REFUSED_NO_UPSTREAM)
        return RevertDecision(RevertAction.ARCHIVE_LOCAL, OUTCOME_ARCHIVED_LOCAL_ONLY)
    raise ValueError("invalid_request")


@dataclass(slots=True)
class RevertRow:
    """One item's result. ``detail`` names the exception CLASS or the admission
    code — never a message, the same disclosure rule the rest of this runtime's
    receipts follow."""

    family: str
    container: str
    item_key: str
    kind: str | None
    outcome: str
    detail: str | None = None

    @property
    def applied(self) -> bool:
        return self.outcome in APPLIED_OUTCOMES

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "container": self.container,
            "item_key": self.item_key,
            "kind": self.kind,
            "outcome": self.outcome,
            "detail": self.detail,
        }


def parse_item_spec(raw: str) -> tuple[str, str, str]:
    """``FAMILY:CONTAINER:KEY`` → the triple. Raises ``RealmSyncError
    invalid_request`` for anything else: an unparseable selector is a fault in
    the REQUEST, and guessing at one is how the wrong desk gets archived.

    **The CONTAINER may be blank, and blank means blank** (w17/hb's row, fixed
    2026-09-06). A drift row whose holder is gone has no container to name — the
    persona-instance family's ``removed`` rows are exactly that: a baselined
    agent with no live record, whose ``workspace_id`` died with the record it
    was read from. The walk writes ``container=""`` there rather than guess one,
    so ``FAMILY::KEY`` is that row's own ``spec`` echoed back and refusing it
    left the family's removals reachable only through ``--all``.

    The canvas family's trick — derive the container from the item key
    (``owner_instance_id_of``) — is not available here and would not be honest
    if it were: a graph id literally CONTAINS its owner's id, while an instance
    id says nothing about the workspace that held it. And this family needs no
    container at all: ``_Upstream.lookup`` reads the persona-instance projection
    (one realm-wide document) by key and never touches the container, so the
    blank is the accurate value rather than a missing one.

    A blank container is never a WILDCARD. Selection stays an exact match
    against the derived drift set (``by_spec`` in :func:`revert_realm_sync`), so
    ``FAMILY::KEY`` reaches only a row that itself reported a blank; a row that
    has a container is still addressed by it. Family and key stay required: a
    blank family has no transition table to dispatch on, and a blank key names
    nothing.
    """

    text = str(raw or "").strip()
    parts = text.split(":", 2)
    if len(parts) != 3 or not parts[0].strip() or not parts[2].strip():
        raise RealmSyncError(
            "invalid_request",
            "--item takes FAMILY:CONTAINER:KEY (e.g. office_actor:ws_x:dev_agent_1234); "
            "the container — and only the container — may be empty, for a row whose "
            "holder is gone (persona_instance::personainst_1234).",
            safe_details={"item": text},
        )
    family, container, item_key = (part.strip() for part in parts)
    if family not in FAMILIES:
        raise RealmSyncError(
            "invalid_request",
            f"Unknown drift family {family!r}; expected one of {sorted(FAMILIES)}.",
            safe_details={"item": text},
        )
    return family, container, item_key


class _Upstream:
    """The last-pulled subtree, read through the PULL lane's own readers.

    Per-container and cached, for the reason ``_read_remote_office`` exists at
    all: the payload is truth and the filename is routing, so an item is looked
    up by its decoded key rather than by recomputing a filename token — and the
    directory's ``unreadable`` count travels with the rows, so an artifact that
    exists and would not decode can be told apart from one that is absent.
    """

    def __init__(self, subtree: Path, *, realm_id: str | None = None, skill_root: Path | None = None) -> None:
        self._subtree = subtree
        #: A version restore (``--to``) reads skills from THAT version's mirror,
        #: never from the live inbox — see ``realm_revert_version``.
        self._skill_root = skill_root
        #: The SKILL family's upstream is NOT under the subtree: it is the
        #: per-realm INBOX mirror, which is the subtree's ``skills/`` tree copied
        #: LF-canonical and package-filtered (tombstones dropped) by the pull. The
        #: revert adopts THAT copy so a revert and a pull install byte-identical
        #: content — reading the raw subtree here would reintroduce the EOL
        #: divergence the mirror exists to normalize.
        self._realm_id = realm_id
        self._offices: dict[str, Any] = {}
        self._boards: dict[str, Any] = {}
        #: The instance family is ONE document for the whole realm, so it caches
        #: as one entry rather than per container.
        self._instances: tuple[dict[str, Any], str | None] | None = None
        #: So is the canvas projection.
        self._flow_graphs: tuple[dict[str, Any], str | None] | None = None
        #: And the persona-definition projection.
        self._persona_defs: tuple[dict[str, Any], bool] | None = None

    def _office(self, workspace_id: str):
        from .office_sync import _read_remote_office

        if workspace_id not in self._offices:
            office_dir = self._subtree / "store" / "office" / paths.safe_path_token(workspace_id)
            self._offices[workspace_id] = _read_remote_office(office_dir)
        return self._offices[workspace_id]

    def _board(self, board_id: str):
        from .board_sync import _read_remote_board

        if board_id not in self._boards:
            board_dir = self._subtree / "store" / "boards" / paths.safe_path_token(board_id)
            self._boards[board_id] = _read_remote_board(board_dir)
        return self._boards[board_id]

    def _instance(self, instance_id: str) -> tuple[Any, bool]:
        """One instance BODY out of the pulled projection, and whether the
        document itself would not decode.

        The whole family lives in ONE artifact, so ``unreadable`` is a property
        of the document rather than of the row: when the projection will not
        parse, every instance is unreadable and none is absent — and absence is
        what drives the archive arm below."""

        from .persona_instance_sync import read_remote_persona_instances

        if self._instances is None:
            bodies, source = read_remote_persona_instances(self._subtree)
            self._instances = (bodies, source)
        bodies, source = self._instances
        if source == "unreadable":
            return None, True
        return bodies.get(instance_id), False

    def _flow_graph(self, graph_id: str) -> tuple[Any, bool]:
        """One canvas BODY out of the pulled projection, and whether the
        document itself would not decode.

        The instance family's shape exactly, and for the same reason: the whole
        family is ONE artifact, so ``unreadable`` is a property of the document
        rather than of the row. An ABSENT projection is not unreadable — an
        older publisher carries none, and reading that as "the realm dropped
        every drawing" would archive the operator's canvases on a version skew.
        """

        from .flow_graph_sync import read_remote_flow_graphs

        if self._flow_graphs is None:
            self._flow_graphs = read_remote_flow_graphs(self._subtree)
        bodies, source = self._flow_graphs
        if source == "unreadable":
            return None, True
        return bodies.get(graph_id), False

    def _persona_def(self, persona_id: str) -> tuple[Any, bool]:
        """One persona-definition BODY out of the pulled ``store/personas.yaml``
        (or a legacy publisher's raw configs), read by the pull's own reader.

        A projection file that exists and does not parse as one is UNREADABLE,
        never absent — ``read_remote_persona_defs`` falls back to the legacy
        configs in that case, and reading its answer as absence would drop the
        baseline on a read failure."""

        from .persona_config_sync import PROJECTION_RELATIVE_PATH, read_remote_persona_defs

        if self._persona_defs is None:
            defs, _dropped, source = read_remote_persona_defs(self._subtree)
            projection = self._subtree.joinpath(*PROJECTION_RELATIVE_PATH.split("/"))
            self._persona_defs = (defs, projection.is_file() and source != "projection")
        defs, unreadable = self._persona_defs
        if unreadable:
            return None, True
        return defs.get(persona_id), False

    def _skill(self, slug: str) -> tuple[Any, bool]:
        """The inbox package DIRECTORY for one slug, or ``None`` when the realm
        does not carry it.

        Never ``unreadable``: a skill package is a directory of files, not a
        document that parses, so there is no third state between present and
        absent. Its admission door runs in :func:`_revert_one` (the pull's own
        ``refuse_package``, over the same bytes).
        """

        from .skill_promotion import realm_inbox_dir

        if self._skill_root is not None:
            root = self._skill_root
        elif self._realm_id is None:
            return None, False
        else:
            root = realm_inbox_dir(self._realm_id)
        package = root.joinpath(*slug.split("/"))
        return (package if (package / "SKILL.md").is_file() else None), False

    def lookup(self, family: str, container: str, item_key: str) -> tuple[Any, bool]:
        """``(entity_or_None, unreadable)``. ``unreadable`` True means the
        artifact is not decodable HERE, which is never the same answer as
        absent."""

        if family == DRIFT_FAMILY_SKILL:
            return self._skill(item_key)
        if family == DRIFT_FAMILY_PERSONA_DEFINITION:
            return self._persona_def(item_key)
        if family == DRIFT_FAMILY_PERSONA_INSTANCE:
            return self._instance(item_key)
        if family == DRIFT_FAMILY_FLOW_GRAPH:
            return self._flow_graph(item_key)
        if family == DRIFT_FAMILY_OFFICE_SURFACE:
            remote = self._office(container)
            return remote.surface, remote.surface_unreadable
        if family == DRIFT_FAMILY_OFFICE_ACTOR:
            remote = self._office(container)
            actor = remote.actors.get(item_key)
            return actor, actor is None and remote.unreadable > 0
        if family == DRIFT_FAMILY_BOARD:
            remote = self._board(container)
            return remote.board, remote.board_unreadable
        remote = self._board(container)
        card = remote.cards.get(item_key)
        return card, card is None and remote.unreadable > 0


#: Which baseline file records each drift family's rows. The two office
#: families share one; a family not named here is a board row (board, card).
_BASELINE_OF_FAMILY = {
    DRIFT_FAMILY_OFFICE_ACTOR: "office",
    DRIFT_FAMILY_OFFICE_SURFACE: "office",
    DRIFT_FAMILY_PERSONA_INSTANCE: "instances",
    DRIFT_FAMILY_FLOW_GRAPH: "flow_graphs",
    DRIFT_FAMILY_SKILL: "skills",
    DRIFT_FAMILY_PERSONA_DEFINITION: "persona_defs",
}


def _baseline_io() -> dict[str, tuple[Any, Any]]:
    """``{baseline: (read, write)}`` in the order a pass writes them back."""

    from .board_sync import read_board_baseline, write_board_baseline
    from .flow_graph_sync import read_flow_graph_baseline, write_flow_graph_baseline
    from .office_sync import read_office_baseline, write_office_baseline
    from .persona_config_sync import read_persona_config_baseline, write_persona_config_baseline
    from .persona_instance_sync import (
        read_persona_instance_baseline,
        write_persona_instance_baseline,
    )
    from .skill_sync import read_skill_baseline, write_skill_baseline

    return {
        "office": (read_office_baseline, write_office_baseline),
        "board": (read_board_baseline, write_board_baseline),
        "instances": (read_persona_instance_baseline, write_persona_instance_baseline),
        "flow_graphs": (read_flow_graph_baseline, write_flow_graph_baseline),
        "skills": (read_skill_baseline, write_skill_baseline),
        "persona_defs": (read_persona_config_baseline, write_persona_config_baseline),
    }


class _Baselines:
    """The per-family baselines one revert pass realigns: read once, edited in
    memory per item, and written back only for the families a pass APPLIED to.

    The baselines are realigned the way the publish/pull lanes maintain them —
    PER ITEM and from the store's own post-write content, never by re-recording
    the whole workspace. Re-recording would zero the drift of every row the
    operator did NOT select, which is exactly the lie this accounting exists to
    prevent.
    """

    def __init__(self, realm_id: str) -> None:
        self._realm_id = realm_id
        self._io = _baseline_io()
        self._maps = {name: read(realm_id) for name, (read, _write) in self._io.items()}
        self._touched: set[str] = set()

    def for_family(self, family: str) -> dict[str, str]:
        return self._maps[_BASELINE_OF_FAMILY.get(family, "board")]

    def mark_applied(self, family: str) -> None:
        self._touched.add(_BASELINE_OF_FAMILY.get(family, "board"))

    def write_touched(self) -> None:
        for name, (_read, write) in self._io.items():
            if name in self._touched:
                write(self._realm_id, self._maps[name])


def _check_selection(requested: list[str], *, revert_all: bool) -> None:
    if revert_all and requested:
        raise RealmSyncError(
            "invalid_request", "Pass --all or --item, never both — the selection must be unambiguous."
        )
    if not revert_all and not requested:
        raise RealmSyncError(
            "invalid_request", "Nothing selected: pass --all, or at least one --item FAMILY:CONTAINER:KEY."
        )


def _require_pulled_subtree(realm) -> tuple[Path, Path]:
    """The local sync repo and this realm's subtree in it, or a refusal.

    The refusal is deliberately BEFORE any selection work, and it covers the
    missing SUBTREE as well as the missing clone. Without the subtree every
    item would read as "upstream does not have this", and the ``added`` arm
    would then archive the operator's whole local office on the strength of a
    directory that was never cloned.
    """

    repo = _sync_repo_path(realm)
    subtree = _realm_subtree(repo, realm.id)
    if not repo.exists():
        raise RealmSyncError(
            "sync_repo_missing",
            "The realm sync repo is not present locally; pull before reverting.",
            safe_details={"missing": "sync_repo", "sync_repo": _safe_display_path(repo)},
        )
    if not subtree.exists():
        raise RealmSyncError(
            "sync_repo_missing",
            "This realm has no pulled subtree in the local sync repo; pull before reverting.",
            safe_details={"missing": "realm_subtree", "sync_repo": _safe_display_path(repo)},
        )
    return repo, subtree


def _select_items(
    drift: list[StoreDriftItem], requested: list[str], *, revert_all: bool
) -> tuple[list[StoreDriftItem], list[RevertRow]]:
    """The drift rows a pass will revert, plus a refused row per ``--item``
    that names nothing in the drift set."""

    if revert_all:
        return list(drift), []
    by_spec = {item.spec: item for item in drift}
    selected: list[StoreDriftItem] = []
    rows: list[RevertRow] = []
    for raw in requested:
        family, container, item_key = parse_item_spec(raw)
        item = by_spec.get(f"{family}:{container}:{item_key}")
        if item is None:
            rows.append(
                RevertRow(
                    family=family,
                    container=container,
                    item_key=item_key,
                    kind=None,
                    outcome=REFUSED_UNKNOWN_ITEM,
                    detail="not_in_drift_set",
                )
            )
            continue
        selected.append(item)
    return selected, rows


def revert_realm_sync(
    realm_id: str,
    *,
    item_specs: list[str] | None = None,
    revert_all: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Revert the selected drifted store rows to the last-pulled upstream.

    Local-only and credential-free by construction: the only thing read from
    outside the store is the checked-out subtree already on disk.
    """

    from .board_store import BoardStore
    from .office_store import OfficeStore

    requested = [spec for spec in (item_specs or []) if str(spec).strip()]
    _check_selection(requested, revert_all=revert_all)

    realm = RealmStore().get(realm_id)
    repo, subtree = _require_pulled_subtree(realm)

    workspaces = _workspaces_for_realm(realm)
    selected, rows = _select_items(
        store_drift_items(realm.id, workspaces), requested, revert_all=revert_all
    )

    upstream = _Upstream(subtree, realm_id=realm.id)
    office_store = OfficeStore()
    board_store = BoardStore()
    baselines = _Baselines(realm.id)

    for item in sorted(selected, key=lambda row: (_PROCESS_ORDER[row.family], row.family, row.container, row.item_key)):
        row = _revert_one(
            item,
            upstream=upstream,
            office_store=office_store,
            board_store=board_store,
            baselines=baselines,
            realm_id=realm.id,
            dry_run=dry_run,
        )
        rows.append(row)
        if row.applied:
            baselines.mark_applied(item.family)

    applied = [row for row in rows if row.applied]
    if not dry_run:
        baselines.write_touched()
        if applied:
            _append_realm_sync_event(
                REVERT_EVENT_TYPE, realm, changed=True, artifacts=len(applied)
            )

    return {
        "id": realm.id,
        "realm_id": realm.id,
        "dry_run": bool(dry_run),
        "selection": "all" if revert_all else "items",
        "count": len(rows),
        "reverted": len(applied),
        "refused": len(rows) - len(applied),
        "items": [row.as_dict() for row in rows],
        # Measured AFTER the pass. On ``--dry-run`` nothing was applied, so this
        # is the unchanged current drift — ``dry_run`` above is what says which.
        "store_drift_after": {
            "boards": _board_store_drift(realm.id, workspaces),
            "office": _office_store_drift(realm.id, workspaces),
        },
        "sync_repo": _safe_display_path(repo),
    }


def _revert_one(
    item: StoreDriftItem,
    *,
    upstream: _Upstream,
    office_store,
    board_store,
    baselines: _Baselines,
    realm_id: str | None = None,
    dry_run: bool,
) -> RevertRow:
    """One item, decided purely and then applied. Every store refusal is caught
    HERE and reported as a row: a realm must not stop converging because one
    file would not archive (the pull's per-entity isolation rule)."""

    entity, unreadable = upstream.lookup(item.family, item.container, item.item_key)
    row = RevertRow(
        family=item.family,
        container=item.container,
        item_key=item.item_key,
        kind=item.kind,
        outcome=REFUSED_UNREADABLE_UPSTREAM,
    )
    if unreadable:
        row.detail = "subtree_artifact_unreadable"
        return row

    decision = classify_revert(
        family=item.family, kind=item.kind, upstream_present=entity is not None
    )
    row.outcome = decision.outcome
    if decision.action is RevertAction.REFUSE:
        row.detail = "no_subtree_artifact"
        return row

    baseline = baselines.for_family(item.family)
    key = item.baseline_key()
    if decision.action is RevertAction.DROP_BASELINE:
        if not dry_run:
            baseline.pop(key, None)
        return row

    if decision.action in (RevertAction.ADOPT, RevertAction.RESTORE):
        refusal = _admission_refusal(item, entity, key)
        if refusal is not None:
            row.outcome = REFUSED_ADMISSION
            row.detail = refusal.code
            return row

    if dry_run:
        return row

    try:
        _apply_revert(
            item, entity, decision.action,
            office_store=office_store, board_store=board_store, realm_id=realm_id,
        )
    except _SkillWriteRefused as exc:
        row.outcome = REFUSED_STORE_ERROR
        row.detail = exc.code
        return row
    except Exception as exc:  # noqa: BLE001 — accounted, never silent; the pass continues
        row.outcome = REFUSED_STORE_ERROR
        row.detail = type(exc).__name__
        return row

    _realign_baseline(
        item, decision.action, baseline, key, row,
        office_store=office_store, board_store=board_store,
    )
    return row


def _refuse_persona_instance_door(item_key: str, entity):
    from .persona_instance_sync import refuse_persona_instance

    return refuse_persona_instance(item_key, entity)


def _refuse_flow_graph_door(item_key: str, entity):
    # The canvas family's door is ``parse_flow_graph_doc`` and ONLY that,
    # because that is the only door ``apply_flow_graph_pull`` holds. Adding the
    # shared ``refuse_entity`` scan here would make a revert stricter than the
    # pull for the same bytes — the operator would be refused a drawing that
    # already landed on this machine through the pull, which is a worse lie
    # than either door alone.
    return _refuse_flow_graph(entity)


def _refuse_skill_door(item_key: str, entity):
    # The skill family's door is ``refuse_package`` over the package DIRECTORY
    # — the exact door ``apply_skill_inbox_pull`` holds, for the canvas family's
    # reason: the same bytes must not be admissible through a pull and refused
    # through a revert. ``refuse_entity`` is not usable here at all; a package
    # is a tree of files, not a JSON-able entity.
    from .sync_admission import refuse_package

    return refuse_package(item_key, entity)


def _refuse_persona_def_door(item_key: str, entity):
    # The pull's own per-definition door, for the canvas family's reason: the
    # same bytes must be admissible through a pull and a revert alike.
    from .persona_config_sync import persona_def_admission_refusal

    return persona_def_admission_refusal(item_key, entity)


#: The family's OWN admission door, where the pull holds one. A family not
#: named here passes the shared ``refuse_entity`` scan.
_ADMISSION_DOORS = {
    DRIFT_FAMILY_PERSONA_INSTANCE: _refuse_persona_instance_door,
    DRIFT_FAMILY_FLOW_GRAPH: _refuse_flow_graph_door,
    DRIFT_FAMILY_SKILL: _refuse_skill_door,
    DRIFT_FAMILY_PERSONA_DEFINITION: _refuse_persona_def_door,
}


def _admission_refusal(item: StoreDriftItem, entity, key: str):
    """The same door every pulled payload passes.

    A revert adopts bytes this machine did not author, so it inherits the
    pull's trust boundary rather than opening a second one beside it — and for
    a family with its own door (the instance family's allowlist totality,
    canonical-id and steering-shape refusals) that means the FAMILY's door, not
    just the shared scan, or a revert would admit a body its own pull would
    have turned away.
    """

    door = _ADMISSION_DOORS.get(item.family)
    if door is not None:
        return door(item.item_key, entity)
    from .sync_admission import refuse_entity

    return refuse_entity(key, payload=to_jsonable(entity))


def _apply_revert(
    item: StoreDriftItem, entity, action: RevertAction, *, office_store, board_store, realm_id: str | None
) -> None:
    """The one store write a decided revert makes. Raises; the caller accounts."""

    if item.family == DRIFT_FAMILY_PERSONA_DEFINITION:
        # ONE arm: RESTORE never arises (the family has no ``removed`` rows)
        # and ARCHIVE_LOCAL is refused by the table, so this is the adopt —
        # the pull's own door, which writes the record through
        # ``AgentStore.save`` and never deletes a persona.
        from .persona_config_sync import adopt_persona_def

        adopt_persona_def(item.item_key, entity)
    elif item.family == DRIFT_FAMILY_SKILL:
        # ONE arm for this family: RESTORE and ADOPT are the same install
        # (the canonical slot is empty for a ``removed`` row and occupied for
        # a ``changed`` one, and the guarded door decides which), so splitting
        # them across the two helpers below would be two spellings of one
        # write.
        if action is RevertAction.ARCHIVE_LOCAL:
            _archive_local_skill(item)
        else:
            _install_skill_from_inbox(item, entity, realm_id=realm_id)
    elif action is RevertAction.RESTORE:
        _restore_from_upstream(
            item, entity, office_store=office_store, board_store=board_store, realm_id=realm_id
        )
    elif action is RevertAction.ADOPT:
        _adopt_from_upstream(
            item, entity, office_store=office_store, board_store=board_store, realm_id=realm_id
        )
    else:  # ARCHIVE_LOCAL
        _archive_local_only(item, office_store=office_store, board_store=board_store)


def _realign_baseline(
    item: StoreDriftItem,
    action: RevertAction,
    baseline: dict[str, str],
    key: str,
    row: RevertRow,
    *,
    office_store,
    board_store,
) -> None:
    """Record the applied row's post-write content as its new baseline."""

    if action is RevertAction.ARCHIVE_LOCAL:
        # A local-only row has no baseline entry by definition; ``pop`` states
        # that rather than assuming it.
        baseline.pop(key, None)
        return
    try:
        baseline[key] = _current_content_hash(item, office_store=office_store, board_store=board_store)
    except Exception as exc:  # noqa: BLE001 — the write landed; the receipt did not
        # The write happened, so the row is NOT reported as refused — but a
        # baseline entry that cannot be re-read is left absent rather than
        # guessed, which reclassifies the row as locally added on the next
        # status. Honest, and repairable by a publish.
        baseline.pop(key, None)
        row.detail = f"baseline_unrecorded:{type(exc).__name__}"
