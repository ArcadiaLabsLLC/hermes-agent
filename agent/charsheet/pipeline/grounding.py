"""Grounding pixel work: cutout onto magenta, cell framing, the face offset, upscale and pad."""

from __future__ import annotations

from agent.charsheet._upstream_doors import frame_x_bounds, remove_background
from agent.charsheet.palette import as_rgba

from .geometry import MAGENTA, MAX_THUMB_PIXELS, QA_BACKDROP, require_scale

__layer__ = "policy"


# ───────────────────────── grounding references ─────────────────────────


def recomposite_on_magenta(image_or_path):
    """The cutout over a flat magenta field — a usable grounding reference.

    Slicing a turnaround leaves transparent cutouts, but the row prompt anchors
    the backdrop to "the same flat chroma field as the attached reference". A
    transparent reference silently removes that anchor, so the field is painted
    back in (plan §7.3, assumption A-2).
    """
    from PIL import Image

    cutout = as_rgba(image_or_path)
    field = Image.new("RGBA", cutout.size, (*MAGENTA, 255))
    field.alpha_composite(cutout)
    return field


def frame_cell(image_or_path, *, frame: int, frames: int):
    """Crop ONE frame cell out of a row strip, at full strip height.

    The half of the §F.2 procedure that actually REMOVES pixels. A row strip is
    already one row, so upscaling the whole strip is not a crop at all — it is
    an enlargement, and at card size it resolves no better than the raw attempt
    it was made from (measured 2026-08-24: ≤2/255 per channel against the source
    at 360 px, 0 of 86_400 pixels differing by more than 8). The remaining
    reduction is per-frame, and a frame is the unit an operator judges: within-
    strip identity means a defect is looked for frame by frame.

    Frame geometry is NOT this module's to invent: the x-range comes from
    :func:`atlas.frame_x_bounds`, the same content-aware rule the real frame
    extraction uses (gutters between poses, merged down to the frame count;
    thin severs at the expected boundaries when the poses touch; even columns
    ONLY as the last resort, when there is no content to read at all). This
    module used to divide the width by *frames* and call that a frame, and on
    2026-08-28 an operator opened the result fullscreen and found half a
    character: `walk-e` attempt 1 is a 2172px 8-frame row whose first pose spans
    x 66-298, the even boundary falls at 272, and the QA crop stopped there —
    26 columns of body cut off, the cut edge standing as a 205px column of
    pixels flush against the frame's right side. Even slots are wrong on real
    strips, which is exactly why the extraction is content-aware; one strip with
    two boundary rules meant the dumb one was feeding the surface whose whole
    job is to show an operator the truth.

    Full height is kept deliberately — a seam sits wherever the model drew it,
    and trimming to the subject would be this module guessing which pixels the
    operator came to look at. Width is the pose's, height is the strip's, and
    the asymmetry is the point: a frame boundary is a fact about the row that
    can be read off the pixels, a subject's top and bottom are not.

    The strip is decoded ONCE and the open image is handed to the geometry, so
    finding the boundary costs a keying pass, not a second read from disk.
    """
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
        raise ValueError(f"frames must be an integer >= 1, got {frames!r}")
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise ValueError(f"frame must be an integer, got {frame!r}")
    if not 0 <= frame < frames:
        raise IndexError(
            f"frame {frame} out of range: this row has {frames} frame(s), "
            f"addressed 0-{frames - 1}"
        )
    strip = as_rgba(image_or_path)
    left, right = frame_x_bounds(strip, frames)[frame]
    if right <= left:
        raise ValueError(
            f"a {strip.width}px strip cannot be split into {frames} frame(s): "
            f"frame {frame} would be empty"
        )
    return strip.crop((left, 0, right, strip.height))


#: The share of the subject's own bounding box, from the top, that is read as
#: the HEAD. A quarter, because a standing figure's head is about that, and
#: because the measure is a comparison against the same figure's body centre —
#: a band that is somewhat too tall or too short moves both centroids toward
#: each other and shrinks the number, it does not change its SIGN, which is the
#: half anything reads.
FACE_BAND = 0.25


