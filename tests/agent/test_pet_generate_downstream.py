"""Fork-owned tests moved out of ``tests/agent/test_pet_generate.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import logging
import os
import pytest
pytestmark = pytest.mark.skipif(
    os.environ.get("HERMES_RUN_SLOW_PET_TESTS") != "1",
    reason=(
        "pet generation image-processing suite is opt-in; run with "
        "HERMES_RUN_SLOW_PET_TESTS=1 scripts/run_tests.sh tests/agent/test_pet_generate.py"
    ),
)
from agent.pet.generate import atlas
from PIL import Image, ImageDraw  # noqa: E402


def test_merge_rejoins_a_subject_severed_into_stacked_slabs():
    # Measured on the rejected walk-se frame: near-total x-overlap, 1px and 2px
    # y-gaps. One character, three boxes.
    merged = atlas._merge_related_boxes(
        [(6, 303, 203, 426), (11, 427, 202, 450), (13, 452, 213, 581)]
    )

    assert merged == [(6, 303, 213, 581)]


def test_merge_keeps_two_real_poses_apart():
    poses = [(0, 0, 100, 200), (250, 0, 350, 200)]

    assert sorted(atlas._merge_related_boxes(poses)) == poses


def test_merge_keeps_two_grid_rows_apart():
    """The 2D-grid path depends on stacked POSES staying separate subjects.

    Rejoining slabs must not also rejoin the two visual rows a model draws when
    it ignores "one horizontal row" — that is the case ``_component_crops``
    exists to handle.
    """
    rows = [(0, 0, 200, 200), (0, 300, 200, 500)]

    assert sorted(atlas._merge_related_boxes(rows)) == rows


def test_merge_still_joins_a_prop_on_the_same_row():
    # The behaviour that was already there: a cape a few px off the body.
    merged = atlas._merge_related_boxes([(100, 50, 200, 250), (208, 80, 230, 200)])

    assert merged == [(100, 50, 230, 250)]


CHROMA = (255, 0, 255, 255)


_SEAM_SLOT = 208


_SEAM_FRAMES = 8


def _seam_severed_strip(*, seams=(-40, 20), severed=3):
    """An 8-pose chroma strip with one pose cut by thin chroma-coloured seams.

    Poses sit close enough that the strip-level horizontal merge collapses them
    into one box — that part is exactly what the live artifact did — so
    extraction falls through to the gutter path and each pose is validated as
    its own column.

    The seams themselves are this fixture's own mechanism, NOT the live one: a
    genuine seam the chroma key opens up. What actually severed the live walk-se
    pose was our own slot-scale line erase, which is fixed at the root and has
    its own tests below. A keyed seam remains possible — a provider really can
    draw one — so this stays as the merge's coverage.
    """
    width, height = _SEAM_SLOT * _SEAM_FRAMES, 800
    img = Image.new("RGBA", (width, height), CHROMA)
    draw = ImageDraw.Draw(img)
    rx, ry, cy = 95, 140, 400
    for i in range(_SEAM_FRAMES):
        cx = i * _SEAM_SLOT + _SEAM_SLOT // 2
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(60, 90, 200, 255))
        if i == severed:
            for offset in seams:
                y = cy + offset
                draw.rectangle((cx - rx, y, cx + rx, y + 1), fill=CHROMA)
    return img


def test_a_pose_severed_by_seam_lines_still_slices_into_whole_frames():
    frames = atlas.extract_strip_frames(
        _seam_severed_strip(), _SEAM_FRAMES, method="auto", fit=False
    )

    assert len(frames) == _SEAM_FRAMES
    severed = frames[3].getbbox()
    intact = frames[2].getbbox()
    assert severed is not None and intact is not None
    # The repaired frame must carry the WHOLE pose, not the tallest slab: its
    # vertical span matches an untouched neighbour's within the seam width.
    assert abs((severed[3] - severed[1]) - (intact[3] - intact[1])) <= 6


def _interior_empty_rows(frame):
    """Fully transparent rows strictly inside the frame's own content bbox."""
    bbox = frame.getbbox()
    if bbox is None:
        return []
    alpha = frame.getchannel("A")
    return [
        y
        for y in range(bbox[1] + 1, bbox[3] - 1)
        if alpha.crop((bbox[0], y, bbox[2], y + 1)).getbbox() is None
    ]


