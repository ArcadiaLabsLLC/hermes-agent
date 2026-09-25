"""A draft's constants, its directories and its serialised spec: SCHEMA, the file names, characters_dir, the spec round-trip, the revision keys."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agent.charsheet._support import shared_characters_dir, write_json_atomic
from agent.charsheet.spec import DEFAULT_FRAME_H, DEFAULT_FRAME_W, DirectionScheme, SheetSpec, StateSpec

__layer__ = "models"


# One number, three documents: `draft.json`, the `status --json` payload, and
# the INSTALLED `character.json` manifest the launcher parses. That is why
# neither `authored_by` NOR `hermes_home` bumped it — an optional, draft-only
# provenance field that a schema-1 reader already tolerates (it is absent when
# unset, and unknown keys were always ignored) is not worth relabelling an
# installed sheet's manifest for. Both fields clear that bar the same way:
# neither is copied into the manifest, and no consumer branches on either to be
# correct — a reader that ignores them renders exactly what it renders today. A
# field that a consumer must read to be correct is a different case and would
# bump all three, which is the argument for splitting them first.
SCHEMA = 1

class Stage(StrEnum):
    """A draft's stage. A member IS its string, so ``draft.json`` is unchanged."""

    TURNAROUND = "turnaround"
    ROWS = "rows"
    COMPOSED = "composed"


# turnaround → rows → composed. Order is the tuple order; nothing branches on a
# stage count.
STAGE_ORDER: Final[tuple[Stage, ...]] = (Stage.TURNAROUND, Stage.ROWS, Stage.COMPOSED)
STAGES = STAGE_ORDER

#: The stage each verb requires — the one table the module docstring's "it is
#: enforced" points at. ``CharacterDraft._require_stage`` is its only reader.
VERB_STAGES: Final[Mapping[str, Stage]] = MappingProxyType({
    "run_turnaround": Stage.TURNAROUND,
    "reroll_direction": Stage.TURNAROUND,
    "approve_direction": Stage.TURNAROUND,
    "approve_all_directions": Stage.TURNAROUND,
    "run_rows": Stage.ROWS,
    "reroll_row": Stage.ROWS,
    "add_state": Stage.ROWS,
    "compose": Stage.ROWS,
    "reopen": Stage.COMPOSED,
})

DRAFTS_DIRNAME = ".drafts"
DRAFT_FILENAME = "draft.json"
MANIFEST_FILENAME = "character.json"
SHEET_FILENAME = "sheet.webp"
# The compose-time colour table, beside the sheet AND beside the draft that
# composed it. Its own file rather than a manifest key: the launcher's swatch
# strip is a display surface that wants only this, and the two directories that
# carry it are different objects whose lifetimes do not agree (a draft can be
# recomposed over a slug another draft installed — see the clobber guard in
# `compose`), so neither one can answer for the other. Absent means a character
# composed before 2026-09-04; see `read_palette`.
PALETTE_FILENAME = "palette.json"
REVISIONS_DIRNAME = "revisions"
THUMBS_DIRNAME = "thumbs"

# QA crops: 2x is what made a one-pixel seam legible in a chat card during the
# 2026-08-24 run, so it is the default. What bounds a crop is not a scale
# ceiling but the output's pixel count, and it is a refusal rather than a clamp
# — a caller who asks for 40x has made a mistake and should be told, not
# silently given 8x and left to wonder why the crop is small.
#
# This constant is also the line between the two pixel bounds (see
# `pipeline.MAX_CONSOLE_CARD_PIXELS` / `pipeline.MAX_THUMB_PIXELS`): at or
# below the default a crop must clear the console's decode ceiling, because it
# is the crop a caller who just asked for a picture gets and the one an agent
# declares to a card. Above it, the caller has asked for a deep zoom on purpose
# and gets one — bounded by the write ceiling, and labelled in the payload.
#
# The SHEET bound (`pipeline.fits_own_sheet`) is not a line here at all: it is
# reported at every scale and refuses nothing. A crop 13.1x its own draft's
# sheet is still a legal picture of one frame — what it is not is a mitigation,
# and the payload is where that gets said.
DEFAULT_THUMB_SCALE = 2

# Which frame cell a crop shows when the caller does not say. Frame 0 is the
# first pose of the strip and the one an operator reaches for first; the point
# of a default is that `thumb --row walk-n` crops SOMETHING, never the whole
# strip (which removes no pixels at all — see `pipeline.frame_cell`).
DEFAULT_THUMB_FRAME = 0


# ─────────────────────────────── locations ───────────────────────────────


def characters_dir() -> Path:
    """The ONE install-wide character library (created on demand).

    Delegates to :func:`agent_runtime.profile_home.get_shared_characters_dir` — at
    CALL time, through :func:`agent.charsheet._support.shared_characters_dir`
    (ruling Q9), so this module imports cleanly without the runtime — and adds
    nothing but the mkdir. This is the single site in hermes that spells the
    characters location: ``drafts_dir``, ``create``, ``load``, ``list_drafts``,
    the install writer and the CLI's installed-character rows all resolve
    through it, which is why head-homing the library was this one delegation and
    not a per-verb edit across fifteen verbs.

    It is deliberately NOT ``get_hermes_home() / "characters"`` any more: a
    per-profile library made "can this lane see that draft" a home comparison,
    and every wrong answer to it — a bare shell resolving the sticky profile, a
    serve prewarm mirroring another persona home mid-read — became a characters
    incident. One directory per root has no such question to get wrong.
    """
    path = shared_characters_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def drafts_dir() -> Path:
    """Where in-progress drafts live (created on demand)."""
    path = characters_dir() / DRAFTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def stamp_recorded_home(directory: Path, home: str) -> bool:
    """Write ``hermes_home`` onto a draft that carries none. Return what happened.

    The value is an ARGUMENT, which is the difference between this and
    :meth:`CharacterDraft.record_home`: the backfill stamps the home the run
    resolved, and a migration stamps the home the draft is LEAVING — a fact the
    directory itself is about to stop witnessing. Same two rules otherwise, and
    both are load-bearing:

    * **It never rewrites.** A draft that already states a home keeps it. A
      relocation is not a re-attribution, and the drafts whose provenance is
      most interesting are exactly the ones an unconditional stamp destroys.
    * **It does not go through** :meth:`CharacterDraft._save`. ``_save`` stamps
      ``updated`` with "now", and the drafts this reaches are dormant exhibits
      whose timeline is the evidence they are kept for. This writes the file
      directly, so every other byte is left as it was found.
    """
    path = Path(directory) / DRAFT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if str(data.get("hermes_home", "") or "").strip():
        return False
    data["hermes_home"] = str(home)
    write_json_atomic(path, data)
    return True


