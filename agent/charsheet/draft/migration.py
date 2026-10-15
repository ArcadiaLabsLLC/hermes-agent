"""``migrate_characters_home`` — a legacy per-home store moved into the install-wide library."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .layout import DRAFTS_DIRNAME, DRAFT_FILENAME, MANIFEST_FILENAME, stamp_recorded_home

__layer__ = "lanes"


def _migration_entry_id(directory: Path) -> str:
    """The id a draft directory lists under — from the FILE, not the leaf name.

    They differ in the case the live disk actually holds: an id-collision pair
    (``<id>/`` beside ``<id>.backup-…/``) whose two ``draft.json`` files carry
    the SAME id. The receipt names directories beside ids for that reason, the
    same reason the backfill's does.
    """
    try:
        data = json.loads((Path(directory) / DRAFT_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Path(directory).name
    if not isinstance(data, dict):
        return Path(directory).name
    return str(data.get("id", "") or Path(directory).name)


def migrate_characters_home(source: Path, destination: Path, *, source_home: str) -> dict:
    """Move a legacy per-home character store into the install-wide library.

    Explicit source and destination :class:`~pathlib.Path` arguments, so the
    rules below are unit-testable without env games and so the CALLER owns the
    decision of which home is being migrated. That matters more than it looks: after the
    library head-homed, ``characters_dir()`` answers the DESTINATION, so a verb
    that resolved its source through it would be asking to move the library onto
    itself. The handler spells the legacy location literally and this function
    refuses the degenerate case anyway.

    Four rules:

    * **Stamp before move.** A draft with no ``hermes_home`` is stamped with the
      SOURCE home (:func:`stamp_recorded_home`) before it is relocated — after
      the move the directory no longer witnesses where the draft lived, and this
      is the last chance to record it first-party. A present key is never
      rewritten.
    * **Move, never copy-and-delete.** One :func:`os.replace` per entry. Draft
      directories keep their leaf names (so a stored binding's ``draftId`` and
      ``load()`` both keep resolving) and installed characters keep their slugs.
    * **A collision is a per-entry refusal.** A destination that already holds
      the leaf or the slug lands in ``skipped`` with a reason, its ``directory``
      (the source it is still sitting in — an id cannot address it, because the
      live store holds an id-collision pair) and its source is left untouched —
      never a merge, never an overwrite. Archive-never-delete makes that the
      only available answer: a move that lands intact destroys nothing, and a
      move that cannot land must destroy nothing either.
    * **Nothing is deleted, the emptied tree included.** The source
      ``characters/`` directory is left standing as its own tombstone — it is
      the only thing left saying a per-home store was ever there, and it is what
      the receipt's ``from`` refers to.

    Idempotent: a second run finds no sources and moves nothing.
    """
    source = Path(source)
    destination = Path(destination)
    moved: list[dict] = []
    stamped: list[dict] = []
    skipped: list[dict] = []
    receipt = {
        "ok": True,
        "from": str(source),
        "to": str(destination),
        "moved": moved,
        "stamped": stamped,
        "skipped": skipped,
    }
    if not source.is_dir() or source.resolve() == destination.resolve():
        return receipt

    def _relocate(child: Path, target: Path, row: dict) -> None:
        # Every refusal carries the SOURCE directory beside the id or slug, for
        # the reason `backfill-home`'s receipt does: the live store holds an
        # id-collision pair (`<id>` and `<id>.backup-…`, one id inside both
        # `draft.json` files), so two refusals list under one id and the
        # directory is the only field that says which entry a row is about. A
        # moved row already carries it as `from`; the installed arm's
        # "not an installed character" skip already carried it; this arm did
        # not, and an operator has to go look at exactly the entry it refused.
        left_where_it_is = {**row, "directory": str(child)}
        if target.exists():
            skipped.append(
                {**left_where_it_is, "reason": f"destination already exists: {target}"}
            )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(child, target)
        except OSError as exc:
            # A cross-volume rename, a lock, a permission — the entry stays where
            # it is and the receipt says why. Reported rather than raised so one
            # stuck entry cannot strand the rest of the store half-migrated.
            skipped.append({**left_where_it_is, "reason": f"could not move: {exc}"})
            return
        moved.append({**row, "from": str(child), "to": str(target)})

    src_drafts = source / DRAFTS_DIRNAME
    for child in sorted(src_drafts.iterdir()) if src_drafts.is_dir() else []:
        if not child.is_dir() or not (child / DRAFT_FILENAME).is_file():
            continue
        draft_id = _migration_entry_id(child)
        if stamp_recorded_home(child, source_home):
            stamped.append({"id": draft_id, "directory": str(child)})
        _relocate(
            child,
            destination / DRAFTS_DIRNAME / child.name,
            {"kind": "draft", "id": draft_id},
        )

    for child in sorted(source.iterdir()):
        if child.name == DRAFTS_DIRNAME or not child.is_dir():
            continue
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.is_file():
            # The same definition of "an installed character" the CLI's
            # installed rows use. A directory that is not one is left where it
            # is rather than swept along — an unrecognised tree under a
            # characters store is exactly the thing a move should not guess at.
            skipped.append(
                {
                    "kind": "installed",
                    "slug": child.name,
                    "directory": str(child),
                    "reason": f"no {MANIFEST_FILENAME}: not an installed character",
                }
            )
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        slug = str(manifest.get("slug", "") or child.name)
        _relocate(child, destination / child.name, {"kind": "installed", "slug": slug})

    return receipt