def _column_centroid(rgba) -> float | None:
    """The alpha-weighted horizontal centroid of *rgba*, or ``None`` if empty.

    Through a one-row resize rather than a pixel loop: the same column-profile
    trick :func:`agent.pet.generate.atlas.normalize_cells` registers with, which
    makes this O(width) in Python instead of O(pixels) — a 1024-square reference
    is a million pixels and this is called once per approved direction.
    """
    from PIL import Image

    profile = list(rgba.getchannel("A").resize((rgba.width, 1), Image.BILINEAR).getdata())
    total = sum(profile)
    if not total:
        return None
    return sum(x * weight for x, weight in enumerate(profile)) / total


def face_offset(image_or_path) -> float | None:
    """How far the HEAD sits from the body's own centre, in pixels; ``None`` if empty.

    Positive is a head to the RIGHT of frame, negative to the left, and that
    sign is the whole reading — it is the quantity the 2026-08-25 field notes
    measured by hand when they found an approved ``e`` reference facing west
    (``-44.8``) while all three ``e`` rows drawn from it faced east (``+10.9``,
    ``+9.9``, ``+10.5``). The reference carried IDENTITY and the row prompt
    carried FACING, so a clean ``approve-direction`` certified nothing about the
    direction it was approving. This is what the approval now reports.

    **It is a measurement, not a verdict.** There is no threshold here and no
    boolean: a number and its sign, published for a person and for a later
    comparison against the rows. A gate would need to know what a correct offset
    is for each of eight sectors on an unknown character, which nothing does —
    the front and back views legitimately measure near zero, and the diagonals
    are small on purpose.

    Both centroids are alpha-weighted, and the chroma field is keyed out first:
    every generated reference is full-bleed magenta at alpha 255, and a measure
    that skipped the keying step would return the centroid of the CANVAS — 0.0
    for every picture ever drawn.

    ``None`` for an empty picture, never ``0.0``: "there is nothing here" and
    "it faces straight at you" are different answers.
    """
    rgba = remove_background(as_rgba(image_or_path), chroma_key=MAGENTA)
    box = rgba.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    subject = rgba.crop(box)
    body = _column_centroid(subject)
    if body is None:
        return None
    band = max(1, round((bottom - top) * FACE_BAND))
    head = _column_centroid(subject.crop((0, 0, right - left, band)))
    if head is None:
        return None
    # One decimal, because that is the precision the field notes are written in
    # and the precision a receipt can be read at; the underlying centroids carry
    # no more meaning than that.
    return round(head - body, 1)


def reference_cell(image_or_path):
    """The whole of a single-pose image, as the QA cell to crop.

    :func:`frame_cell`'s counterpart for a picture that holds ONE pose — a
    turnaround direction reference. There is no strip to slice, so the cell IS
    the image, and the honest way to say that is a named function rather than a
    ``frames=1`` call into geometry whose whole job is finding the gutters
    between poses.

    It lives here rather than in the draft machine because decoding pixels is
    this module's job: the caller weighs a size and writes a file, and never
    opens one.
    """
    return as_rgba(image_or_path)


