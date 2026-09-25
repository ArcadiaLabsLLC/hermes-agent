"""Palette and frame packing (the no-flip chokepoint) and ``validate_sheet``."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from agent.charsheet._upstream_doors import CELL_HEIGHT, CELL_WIDTH, _clear_transparent_rgb, _fit_to_cell, extract_strip_frames, normalize_cells, remove_background
from agent.charsheet.palette import DEFAULT_MAX_COLORS, build_palette, lock_to_palette
from agent.charsheet.spec import SheetSpec

from .geometry import _open_rgba
from .handedness import accept_basis_token, detect_mirrored_art
from .handedness_report import mirrored_art_error

__layer__ = "lanes"


# ─────────────────────────── compose / validate ───────────────────────────


def build_sheet_palette(palette_sources: Iterable, *, max_colors: int = DEFAULT_MAX_COLORS):
    """The locked palette for a sheet, from its approved grounding references.

    The references on disk carry the magenta field, so they are keyed back to
    cutouts first: leaving the chroma in would spend palette slots on a colour
    that must never reach a cell, and would pull every locked pixel toward
    magenta. §7.2 specifies the *cutouts'* opaque pixels, and this is where that
    happens — :func:`~agent.charsheet.palette.build_palette` deliberately knows
    nothing about chroma keys.
    """
    cutouts = [remove_background(_open_rgba(source)) for source in palette_sources]
    if not cutouts:
        raise ValueError("build_sheet_palette needs at least one approved reference")
    return build_palette(cutouts, max_colors=max_colors)


def compose_draft_frames(
    spec: SheetSpec,
    strips_by_key: dict[str, Path],
    palette_sources: list[Path],
) -> dict[str, list]:
    """Approved strips → registered, palette-locked cells for every sheet row.

    Order matters and is fixed by the plan (§4.3):

    1. Extract raw (``fit=False``) frames from each row's strip. Every row is an
       authored one — mirrored directions are never composed (ruling 3-B), so
       there is no derive step here and no ``mirror_frames`` call anywhere in
       this package; the consumer flips them at draw time.
    2. ``normalize_cells`` over ALL rows at once. One shared scale is the whole
       point: a character that changes size as it turns is the failure this
       prevents, and per-row normalization would guarantee it. Dropping the
       mirrored rows does not move that scale — a horizontal flip preserves
       every bounding box it measures.
    3. Palette-lock every cell.

    Re-extraction uses ``method="auto"``: the strict geometry gate already ran at
    generation time (a strip only became approvable by slicing), so compose must
    be deterministic and total, not a second chance to fail.
    """
    frames_by_key: dict[str, list] = {}
    for row in spec.authored_rows():
        strip = strips_by_key.get(row.key)
        if strip is None:
            raise ValueError(
                f"no strip for authored row {row.key!r}; rows present: "
                f"{sorted(strips_by_key)}"
            )
        frames_by_key[row.key] = extract_strip_frames(
            Path(strip), row.frames, method="auto", fit=False
        )

    normalized = normalize_cells(frames_by_key)
    palette = build_sheet_palette(palette_sources)
    return {
        key: [lock_to_palette(cell, palette) for cell in cells]
        for key, cells in normalized.items()
    }


def compose_sheet(spec: SheetSpec, cells_by_key: dict[str, list]):
    """Pack cells into the sheet described by *spec* (RGBA, residue cleared).

    Row placement is ``row.index`` from the spec, column placement is frame
    order; a row with missing or short cell lists leaves its tail transparent
    rather than shifting anything.
    """
    from PIL import Image

    width, height = spec.sheet_size()
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for row in spec.rows():
        cells = cells_by_key.get(row.key) or []
        for column, frame in enumerate(cells[: row.frames]):
            cell = frame.convert("RGBA")
            if cell.size != (spec.frame_w, spec.frame_h):
                if (spec.frame_w, spec.frame_h) != (CELL_WIDTH, CELL_HEIGHT):
                    raise ValueError(
                        f"cell {column} of row {row.key!r} is "
                        f"{cell.width}x{cell.height}, expected "
                        f"{spec.frame_w}x{spec.frame_h}; only the upstream "
                        f"{CELL_WIDTH}x{CELL_HEIGHT} cell geometry can be re-fitted"
                    )
                cell = _fit_to_cell(cell)
            sheet.alpha_composite(cell, (column * spec.frame_w, row.index * spec.frame_h))
    return _clear_transparent_rgb(sheet)


def _rgb_residue_count(rgba) -> int:
    """Transparent pixels that still carry colour, counted in Pillow's C loops.

    The same predicate the pixel-by-pixel version used — ``alpha == 0 and any of
    R, G, B``— expressed as band operations, because this walks every pixel of
    the sheet on EVERY compose and the Python loop was 0.39 s of a 3.0 s
    ``validate_sheet`` on a 576x3120 fixture (12x, measured 2026-08-25). Pillow
    only: ``numpy`` is absent from the venv this pipeline runs in.
    """
    from PIL import ImageChops

    red, green, blue, alpha = rgba.split()
    coloured = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
        lambda value: 255 if value else 0
    )
    clear = alpha.point(lambda value: 255 if value == 0 else 0)
    return sum(ImageChops.multiply(coloured, clear).histogram()[1:])


def validate_sheet(
    spec: SheetSpec, image, *, accept_handedness: Sequence[str] = ()
) -> dict:
    """Geometry, occupancy, collapse and residue checks, driven by *spec*.

    Returns ``{ok, width, height, errors, warnings, filled_rows, handedness}``.
    Errors block an install (wrong size, empty sheet, sprites collapsed by a bad
    row, a multi-pose frame that slipped the extractor, RGB residue under
    transparency, a row drawn as the mirror of the direction it claims); a
    single blank row is a warning, because which rows are required is the
    caller's policy, not the validator's.

    The geometry guards are upstream's ``validate_atlas`` guards generalized off
    ``ROW_SPECS``: the collapse floor exists because ``normalize_cells`` shares
    one scale across all rows, so one degenerate row can shrink the entire
    character while every cell still passes a non-empty check (§A-5).

    ``handedness`` is :func:`detect_mirrored_art`'s whole answer, carried in the
    payload whether or not it found anything — including its ``unjudged`` list,
    so a caller can always see which rows this could not answer for.

    **Only a finding carrying ``severity: "error"`` blocks**, and there are two
    such shapes (see :func:`detect_mirrored_art`): one row that BOTH passes
    agree about, and a whole STATE whose every judged row reads as a mirror. A
    single-basis finding about a single row is a WARNING with the whole text
    intact. That is not a softening for convenience, it is what the measurements
    force: the true floor on real art is +6.78% rotation / +7.64% states and the
    false ceiling on correct art displaced sideways is +18.75%, so on ONE
    reading about ONE row the two populations overlap and no threshold separates
    them. Round one made every flagged row a refusal, which bought certainty it
    did not have and pointed ``reroll-row`` at correct art in two reachable
    shapes. Say the consequence out loud: ``characters start`` creates ``idle:6,
    walk:8``, the cross-state pass needs three states, so on the DEFAULT
    character neither refusal is reachable and this check can only ever warn —
    and on a two-state cut of the live art a whole mirrored state already scored
    bit-identical to the correct sheet, so it was nearly blind there before any
    of this existed.

    **``accept_handedness`` is the one way past a refusal, it names rows, and it
    names the basis with them.** It applies to the ERROR cases only: there is
    nothing to accept about a warning, which does not block. A row refused on
    two bases is refused by two independent bodies of evidence, and a bare row
    name waived both at once — an operator accepting a PLACEMENT reading also
    silenced the cross-state one, which placement cannot explain. So the token
    names what is being waived and is DERIVED from the finding
    (:func:`accept_basis_token`): ``<row>:rotation+states`` for a two-basis
    refusal, ``<row>:states`` for a whole-state one. A bare ``<row>`` is refused
    with the spelling it needs. **Both error shapes are overridable, and that is
    a requirement rather than a convenience: an error with no way past it is a
    wall, and ``compose`` has no other door.** A whole-state refusal is still
    accepted one ROW at a time — a state-wide reading waived state-wide, in one
    token, is the blanket this grammar exists to refuse. An accepted row becomes
    a warning that still carries the whole refusal text, and rides in
    ``handedness["accepted"]`` as ``{row, gain, basis}`` — accepting a +40%
    finding and an +8.1% one used to be indistinguishable afterwards. Naming a
    row that was NOT flagged is itself an error: an acceptance with nothing to
    accept is a bypass lying in wait for the next refusal.

    **A malformed acceptance is folded into the block for the row it names**,
    rather than appended beside it. A bare row name used to produce two entries
    in ``errors`` about one finding — the acceptance complaint, and then the
    entire diagnostic again underneath it — so the message an operator got for
    typing the flag wrong was LONGER than the refusal that taught them the flag,
    and 79% of it was text they had just read. One row is one block, and the
    spelling the validator wants is printed once, on that block's ``accept``
    line, through :func:`accept_basis_token`. An acceptance naming a row that is
    not on the sheet, was never flagged, or only warned has no block to fold
    into and stays an error of its own.
    """
    rgba = _open_rgba(image)
    errors: list[str] = []
    warnings: list[str] = []
    expected = spec.sheet_size()
    if rgba.size != expected:
        errors.append(
            f"expected {expected[0]}x{expected[1]}, got {rgba.width}x{rgba.height}"
        )
        return {
            "ok": False,
            "width": rgba.width,
            "height": rgba.height,
            "errors": errors,
            "warnings": warnings,
            "filled_rows": [],
            "handedness": {
                "flagged": [],
                "accepted": [],
                "judged": [],
                "unjudged": [
                    {
                        "rows": [row.key for row in spec.rows()],
                        "reason": (
                            "the sheet is not the size its spec describes; rows "
                            "cannot be cut out of it"
                        ),
                    }
                ],
            },
        }

    filled_rows: list[str] = []
    boxes_by_row: dict[str, list[tuple[int, int, int, int]]] = {}
    for row in spec.rows():
        row_pixels = 0
        boxes: list[tuple[int, int, int, int]] = []
        top = row.index * spec.frame_h
        for column in range(row.frames):
            left = column * spec.frame_w
            cell = rgba.crop((left, top, left + spec.frame_w, top + spec.frame_h))
            row_pixels += sum(cell.getchannel("A").histogram()[1:])
            bbox = cell.getbbox()
            if bbox is not None:
                boxes.append(bbox)
        if row_pixels > 0:
            filled_rows.append(row.key)
            boxes_by_row[row.key] = boxes
        else:
            warnings.append(f"row '{row.key}' has no frames")

    if not filled_rows:
        errors.append("sheet is empty — no row produced any frames")

    all_widths = sorted(
        right - left for boxes in boxes_by_row.values() for left, _t, right, _b in boxes
    )
    all_heights = sorted(
        bottom - top for boxes in boxes_by_row.values() for _l, top, _r, bottom in boxes
    )
    global_med_w = 0
    global_med_h = 0
    if all_widths and all_heights:
        global_med_w = all_widths[len(all_widths) // 2]
        global_med_h = all_heights[len(all_heights) // 2]
        min_h = max(56, round(spec.frame_h * 0.28))
        if global_med_h < min_h:
            errors.append(
                f"sheet sprites are too small after normalization (median frame "
                f"height {global_med_h}px, floor {min_h}px)"
            )

    for key, boxes in boxes_by_row.items():
        if len(boxes) <= 1:
            continue
        widths = sorted(right - left for left, _t, right, _b in boxes)
        heights = sorted(bottom - top for _l, top, _r, bottom in boxes)
        med_w = max(1, widths[len(widths) // 2])
        med_h = max(1, heights[len(heights) // 2])
        if widths[-1] > max(med_w * 3.0, med_w + 96) and heights[-1] <= med_h * 1.6:
            errors.append(f"row '{key}' contains a multi-pose frame outlier")
        # The `if global_med_w and global_med_h:` guard that used to wrap this
        # was a branch no sheet could take, and is deleted (2026-09-05, off the
        # one-armed-branch report). Reaching this line means `boxes_by_row`
        # carries a row with at least two boxes; every box is a `getbbox()` and
        # so spans at least one pixel; and a non-empty `boxes_by_row` is exactly
        # what makes `all_widths`/`all_heights` non-empty above, which is what
        # assigns both medians. Both are therefore >= 1 here, and the zeroes
        # they are initialised to are only ever read by the check above this
        # loop.
        if med_w < max(32, round(global_med_w * 0.42)) or med_h < max(
            40, round(global_med_h * 0.50)
        ):
            errors.append(
                f"row '{key}' appears collapsed (median {med_w}x{med_h}px, "
                f"sheet median {global_med_w}x{global_med_h}px)"
            )

    residue = _rgb_residue_count(rgba)
    if residue:
        errors.append(f"{residue} transparent pixels retain RGB residue")

    # Last, after the collapse/outlier/residue checks above — but NOT conditional
    # on them: only the wrong-SIZE early return short-circuits this, and every
    # other error still leaves the handedness answer in the payload. Its findings
    # are errors unless the operator accepted that row by name — see the
    # docstring for why this one is not allowed to be a plain warning.
    handedness = detect_mirrored_art(spec, rgba)
    flagged_by_row = {finding["row"]: finding for finding in handedness["flagged"]}
    known_rows = {row.key for row in spec.rows()}
    accepted: list[dict] = []
    # A complaint about a MALFORMED acceptance is folded into the block for the
    # row it is about, never appended beside it. Both used to be entries in
    # `errors` about the same finding, so `--accept-handedness walk-e` printed
    # the acceptance complaint and then the whole diagnostic a second time
    # underneath it — measured 2026-08-26 at 1519 characters against the plain
    # refusal's 1206, of which 1206 was text the operator had just read. There
    # is one row, so there is one block.
    acceptance_notes: dict[str, list[str]] = {}
    for token in dict.fromkeys(str(row).strip() for row in accept_handedness):
        if not token:
            continue
        key, _colon, basis = token.partition(":")
        key = key.strip()
        basis = basis.strip()
        finding = flagged_by_row.get(key)
        if key not in known_rows:
            errors.append(
                f"handedness acceptance names {key!r}, which is not a row of this "
                f"sheet ({', '.join(sorted(known_rows))})"
            )
        elif finding is None:
            errors.append(
                f"handedness acceptance names {key!r}, which was not flagged — an "
                "acceptance with nothing to accept is a bypass waiting for the "
                "next refusal; drop it"
            )
        elif finding.get("severity") != "error":
            errors.append(
                f"handedness acceptance names {key!r}, which is a WARNING and "
                "does not block this install — there is nothing to accept. Only "
                "a row both passes agree about is refused; drop it"
            )
        elif not basis:
            acceptance_notes.setdefault(key, []).append(
                f"--accept-handedness {key}, with no basis. "
                + (
                    "That row is refused because its whole state reads as "
                    "mirrored, and the evidence is every judged row of "
                    f"{finding['state']!r} — a bare row name waives a "
                    "state-wide reading one row at a time without saying so. "
                    if finding.get("wholeState")
                    else "That row is refused because TWO independent reads "
                    "agree about it, and a bare row name waives both — "
                    "including the cross-state evidence, which a placement or "
                    "framing argument cannot explain. "
                )
                + "Name what you are waiving; the spelling this finding needs is "
                "on the accept line below."
            )
        elif basis != accept_basis_token(finding["basis"]):
            acceptance_notes.setdefault(key, []).append(
                f"--accept-handedness {key}:{basis}, but this finding's bases are "
                f"{finding['basis']!r}, so the acceptance is spelled "
                f"{key}:{accept_basis_token(finding['basis'])}."
            )
        else:
            accepted.append(
                {"row": key, "gain": finding["gain"], "basis": finding["basis"]}
            )
    handedness["accepted"] = accepted
    accepted_rows = {entry["row"] for entry in accepted}
    for finding in handedness["flagged"]:
        waived = finding["row"] in accepted_rows
        message = mirrored_art_error(
            finding,
            acceptance_error=" ".join(acceptance_notes.get(finding["row"], ())) or None,
            accepted=waived,
        )
        if waived:
            warnings.append(f"handedness accepted by the operator — {message}")
        elif finding.get("severity") == "error":
            errors.append(message)
        else:
            # The disposition rides on the block's own headline now, so the
            # list-level tag says only which list this is.
            warnings.append(f"handedness warning — {message}")

    return {
        "ok": not errors,
        "width": rgba.width,
        "height": rgba.height,
        "errors": errors,
        "warnings": warnings,
        "filled_rows": filled_rows,
        "handedness": handedness,
    }
