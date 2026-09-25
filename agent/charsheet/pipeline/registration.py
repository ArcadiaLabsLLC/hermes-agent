"""Seam and registration arithmetic for the handedness detector, and its measured thresholds."""

from __future__ import annotations

from agent.charsheet.spec import RowSpec, SheetSpec

__layer__ = "policy"


# How much better a chain of authored directions must fit together once ONE row
# is flipped horizontally before we call that row's art mirrored.
#
# The number is measured, not chosen, and the population it separates was
# re-measured on 2026-08-25 once registration (below) entered the measure.
# Registration costs sensitivity — it takes back the part of the old signal that
# was really PLACEMENT — so both bands moved and the separation narrowed:
#
#   TRUE  (real art known to be mirrored): the live `anime-girl` pre-fix sheet's
#         three `ne` rows score +12.28% / +8.52% / +7.37%, and mirroring each of
#         the nine interior rows of the REPAIRED sheet one at a time scores
#         +4.33% ... +15.86%. Twelve samples, floor +4.33%.
#   FALSE (real art known to be correct): every interior row of the repaired
#         sheet reads -4.53% ... -18.85%, and `cobalt-robot-courier` — 4-way, a
#         satchel over one shoulder, deliberately asymmetric — reads +1.72%.
#         Ceiling +1.72%.
#
# **The threshold is not the lever, and moving it cannot become one.** Both
# bands were re-measured on 2026-08-25 in the direction the note above does not
# reach, and they OVERLAP:
#
#   The true floor is BELOW the line, on real art. Mirroring each interior row
#   of the repaired live sheet one at a time, `jumping-se` reads +6.78% in the
#   rotation and +7.64% across the states — flagged by NEITHER pass. That sheet
#   composes, installs and bundles with no refusal and no warning. The founding
#   defect sits AT the line: the pre-fix sheet's third genuinely mirrored row,
#   `jumping-ne`, reads +7.37%, and the install was refused only because the
#   other two cleared it.
#
#   The false ceiling is far ABOVE that floor once art is stressed. Sliding a
#   CORRECT `idle-e` sideways: -24 px reads +9.38%, -32 px +17.92%, -40 px
#   +18.75%, -56 px +7.76% and installs again. It is a BAND of roughly -20 to
#   -48 px, not a threshold.
#
# max(false) is about +18.75% and min(true) is +7.64%. An 8% line does not
# separate two populations there; it sits inside both of them. So the number
# stays where it is and what changed is what ONE reading is allowed to do: a
# single basis WARNS, and only two independent bases agreeing about the same row
# REFUSE (see :func:`detect_mirrored_art` and :func:`validate_sheet`). Sensitivity
# is bought back by the cross-state pass below and by the operator's eye, and the
# named acceptance in :func:`validate_sheet` is the door past a two-basis refusal.
#
# It is a RATIO on purpose: an absolute pixel distance is a property of the
# character's palette and silhouette and would need retuning per art style. A
# ratio is scale-free, and assumes nothing about skin tone, hue or style — only
# that a rotation sequence is a rotation sequence.
MIRROR_GAIN_THRESHOLD = 0.08


# How far one row may be slid sideways, before either distance is taken, so that
# PLACEMENT cannot be read as handedness. One twelfth of the frame each way —
# 16 px on the 192 px cell.
#
# Without this the measure has no registration step at all, and any horizontal
# displacement between neighbouring rows enters the distance and therefore the
# ratio. Measured on the REPAIRED (correct) live sheet by sliding `idle-e`
# sideways and changing nothing else: -7 px scored +9.81% and refused the
# install; -24 px scored +18.75%, past every genuine reading on the defective
# sheet. What kept that off real characters was ``normalize_cells`` centring each
# row on its union bbox — upstream pet code this package imports and does not
# own — and that centring is not as tight as it looks: it pins the union BOX,
# not the body, so the body still lands up to 10 px apart between neighbouring
# rows on art that passes (measured across all three states of the live sheet).
# The shipped measure charged all of that to handedness.
#
# The reachable driver is a PROP, not a stray offset: a bag, a cape or a sheathed
# sword hanging off one side of ONE row widens that row's union bbox, so centring
# it moves the BODY by half the prop's width. With this window a one-sided prop
# up to a quarter of the frame (48 px, body -24 px) still installs (+5.19%);
# without it a 24 px prop already refused (+9.05%).
#
# The window BOUNDS the blindness, it does not remove it: a pure translation
# larger than the window still crosses (-24 px reads +10.91% even registered).
# That residue is why the acceptance path in :func:`validate_sheet` exists.
REGISTRATION_WINDOW_DIVISOR = 12


