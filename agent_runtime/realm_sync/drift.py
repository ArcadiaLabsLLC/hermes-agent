"""Local store drift against the never-synced baselines, itemized per row.

``store_drift_items`` is the one walk; every count the status envelope carries is
DERIVED from its rows, so a counted change is a change the revert lane can address.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from agent_runtime.profile_home import get_shared_skills_dir

from .. import paths
from ..models import Workspace
from ..store import RealmStore, skill_tombstoned
from .families import SyncFamily
from .publish_scans import _office_publish_scan
from .artifacts import (
    _flow_graph_projection,
    _iter_publishable_skill_packages,
    publishable_skill_packages,
)

__layer__ = "stores"
__all__ = [
    "DRIFT_FAMILY_BOARD",
    "DRIFT_FAMILY_BOARD_CARD",
    "DRIFT_FAMILY_FLOW_GRAPH",
    "DRIFT_FAMILY_OFFICE_ACTOR",
    "DRIFT_FAMILY_OFFICE_SURFACE",
    "DRIFT_FAMILY_PERSONA_INSTANCE",
    "DRIFT_FAMILY_SKILL",
    "DRIFT_KEY_BOARD_DEF",
    "DRIFT_KEY_OFFICE_SURFACE",
    "DRIFT_KIND_ADDED",
    "DRIFT_KIND_CHANGED",
    "DRIFT_KIND_REMOVED",
    "DRIFT_WALKS",
    "StoreDriftItem",
    "_BASELINE_KEY_OF",
    "_BOARD_DRIFT_COUNTS",
    "_FLOW_GRAPH_DRIFT_COUNTS",
    "_OFFICE_DRIFT_COUNTS",
    "_PERSONA_INSTANCE_DRIFT_COUNTS",
    "_SKILL_DRIFT_COUNTS",
    "_any_store_drift",
    "_board_baseline_key",
    "_board_card_baseline_key",
    "_board_store_drift",
    "_board_store_drift_items",
    "_drift_counts",
    "_flow_graph_drift_key",
    "_flow_graph_store_drift_items",
    "_office_actor_baseline_key",
    "_office_store_drift",
    "_office_store_drift_items",
    "_office_surface_baseline_key",
    "_persona_instance_drift_key",
    "_persona_instance_store_drift_items",
    "_skill_drift_key",
    "_skill_drift_walk",
    "_skill_store_drift_items",
    "store_drift_items",
]


#: The itemizable store-drift families — members of the ONE sync vocabulary,
#: ``families.SyncFamily``; these names are import-compatibility aliases for
#: ``realm_revert`` and its tests (each IS the member), and nothing in this
#: package reads them. A family is the pair (store, row granularity) — never the
#: layer — because it is what a per-item revert has to address:
#: ``board``/``office_surface`` are the CONTAINER definitions,
#: ``board_card``/``office_actor`` the rows inside them.
DRIFT_FAMILY_BOARD = SyncFamily.BOARD
DRIFT_FAMILY_BOARD_CARD = SyncFamily.BOARD_CARD
DRIFT_FAMILY_OFFICE_SURFACE = SyncFamily.OFFICE_SURFACE
DRIFT_FAMILY_OFFICE_ACTOR = SyncFamily.OFFICE_ACTOR
#: The replicated persona-INSTANCE family (instance-replication plan H4). Rows
#: here are the AGENTS behind the desks, not the desks: an actor and its
#: instance drift independently (an operator can rename an agent without moving
#: its desk), so folding the two into one family would let one row's publish
#: silently speak for the other's.
DRIFT_FAMILY_PERSONA_INSTANCE = SyncFamily.PERSONA_INSTANCE
#: The replicated CANVAS family (canvas-replication plan w13/h2). Joined the
#: drift set on 2026-09-05, in the same change as its revert arm — w14/h2
#: deliberately shipped the counts as a top-level ``flow_graphs`` key first,
#: because ``realm_revert`` subscripts ``_PROCESS_ORDER[row.family]`` and a
#: drift row with no revert arm offers the operator an exit that does not exist.
#: The arm exists now, so the rows do.
DRIFT_FAMILY_FLOW_GRAPH = SyncFamily.FLOW_GRAPH
#: The SKILL PACKAGE family (2026-09-12, held-skill-publish-direction §4.5). The
#: LAST synced family to get drift rows, and the reason is the reason it had no
#: baseline: with no never-synced baseline there was nothing to compare a local
#: package against, so an operator who edited a skill got "In sync" from the sheet
#: while their canonical copy differed from what the realm carries — and no revert
#: row, because a row the revert lane cannot address is an exit that does not
#: exist. The container is EMPTY: a skill package is held by the shared skills
#: root, which is one per machine and not a realm-scoped container, so the row's
#: own spec is ``skill::<slug>`` (``parse_item_spec`` accepts a blank container —
#: see its docstring).
DRIFT_FAMILY_SKILL = SyncFamily.SKILL

DRIFT_KIND_ADDED = "added"
DRIFT_KIND_CHANGED = "changed"
DRIFT_KIND_REMOVED = "removed"

#: The item_key a CONTAINER definition row carries. The container itself is
#: already named by ``container``, so this is the same suffix its baseline key
#: has always used (``<board_id>:board`` / ``<workspace_id>:office``) rather
#: than a second spelling invented for the wire.
DRIFT_KEY_BOARD_DEF = "board"
DRIFT_KEY_OFFICE_SURFACE = "office"


@dataclass(frozen=True, slots=True)
class StoreDriftItem:
    """ONE drifted store row, and the only thing the counts are made of.

    The counts below used to be four ``+= 1`` accumulators inside the walk, so
    the sheet could say "1 actor removed" and nothing in the runtime could say
    WHICH — the operator's only exit from unpublished changes was Publish, for
    an item the product would not name (measured 2026-08-31 on the Mac store:
    ``offices_changed 1, actors_removed 1``). Itemizing first and deriving the
    counts keeps ONE walk and ONE authority: a row that is counted is a row that
    can be reverted, by construction rather than by two loops agreeing.
    """

    family: str
    container: str  # workspace_id (office families) or board_id (board families)
    item_key: str
    kind: str  # added | changed | removed

    def as_dict(self) -> dict[str, str]:
        return {
            "family": self.family,
            "container": self.container,
            "item_key": self.item_key,
            "kind": self.kind,
        }

    @property
    def spec(self) -> str:
        """The ``FAMILY:CONTAINER:KEY`` token ``realm sync revert --item`` takes."""

        return f"{self.family}:{self.container}:{self.item_key}"

    def baseline_key(self) -> str:
        """This row's key in its family's baseline sidecar.

        Delegated to the sidecar owners' own key helpers rather than respelled:
        the revert lane realigns these exact entries, and a second spelling of a
        key is free to disagree with the first.
        """

        return _BASELINE_KEY_OF.get(self.family, _office_actor_baseline_key)(self)



def _board_baseline_key(item: StoreDriftItem) -> str:
    from ..board_sync import _board_key

    return _board_key(item.container)


def _board_card_baseline_key(item: StoreDriftItem) -> str:
    from ..board_sync import _card_key

    return _card_key(item.container, item.item_key)


def _office_surface_baseline_key(item: StoreDriftItem) -> str:
    from ..office_sync import _surface_key

    return _surface_key(item.container)


def _office_actor_baseline_key(item: StoreDriftItem) -> str:
    from ..office_sync import _actor_key

    return _actor_key(item.container, item.item_key)


def _persona_instance_drift_key(item: StoreDriftItem) -> str:
    from ..persona_instance_sync import instance_baseline_key

    # Keyed on the id ALONE, with no container in it, and that is the Option A
    # ruling showing through: one shared instance id realm-wide means the id is
    # already unique across every workspace, so a workspace-qualified key would
    # be a second spelling of an identity that has only one.
    return instance_baseline_key(item.item_key)


def _skill_drift_key(item: StoreDriftItem) -> str:
    from ..skill_sync import skill_baseline_key

    # The slug alone, for the flow-graph family's reason one step further: a
    # skill slug is unique in the ONE shared skills root, so there is no
    # container to qualify it with.
    return skill_baseline_key(item.item_key)


def _flow_graph_drift_key(item: StoreDriftItem) -> str:
    from ..flow_graph_sync import flow_graph_baseline_key

    # Same reasoning as the instance family's, one step further along: graph
    # identity IS the owner instance's id (``runtime:<id>``), so the key is
    # already realm-unique and the container is display and scoping only.
    return flow_graph_baseline_key(item.item_key)


#: Which baseline-sidecar key a drift row realigns, per family (rule 12's table
#: for the ladder ``baseline_key`` used to be). A family missing here is keyed
#: as an office actor, which is what the ladder's last arm did.
_BASELINE_KEY_OF: Final[Mapping[str, Callable[[StoreDriftItem], str]]] = {
    SyncFamily.BOARD: _board_baseline_key,
    SyncFamily.BOARD_CARD: _board_card_baseline_key,
    SyncFamily.OFFICE_SURFACE: _office_surface_baseline_key,
    SyncFamily.OFFICE_ACTOR: _office_actor_baseline_key,
    SyncFamily.PERSONA_INSTANCE: _persona_instance_drift_key,
    SyncFamily.SKILL: _skill_drift_key,
    SyncFamily.FLOW_GRAPH: _flow_graph_drift_key,
}

#: (count name, family, kind or None for "every row of this family"). The
#: existing four-key count shapes are DERIVED through these tables — the
#: launcher parses them today, so they are additive-only contracts.
_BOARD_DRIFT_COUNTS = (
    ("boards_changed", SyncFamily.BOARD, None),
    ("cards_changed", SyncFamily.BOARD_CARD, DRIFT_KIND_CHANGED),
    ("cards_added", SyncFamily.BOARD_CARD, DRIFT_KIND_ADDED),
    ("cards_removed", SyncFamily.BOARD_CARD, DRIFT_KIND_REMOVED),
)
_OFFICE_DRIFT_COUNTS = (
    ("offices_changed", SyncFamily.OFFICE_SURFACE, None),
    ("actors_changed", SyncFamily.OFFICE_ACTOR, DRIFT_KIND_CHANGED),
    ("actors_added", SyncFamily.OFFICE_ACTOR, DRIFT_KIND_ADDED),
    ("actors_removed", SyncFamily.OFFICE_ACTOR, DRIFT_KIND_REMOVED),
)
#: The instance family's counts. A NEW key group under ``store_drift``, additive
#: like the ``items`` list beside it: a launcher that does not read it is
#: unaffected, and one that does can finally say WHICH agent is unpublished
#: rather than only that a desk is.
_PERSONA_INSTANCE_DRIFT_COUNTS = (
    ("instances_changed", SyncFamily.PERSONA_INSTANCE, DRIFT_KIND_CHANGED),
    ("instances_added", SyncFamily.PERSONA_INSTANCE, DRIFT_KIND_ADDED),
    ("instances_removed", SyncFamily.PERSONA_INSTANCE, DRIFT_KIND_REMOVED),
)
#: The canvas family's counts, additive beside the instance family's and shaped
#: identically. The top-level ``flow_graphs`` row keeps its own ``unpublished``
#: number and the two are NOT the same total: ``unpublished`` counts drawings
#: this machine holds that the realm has not seen, so it equals
#: ``canvases_added + canvases_changed`` and says nothing about
#: ``canvases_removed`` — a graph that was reaped here still has a baseline
#: entry and nothing left to publish. One walk, two questions.
_FLOW_GRAPH_DRIFT_COUNTS = (
    ("canvases_changed", SyncFamily.FLOW_GRAPH, DRIFT_KIND_CHANGED),
    ("canvases_added", SyncFamily.FLOW_GRAPH, DRIFT_KIND_ADDED),
    ("canvases_removed", SyncFamily.FLOW_GRAPH, DRIFT_KIND_REMOVED),
)
#: The skill family's counts, shaped like every family above it. ``_any_store_drift``
#: sums every count dict it finds under ``store_drift``, so adding this group is
#: what makes a locally-edited skill light ``unpublished_changes`` — the operator's
#: "I have changes I can push" — instead of the sheet reading "In sync" over a
#: canonical package that differs from the realm's.
_SKILL_DRIFT_COUNTS = (
    ("skills_changed", SyncFamily.SKILL, DRIFT_KIND_CHANGED),
    ("skills_added", SyncFamily.SKILL, DRIFT_KIND_ADDED),
    ("skills_removed", SyncFamily.SKILL, DRIFT_KIND_REMOVED),
)


def _drift_counts(
    items: list[StoreDriftItem], spec: tuple[tuple[str, str, str | None], ...]
) -> dict[str, int]:
    """The counts, DERIVED from the rows. Every row of a family lands in exactly
    one counter and every counter counts rows, so ``any count > 0`` and
    ``items != []`` cannot disagree."""

    return {
        name: sum(
            1
            for item in items
            if item.family == family and (kind is None or item.kind == kind)
        )
        for name, family, kind in spec
    }


def store_drift_items(realm_id: str, workspaces: list[Workspace]) -> list[StoreDriftItem]:
    """Every drifted store row for this realm, board families first."""

    return [item for walk in DRIFT_WALKS for item in walk(realm_id, workspaces)]


def _skill_store_drift_items(realm_id: str) -> list[StoreDriftItem]:
    """The SKILL half of the drift walk (held-skill-publish-direction §4.5).

    Scoped exactly as the publish is — ``publishable_skill_packages(realm)``, the
    same iteration and the same two filters — so a row can never name a package
    this realm would not ship. It takes no ``workspaces``: a skill package belongs
    to the machine's ONE shared skills root, not to a workspace, which is also why
    every row's container is blank.

    Three facts per slug: the canonical package's sync hash (``local``), the
    baseline sidecar's entry, and the realm's copy in the inbox mirror
    (``inbox``). The rows, and what each one deliberately is NOT:

    * ``changed`` — baselined, local moved, and the realm's copy did NOT
      (``inbox`` absent or equal to the baseline). My unpublished edit: Publish
      ships it, Revert adopts the realm's copy back over it.
    * ``added`` — no baseline and no inbox copy: a package this realm has never
      carried. Revert archives it (never deletes).
    * ``removed`` — baselined, and no local package at all. Revert reinstalls from
      the inbox, or drops the stale entry when the inbox has nothing.
    * **both moved → NO ROW.** That is the held card's, and a drift row beside it
      would offer Publish as an exit from a conflict — overwriting the realm's
      copy with mine, which is the one thing the hold exists to prevent. The
      operator's exit there is ``realm sync resolve``, and after it the package
      appears here as ``changed`` (``--take local``) or not at all
      (``--take remote``).
    * no baseline but an inbox copy that EQUALS local → no row: converged, and a
      pull will record the baseline.

    A tombstoned slug produces nothing, by ``publishable_skill_packages`` for the
    live rows and by an explicit ledger check for the ``removed`` arm: the delete
    lane archived that package on purpose, and reporting it as locally removed
    would offer a revert that reinstalls what a member deleted realm-wide.
    """

    from ..skill_promotion import (
        _iter_packages,
        realm_inbox_dir,
        skill_package_sync_hash,
    )
    from ..skill_sync import read_skill_baseline, skill_baseline_key, split_skill_baseline_key

    realm = RealmStore().get(realm_id)
    baseline = read_skill_baseline(realm_id)
    inbox_hashes = {
        slug: skill_package_sync_hash(package_dir)
        for slug, package_dir in _iter_packages(realm_inbox_dir(realm_id))
    }
    # "No local package" is asked of the WHOLE canonical root, not of the
    # publishable subset: a package that exists locally but is de-selected has not
    # been removed, and calling it ``removed`` would offer a revert that reinstalls
    # a package already on disk.
    root = get_shared_skills_dir()
    local_slugs = (
        {slug for slug, _dir in _iter_publishable_skill_packages(root)} if root.is_dir() else set()
    )

    def _row(slug: str, kind: str) -> StoreDriftItem:
        return StoreDriftItem(
            family=SyncFamily.SKILL, container="", item_key=slug, kind=kind
        )

    items: list[StoreDriftItem] = []
    for slug, package_dir in publishable_skill_packages(realm):
        local_hash = skill_package_sync_hash(package_dir)
        base_hash = baseline.get(skill_baseline_key(slug))
        inbox_hash = inbox_hashes.get(slug)
        if base_hash is None:
            if inbox_hash is None:
                items.append(_row(slug, DRIFT_KIND_ADDED))
            continue
        if local_hash == base_hash:
            continue
        if inbox_hash is None or inbox_hash == base_hash:
            items.append(_row(slug, DRIFT_KIND_CHANGED))
    for key in sorted(baseline):
        slug = split_skill_baseline_key(key)
        if slug is None or slug in local_slugs:
            continue
        if skill_tombstoned(realm, slug) is not None:
            continue
        items.append(_row(slug, DRIFT_KIND_REMOVED))
    return items


def _flow_graph_store_drift_items(
    realm_id: str, workspaces: list[Workspace]
) -> list[StoreDriftItem]:
    """The CANVAS half of the drift walk (canvas-replication w13/h2, revert arm).

    Scoped exactly as the publish is — ``_office_publish_scan(workspaces)
    .instance_ids``, the desks this realm ships — and resolved through
    :func:`_flow_graph_projection`, so the hash compared here is the same
    projected body the publish would have written. A second walk of the graph
    directory would report drawings this realm does not publish, and offer a
    revert whose upstream could never exist.

    Two guards, both the sibling families':

    * a canvas the projection REFUSES (unreadable, no ``graph_id``, an owner
      mismatch) contributes no row. It is already named on the top-level
      ``flow_graphs.unreadable`` list, and a drift row would offer a revert that
      reads a file this machine cannot project.
    * ``removed`` is a baselined graph id with no live canvas behind it — a
      drawing that was reaped or archived here.

    **The container is the OWNER INSTANCE id, not the workspace.** Every other
    family's container is the thing that holds the row (a workspace, a board),
    and for a canvas that is the desk — whose identity in this family IS the
    owner instance id, since graph identity is derived from it
    (``runtime_<instance id>``). It is derived from the graph id itself, so it is
    never blank — which is why the workspace was rejected: a ``removed`` row's
    desk is gone, so its workspace cannot be looked up, and the container would
    have gone blank on exactly the rows an operator most wants to revert.
    (Until 2026-09-06 that also made the row unaddressable, because
    ``parse_item_spec`` refused a blank container; it now accepts one — see that
    function — so this is a naming property, no longer a reachability one.)
    """

    from ..flow_graph import owner_instance_id_of
    from ..flow_graph_sync import flow_graph_baseline_key, read_flow_graph_baseline

    scan = _office_publish_scan(workspaces)
    projection = _flow_graph_projection(scan.instance_ids)
    baseline = read_flow_graph_baseline(realm_id)
    prefix = flow_graph_baseline_key("")
    baselined_ids = {key[len(prefix):] for key in baseline if key.startswith(prefix)}

    def _row(graph_id: str, kind: str) -> StoreDriftItem:
        return StoreDriftItem(
            family=SyncFamily.FLOW_GRAPH,
            container=owner_instance_id_of(graph_id),
            item_key=graph_id,
            kind=kind,
        )

    items: list[StoreDriftItem] = []
    current_ids: set[str] = set()
    for graph_id, body_hash in sorted(projection.hashes().items()):
        current_ids.add(graph_id)
        base_hash = baseline.get(flow_graph_baseline_key(graph_id))
        if base_hash is None:
            items.append(_row(graph_id, DRIFT_KIND_ADDED))
        elif base_hash != body_hash:
            items.append(_row(graph_id, DRIFT_KIND_CHANGED))
    for graph_id in sorted(baselined_ids - current_ids):
        items.append(_row(graph_id, DRIFT_KIND_REMOVED))
    return items


def _persona_instance_store_drift_items(
    realm_id: str, workspaces: list[Workspace]
) -> list[StoreDriftItem]:
    """The replicated-agent half of the drift walk (instance-replication H4).

    Scoped exactly as the mint is: PLACEMENT-BACKED rows whose ``workspace_id``
    belongs to this realm. Canonical channels are excluded, because every member
    derives its own — reporting one as ``added`` would offer the operator a
    publish that the pull door on the other end refuses by design.

    Two under-count guards, both the office family's, both preferring silence to
    a delete-shaped lie:

    * a store whose rows do not fully READ (``scan.unreadable``) contributes NO
      accounting at all. Spending only the rows would hand back a short list, and
      the baseline diff would then report N removals for agents whose files
      merely would not open here.
    * a REPLICA is not drift. That is the baseline-alignment property doing its
      job rather than a special case: the mint recorded the remote hash, so a
      fresh replica's projection equals its baseline entry and the walk below
      simply does not produce a row for it.
    """

    from ..persona_assignments import PersonaInstanceStore, is_canonical_persona_channel
    from ..persona_instance_sync import (
        instance_baseline_key,
        persona_instance_def_hash,
        project_persona_instance,
        read_persona_instance_baseline,
    )

    baseline = read_persona_instance_baseline(realm_id)
    try:
        scan = PersonaInstanceStore().scan_all()
    except Exception:  # noqa: BLE001 — an unreadable listing is not evidence of removal
        return []
    if scan.unreadable:
        return []

    workspace_ids = {ws.id for ws in workspaces}
    prefix = instance_baseline_key("")
    baselined_ids = {key[len(prefix):] for key in baseline if key.startswith(prefix)}
    items: list[StoreDriftItem] = []
    current_ids: set[str] = set()
    by_id = {instance.id: instance for instance in scan.instances}

    for instance in scan.instances:
        if is_canonical_persona_channel(instance):
            continue
        if instance.workspace_id not in workspace_ids:
            continue
        current_ids.add(instance.id)
        base_hash = baseline.get(instance_baseline_key(instance.id))
        body_hash = persona_instance_def_hash(project_persona_instance(instance))
        if base_hash is None:
            kind = DRIFT_KIND_ADDED
        elif base_hash != body_hash:
            kind = DRIFT_KIND_CHANGED
        else:
            continue
        items.append(
            StoreDriftItem(
                family=SyncFamily.PERSONA_INSTANCE,
                container=str(instance.workspace_id or ""),
                item_key=instance.id,
                kind=kind,
            )
        )
    for instance_id in sorted(baselined_ids - current_ids):
        # A baselined agent that is no longer live here: retired, or moved out of
        # this realm's workspaces. ``container`` comes from the row when there
        # still is one, and is empty when there is not — a guess would be worse
        # than a blank, since the revert lane addresses this family by ID.
        # The blank is ADDRESSABLE since 2026-09-06: ``parse_item_spec`` takes
        # ``persona_instance::<id>``, this row's own ``spec`` echoed back, so a
        # removal is no longer reachable only through ``--all`` (w17/hb's row).
        record = by_id.get(instance_id)
        items.append(
            StoreDriftItem(
                family=SyncFamily.PERSONA_INSTANCE,
                container=str(getattr(record, "workspace_id", "") or ""),
                item_key=instance_id,
                kind=DRIFT_KIND_REMOVED,
            )
        )
    return items


def _board_store_drift_items(realm_id: str, workspaces: list[Workspace]) -> list[StoreDriftItem]:
    """The per-row half of :func:`_board_store_drift` — see that docstring for
    the semantics; this function IS the walk it counts."""

    from .. import board_models
    from ..board_store import BoardStore
    from ..board_sync import read_board_baseline

    workspace_ids = {ws.id for ws in workspaces}
    baseline = read_board_baseline(realm_id)
    store = BoardStore()
    items: list[StoreDriftItem] = []
    for board in store.list_all():
        if board.workspace_id not in workspace_ids:
            continue
        board_base = baseline.get(f"{board.board_id}:board")
        if board_base != board_models.board_content_hash(board):
            items.append(
                StoreDriftItem(
                    family=SyncFamily.BOARD,
                    container=board.board_id,
                    item_key=DRIFT_KEY_BOARD_DEF,
                    kind=DRIFT_KIND_CHANGED if board_base is not None else DRIFT_KIND_ADDED,
                )
            )
        card_prefix = f"{board.board_id}:card:"
        baseline_card_ids = {key[len(card_prefix):] for key in baseline if key.startswith(card_prefix)}
        current_card_ids: set[str] = set()
        for card in store.list_cards(board.board_id):
            current_card_ids.add(card.card_id)
            base_hash = baseline.get(f"{card_prefix}{card.card_id}")
            if base_hash is None:
                kind = DRIFT_KIND_ADDED
            elif base_hash != board_models.board_content_hash(card):
                kind = DRIFT_KIND_CHANGED
            else:
                continue
            items.append(
                StoreDriftItem(
                    family=SyncFamily.BOARD_CARD,
                    container=board.board_id,
                    item_key=card.card_id,
                    kind=kind,
                )
            )
        for card_id in sorted(baseline_card_ids - current_card_ids):
            items.append(
                StoreDriftItem(
                    family=SyncFamily.BOARD_CARD,
                    container=board.board_id,
                    item_key=card_id,
                    kind=DRIFT_KIND_REMOVED,
                )
            )
    return items


def _board_store_drift(realm_id: str, workspaces: list[Workspace]) -> dict[str, int]:
    """Board content drift vs the never-synced baseline sidecar, for boards whose
    ``workspace_id`` belongs to this realm's workspaces.

    Compares CURRENT ``BoardStore`` semantic content hashes (``board_content_hash``
    — revision/timestamps excluded) against ``read_board_baseline(realm_id)``: the
    exact hash/baseline machinery the publish and pull lanes already use. A
    missing/empty baseline on a server-bound realm means nothing has been
    published yet, so every board+card counts as unpublished — that is honest.

    Pure and read-only: no git, no network, no new merge rules (office plan §10
    simplicity budget). ``boards_changed`` counts board defs whose hash drifted;
    ``cards_changed`` counts active cards whose hash drifted from a known
    baseline; ``cards_added`` counts active cards with no baseline entry; and
    ``cards_removed`` counts baseline cards no longer active locally (archived /
    deleted since the last publish).

    DERIVED from :func:`_board_store_drift_items` since 2026-08-31 — one walk,
    one authority. The four keys and their exact meanings are unchanged (the
    launcher parses them); what changed is that each one is now the size of a
    NAMED set of rows rather than an accumulator nothing else can see.
    """

    return _drift_counts(_board_store_drift_items(realm_id, workspaces), _BOARD_DRIFT_COUNTS)


def _office_store_drift_items(realm_id: str, workspaces: list[Workspace]) -> list[StoreDriftItem]:
    """The per-row half of :func:`_office_store_drift` — see that docstring for
    the semantics and for both under-count guards; this function IS the walk it
    counts, guards included."""

    from .. import office_models
    from ..office_store import OfficeStore
    from ..office_sync import _actor_key, _surface_key, read_office_baseline

    baseline = read_office_baseline(realm_id)
    store = OfficeStore()
    items: list[StoreDriftItem] = []
    for workspace in workspaces:
        workspace_id = workspace.id
        if not paths.office_dir(workspace_id).exists():
            continue
        try:
            surface = store.get_surface(workspace_id)
        except Exception:  # noqa: BLE001 — missing or unreadable: skip the row, never guess
            surface = None
        if surface is not None:
            surface_base = baseline.get(_surface_key(workspace_id))
            if surface_base != office_models.office_content_hash(surface):
                items.append(
                    StoreDriftItem(
                        family=SyncFamily.OFFICE_SURFACE,
                        container=workspace_id,
                        item_key=DRIFT_KEY_OFFICE_SURFACE,
                        kind=DRIFT_KIND_CHANGED if surface_base is not None else DRIFT_KIND_ADDED,
                    )
                )
        try:
            scan = store.scan_actors(workspace_id)
        except Exception:  # noqa: BLE001 — unreadable listing is not evidence of removal
            continue
        if scan.unreadable:
            continue
        actor_prefix = _actor_key(workspace_id, "")
        baseline_actor_keys = {key[len(actor_prefix):] for key in baseline if key.startswith(actor_prefix)}
        current_actor_keys: set[str] = set()
        for actor in scan.actors:
            current_actor_keys.add(actor.actor_key)
            base_hash = baseline.get(_actor_key(workspace_id, actor.actor_key))
            if base_hash is None:
                kind = DRIFT_KIND_ADDED
            elif base_hash != office_models.office_content_hash(actor):
                kind = DRIFT_KIND_CHANGED
            else:
                continue
            items.append(
                StoreDriftItem(
                    family=SyncFamily.OFFICE_ACTOR,
                    container=workspace_id,
                    item_key=actor.actor_key,
                    kind=kind,
                )
            )
        for actor_key in sorted(baseline_actor_keys - current_actor_keys):
            items.append(
                StoreDriftItem(
                    family=SyncFamily.OFFICE_ACTOR,
                    container=workspace_id,
                    item_key=actor_key,
                    kind=DRIFT_KIND_REMOVED,
                )
            )
    return items


def _office_store_drift(realm_id: str, workspaces: list[Workspace]) -> dict[str, int]:
    """Mission Office content drift vs the never-synced baseline sidecar, for the
    workspaces that belong to this realm.

    The office twin of ``_board_store_drift`` directly above, and deliberately
    the same shape: compare CURRENT ``OfficeStore`` semantic content hashes
    (``office_content_hash`` — revision/timestamps excluded) against
    ``read_office_baseline(realm_id)``, the exact baseline the office publish and
    pull lanes already write and read. A missing/empty baseline on a server-bound
    realm means nothing has been published yet, so every current actor counts as
    added — that is honest, and it mirrors the board rule.

    This exists because the outbound direction had no accounting at all: git only
    knows the checked-out realm repo, and archiving every actor of a workspace
    never touches that repo until publish, so the sheet kept saying "In sync"
    while the local store had drifted away from what was published (measured
    2026-08-29 on ``ws_testv4_afb811``).

    Pure and read-only: no git, no network, no writes (office plan §10 simplicity
    budget). ``offices_changed`` counts surfaces whose hash drifted;
    ``actors_changed`` counts active actors whose hash drifted from a known
    baseline; ``actors_added`` counts active actors with no baseline entry; and
    ``actors_removed`` counts baseline actors no longer active locally (archived
    or removed since the last publish).

    Two under-count guards, both preferring silence to a delete-shaped lie:

    * an actor directory that does not fully READ (``scan.unreadable``) skips
      that workspace's ENTIRE actor accounting. ``scan_actors`` carries the
      shortfall precisely so this arm can ask; spending only its rows would hand
      back a short list and the baseline diff would then report N removals for
      actors whose files merely would not open here — the same lie
      ``update_office_baseline_after_sync`` refuses to write.
    * a workspace with no office directory contributes nothing, and a
      missing/unreadable surface only skips its own ``offices_changed`` row (the
      actor accounting still runs when the listing is readable).

    DERIVED from :func:`_office_store_drift_items` since 2026-08-31 — one walk,
    one authority, the board twin's change for the board twin's reason. The four
    keys and their meanings are unchanged.
    """

    return _drift_counts(_office_store_drift_items(realm_id, workspaces), _OFFICE_DRIFT_COUNTS)


def _any_store_drift(store_drift: dict[str, Any]) -> bool:
    """True iff any drift family reports a nonzero count (drives the additive
    ``unpublished_changes`` status flag).

    Only the COUNT families are asked. ``store_drift`` also carries the additive
    ``items`` list, and a list has no counts to sum — the two can never disagree
    anyway (every row lands in exactly one counter, see :func:`_drift_counts`),
    so this reads the halves it was written for rather than growing a second
    answer for the same question.
    """

    return any(
        count
        for family in store_drift.values()
        if isinstance(family, dict)
        for count in family.values()
    )


def _skill_drift_walk(realm_id: str, _workspaces: list[Workspace]) -> list[StoreDriftItem]:
    """The skill walk in the table's shape: a skill package belongs to the ONE
    shared skills root, not to a workspace, so the workspaces are not asked."""

    return _skill_store_drift_items(realm_id)


#: The drift walk, one family group per entry, in the order the rows are
#: reported (board families first). ``store_drift_items`` iterates this and
#: nothing else, so a family is in the walk if and only if it is listed here.
DRIFT_WALKS: Final[tuple[Callable[[str, list[Workspace]], list[StoreDriftItem]], ...]] = (
    _board_store_drift_items,
    _office_store_drift_items,
    _persona_instance_store_drift_items,
    _flow_graph_store_drift_items,
    _skill_drift_walk,
)
