"""One pass per store family over what this realm publishes: board, office, level, map.

Each scan returns the artifacts together with what it refused (and, where the
publish records a baseline, the hashes it read) so a family that cannot travel is a
typed row, never a silent omission.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from .. import paths
from ..models import Workspace
from .models import RealmSyncArtifact

__layer__ = "stores"
__all__ = [
    "BoardPublishScan",
    "LevelPublishScan",
    "MapPublishScan",
    "OfficePublishScan",
    "_board_publish_scan",
    "_level_publish_scan",
    "_map_publish_scan",
    "_office_publish_scan",
]


class BoardPublishScan(NamedTuple):
    """What ONE pass over the board store says this realm publishes, and what
    it refused. ``OfficePublishScan``'s twin, for the same defect."""

    artifacts: list[RealmSyncArtifact]
    refused: list[dict[str, Any]]


def _board_publish_scan(workspaces: list[Workspace]) -> BoardPublishScan:
    """Mission Board artifact family: board.json + active card files for boards
    whose workspace belongs to this realm. ``archive/``, ``conflicts/``,
    ``idempotency/`` and the never-synced baseline are all excluded (only
    ``board.json`` and ``cards/`` are walked). Publish replaces the realm subtree
    wholesale (see ``publish_realm_sync``), so card removals/archives propagate
    as absences; pull applies per-card LWW via ``board_sync.apply_board_pull``.

    A board whose card directory does not fully read publishes NOTHING and is
    refused typed instead — the office arm's reasoning, unchanged: publish
    copies card FILES verbatim, absences ARE removals, so a card that merely
    would not decode here becomes a card archived on every peer. Dropping the
    whole board from the subtree is safe where dropping one card is not, because
    a pull only classifies the board directories the subtree contains.
    """

    from ..board_store import BoardStore

    workspace_ids = {ws.id for ws in workspaces}
    store = BoardStore()
    artifacts: list[RealmSyncArtifact] = []
    refused: list[dict[str, Any]] = []
    board_scan = store.scan_all()
    if board_scan.unreadable:
        # Cannot be realm-filtered or even named: the board id and its workspace
        # both live inside the file that would not parse. Counted anyway —
        # silence here published a realm that quietly lacked a board.
        refused.append(
            {
                "board_id": None,
                "reason": "board_unreadable",
                "unreadable": board_scan.unreadable,
            }
        )
    for board in board_scan.boards:
        if board.workspace_id not in workspace_ids:
            continue
        card_scan = store.scan_cards(board.board_id)
        if card_scan.unreadable:
            refused.append(
                {
                    "board_id": board.board_id,
                    "reason": "sync_unknowable",
                    "unreadable": card_scan.unreadable,
                }
            )
            continue
        board_token = paths.safe_path_token(board.board_id)
        def_path = paths.board_def_path(board.board_id)
        if def_path.exists():
            artifacts.append(
                RealmSyncArtifact(
                    kind="board",
                    source=def_path,
                    relative_path=f"store/boards/{board_token}/board.json",
                    destination=def_path,
                )
            )
        cards_dir = paths.board_cards_dir(board.board_id)
        if cards_dir.exists():
            for card_path in sorted(cards_dir.glob("*.json")):
                artifacts.append(
                    RealmSyncArtifact(
                        kind="board_card",
                        source=card_path,
                        relative_path=f"store/boards/{board_token}/cards/{card_path.name}",
                        destination=card_path,
                    )
                )
    return BoardPublishScan(artifacts=artifacts, refused=refused)


class OfficePublishScan(NamedTuple):
    """What ONE pass over the office store says this realm publishes.

    FOUR facts, resolved together on purpose. The artifacts and the persona ids
    the placements REQUIRE used to be two independent walks of the same
    directories, and a workspace excluded from one but not the other publishes a
    placement whose persona definition never travelled. ``refused`` is the third
    because it is the reason the others are short — a shortened answer that
    does not carry its own shortfall is the defect this stage retires.

    ``instance_ids`` is the fourth, added for instance replication, and it comes
    off the SAME walk for exactly the reason ``persona_ids`` does: a second
    ``actors_dir.glob`` would be a second authority over which desks this
    publish contains, and the refusal gate above cannot speak for a walk it did
    not take. A workspace refused here therefore contributes no instance id
    either — the placement that would have needed the agent is not travelling.
    """

    artifacts: list[RealmSyncArtifact]
    persona_ids: list[str]
    refused: list[dict[str, Any]]
    instance_ids: list[str] = ()  # type: ignore[assignment]


