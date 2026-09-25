"""Generation lanes: the turnaround, a direction re-roll, and the row strips (reject-and-retry)."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.charsheet import prompts
from agent.charsheet._upstream_doors import extract_strip_frames, remove_background
from agent.charsheet.spec import RowSpec, SheetSpec

from .geometry import NON_DIRECTIONAL_VIEW, PREFIX_TURNAROUND, _ROW_GEN_ATTEMPTS, _open_rgba, _save_png, row_prefix, turnaround_order, view_prefix
from .grounding import recomposite_on_magenta
from .provider import _draftsman

__layer__ = "lanes"

logger = logging.getLogger(__name__)


def generate_turnaround(
    spec: SheetSpec,
    concept: str,
    base_image,
    *,
    style: str | None = "auto",
    provider=None,
    out_dir,
) -> dict[str, Path]:
    """ONE strip → one grounding reference per authored direction.

    A single generation is the point: cross-call identity drift becomes
    within-image consistency, because the model holds a character together far
    better inside one image than across five (§7.1). The slice index → direction
    mapping is exactly :func:`turnaround_order`, the same order the prompt numbers
    its slots in, so a mis-slice shows up as a wrong-looking direction in QA
    rather than as a silently mislabelled reference.

    Returns ``{direction: png path}``. Slicing failures raise: a strip that
    cannot be cut into the authored views is a failed roll, and re-rolling the
    whole turnaround is the operator's call, not a silent salvage.
    """
    order = turnaround_order(spec.scheme.authored)
    base = Path(base_image)
    if not base.is_file():
        raise ValueError(f"base image not found: {base}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    strip = _draftsman()(
        prompts.build_turnaround_prompt(concept, order, style=style),
        reference_images=[base],
        aspect_ratio="landscape",
        prefix=PREFIX_TURNAROUND,
        provider=provider,
    )
    # No count re-check on the way out. ``extract_strip_frames`` ends in
    # ``_validate_extracted_frames``, whose FIRST tier is "wrong frame count"
    # and raises under BOTH methods, and the fit branch after it is a per-frame
    # map — so this call answers exactly ``len(order)`` cutouts or it raises.
    # The guard that stood here could never be true (w17/hb); the two other
    # ``extract_strip_frames`` call sites in this module already trust that
    # contract instead of re-checking it, and the refusal is pinned by
    # ``test_a_turnaround_strip_that_cannot_be_cut_into_the_authored_directions_is_refused``.
    cutouts = extract_strip_frames(strip, len(order), fit=False)

    refs: dict[str, Path] = {}
    for direction, cutout in zip(order, cutouts):
        refs[direction] = _save_png(
            recomposite_on_magenta(cutout), out_dir / f"turnaround-{direction}.png"
        )
    logger.info("charsheet turnaround: %d references from one strip", len(refs))
    return refs


def generate_direction_view(
    direction: str,
    concept: str,
    base_image,
    *,
    style: str | None = "auto",
    note: str = "",
    provider=None,
    out,
) -> Path:
    """Re-roll ONE direction reference on a square canvas, with the note applied.

    Grounded on the base image (not on the rejected slice — the operator rejected
    it) and given the same key-then-magenta treatment as a turnaround slice, so a
    re-rolled reference is interchangeable with a sliced one.
    """
    base = Path(base_image)
    if not base.is_file():
        raise ValueError(f"base image not found: {base}")

    generated = _draftsman()(
        prompts.build_direction_view_prompt(concept, direction, style=style, note=note),
        reference_images=[base],
        aspect_ratio="square",
        prefix=view_prefix(direction),
        provider=provider,
    )
    keyed = remove_background(_open_rgba(generated))
    return _save_png(recomposite_on_magenta(keyed), Path(out))


def generate_row_strip(
    row: RowSpec,
    concept: str,
    direction_ref,
    *,
    style: str | None = "auto",
    note: str = "",
    provider=None,
    out,
) -> Path:
    """Generate one animation strip for *row*, gated on being sliceable.

    *direction_ref* is the approved reference this row is grounded on: the
    direction's turnaround view for a directional row, the base image for a fixed
    row (which is also why a fixed row is prompted in the front view — see
    :data:`NON_DIRECTIONAL_VIEW`).

    The gate is mechanical and runs before the strip is accepted: the frames must
    segment with clean per-pose gutters (``method="components"``, which raises
    when poses touch). Up to :data:`_ROW_GEN_ATTEMPTS` rolls, the last one lenient
    (``method="auto"``, which raises only on a wrong frame count or an empty
    frame) so a stubborn row still yields something the operator can look at and
    re-roll. Returns the path of the ACCEPTED strip.
    """
    direction = row.direction or NON_DIRECTIONAL_VIEW
    ref = Path(direction_ref)
    if not ref.is_file():
        raise ValueError(f"grounding reference for row {row.key!r} not found: {ref}")

    prompt = prompts.build_directional_row_prompt(
        row.state, direction, row.frames, concept, style=style, note=note
    )
    last_error: Exception | None = None
    for attempt in range(_ROW_GEN_ATTEMPTS):
        strict = attempt < _ROW_GEN_ATTEMPTS - 1
        try:
            candidate = _draftsman()(
                prompt,
                reference_images=[ref],
                aspect_ratio="landscape",
                prefix=row_prefix(row.key),
                provider=provider,
            )
            extract_strip_frames(
                candidate,
                row.frames,
                method="components" if strict else "auto",
                fit=False,
            )
        except Exception as exc:  # noqa: BLE001 - retried; the reason is reported below
            last_error = exc
            logger.warning(
                "charsheet row %r attempt %d/%d rejected: %s",
                row.key,
                attempt + 1,
                _ROW_GEN_ATTEMPTS,
                exc,
            )
            continue
        logger.info("charsheet row %r accepted on attempt %d", row.key, attempt + 1)
        return _save_png(candidate, Path(out))

    raise ValueError(
        f"row {row.key!r} produced no sliceable strip in {_ROW_GEN_ATTEMPTS} "
        f"attempts; last failure: {last_error}"
    ) from last_error