def registration_window(frame_w: int) -> int:
    """Half-width, in pixels, of the shift search for a *frame_w*-wide cell."""
    return max(1, round(frame_w / REGISTRATION_WINDOW_DIVISOR))


def _cell_distance(left, right) -> float:
    """Mean absolute per-channel difference of two same-size RGBA cells.

    Pillow only. ``numpy`` is not a dependency of this package — it enters the
    project solely through the ``voice``/``wake`` extras — and the runtime venv
    this pipeline actually executes in does not have it. A gate that imports
    numpy is a gate that never runs where it matters.
    """
    from PIL import ImageChops, ImageStat

    difference = ImageChops.difference(left, right)
    return sum(ImageStat.Stat(difference).mean) / len(difference.getbands())


def _row_cells(rgba, spec: SheetSpec, row: RowSpec) -> list:
    """The row's frame cells, left to right, cut out of a composed sheet."""
    top = row.index * spec.frame_h
    return [
        rgba.crop(
            (
                column * spec.frame_w,
                top,
                (column + 1) * spec.frame_w,
                top + spec.frame_h,
            )
        )
        for column in range(row.frames)
    ]


def _padded(cell, pad: int):
    """*cell* on a transparent canvas *pad* px wider on each side."""
    from PIL import Image

    canvas = Image.new("RGBA", (cell.width + 2 * pad, cell.height), (0, 0, 0, 0))
    canvas.alpha_composite(cell, (pad, 0))
    return canvas


def _registered_distance(left, right, window: int) -> tuple[float, int]:
    """``(distance, shift)`` — the smallest distance over a symmetric shift grid.

    Both cells are compared on ONE canvas ``window`` px wider on each side, so no
    content falls off an edge and both distances are divided by the same pixel
    count: the padding scales the two terms of the ratio identically and cancels.

    The grid is symmetric about zero on purpose. ``distance(shift(flip a, d),
    flip b) == distance(shift(a, -d), b)``, so under a global flip the SET of
    scores over a symmetric grid is unchanged and its minimum is EXACTLY equal —
    which is what keeps the "a sheet mirrored on every row is a fixed point"
    property true of the registered measure and not merely of the raw one. An
    asymmetric grid, or a cross-correlation peak with a first-wins tie-break,
    would break that equality on symmetric art.
    """
    if window <= 0:
        return _cell_distance(left, right), 0
    width, height = left.size
    fixed = _padded(right, window)
    sliding = _padded(left, 2 * window)
    best: float | None = None
    best_shift = 0
    for shift in range(-window, window + 1):
        start = window - shift
        score = _cell_distance(
            sliding.crop((start, 0, start + width + 2 * window, height)), fixed
        )
        if best is None or score < best:
            best, best_shift = score, shift
    return best, best_shift