def _office_publish_scan(workspaces: list[Workspace]) -> OfficePublishScan:
    """Mission Office artifact family: office.json + active actor files for
    surfaces whose workspace belongs to this realm. ``archive/``,
    ``conflicts/`` and the never-synced baseline are all excluded (only
    ``office.json`` and ``actors/`` are walked). Publish replaces the realm
    subtree wholesale (see ``publish_realm_sync``), so actor removals/archives
    propagate as absences; pull applies the per-actor 3-way baseline merge via
    ``office_sync.apply_office_pull``.

    A workspace whose actor directory does not fully read publishes NOTHING and
    is refused typed instead. That is the whole point of the scan: publish
    copies actor FILES verbatim, so the undecodable one travels, and "removals
    propagate as absences" then turns every peer's pull into a desk removal for
    an actor whose file merely would not open here. Dropping the workspace from
    the subtree is safe where dropping one actor is not — a pull only classifies
    the office directories the subtree actually contains.
    """

    from ..office_store import OfficeStore
    from ..office_sync import OfficeSyncRefusal

    workspace_ids = {ws.id for ws in workspaces}
    store = OfficeStore()
    artifacts: list[RealmSyncArtifact] = []
    persona_ids: list[str] = []
    instance_ids: list[str] = []
    refused: list[dict[str, Any]] = []
    for workspace_token in store.list_workspaces():
        try:
            surface = store.get_surface(workspace_token)
        except Exception as exc:  # noqa: BLE001 — accounted, never silent
            # Cannot be realm-filtered: the workspace id lives INSIDE the file
            # that would not parse, so this row names the store token and is
            # reported to whoever publishes. Silence here published an empty
            # office for a surface that exists.
            refused.append(
                {
                    "workspace_id": str(workspace_token),
                    "reason": "surface_unreadable",
                    "error": type(exc).__name__,
                }
            )
            continue
        if surface.workspace_id not in workspace_ids:
            continue
        # ``scan.unreadable`` is what the refusal below is minted from: the rows
        # alone answer "these are the actors" for a directory this read may only
        # have partly decoded.
        scan = store.scan_actors(workspace_token)
        refusal = OfficeSyncRefusal.for_scan(surface.workspace_id, scan)
        if refusal is not None:
            refused.append(refusal.as_dict())
            continue
        ws_token = paths.safe_path_token(workspace_token)
        surface_path = paths.office_surface_path(workspace_token)
        if surface_path.exists():
            artifacts.append(
                RealmSyncArtifact(
                    kind="office",
                    source=surface_path,
                    relative_path=f"store/office/{ws_token}/office.json",
                    destination=surface_path,
                )
            )
        # ONE walk of ``scan.actors`` for both facts. The artifact list used to
        # come from a second ``actors_dir.glob("*.json")`` while the persona ids
        # came from the scan — two authorities over one publish, and the glob was
        # the one the refusal gate above cannot speak for. Whatever the gate let
        # through, the gate SAW: a file it never decoded into a row is a file
        # this publish has no reading of, and shipping it verbatim would put a
        # row on every peer's canvas that no local reader ever admitted existed.
        for actor in scan.actors:
            actor_path = paths.office_actor_path(workspace_token, actor.actor_key)
            artifacts.append(
                RealmSyncArtifact(
                    kind="office_actor",
                    source=actor_path,
                    relative_path=f"store/office/{ws_token}/actors/{actor_path.name}",
                    destination=actor_path,
                )
            )
            if actor.persona_id and actor.persona_id not in persona_ids:
                persona_ids.append(actor.persona_id)
            # The instance the desk is bound to, off THIS row, in THIS walk. The
            # actor key IS the canonical instance id for instance-bound actors
            # (``_canonical_actor_key``), but the payload's own field is read
            # rather than the filename-shaped key, because payload is truth and
            # the key is routing (office plan §4.3).
            if actor.persona_instance_id and actor.persona_instance_id not in instance_ids:
                instance_ids.append(actor.persona_instance_id)
    return OfficePublishScan(
        artifacts=artifacts,
        persona_ids=persona_ids,
        refused=refused,
        instance_ids=instance_ids,
    )


class LevelPublishScan(NamedTuple):
    """What ONE pass over the level store says this realm publishes.

    THREE facts from one walk, for the reason ``OfficePublishScan`` states one
    class up: the artifacts, the content hashes the publish records as its new
    baseline, and the levels that would not travel. Deriving the hashes from a
    second walk is the specific mistake available here — the publish writes the
    bytes THIS scan read, and a baseline computed from a re-read is free to
    disagree with them, which the publisher then meets as a HOLD on their own
    environment at the next pull.
    """

    artifacts: list[RealmSyncArtifact]
    hashes: dict[str, str]
    refused: list[dict[str, Any]]