# ──────────────────────────── spec round-trip ────────────────────────────


def spec_to_dict(spec: SheetSpec) -> dict:
    """JSON form of a :class:`SheetSpec` — states, scheme and cell geometry.

    The sheet's taxonomy must travel *with* the sheet: the pet readers infer row
    lists from image height, and a 16-row character sheet pushed through that
    inference is silently misread as a 9-row pet (plan §0.4).
    """
    return {
        "states": [
            {"name": state.name, "frames": state.frames, "directional": bool(state.directional)}
            for state in spec.states
        ],
        "scheme": {
            "order": list(spec.scheme.order),
            "authored": list(spec.scheme.authored),
            "mirrored": dict(spec.scheme.mirrored),
        },
        "frameW": spec.frame_w,
        "frameH": spec.frame_h,
    }


def spec_from_dict(data: dict) -> SheetSpec:
    """Rebuild a :class:`SheetSpec` from :func:`spec_to_dict` output."""
    if not isinstance(data, dict):
        raise ValueError(f"spec must be a JSON object, got {type(data).__name__}")
    raw_states = data.get("states")
    if not isinstance(raw_states, list) or not raw_states:
        raise ValueError("spec.states must be a non-empty list")
    states = []
    for entry in raw_states:
        if not isinstance(entry, dict):
            raise ValueError(f"spec.states entry must be an object, got {entry!r}")
        try:
            states.append(
                StateSpec(
                    name=str(entry["name"]),
                    frames=int(entry["frames"]),
                    directional=bool(entry["directional"]),
                )
            )
        except KeyError as exc:
            raise ValueError(f"spec.states entry {entry!r} is missing {exc.args[0]!r}") from None

    raw_scheme = data.get("scheme")
    if not isinstance(raw_scheme, dict):
        raise ValueError("spec.scheme must be a JSON object")
    try:
        scheme = DirectionScheme(
            order=tuple(str(d) for d in raw_scheme["order"]),
            authored=tuple(str(d) for d in raw_scheme["authored"]),
            mirrored={str(k): str(v) for k, v in dict(raw_scheme.get("mirrored") or {}).items()},
        )
    except KeyError as exc:
        raise ValueError(f"spec.scheme is missing {exc.args[0]!r}") from None

    return SheetSpec(
        states=tuple(states),
        scheme=scheme,
        frame_w=int(data.get("frameW", DEFAULT_FRAME_W)),
        frame_h=int(data.get("frameH", DEFAULT_FRAME_H)),
    )


# ───────────────────────────── revision keys ─────────────────────────────


def turnaround_item(direction: str) -> str:
    """Revision-store key for a direction reference."""
    return f"turnaround@{direction}"


def row_item(key: str) -> str:
    """Revision-store key for a row strip (``row@walk-e``).

    The leading ``row@`` is the store's ITEM-KIND separator — it is not the
    sheet's row-key separator, which is the hyphen. Both live in one string on
    purpose: the store never parses keys, so the two namespaces cannot collide.
    """
    return f"row@{key}"


def _strip_filename(key: str, attempt: int) -> str:
    return f"{key}-{attempt}.png"


def path_or_none(path: Path | None) -> str | None:
    """One spelling of "there is no file here" for the whole payload.

    A path field is a ``str`` or ``None``; ``""`` is neither, and it is what a
    consumer gets when a ``Path | None`` is coerced through ``str(x or "")``.
    Every path in ``status --json`` goes through here so absence cannot acquire
    a second spelling one field at a time.

    **Public because the rule is not this module's alone.** It shipped private
    and ``hermes_cli.harness._characters_draft_summary`` — the ``list`` row,
    carrying the same ``baseImage`` field — kept its own ``str(x) if x else ""``
    for exactly as long. A one-module helper enforcing a payload-wide rule is
    how the fourth field got missed; the CLI imports this one now.
    """
    return str(path) if path is not None else None


def read_palette(directory: Path) -> list[str] | None:
    """The compose-time colour table in *directory*, or ``None`` if there is none.

    ``None`` and ``[]`` are DIFFERENT facts on the wire and this is where the
    difference is made. ``None`` means nobody wrote a table here — the character
    was composed before the table existed, or this draft has not composed yet —
    and every payload built on it omits the key entirely. ``[]`` would mean a
    sheet with no opaque pixels at all, which validation refuses, so it is not a
    value any composed character can carry. A producer that flattened absence to
    an empty list would hand the launcher one value for two facts, and the strip
    would render "no colours" for a character that simply predates this field.

    Total by construction: a missing, unreadable or malformed file is absence,
    not an exception. A colour table is a display detail, and taking
    ``characters list`` down over one is a worse outcome than a missing strip.
    """
    try:
        raw = json.loads((directory / PALETTE_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, list):
        return None
    return [str(entry) for entry in raw]