def _seam_distance(left_cells, right_cells, *, window: int) -> tuple[float, float]:
    """``(as drawn, with one side flipped)`` — mean over column-paired frames.

    Paired by column index rather than by pose: neighbouring rows are separate
    generations and their animation phases do not line up anyway, so averaging
    across the whole row is what takes the phase noise out of the number.

    Each pairing is REGISTERED first (:func:`_registered_distance`) and both
    orientations get the same freedom, so a sideways displacement between the two
    rows cancels out of the ratio instead of reading as handedness. *window* is
    the only knob; ``window=0`` is the unregistered measure and exists so a test
    can show what registration bought.

    ``distance(flip(a), b) == distance(a, flip(b))`` — flipping both operands is
    a re-indexing that changes no per-pixel difference, and the symmetric shift
    grid preserves it — so a seam has exactly ONE mirrored distance and which
    side we flip to compute it does not matter.
    """
    from PIL import Image

    paired = min(len(left_cells), len(right_cells))
    if paired == 0:
        raise ValueError("cannot measure a seam between rows with no frames")
    direct = 0.0
    flipped = 0.0
    for index in range(paired):
        left = left_cells[index]
        right = right_cells[index]
        direct += _registered_distance(left, right, window)[0]
        flipped += _registered_distance(
            left.transpose(Image.FLIP_LEFT_RIGHT), right, window
        )[0]
    return (direct / paired, flipped / paired)


def _seam_record(left: str, right: str, direct: float, flipped: float) -> dict:
    return {"rows": (left, right), "distance": direct, "mirroredDistance": flipped}


def _seam_evidence(row: str, seams: list[dict]) -> list[dict]:
    """The seams a finding quotes, named from the flagged row's point of view."""
    return [
        {
            "with": next(key for key in seam["rows"] if key != row),
            "distance": seam["distance"],
            "mirroredDistance": seam["mirroredDistance"],
        }
        for seam in seams
    ]


def _gain(seams: list[dict]) -> float | None:
    """``(as drawn - flipped) / as drawn`` over *seams*; ``None`` when 0 apart."""
    as_drawn = sum(seam["distance"] for seam in seams)
    if as_drawn <= 0:
        return None
    return (as_drawn - sum(seam["mirroredDistance"] for seam in seams)) / as_drawn


def _contradicted(entry: dict, cross: dict[str, float], suspected: set[str]) -> bool:
    """Do the OTHER states vouch for this row, or merely agree with it?

    A negative cross-state reading means "every state draws this direction the
    same way". That is exculpatory exactly when the other states' copies of the
    direction are not themselves under suspicion, and it is worth nothing when
    they are: a direction mirrored in EVERY state is a fixed point of the
    cross-state pass and reads strongly negative there PRECISELY BECAUSE it is
    consistently wrong. Measured on the fixture, both halves. Two mirrored rows
    flanking a correct one leave the correct middle row at -97.62% across the
    states, and `e` is over threshold in one state's rotation out of three. The
    founding defect — `ne` mirrored in all three states — leaves each mirrored
    row at -111.32% across the states, and `ne` is over threshold in three
    rotations out of three. Reading the SIGN alone would exonerate the second,
    which is the defect this whole gate was built for; *suspected* is what
    separates them.
    """
    gain = cross.get(entry["row"])
    if gain is None or gain >= 0:
        return False
    return entry["direction"] not in suspected