def upscale_on_backdrop(
    image_or_path,
    *,
    scale: int,
    backdrop=QA_BACKDROP,
    chroma_key: tuple[int, int, int] | None = MAGENTA,
):
    """The §F.2 looking procedure: key, composite on flat dark, NEAREST upscale.

    Three steps, all learned the expensive way on 2026-08-24. **Key the chroma
    field out** because everything this package generates arrives on a full-bleed
    magenta field at alpha 255 — composite that over a backdrop and the backdrop
    is replaced pixel for pixel, so a "flat dark ground" that never renders is
    exactly as useful as no ground at all. And §F.1's actual complaint is that
    the seam is invisible *against the magenta*. **A flat opaque backdrop**
    because once the field is gone the pixels a QA surface must judge sit over
    transparency, and a dark line drawn over transparency renders as nothing at
    all in a chat card. **NEAREST** because any smoothing filter averages a
    one-pixel seam into its neighbours — the defect is destroyed by the very
    step meant to make it visible.

    *chroma_key* is the field to remove; ``None`` composites the source as it
    stands (for an image that is already a cutout). An image that already
    carries transparency is left alone by the keyer either way.

    The output pixel count is checked against the WRITE-SAFETY ceiling BEFORE
    the resize (:data:`MAX_THUMB_PIXELS`) and the refusal names the source
    dimensions, so a caller can see which half of ``source x scale**2`` was the
    problem. That ceiling is about what may exist on disk, not about what a chat
    card may decode — that is :data:`MAX_CONSOLE_CARD_PIXELS`, applied (with
    the draft's own sheet bound) by the verb that knows which crop is the
    default one.

    Returns an RGBA image whose alpha is 255 everywhere *when the backdrop is
    opaque* (the default). With :data:`TRANSPARENT_BACKDROP` the keyed sprite's
    own alpha survives — the console-card lane, where the viewer draws the
    ground.
    """
    from PIL import Image

    scale = require_scale(scale)
    source = as_rgba(image_or_path)
    pixels = source.width * source.height * scale * scale
    if pixels > MAX_THUMB_PIXELS:
        raise ValueError(
            f"scale {scale} on a {source.width}x{source.height} source would write "
            f"{source.width * scale}x{source.height * scale} = {pixels:,} pixels, "
            f"over the {MAX_THUMB_PIXELS:,}-pixel write budget; ask for a smaller "
            "scale, or a single frame instead of a whole strip"
        )
    if chroma_key is not None:
        source = remove_background(source, chroma_key=tuple(chroma_key))
    field = Image.new("RGBA", source.size, tuple(backdrop))
    field.alpha_composite(source)
    if scale == 1:
        return field
    return field.resize((field.width * scale, field.height * scale), Image.NEAREST)


def pad_to_square(image_or_path, *, backdrop=QA_BACKDROP):
    """Centre a FINISHED crop on a square field of the same flat dark ground.

    The console's hero card is a fixed 1:1 centre-cover square (§13.17) and a
    character cell is taller than it is wide, so an unpadded crop is drawn there
    as a torso zoom — the operator is shown the middle of a frame and told it is
    the frame. The launcher's card geometry is ruled and is not moving, so the
    fix is on this side: hand the card a picture whose whole content already sits
    inside the square it will draw.

    **Additive by construction.** Side is ``max(width, height)``, so the shorter
    axis gains margin and NEITHER axis loses a pixel — this is the one step in
    the looking procedure that cannot remove anything. It runs last, after
    :func:`upscale_on_backdrop`, because a pad before the NEAREST upscale would
    be enlarged along with the art and the margins would stop being a known flat
    colour. Same *backdrop* as the upscale for the same reason it has one at all:
    a second ground colour in one picture reads as a second image.

    The write-safety ceiling is checked against the PADDED size and before the
    field is allocated — padding raises the pixel count, and the count that
    matters is the file's.
    """
    from PIL import Image

    source = as_rgba(image_or_path)
    side = max(source.width, source.height)
    pixels = side * side
    if pixels > MAX_THUMB_PIXELS:
        raise ValueError(
            f"padding a {source.width}x{source.height} crop square would write "
            f"{side}x{side} = {pixels:,} pixels, over the {MAX_THUMB_PIXELS:,}-pixel "
            "write budget; ask for a smaller scale, or take the crop without --square"
        )
    if source.width == source.height:
        return source
    field = Image.new("RGBA", (side, side), tuple(backdrop))
    field.alpha_composite(source, ((side - source.width) // 2, (side - source.height) // 2))
    return field
