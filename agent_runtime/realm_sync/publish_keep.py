"""Which board and office documents a publish writes from the store, and which keep the team copy's bytes.

A publish used to export every board and office document byte for byte, so it shipped what the member never
changed, and shipped over what the member had not yet chosen:

* **A document the member did not change keeps the team's bytes** (RT-REALM-PUBLISH-RESTAMPS-UNCHANGED-FILES,
  review w1118a.36 D3). A pull's adopters, and revert, stamp ``updated_by`` on what they write, and the content
  compare ignores the stamp while the byte export did not: every publish after a pull rewrote "who last edited"
  on each document a teammate had touched. "Did the member change this document" has ONE owner, the status's
  per-family content compare against the baseline (``drift._office_store_drift_items`` /
  ``drift._board_store_drift_items``): a document it does not name, which the team copy holds, is written as the
  team copy holds it.
* **A HELD document keeps the team's copy** (RT-REALM-LOCAL-EDIT-OUTLIVES-A-TEAMMATES-DELETE, review w1118a.36
  D1). A pull that meets an unpublished local edit of a desk or card the team changed or deleted holds it — a
  conflict sidecar, the member's to resolve (``office_store.conflicts``, ``board_sync``). Publishing the local
  copy over the hold re-added a desk a teammate deleted before the member chose anything. Until they do, the
  publish carries the team's copy of it (the team's bytes, or its absence), and the baseline keeps the entry it
  had (``held_baseline_entries``), so the next pull still sees the two-sided change.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from .. import paths
from ..models import Workspace
from .families import SyncFamily
from .models import RealmSyncArtifact

__layer__ = "stores"
__all__ = ["held_baseline_entries", "held_document_paths", "keep_team_copies"]

#: The published families whose documents the content compare decides, and where each holds its rows.
_HOLDING_FAMILIES = (("office", "actors", SyncFamily.OFFICE_ACTOR), ("boards", "cards", SyncFamily.BOARD_CARD))


def held_document_paths() -> frozenset[str]:
    """Subtree-relative paths (``store/office/<ws>/actors/<file>``, ``store/boards/<board>/cards/<file>``) of
    every desk and card a pull HELD here: an unresolved conflict sidecar sits beside it, under the same file
    name (``paths.office_conflict_path`` / ``paths.board_conflict_path``)."""

    held: set[str] = set()
    for family, rows, _kind in _HOLDING_FAMILIES:
        root = paths.store_root() / family
        if not root.is_dir():
            continue
        for sidecar in root.glob("*/conflicts/*.json"):
            if not sidecar.name.endswith(".resolved.json"):
                held.add(f"store/{family}/{sidecar.parent.parent.name}/{rows}/{sidecar.name}")
    return frozenset(held)


def held_baseline_entries(keys: Iterable[str], is_held, old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """``new`` with each HELD key's entry put back as ``old`` had it (dropped where ``old`` had none).

    ``is_held(key)`` answers for one baseline key. A publish records the store's hashes as the baseline; for a
    held row that would claim the member's unchosen copy is what the realm has, and the next pull would then
    read the team's delete as one the member agreed to. MUTATION: return ``new`` unchanged and
    test_a_held_desk_is_not_published_until_the_member_chooses reddens at its second pull."""

    for key in keys:
        if not is_held(key):
            continue
        if key in old:
            new[key] = old[key]
        else:
            new.pop(key, None)
    return new


def _drift_key(artifact: RealmSyncArtifact) -> tuple[str, str, str] | None:
    """The status's row key for a board or office document, read from the store file it publishes."""

    from .drift import DRIFT_KEY_BOARD_DEF, DRIFT_KEY_OFFICE_SURFACE

    try:
        data = json.loads(artifact.source.read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    kind = str(artifact.kind)
    if kind == str(SyncFamily.OFFICE):
        parts = (SyncFamily.OFFICE_SURFACE, data.get("workspace_id"), DRIFT_KEY_OFFICE_SURFACE)
    elif kind == str(SyncFamily.OFFICE_ACTOR):
        parts = (SyncFamily.OFFICE_ACTOR, data.get("workspace_id"), data.get("actor_key"))
    elif kind == str(SyncFamily.BOARD):
        parts = (SyncFamily.BOARD, data.get("board_id"), DRIFT_KEY_BOARD_DEF)
    elif kind == str(SyncFamily.BOARD_CARD):
        parts = (SyncFamily.BOARD_CARD, data.get("board_id"), data.get("card_id"))
    else:
        return None
    if not all(isinstance(part, str) and part for part in parts[1:]):
        return None
    return str(parts[0]), str(parts[1]), str(parts[2])


def keep_team_copies(
    realm_id: str, workspaces: list[Workspace], subtree: Path, artifacts: list[RealmSyncArtifact]
) -> list[RealmSyncArtifact]:
    """``artifacts`` as the publish writes them: a held desk or card as the team copy has it, and a board or
    office document the content compare does not name as changed with the team copy's bytes."""

    from .drift import _board_store_drift_items, _office_store_drift_items

    held = held_document_paths()
    drifted = {
        (str(item.family), item.container, item.item_key)
        for item in (*_office_store_drift_items(realm_id, workspaces), *_board_store_drift_items(realm_id, workspaces))
    }
    compared = {str(SyncFamily.OFFICE), str(SyncFamily.OFFICE_ACTOR), str(SyncFamily.BOARD), str(SyncFamily.BOARD_CARD)}
    kept: list[RealmSyncArtifact] = []
    seen: set[str] = set()
    for artifact in artifacts:
        rel = artifact.relative_path.replace("\\", "/")
        seen.add(rel)
        team = subtree / rel
        if rel in held:
            # MUTATION: append ``artifact`` here and
            # test_a_held_desk_is_not_published_until_the_member_chooses reddens at the team's tree.
            if team.is_file():
                kept.append(replace(artifact, content=team.read_bytes()))
            continue
        if str(artifact.kind) in compared and team.is_file():
            key = _drift_key(artifact)
            # MUTATION: drop the ``not in drifted`` test (always the team's bytes) and
            # test_a_publish_carries_the_members_own_edit reddens; drop this branch and
            # test_a_publish_after_a_pull_leaves_the_teammates_documents_as_they_were reddens.
            if key is not None and key not in drifted:
                kept.append(replace(artifact, content=team.read_bytes()))
                continue
        kept.append(artifact)
    for rel in sorted(held - seen):
        team = subtree / rel
        if not team.is_file():
            continue
        kind = next(kind for family, _rows, kind in _HOLDING_FAMILIES if rel.startswith(f"store/{family}/"))
        kept.append(
            RealmSyncArtifact(
                kind=kind,
                source=team,
                relative_path=rel,
                destination=paths.store_root().joinpath(*rel.split("/")[1:]),
                content=team.read_bytes(),
            )
        )
    return kept
