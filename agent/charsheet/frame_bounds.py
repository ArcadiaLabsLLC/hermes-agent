"""WHERE each frame of a row strip begins and ends — the charsheet's crop geometry.

Fork-owned (charsheet QA crop). Lane FOOTPRINT-DROP (2026-09-27) moved it out of
upstream's ``agent/pet/generate/atlas.py``, where it had been appended; it composes
upstream's own content-aware helpers, read at call time through
``agent.charsheet._upstream_doors`` so one strip never has two boundary rules.
"""

from __future__ import annotations

from agent.charsheet._upstream_doors import (
    atlas_erase_long_axis_lines,
    atlas_frame_x_ranges,
    atlas_sever_expected_gutters,
    remove_background,
)

__layer__ = "models"


def frame_x_bounds(
    strip,
    frame_count: int,
    *,
    chroma_key: tuple[int, int, int] | None = None,
) -> list[tuple[int, int]]:
    """WHERE each frame of a row strip begins and ends, in strip coordinates.

    The frame boundaries as a value, for callers that must CROP THE SOURCE
    rather than receive extracted frames — a QA surface showing an operator the
    pixels a provider actually returned, magenta field and all, cannot use
    :func:`agent.pet.generate.atlas.extract_strip_frames`'s output because that output has been keyed,
    isolated and re-fitted. Before 2026-08-28 the charsheet's `frame_cell` met
    that need with its own rule — width divided by frame count — and the two
    rules disagreed on the first real strip anyone opened fullscreen: an 8-frame
    2172px row whose first pose spans x 66-298 has an even-slot boundary at 272,
    and the QA crop cut the character in half. Even slots are wrong on real
    strips; that is the whole reason the extraction below is content-aware. One
    strip must not have two boundary rules, and the content-aware one is the
    one that is right.

    The order is ``method="auto"``'s, and each step is the same helper the
    lenient path of :func:`agent.pet.generate.atlas.extract_strip_frames` calls:

    1. Key the background and erase strip-spanning floors/dividers, because a
       drawn floor bridges every pose into one run. Both are strip-scale facts
       and must be judged at strip scale (see :func:`_erase_long_axis_lines`).
    2. :func:`_frame_x_ranges` — the empty gutters between poses, merged across
       the smallest gaps down to *frame_count*. This is the authority.
    3. If the poses touch, :func:`_sever_expected_gutters` cuts thin bands at the
       expected boundaries and step 2 runs again.
    4. Only if there is still nothing to read — an empty strip, or content that
       cannot be separated into *frame_count* pieces — fall back to
       :func:`_slot_bounds`, the even columns. Last resort, never first.

    A single-frame row returns the whole strip: with one frame there is no
    boundary to place, and trimming to the subject would be this function
    guessing which pixels the caller came to look at.

    Each range gets a little breathing room, as the extraction's pad does — but
    clamped to the neighbouring pose's own edge, so the padding can never reach
    another pose's pixels. The extraction can afford a
    raw pad because it cleans slivers out of each crop afterwards; a caller
    cropping the source verbatim cannot, so the restraint lives here.

    Bounds are x only. Height is the caller's business — every route above
    crops full height so tall ears and halos are never clipped.
    """
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 1:
        raise ValueError(f"frame_count must be an integer >= 1, got {frame_count!r}")

    strip = strip.convert("RGBA")  # an open image: the one caller decodes the strip once

    width = strip.width
    if frame_count == 1:
        return [(0, width)]

    base = atlas_erase_long_axis_lines(remove_background(strip, chroma_key=chroma_key))
    ranges = atlas_frame_x_ranges(base, frame_count)
    if ranges is None:
        ranges = atlas_frame_x_ranges(atlas_sever_expected_gutters(base, frame_count), frame_count)
    if ranges is None:
        return _slot_bounds(width, frame_count)

    margin = max(2, min(16, round((width / frame_count) * 0.04)))
    return [
        (
            max(0 if i == 0 else ranges[i - 1][1], left - margin),
            min(width if i == len(ranges) - 1 else ranges[i + 1][0], right + margin),
        )
        for i, (left, right) in enumerate(ranges)
    ]


def _slot_bounds(width: int, frame_count: int) -> list[tuple[int, int]]:
    return [
        (round(i * width / frame_count), round((i + 1) * width / frame_count))
        for i in range(frame_count)
    ]
