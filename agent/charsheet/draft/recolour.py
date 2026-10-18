"""The palette op log: record a swatch recolour as a draft step, and replay the log at compose (``PaletteOps``).

**Where the log lives.** ``draft.json`` key ``palette_ops``, a list in the order the
operator made the edits, absent until the first one. A draft-only optional key that a
schema-1 reader ignores (the bar ``layout.SCHEMA`` states), so ``SCHEMA`` does not move;
the installed manifest never carries it — the installed SHEET carries its effect.

**The op.** ``{"op": "recolour", "from": "#rrggbb", "to": "#rrggbb", "at": <utc>}``. A
swatch is named by its colour, never its index: :func:`agent.charsheet.palette.palette_table`
orders swatches by coverage, so an index moves the moment a recolour merges two swatches.
The match is exact (:func:`agent.charsheet.palette.recolour`) — the sheet is palette-locked.

**Replay.** :meth:`Composer.compose` builds the sheet from the approved strips and then runs
:func:`replay` over it, in log order, BEFORE validation, so the validated sheet is the
installed sheet. ``reopen`` cannot reach the turnaround stage, so the palette the strips are
locked into is the one the ops were made against: a re-rolled row snaps into the same table
and takes the same recolours. An op whose colour no longer appears matches zero pixels; the
compose answer reports it (``pixels: 0``) rather than refusing.

**The verb.** :meth:`PaletteOps.recolour` runs at stage ``composed`` (the only stage with a
palette to pick from), under the draft's generation lock (a second writer is refused with
``DraftBusy``). It appends the op FIRST and then edits the installed sheet in place: a crash
between the two leaves the log ahead of the sheet, and the next compose replays it.
"""

from __future__ import annotations

import logging

from agent.charsheet import palette, pipeline
from agent.charsheet._support import safe_segment, slugify, utc_now, write_bytes_atomic, write_json_atomic

from .installed import read_installed_manifest
from .layout import PALETTE_FILENAME, PALETTE_OPS_KEY, SHEET_FILENAME, characters_dir, read_palette

__layer__ = "lanes"

logger = logging.getLogger(__name__)


def replay(sheet, ops: list[dict]):
    """*sheet* with every op of *ops* applied in order, and one ``{from, to, pixels}`` per op."""
    report: list[dict] = []
    for op in ops:
        sheet, pixels = palette.recolour(sheet, op["from"], op["to"])
        report.append({"from": op["from"], "to": op["to"], "pixels": pixels})
    return sheet, report


class PaletteOps:
    """The palette op log of one :class:`CharacterDraft`, by composition."""

    def __init__(self, draft) -> None:
        self.draft = draft

    def ops(self) -> list[dict]:
        raw = self.draft._data.get(PALETTE_OPS_KEY) or []
        return [dict(op) for op in raw if isinstance(op, dict) and op.get("op") == "recolour"]

    def recolour(self, source: str, target: str) -> dict:
        """Recolour one swatch of the composed sheet and record the edit as a draft step."""
        draft = self.draft
        with draft.generation_lock("recolour"):
            draft._require_stage("recolour")
            before, after = palette.opaque_hex(source), palette.opaque_hex(target)
            if before == after:
                raise ValueError(f"recolour {before} -> {after} changes nothing")
            swatches = read_palette(draft.directory)
            if swatches is None:
                raise ValueError(f"draft {draft.id} has no palette.json; compose it before recolouring")
            if f"{before}ff" not in swatches:
                raise ValueError(f"{before} is not a swatch of draft {draft.id} (palette: {', '.join(swatches)})")
            directory = characters_dir() / safe_segment(slugify(draft.slug))
            if str(read_installed_manifest(directory).get("draftId", "")) != draft.id:
                raise ValueError(
                    f"the sheet installed at {directory} is not draft {draft.id}'s; compose it before recolouring"
                )
            op = {"op": "recolour", "from": before, "to": after, "at": utc_now()}
            draft._data[PALETTE_OPS_KEY] = [*self.ops(), op]
            draft._save()
            sheet_path = directory / SHEET_FILENAME
            sheet, pixels = palette.recolour(palette.as_rgba(sheet_path), before, after)
            write_bytes_atomic(sheet_path, pipeline.atlas_to_webp_bytes(sheet))
            table = pipeline.palette_table(sheet)
            write_json_atomic(directory / PALETTE_FILENAME, table)
            write_json_atomic(draft.directory / PALETTE_FILENAME, table)
            logger.info("charsheet draft %s recolour %s -> %s (%d px)", draft.id, before, after, pixels)
            return {
                "op": op,
                "pixels": pixels,
                "paletteOps": self.ops(),
                "palette": table,
                "sheet": str(sheet_path),
            }
