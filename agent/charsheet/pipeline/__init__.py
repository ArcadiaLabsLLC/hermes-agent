"""The charsheet pixel pipeline: turnaround → direction refs → rows → sheet.

Stage order is the operator's QA order (plan H §4): one wide turnaround strip is
sliced into the authored direction references, each approved reference grounds
that direction's animation strips, and at compose time those strips are
registered, palette-locked, packed and validated. Nothing is mirrored on the way:
a sheet carries the authored directions only (launcher ADR 0024 ruling 3-B) and
the consumer flips the other three at draw time.

Three constraints are load-bearing here:

* **One provider seam.** Every generation goes through :func:`_generate_image`,
  resolved at call time by :func:`_draftsman`. Nothing else in the charsheet
  package talks to a provider, so the whole flow runs offline against a fake by
  replacing that one function in-process — or, for a process nobody is
  monkeypatching, by arming ``HERMES_CHARSHEET_DRAFTSMAN=fake``
  (:mod:`agent.charsheet.fake_draftsman`).
* **Grounding refs carry the chroma field.** The row prompts tell the model to
  reuse "the same flat chroma-key field as the attached reference"; a sliced
  turnaround cutout is transparent, so it is re-composited onto flat magenta
  before it is written (§7.3). The same treatment is applied to a re-rolled
  single view, so every direction reference is interchangeable.
* **Geometry is gated mechanically, identity is gated by a human.** A strip whose
  poses touch cannot be sliced into frames, and no operator should be asked to
  review that — such rolls are rejected and regenerated here (the pet hatch
  retry pattern), and only strips that *can* be sliced reach QA.

Composition and validation are written fresh rather than reused: upstream's
``compose_atlas``/``validate_atlas`` are welded to the module-global ``ROW_SPECS``
taxonomy, while a character sheet's row list is data that arrives with the spec.
Everything below therefore loops over ``spec.rows()`` and never imports
``ROW_SPECS``.

Package map (lane B1, sheet ``god-file-layout-sheets/pipeline.md`` §1). Entry
points are what the outside calls; everything else is reached only from inside.
Layers point down (models <- policy <- stores <- lanes <- wiring); this map is
``lanes`` because it imports the lanes it re-exports.

    agent/charsheet/_upstream_doors.py  models  every upstream agent.pet name the package reads
    agent/charsheet/pipeline/
      __init__.py          lanes    this map; re-exports __all__ and the test-read privates
      findings.py          models   the finding vocabulary: MirrorBasis, Severity, Attribution, the accept tokens
      geometry.py          models   chroma field, pixel budgets, prefixes, PNG I/O, turnaround_order
      provider.py          stores   the provider seam: deadline, _generate_image, _draftsman
      grounding.py         policy   cutout -> magenta, cell framing, face offset, upscale/pad
      registration.py      policy   seam/registration arithmetic and the measured thresholds
      generate.py          lanes    turnaround, direction re-roll, row strips (reject-and-retry)
      compose.py           lanes    palette + frame packing (the no-flip chokepoint) AND validate_sheet (SheetValidation phases)
      handedness.py        lanes    detect_mirrored_art = HandednessDetector: states -> rotation -> convict -> attribute -> summarise
      handedness_report.py lanes    the operator-facing rendering of a finding: REPORT_SECTIONS, walked in order

    entry point                                            opens
    generate_turnaround / _direction_view / _row_strip     generate -> provider -> grounding
    frame_cell, face_offset, reference_cell                grounding -> geometry
    compose_sheet / compose_draft_frames / build_palette   compose -> grounding
    validate_sheet                                         compose -> handedness -> handedness_report
    detect_mirrored_art                                    handedness -> registration -> geometry
    mirrored_art_error / handedness_summary                handedness_report -> findings

The provider seam is patched where it is BOUND: ``pipeline.provider._generate_image``
(``_draftsman`` reads it as a module global there) and
``pipeline.provider.provider_timeout_seconds``; a patch on the package attribute
reaches no caller.
"""

from __future__ import annotations

from agent.charsheet._upstream_doors import atlas_to_webp_bytes, extract_strip_frames, imagegen
from agent.charsheet.palette import palette_table
from agent.charsheet.spec import row_key

from . import compose, findings, generate, geometry, grounding, handedness, handedness_report, provider, registration
from .compose import (
    SheetValidation,
    build_sheet_palette,
    compose_draft_frames,
    compose_sheet,
    validate_sheet,
)
from .findings import (
    Attribution,
    MirrorBasis,
    Severity,
    accept_basis_token,
)
from .generate import (
    generate_direction_view,
    generate_row_strip,
    generate_turnaround,
)
from .geometry import (
    MAGENTA,
    MAX_CONSOLE_CARD_PIXELS,
    MAX_THUMB_PIXELS,
    NON_DIRECTIONAL_VIEW,
    PREFIX_TURNAROUND,
    QA_BACKDROP,
    TRANSPARENT_BACKDROP,
    fits_console_budget,
    fits_own_sheet,
    require_scale,
    row_prefix,
    turnaround_order,
    view_prefix,
)
from .grounding import (
    FACE_BAND,
    _column_centroid,
    face_offset,
    frame_cell,
    pad_to_square,
    recomposite_on_magenta,
    reference_cell,
    upscale_on_backdrop,
)
from .handedness import (
    HandednessDetector,
    detect_mirrored_art,
)
from .handedness_report import (
    REPORT_SECTIONS,
    handedness_summary,
    mirrored_art_error,
)
from .provider import (
    PROVIDER_TIMEOUT_SECONDS,
    _draftsman,
    _generate_image,
    provider_timeout_seconds,
)
from .registration import (
    MIRROR_GAIN_THRESHOLD,
    REGISTRATION_WINDOW_DIVISOR,
    _registered_distance,
    _row_cells,
    _run_findings,
    _seam_distance,
    registration_window,
)

__layer__ = "lanes"

__all__ = [
    "MAGENTA",
    "MIRROR_GAIN_THRESHOLD",
    "PREFIX_TURNAROUND",
    "PROVIDER_TIMEOUT_SECONDS",
    "REGISTRATION_WINDOW_DIVISOR",
    "accept_basis_token",
    "atlas_to_webp_bytes",
    "build_sheet_palette",
    "compose_draft_frames",
    "compose_sheet",
    "fits_console_budget",
    "fits_own_sheet",
    "frame_cell",
    "generate_direction_view",
    "generate_row_strip",
    "generate_turnaround",
    "handedness_summary",
    "pad_to_square",
    "palette_table",
    "provider_timeout_seconds",
    "recomposite_on_magenta",
    "registration_window",
    "row_prefix",
    "turnaround_order",
    "TRANSPARENT_BACKDROP",
    "upscale_on_backdrop",
    "validate_sheet",
    "view_prefix",
]