def _attribute_run(
    run: list[tuple[int, dict]], cross: dict[str, float], suspected: set[str]
) -> tuple[dict | None, str]:
    """``(culprit, how)`` — which row of a run the evidence can actually NAME.

    ``how`` is ``"both"`` (a second, independent basis convicts this row),
    ``"rotation"`` (ONE flagged row, alone, with nothing contradicting it), or
    the reason no row could be named at all: ``"run"`` (two or more flagged
    together, which the rotation cannot take apart) or ``"contradicted"`` (the
    single flagged row is vouched for by the other states).

    **"The culprit is the run's maximum" is retired, not re-tuned.** It was true
    of every case round two measured and false in two it did not, both of which
    put an INNOCENT row at the top of the run. A CORRECT row displaced sideways
    past the registration window reads high and drags its untouched neighbour
    higher still — measured on the fixture, `walk-e` slid -24 px reads +10.48%
    while the untouched `walk-ne` reads +10.68% and wins. And a correct row
    FLANKED by two mirrored ones wins its run outright: `idle-e`, correct,
    +14.28% between a mirrored `idle-se` and a mirrored `idle-ne`. Both are
    reachable — the first is a prop or a framing drift, the second is what a
    SECOND badly-worded diagonal in ``VIEW_LANGUAGE`` produces, the way `ne`
    alone produced the first defect this package ever saw.

    So the ranking never names anybody. Adjacent flagged rows are taken apart by
    a second BASIS or not at all, which is the same argument that leaves the
    rotation's end rows unjudged: one seam cannot say which of the two rows
    beside it is mirrored, and neither can two rows that raised each other. A
    lone flagged row has nothing to be confused with, so it is still named —
    which is what keeps the founding defect attributable, since `ne` mirrored in
    every state flags one isolated row per state.
    """
    entries = [entry for _position, entry in run]
    convicted = [
        entry
        for entry in entries
        if (cross.get(entry["row"]) or 0.0) >= MIRROR_GAIN_THRESHOLD
    ]
    # EXACTLY one, and the count is the rule rather than a tie-break. Ranking
    # two convictions would be a knob no fixture can reach — measured: two
    # ADJACENT mirrored rows never form a rotation run at all, because a
    # contiguous block is visible only at its edges and both rows' rotation
    # gains go NEGATIVE (`idle-e` + `idle-ne` mirrored reads -5.30% / -15.36%).
    # A run holding two cross-state convictions is a shape nothing here
    # understands, and the safe answer to a shape you do not understand is to
    # name nobody rather than to sort it.
    if len(convicted) == 1:
        return convicted[0], "both"
    if len(entries) >= 2:
        return None, "run"
    if _contradicted(entries[0], cross, suspected):
        return None, "contradicted"
    return entries[0], "rotation"


def _finding_from_run(
    run: list[tuple[int, dict]], cross: dict[str, float], suspected: set[str]
) -> dict:
    culprit, how = _attribute_run(run, cross, suspected)
    ranked = sorted(
        (entry for _position, entry in run),
        key=lambda entry: entry["gain"],
        reverse=True,
    )
    anchor = culprit if culprit is not None else ranked[0]
    finding = dict(anchor)
    finding["attributed"] = culprit is not None
    finding["attribution"] = how
    # ``corroborating`` carries "do NOT re-roll these", so it is only honest
    # once a row has actually been named as the fault. An unattributed run lists
    # its rows as ``alternatives`` instead: any of them may be the one.
    finding["corroborating"] = (
        [
            {"row": entry["row"], "gain": entry["gain"]}
            for entry in ranked
            if entry["row"] != anchor["row"]
        ]
        if culprit is not None
        else []
    )
    finding["alternatives"] = (
        []
        if culprit is not None
        else [{"row": entry["row"], "gain": entry["gain"]} for entry in ranked]
    )
    return finding


def _run_findings(
    scored: list[tuple[int, dict]], cross: dict[str, float], suspected: set[str]
) -> list[dict]:
    """One finding per contiguous RUN of over-threshold rows.

    A mirrored row raises BOTH its neighbours toward the line, because their
    seams against it prefer the flip from their side too. Reporting each of them
    as its own error is not a harmless excess of caution: every message names
    ``characters reroll-row``, ``reroll_row`` proposes and approves
    unconditionally, and there is no ``approve-row`` verb to undo it — so an
    operator who obeys a three-row refusal literally spends two correct approved
    attempts. Measured on the live repaired sheet: mirroring `idle-e` alone puts
    `idle-e` at +13.33% and `idle-ne` at +11.87%.

    WHICH row of the run is named is :func:`_attribute_run`'s job, and it is not
    simply the maximum — see that function for the two measured shapes where the
    maximum is an innocent row.
    """
    over = [item for item in scored if item[1]["gain"] >= MIRROR_GAIN_THRESHOLD]
    findings: list[dict] = []
    run: list[tuple[int, dict]] = []
    for item in over:
        if run and item[0] != run[-1][0] + 1:
            findings.append(_finding_from_run(run, cross, suspected))
            run = []
        run.append(item)
    if run:
        findings.append(_finding_from_run(run, cross, suspected))
    return findings