def _level_publish_scan(workspaces: list[Workspace]) -> LevelPublishScan:
    """The workspace LEVEL family: one document per workspace in this realm.

    **Scoped by TOKEN, not by an id inside the file.** hermes does not parse this
    document (``level_sync``'s module docstring says why), so the workspace it
    belongs to is named by the FILENAME. The realm filter therefore tokenizes the
    workspace ids it already holds and matches those — the token is a pure
    function of the id, so this is exact in the direction that matters: a level
    is published only if a workspace of this realm tokenizes to its name.

    **A level that will not read publishes NOTHING and is refused typed**, the
    office scan's rule for the office scan's reason. Publish copies the file
    verbatim, so an undecodable document would travel; every peer's
    :func:`apply_level_pull` then refuses it on arrival, and the operator who
    could actually fix it — the one whose disk holds the broken file — is the one
    person the silence would keep it from.
    """

    from ..level_sync import (
        LevelDocumentError,
        LevelStore,
        level_document_hash,
        published_relative_path,
    )

    wanted = {paths.safe_path_token(ws.id) for ws in workspaces}
    store = LevelStore()
    artifacts: list[RealmSyncArtifact] = []
    hashes: dict[str, str] = {}
    refused: list[dict[str, Any]] = []
    for token in store.list_workspace_tokens():
        if token not in wanted:
            continue
        raw = store.read(token)
        if raw is None:
            # Listed by the directory walk and unreadable by the store's own
            # read (an OSError it swallows). Not silence: the same typed row an
            # undecodable document gets, because from the publish's side the two
            # are one fact — this realm has a level here that cannot travel.
            refused.append({"workspace_token": token, "reason": "level_unreadable", "error": "OSError"})
            continue
        try:
            hashes[token] = level_document_hash(raw)
        except LevelDocumentError as exc:
            refused.append({"workspace_token": token, "reason": exc.code, "error": type(exc).__name__})
            continue
        source = paths.level_path(token)
        artifacts.append(
            RealmSyncArtifact(
                kind="level",
                source=source,
                relative_path=published_relative_path(token),
                destination=source,
            )
        )
    return LevelPublishScan(artifacts=artifacts, hashes=hashes, refused=refused)


class MapPublishScan(NamedTuple):
    """What ONE pass over the map catalogue says this realm publishes.

    Three facts from one walk, for ``LevelPublishScan``'s reason: the artifacts,
    the content hashes the publish records as its new baseline, and the maps that
    would not travel.
    """

    artifacts: list[RealmSyncArtifact]
    hashes: dict[str, str]
    refused: list[dict[str, Any]]


def _map_publish_scan() -> MapPublishScan:
    """The MAP CATALOGUE family: one document per named map on this install.

    **No realm filter, and no workspace argument.** Every scan above this one
    narrows by the realm's workspaces; this one cannot, because a map id is the
    launcher's ``SavedMapId`` and belongs to the install rather than to a
    workspace or a realm. The realm therefore carries the whole catalogue. The
    cost — a member pulls catalogue entries it has no workspace standing on — is
    strictly smaller than the alternative, which is a catalogue missing exactly
    the entry an incoming level's sidecar names: the ``unnamed · yours`` caption
    the owner reported on 2026-09-22.

    **A map that will not read publishes NOTHING and is refused typed**, the
    level scan's rule for the level scan's reason: publish copies verbatim, so an
    undecodable document would travel and every peer's :func:`apply_map_pull`
    would refuse it on arrival, keeping the failure from the one operator whose
    disk holds the broken file.
    """

    from ..map_sync import (
        MapDocumentError,
        MapStore,
        map_document_hash,
        published_relative_path,
    )

    store = MapStore()
    artifacts: list[RealmSyncArtifact] = []
    hashes: dict[str, str] = {}
    refused: list[dict[str, Any]] = []
    for token in store.list_map_tokens():
        raw = store.read(token)
        if raw is None:
            # Listed by the directory walk and unreadable by the store's own
            # read (an OSError it swallows). The same typed row an undecodable
            # document gets, because from the publish's side the two are one
            # fact — this install has a map here that cannot travel.
            refused.append({"map_token": token, "reason": "map_unreadable", "error": "OSError"})
            continue
        try:
            hashes[token] = map_document_hash(raw)
        except MapDocumentError as exc:
            refused.append({"map_token": token, "reason": exc.code, "error": type(exc).__name__})
            continue
        source = paths.map_path(token)
        artifacts.append(
            RealmSyncArtifact(
                kind="map",
                source=source,
                relative_path=published_relative_path(token),
                destination=source,
            )
        )
    return MapPublishScan(artifacts=artifacts, hashes=hashes, refused=refused)
