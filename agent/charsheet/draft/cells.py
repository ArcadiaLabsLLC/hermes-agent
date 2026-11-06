"""An approved row's registered frameW×frameH cells, as one strip (``RowCells``, ``characters cells``).

Row ``RT-CHARS-APPROVED-ROW-CELLS``: ``status``'s ``approvedPath`` is the RAW roll the draftsman
returned (its own slot pitch and height), so a consumer slicing it by ``frameW`` cuts the wrong
cells. This writes what compose would pack for that row — the same extraction, the same shared
scale, the same palette lock — as ``frames × frameW`` by ``frameH``, and names it.
"""

from __future__ import annotations

import logging

from agent.charsheet import pipeline

from .layout import CELLS_DIRNAME, row_item, turnaround_item

__layer__ = "lanes"

logger = logging.getLogger(__name__)


class RowCells:
    """The registered cells of one approved row — one stage of :class:`CharacterDraft`, by composition."""

    def __init__(self, draft) -> None:
        self.draft = draft

    def row_cells(self, row_key: str) -> dict:
        """Write the approved strip of *row_key* as registered cells and return its path and geometry.

        The shared scale is measured over every authored row that has an approved strip
        (``registeredWith``), so once every row is approved the cells are exactly compose's
        (before any recolour op, which compose replays on the whole sheet). The palette lock
        applies when every authored direction has an approved reference (``paletteLocked``), as
        compose requires. Stage-free like ``thumb``: looking is never out of order.
        """
        draft = self.draft
        spec = draft.spec
        row = draft._authored_row(row_key)
        store = draft.store
        approved = store.approved_index(row_item(row.key))
        if approved is None or store.current(row_item(row.key)) is None:
            raise ValueError(
                f"row {row.key!r} has no approved strip; approve one first "
                f"(`characters status --draft {draft.id}` lists its attempts)"
            )
        strips = {
            authored.key: path
            for authored in spec.authored_rows()
            if (path := store.current(row_item(authored.key))) is not None
        }
        references = [store.current(turnaround_item(direction))
                      for direction in pipeline.turnaround_order(spec.scheme.authored)]
        locked = all(reference is not None for reference in references)
        cells = pipeline.register_row_cells(spec, strips, references if locked else None)[row.key]
        strip = pipeline.pack_row_strip(spec, cells)
        out = draft.directory / CELLS_DIRNAME / f"{row.key}-attempt-{approved + 1}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        strip.save(out, format="PNG")
        logger.info("charsheet draft %s: row %s approved attempt %d → cells %s", draft.id, row.key, approved, out)
        return {
            "row": row.key,
            "attempt": approved,
            "frames": row.frames,
            "frameW": spec.frame_w,
            "frameH": spec.frame_h,
            "width": strip.width,
            "height": strip.height,
            "path": str(out),
            "source": str(strips[row.key]),
            "registeredWith": sorted(strips),
            "paletteLocked": locked,
        }
