"""The shared LENS RECIPE family's drift rows and its revert arm (row ``RT-LENS-RECIPE-DRIFT-ARM``).

Plan ``docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md`` §3 (Drift, Revert):
the ``level`` family's pair (``level_drift.py``, ``realm_revert_level.py``) over the shelf, joined in
one change, because a drift row the revert lane cannot address is an exit that does not exist.
``drift.DRIFT_WALKS`` / ``drift._BASELINE_KEY_OF`` and ``realm_revert._FAMILY_ARMS`` register it.

Every write goes through the shelf's one door, ``DocumentStore(LENS_RECIPE_FAMILY)``, so a revert
writes nothing a pull could not have written and touches no monitor (a shelf write moves only the
Lens store revision, the family's ``on_change``). A recipe the realm never carried has no local
archive (``realm_revert.NO_LOCAL_ARCHIVE_FAMILIES``): un-sharing is ``runtime.lens.recipe.withdraw``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models import Workspace
from .families import SyncFamily

if TYPE_CHECKING:
    from .drift import StoreDriftItem

__layer__ = "stores"


def lens_recipe_drift_key(item: StoreDriftItem) -> str:
    from ..lens.recipe_shelf import LENS_RECIPE_FAMILY

    return LENS_RECIPE_FAMILY.baseline_key(item.item_key)


def lens_recipe_store_drift_items(realm_id: str, workspaces: list[Workspace]) -> list[StoreDriftItem]:
    """One row per shelf document of this realm's workspaces whose bytes differ from the last-synced
    baseline, keyed ``<workspace token>/<recipe id>`` and held by its workspace token.

    Scoped exactly as the publish is (``lens_recipe_publish_scan``). A document the scan REFUSES, or
    one a pull HELD (a conflict is parked for it), gives no row — the level family's two guards."""

    from ..lens.recipe_shelf import LENS_RECIPE_FAMILY, lens_recipe_publish_scan
    from .document_family import DocumentStore, read_document_baseline
    from .drift import DRIFT_KIND_ADDED, DRIFT_KIND_CHANGED, DRIFT_KIND_REMOVED, StoreDriftItem

    family = LENS_RECIPE_FAMILY
    scan = lens_recipe_publish_scan(workspace.id for workspace in workspaces)
    baseline = read_document_baseline(family, realm_id)
    prefix = family.baseline_key("")
    baselined = {key[len(prefix):] for key in baseline if key.startswith(prefix)}
    refused = {str(row.get(family.token_field)) for row in scan.refused}
    held = {token for token in baselined | set(scan.hashes) if family.conflict_path(realm_id, token).is_file()}

    def _row(token: str, kind: str) -> StoreDriftItem:
        return StoreDriftItem(family=SyncFamily.LENS_RECIPE, container=token.split("/", 1)[0],
                              item_key=token, kind=kind)

    items: list[StoreDriftItem] = []
    for token, body_hash in sorted(scan.hashes.items()):
        if token in held:
            continue
        base_hash = baseline.get(family.baseline_key(token))
        if base_hash is None:
            items.append(_row(token, DRIFT_KIND_ADDED))
        elif base_hash != body_hash:
            items.append(_row(token, DRIFT_KIND_CHANGED))
    local = set(DocumentStore(family).list_tokens())  # a recipe outside this realm is not "removed"
    for token in sorted(baselined - local - refused - held):
        items.append(_row(token, DRIFT_KIND_REMOVED))
    return items


# --- the revert arm (``realm_revert._FAMILY_ARMS``) -------------------------------------------------


def read_lens_recipe_upstream(subtree: Path) -> tuple[dict[str, bytes], set[str]]:
    """``(recipe bytes by token, tokens whose published file will not read)`` — the pull's reader."""

    from ..lens.recipe_shelf import LENS_RECIPE_FAMILY
    from .document_family import read_remote_documents

    recipes, refused = read_remote_documents(LENS_RECIPE_FAMILY, subtree)
    return recipes, {str(row.get("key")) for row in refused}


def refuse_lens_recipe_door(token: str, raw: bytes) -> Any:
    """The pull's own door past the reader: a recipe not filed where it says is refused
    ``recipe_misfiled`` (``recipe_shelf.realm_admit``). A row's token is already this realm's."""

    import json

    from ..lens.recipe_shelf import RecipeDocumentError, RecipeRefusal, filed_token

    if filed_token(json.loads(raw)) != token:
        return RecipeDocumentError(RecipeRefusal.MISFILED)
    return None


def apply_lens_recipe(item: Any, entity: bytes, _action: Any, **_stores: Any) -> None:
    """RESTORE / ADOPT: the last-pulled bytes, VERBATIM, through the shelf's door."""

    from ..lens.recipe_shelf import LENS_RECIPE_FAMILY
    from .document_family import DocumentStore

    DocumentStore(LENS_RECIPE_FAMILY).write(item.item_key, entity)


def lens_recipe_content_hash(item: Any) -> str:
    """The shelf's post-write bytes, hashed as the drift walk and the publish hash them."""

    from ..lens.recipe_shelf import LENS_RECIPE_FAMILY
    from .document_family import DocumentStore, document_hash

    raw = DocumentStore(LENS_RECIPE_FAMILY).read(item.item_key)
    if raw is None:
        raise FileNotFoundError(item.item_key)
    return document_hash(LENS_RECIPE_FAMILY, raw)