def _slot_crop_with_a_wide_body_row(width=221, height=400):
    """One pose, cropped to its own slot, with a bar of its own art across it.

    Already keyed, so the bar is the 3 rows the eraser would see after
    defringing: thin enough to read as a "line", and 88% of the crop wide.
    Nothing here is a drawn floor; it is all one character.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    body = round(width * 0.45)
    x0 = (width - body) // 2
    draw.rectangle((x0, 60, x0 + body, 340), fill=(60, 90, 200, 255))
    bar = round(width * 0.88)
    bx = (width - bar) // 2
    draw.rectangle((bx, 198, bx + bar, 200), fill=(60, 90, 200, 255))
    return img


def test_a_slot_crop_keeps_the_poses_own_wide_rows():
    isolated = atlas._isolate_slot_subject(_slot_crop_with_a_wide_body_row())

    assert _interior_empty_rows(isolated) == []
    # The wide row itself is still drawn, not merely bridged by something else.
    assert isolated.getchannel("A").crop((0, 198, 221, 201)).getbbox() is not None


def _strip_with_a_drawn_floor(*, floor=True):
    """Eight poses on chroma, optionally standing on one drawn ground line."""
    width, height = _SEAM_SLOT * _SEAM_FRAMES, 800
    img = Image.new("RGBA", (width, height), CHROMA)
    draw = ImageDraw.Draw(img)
    rx, ry, cy = 95, 140, 400
    for i in range(_SEAM_FRAMES):
        cx = i * _SEAM_SLOT + _SEAM_SLOT // 2
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(60, 90, 200, 255))
    if floor:
        # Spans the whole strip and touches every pose — the thing the eraser
        # was built for.
        draw.rectangle((0, 536, width, 540), fill=(90, 90, 90, 255))
    return img


def test_a_floor_line_drawn_across_the_whole_strip_stops_bridging_the_poses():
    """The floor's PURPOSE test: it must stop welding the row into one blob.

    Not "every floor pixel is gone" — the span under a pose's own feet has body
    directly above it and is kept, which is what protects a character's own
    aligned anatomy. That stub belongs to the pose it touches and separates
    nothing. What has to die is the span crossing the background BETWEEN poses.
    """
    keyed = atlas.remove_background(_strip_with_a_drawn_floor())
    assert len(atlas._component_boxes(keyed)) == 1  # one welded blob

    erased = atlas._erase_long_axis_lines(keyed)

    assert len(atlas._component_boxes(erased)) >= _SEAM_FRAMES
    # The gutter between the first two poses is clear through the floor band.
    gutter = (_SEAM_SLOT - 12, 537, _SEAM_SLOT + 12, 540)
    assert erased.getchannel("A").crop(gutter).getbbox() is None
    # The poses themselves are untouched.
    assert erased.getchannel("A").crop((0, 300, keyed.width, 500)).getbbox() is not None


def _aligned_band_strip():
    """The SE shape: every pose carries the SAME thin wide row at the SAME height.

    This is what a chin/shoulder contour does at a diagonal angle — it lands at
    one height in all eight poses and the band covers >=85% of the strip while
    being pure anatomy. Coverage cannot tell it from a drawn floor. What can:
    every column of it has body directly above and below, because it is the
    silhouette's own widest row, not something laid across the background.
    """
    width, height = _SEAM_SLOT * _SEAM_FRAMES, 800
    img = Image.new("RGBA", (width, height), CHROMA)
    draw = ImageDraw.Draw(img)
    rx, ry, cy = 95, 140, 400
    for i in range(_SEAM_FRAMES):
        cx = i * _SEAM_SLOT + _SEAM_SLOT // 2
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(60, 90, 200, 255))
        # The shoulder line: wider than the body here, same height every frame.
        draw.rectangle((cx - rx, cy - 101, cx + rx, cy - 97), fill=(60, 90, 200, 255))
    return img


def test_anatomy_aligned_across_every_pose_is_not_mistaken_for_a_floor():
    frames = atlas.extract_strip_frames(
        _aligned_band_strip(), _SEAM_FRAMES, method="auto", fit=False
    )

    assert len(frames) == _SEAM_FRAMES
    scanlines = {i: _interior_empty_rows(f) for i, f in enumerate(frames)}
    assert all(rows == [] for rows in scanlines.values()), scanlines
    heights = [f.getbbox()[3] - f.getbbox()[1] for f in frames]
    assert max(heights) - min(heights) <= 6, heights


def test_an_aligned_body_band_survives_the_eraser_and_a_floor_does_not():
    """Same width, same thinness, opposite verdicts — decided by context alone."""
    body = atlas.remove_background(_aligned_band_strip())
    floor = atlas.remove_background(_strip_with_a_drawn_floor())

    body_kept = atlas._erase_long_axis_lines(body)
    floor_cut = atlas._erase_long_axis_lines(floor)

    band = (0, 299, body.width, 303)
    before = body.getchannel("A").crop(band).getbbox()
    after = body_kept.getchannel("A").crop(band).getbbox()
    assert before is not None and after is not None
    # The anatomy band is still substantially there, not a residue.
    assert len(atlas._component_boxes(body_kept)) == len(atlas._component_boxes(body))
    # The floor, meanwhile, no longer welds the row together.
    assert len(atlas._component_boxes(floor_cut)) > len(atlas._component_boxes(floor))


def test_a_strip_with_a_drawn_floor_still_slices_into_whole_frames():
    frames = atlas.extract_strip_frames(
        _strip_with_a_drawn_floor(), _SEAM_FRAMES, method="auto", fit=False
    )

    assert len(frames) == _SEAM_FRAMES
    for frame in frames:
        assert frame.getbbox() is not None


def _wide_row_strip():
    """The live shape: every pose carries a thin wide row of its OWN art.

    Poses sit close enough that the strip-level merge collapses them, so this
    goes down the gutter path and each pose is isolated inside its own narrow
    crop — the exact place the eraser used to mistake a body row for a floor.

    What separates a body row from a floor is not how wide it is but whether the
    OTHER poses are wide at the same height. Only two frames get a bar, and each
    sits where every pose is narrow, so at strip scale the row is ~55% covered
    (no floor) while inside that pose's own slot it clears 85% and used to be
    deleted. This is the live artifact's shape: real poses differ frame to frame,
    which is why nothing was erased from the strip but plenty was from the slots.
    """
    width, height = _SEAM_SLOT * _SEAM_FRAMES, 800
    img = Image.new("RGBA", (width, height), CHROMA)
    draw = ImageDraw.Draw(img)
    rx, ry, cy = 95, 140, 400
    bars = {3: cy - 120, 6: cy + 108}
    for i in range(_SEAM_FRAMES):
        cx = i * _SEAM_SLOT + _SEAM_SLOT // 2
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(60, 90, 200, 255))
        if i in bars:
            top = bars[i]
            draw.rectangle((cx - rx, top, cx + rx, top + 4), fill=(60, 90, 200, 255))
    return img


def test_a_poses_own_wide_row_is_not_erased_into_a_scanline():
    frames = atlas.extract_strip_frames(_wide_row_strip(), _SEAM_FRAMES, method="auto", fit=False)

    assert len(frames) == _SEAM_FRAMES
    scanlines = {i: _interior_empty_rows(f) for i, f in enumerate(frames)}
    assert all(rows == [] for rows in scanlines.values()), scanlines

    # An erased row does not always leave a hole: when it cuts near one end, the
    # smaller slab is dropped as noise and the pose silently loses its head. So
    # measure the pose too — every frame must still be as tall as its unbarred
    # neighbours.
    heights = [f.getbbox()[3] - f.getbbox()[1] for f in frames]
    assert max(heights) - min(heights) <= 6, heights


def _frame_with(boxes, size=(220, 600)):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for left, top, right, bottom in boxes:
        draw.rectangle((left, top, right - 1, bottom - 1), fill=(200, 60, 60, 255))
    return img


def _multi_subject_frames():
    scattered = _frame_with([(20, 20, 200, 180), (20, 260, 200, 420), (20, 500, 200, 590)])
    plain = _frame_with([(20, 200, 200, 400)])
    return [plain, plain, scattered] + [plain] * 5


def _width_outlier_frames():
    narrow = _frame_with([(90, 200, 130, 400)])
    wide = _frame_with([(20, 200, 420, 400)], size=(440, 600))
    return [narrow] * 7 + [wide]


@pytest.mark.parametrize(
    "frames,message",
    [
        (_multi_subject_frames, "multiple separated subjects"),
        (_width_outlier_frames, "multi-pose width outlier"),
    ],
)
def test_a_soft_check_raises_strict_and_only_warns_lenient(frames, message, caplog):
    built = frames()

    with pytest.raises(ValueError, match=message):
        atlas._validate_extracted_frames(built, 8, strict=True)

    with caplog.at_level(logging.WARNING, logger=atlas.__name__):
        atlas._validate_extracted_frames(built, 8, strict=False)

    assert any(message in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("strict", [True, False])
def test_an_empty_frame_is_a_hard_error_under_both_methods(strict):
    frames = [_frame_with([(20, 200, 200, 400)])] * 7 + [_frame_with([])]

    with pytest.raises(ValueError, match="frame 7 is empty"):
        atlas._validate_extracted_frames(frames, 8, strict=strict)


@pytest.mark.parametrize("strict", [True, False])
def test_a_short_frame_count_is_a_hard_error_under_both_methods(strict):
    frames = [_frame_with([(20, 200, 200, 400)])] * 7

    with pytest.raises(ValueError, match="expected 8 frames, got 7"):
        atlas._validate_extracted_frames(frames, 8, strict=strict)


def test_a_fully_keyed_out_strip_still_raises_under_auto():
    blank = Image.new("RGBA", (_SEAM_SLOT * _SEAM_FRAMES, 800), CHROMA)

    with pytest.raises(ValueError):
        atlas.extract_strip_frames(blank, _SEAM_FRAMES, method="auto", fit=False)
