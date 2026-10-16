"""The workspace LEVEL family's half of the store-drift walk, and its counts.

Owner ruling 2026-10-10 ("fold the ``levels`` status row into ``store_drift``,
one count"), built by ``docs/agent-runtime-harness/planned/realm-level-revert-arm-2026-10-15.md``
S2: a level joins the drift set in the same change as its revert arm
(``realm_revert._FAMILY_ARMS``), the canvas family's rule — a drift row the
revert lane cannot address is an exit that does not exist. The top-level
``levels`` status row stays beside it for one release (ruling 2), so an older
launcher keeps its count.

Separate from ``drift.py`` only for size; ``drift.DRIFT_WALKS`` and
``drift._BASELINE_KEY_OF`` register it, and nothing else reads it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import paths
from ..models import Workspace
from .families import SyncFamily

if TYPE_CHECKING:
    from .drift import StoreDriftItem

__layer__ = "stores"

#: The level family's counts, shaped like every sibling family's. ``_any_store_drift``
#: sums them, so an unpublished level lights ``unpublished_changes`` through the
#: drift block as well as through the top-level row.
LEVEL_DRIFT_COUNTS = (
    ("levels_changed", SyncFamily.LEVEL, "changed"),
    ("levels_added", SyncFamily.LEVEL, "added"),
    ("levels_removed", SyncFamily.LEVEL, "removed"),
)


def level_drift_key(item: StoreDriftItem) -> str:
    from ..level_sync import level_baseline_key

    return level_baseline_key(item.item_key)


def level_store_drift_items(realm_id: str, workspaces: list[Workspace]) -> list[StoreDriftItem]:
    """One row per workspace level whose bytes differ from the last-synced baseline.

    Scoped exactly as the publish is (``_level_publish_scan``), so a row never names
    a level this realm would not ship, and keyed by the workspace TOKEN — the only
    identity a level has (hermes does not parse the document). The container is the
    same token: the workspace holds the level, and a ``removed`` row's workspace may
    no longer resolve, so an id read off a record would go blank exactly there.

    ``removed`` is a baselined token with no level on this machine at all. Two
    guards, both the sibling families':

    * a level the scan REFUSES (will not read) contributes no row; it is named on
      the top-level ``levels.refused`` list, and a row would offer a revert over a
      file this machine cannot read.
    * a HELD level (a conflict sidecar is parked for it) contributes no row; the
      hold's exit is ``realm sync resolve``, and a revert row beside it would
      adopt the realm's copy around the hold — the skill family's rule.
    """

    from ..level_sync import LevelStore, level_baseline_key, read_level_baseline
    from .drift import DRIFT_KIND_ADDED, DRIFT_KIND_CHANGED, DRIFT_KIND_REMOVED, StoreDriftItem
    from .publish_scans import _level_publish_scan

    scan = _level_publish_scan(workspaces)
    baseline = read_level_baseline(realm_id)
    prefix = level_baseline_key("")
    baselined = {key[len(prefix):] for key in baseline if key.startswith(prefix)}
    refused = {str(row.get("workspace_token")) for row in scan.refused}
    held = {token for token in baselined | set(scan.hashes)
            if paths.level_conflict_path(realm_id, token).is_file()}

    def _row(token: str, kind: str) -> StoreDriftItem:
        return StoreDriftItem(family=SyncFamily.LEVEL, container=token, item_key=token, kind=kind)

    items: list[StoreDriftItem] = []
    for token, body_hash in sorted(scan.hashes.items()):
        if token in held:
            continue
        base_hash = baseline.get(level_baseline_key(token))
        if base_hash is None:
            items.append(_row(token, DRIFT_KIND_ADDED))
        elif base_hash != body_hash:
            items.append(_row(token, DRIFT_KIND_CHANGED))
    local = set(LevelStore().list_workspace_tokens())  # a level outside this realm is not "removed"
    for token in sorted(baselined - local - refused - held):
        items.append(_row(token, DRIFT_KIND_REMOVED))
    return items
