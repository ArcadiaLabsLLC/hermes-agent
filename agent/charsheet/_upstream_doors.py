"""The charsheet package's door onto upstream pixel machinery (program ruling Q5: one per fork package).

Every upstream ``agent.pet`` name the charsheet package reads is imported HERE, so a
weekly upstream merge that renames one breaks this file and nothing else. The block
below is the "ONE intentional drift surface" that used to open ``pipeline.py``,
moved whole.

Layer: ``models`` -- the lowest, so every module of the package may read a door.
"""

from __future__ import annotations

# --- Upstream reuse (the ONE intentional drift surface) ----------------------
# House policy: import upstream pixel machinery, never edit or copy it. The two
# leading-underscore helpers are private to `agent.pet.generate.atlas` and are
# read deliberately, through the two call-time doors below — `_fit_to_cell` is the exact cell-fit contract the pet
# renderer assumes and `_clear_transparent_rgb` is the residue rule the atlas
# validator enforces, so a local copy of either would drift silently as upstream
# retunes. `CELL_WIDTH`/`CELL_HEIGHT` come along because `_fit_to_cell` hardcodes
# that cell geometry: a spec with a different frame size must be refused rather
# than silently re-fitted to 192x208. `frame_x_bounds` is here for the same
# reason under a sharper lesson: this module HAD a local copy of frame geometry
# (width / frames), it disagreed with upstream's content-aware rule on the first
# real strip, and it shipped a QA crop with half a character in it (2026-08-28).
# Centralized in this ONE block so an upstream rename breaks loudly, at import
# time, in a single place (plan §A-6).
from agent.pet.generate import imagegen
from agent.pet.generate.atlas import CELL_HEIGHT, CELL_WIDTH, extract_strip_frames, frame_x_bounds, normalize_cells, remove_background
from agent.pet.generate.encoding import atlas_to_webp_bytes

__layer__ = "models"

__all__ = [
    "CELL_HEIGHT",
    "CELL_WIDTH",
    "atlas_to_webp_bytes",
    "charsheet_setting",
    "clear_transparent_rgb",
    "extract_strip_frames",
    "fit_to_cell",
    "frame_x_bounds",
    "imagegen",
    "normalize_cells",
    "remove_background",
]


def fit_to_cell(image):
    """``agent.pet.generate.atlas._fit_to_cell`` — the cell-fit contract the pet
    renderer assumes. Private upstream; a held widening row in
    ``upstream-footprint-ledger.md`` asks upstream to publish it (ruling Q7)."""
    from agent.pet.generate.atlas import _fit_to_cell

    return _fit_to_cell(image)


def clear_transparent_rgb(image):
    """``agent.pet.generate.atlas._clear_transparent_rgb`` — the residue rule the
    atlas validator enforces. Private upstream; held widening row as above."""
    from agent.pet.generate.atlas import _clear_transparent_rgb

    return _clear_transparent_rgb(image)


def charsheet_setting(key: str, default):
    """``charsheet.<key>`` from ``config.yaml``, read at call time.

    Lazy because this package must not import ``hermes_cli`` at module scope
    (``harness.py`` imports it the other way round). The key's ruled home is the
    plugin manifest's ``config_schema`` — the runtime-queue row on the harness
    config keys owns that move; this door is where it will land.
    """
    from hermes_cli.config import cfg_get, load_config_readonly

    return cfg_get(load_config_readonly(), "charsheet", key, default=default)
