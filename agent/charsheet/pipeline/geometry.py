"""Charsheet geometry: the chroma field, the pixel budgets, the file prefixes, PNG/RGBA I/O."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from agent.charsheet import prompts
from agent.charsheet.palette import as_rgba
from agent.charsheet.spec import CHAR8, SheetSpec

__layer__ = "models"


# The chroma field every generated charsheet image is drawn on and every
# grounding reference is re-composited onto. Hot magenta is what the upstream
# prompt language asks for and what `remove_background`'s saturated fast path is
# tuned against.
MAGENTA: tuple[int, int, int] = (255, 0, 255)

# What a QA crop is composited onto. Near-black but not black: an image with a
# black outline still reads against it, while a hole in the art does not
# masquerade as one. Opaque by construction — the whole point of the backdrop is
# that a defect over TRANSPARENT pixels shows up as something rather than as
# nothing (the 2026-08-24 seam hunt, plan §F.2).
#
# It only shows through something that HAS transparency, which is why
# `upscale_on_backdrop` keys the chroma field out first: a row attempt off the
# provider is a full-bleed magenta field at alpha 255 everywhere, and
# compositing that over the backdrop replaces every backdrop pixel — the step
# renders, costs a full-image composite, and changes nothing.
QA_BACKDROP: tuple[int, int, int, int] = (18, 18, 22, 255)

# The console-card ground (operator ruling 2026-08-29): a `--square` card crop
# keeps the keyed sprite's transparency and lets the console draw its own
# ground (checkerboard) behind it. Compare crops keep QA_BACKDROP — flat opaque
# is the looking procedure's considered design, where a 1-px seam must not
# vanish into a viewer's unknown flatten color.
TRANSPARENT_BACKDROP: tuple[int, int, int, int] = (0, 0, 0, 0)

# Two bounds with two different correct values. They were ONE number until a
# 2026-08-24 re-review, and one number could not be right for both.
#
# `MAX_THUMB_PIXELS` is the WRITE-SAFETY ceiling — what this package may put on
# disk at all, evaluated before the resize. The old ceiling was a bare
# `1 <= scale <= 8`: a count with no relationship to the source. `--scale 8` on a
# live 1536x1024 row attempt wrote 12288x8192 = 100_663_296 pixels — past
# Pillow's own `Image.MAX_IMAGE_PIXELS` bomb threshold (89_478_485), so the verb
# produced a file Pillow refuses to reopen without a `DecompressionBombWarning`,
# and RAISES for a caller running under `-W error`. The quantity a caller cares
# about is the output's pixel count; a scale factor alone can never express it,
# because the same factor is harmless on one source and a bomb on another.
#
# 16M pixels is 64 MiB decoded RGBA: under a fifth of Pillow's threshold, so a
# crop this package writes always reopens cleanly.
MAX_THUMB_PIXELS = 16_000_000

# `MAX_CONSOLE_CARD_PIXELS` is the CONSOLE DECODE ceiling — *will this file
# sink a chat card* — and it is ONE of the two bounds a crop is weighed against.
# Launcher risk D.3 asks `thumb` to retire the cost of decoding a full sheet
# into a chat card, and states a second check plainly: *a crop that is not
# smaller than the sheet is not a mitigation.* Those are two different
# questions, and until 2026-08-25 one boolean answered both under one name.
#
# A bomb threshold cannot express either — it sits 28x above the sheet, so
# `--scale 8` on a live attempt passed the write ceiling at 2176x5792 =
# 12_603_392 px, 3.94x the sheet it is supposed to be lighter than, and nothing
# in the payload said so.
#
# So this budget is SIZED from a sheet — `CHAR8`, 1536x2080 = 3_194_880 px /
# 12.2 MiB decoded RGBA, the largest sheet this package's default spec composes
# — but what it MEANS is a fixed console decode ceiling, never *is this lighter
# than the sheet in your hand*. It is a module constant. It does not move with a
# draft, and :func:`fits_console_budget` has never compared anything to the
# caller's own sheet.
#
# An earlier wording of this comment claimed the opposite — "a sheet that grows
# moves the budget with it, and the number can never drift from the thing it is
# measured against" — and both halves are false, measured at both ends:
#
#   * GROWN: `characters add-state --state jumping:6` recomposed the live
#     `anime-girl` sheet at 1536x3120 = 4_792_320 px, **1.50x this number**,
#     which did not move. On such a draft the default-scale refusal in
#     `draft.row_thumb` can reject a crop that is genuinely lighter than the
#     sheet that draft will compose.
#   * SMALL: a `--directions 4`, `idle:2` draft composes 384x624 = 239,616 px,
#     **13.3x lighter than this number**, so a crop that clears this budget can
#     be many times that draft's whole sheet (A2 measured 1774x1774 =
#     3_147_076 px live, 13.1x, and 1.5% under this ceiling).
#
# Those two measurements are why the boolean was SPLIT rather than re-aimed
# (owner ruling 2026-08-25). This constant answers the console question and
# keeps its old value; :func:`fits_own_sheet` answers the sheet question against
# the draft's OWN `spec.sheet_size()`; `draft.row_thumb` carries both answers.
# The name says which one this is, because the name is what a reader trusts.
MAX_CONSOLE_CARD_PIXELS = CHAR8.sheet_size()[0] * CHAR8.sheet_size()[1]


def require_scale(scale) -> int:
    """The ONE gate on an upscale factor; returns it, or refuses with a reason.

    Public because two callers must agree: :func:`upscale_on_backdrop` reads it
    before allocating, and a caller weighing the OUTPUT against a budget has to
    know the number is an int before multiplying by it — ``512 * "2"`` is a
    perfectly good string, and arithmetic on one is how a type error reaches a
    consumer wearing a budget refusal's clothes. A second spelling of this
    check is a second answer to "is 0 a scale?".
    """
    if isinstance(scale, bool) or not isinstance(scale, int) or scale < 1:
        raise ValueError(f"scale must be an integer >= 1, got {scale!r}")
    return scale


def fits_console_budget(width: int, height: int) -> bool:
    """Is a ``width`` x ``height`` image under the console's fixed decode ceiling?

    Pure, and public because the answer is a FACT a payload has to carry: the
    verb that writes a crop cannot know whether its caller will declare the path
    to a card or open it in a fullscreen viewer, so it reports which the file is
    fit for instead of guessing.

    This is HALF the question. It says the file will not sink the console; it
    says nothing about whether cropping bought anything, which is
    :func:`fits_own_sheet`. See :data:`MAX_CONSOLE_CARD_PIXELS`.
    """
    return width * height <= MAX_CONSOLE_CARD_PIXELS


def fits_own_sheet(width: int, height: int, spec: SheetSpec) -> bool:
    """Is a ``width`` x ``height`` image no larger than *spec*'s own sheet?

    The other half, and the one launcher risk D.3 actually states: *a crop that
    is not smaller than the sheet is not a mitigation.* It moves with the draft,
    because it is computed from that draft's ``spec.sheet_size()`` every time —
    which is exactly what :data:`MAX_CONSOLE_CARD_PIXELS` is not, and why one
    boolean could never carry both answers.

    The two disagree on real drafts in BOTH directions, which is the whole
    reason they are two booleans:

    * a ``--directions 4``, ``idle:2`` draft (384x624 = 239,616 px) took a
      default 1774x1774 = 3_147_076 px crop: under the console ceiling, 13.1x
      its own sheet.
    * an ``add-state``-grown ``anime-girl`` (1536x3120 = 4_792_320 px) can take
      a crop over the console ceiling that is still lighter than the sheet that
      draft will compose.

    ``<=`` rather than ``<``, matching :func:`fits_console_budget`: the
    guarantee is *not larger than*, and a name that promised *strictly smaller*
    would be the same defect one word further along.
    """
    sheet_w, sheet_h = spec.sheet_size()
    return width * height <= sheet_w * sheet_h


# A non-directional state has no facing to hold, but the row prompt is built
# around explicit view language. Front view is the neutral choice: it is the one
# view that shows the whole character, and a fixed row is drawn once and shown
# from whatever angle the consumer likes. Such rows are grounded on the base
# image, not on a direction reference (see `generate_row_strip`).
NON_DIRECTIONAL_VIEW = "s"

# Attempts per row strip, last one lenient — mirrors the pet hatch loop.
_ROW_GEN_ATTEMPTS = 3

# Provider-file prefixes. Public so tests and the CLI can key off them instead of
# duplicating the strings.
PREFIX_TURNAROUND = "charsheet_turnaround"


def view_prefix(direction: str) -> str:
    """Provider-file prefix for a single-view re-roll of *direction*."""
    return f"charsheet_view_{direction}"


def row_prefix(key: str) -> str:
    """Provider-file prefix for a row strip (``charsheet_row_walk-e``).

    Row keys are filename-safe by construction: the state half is
    ``[a-z][a-z0-9_]*`` and the separator is a hyphen, so the key travels into
    a provider filename verbatim.
    """
    return "charsheet_row_" + str(key)


def _save_png(image_or_path, out: Path) -> Path:
    """Write *image_or_path* to *out* as PNG, creating parent directories."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    as_rgba(image_or_path).save(out, format="PNG")
    return out


def turnaround_order(authored: Iterable[str]) -> tuple[str, ...]:
    """*authored* sorted in turnaround convention: front view first, back last.

    Derived from the compass ring in :data:`prompts.VIEW_LANGUAGE` rather than
    written out per scheme: each direction is ranked by its ring distance from the
    front view, so the 8-way authored set yields ``s, se, e, ne, n`` and the
    4-way set yields ``s, e, n`` with no direction count anywhere in the code.
    """
    ring = list(prompts.VIEW_LANGUAGE)
    if NON_DIRECTIONAL_VIEW not in ring:
        raise ValueError(
            f"prompts.VIEW_LANGUAGE has no {NON_DIRECTIONAL_VIEW!r} entry; the "
            "turnaround order is defined relative to the front view"
        )
    front = ring.index(NON_DIRECTIONAL_VIEW)
    size = len(ring)

    def rank(direction: str) -> tuple[int, int]:
        if direction not in ring:
            raise ValueError(
                f"unknown direction {direction!r}: no camera-view language for it "
                f"(known directions: {', '.join(ring)})"
            )
        offset = abs(ring.index(direction) - front)
        return (min(offset, size - offset), ring.index(direction))

    return tuple(sorted(authored, key=rank))
