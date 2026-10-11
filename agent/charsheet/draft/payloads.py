"""The read payloads the ``characters`` verbs and their method twins share.

Moved out of ``hermes_cli/harness_parts/characters/payloads.py`` (D2.10) so the
argv verbs and the ``runtime.characters.*`` read twins build one shape from one
place: ``agent_runtime`` must not import ``hermes_cli``, and ``agent.charsheet``
is importable from both. The argv module keeps the emit/refusal shapes; the rows,
the draftsman block and the thumb dispatch live here.
"""

from __future__ import annotations

import json

__layer__ = "lanes"
__all__ = [
    "draft_summary",
    "draftsman",
    "installed_rows",
    "thumb_result",
]


def draftsman() -> dict:
    """``{"draftsman": "fake"}`` while the seam is armed, and NOTHING when it is not.

    Additive and conditional, in that order. Additive: the character payloads
    are ruled supersets, so a key that appears is free. Conditional, and never
    ``"real"``: an old reader must see byte-identical output on the door it has
    always used, so "absent" keeps meaning "the provider door" and the key
    exists only to make the OTHER case impossible to miss — a sandbox that
    forgot to arm the seam reads as a paid run rather than a silent one, and a
    field run that armed it by accident says so on every row it writes.

    Read per emit, not once: the variable belongs to the process, and a serve
    may be spawned by a launcher that set it (RL-26).
    """
    from agent.charsheet.fake_draftsman import active_draftsman_name

    name = active_draftsman_name()
    return {"draftsman": name} if name else {}


def thumb_result(draft, *, row_key: str, direction: str, attempt: int,
                 requested_frame: int | None, scale: int | None, square: bool) -> dict:
    """One crop: a direction reference when ``direction`` is named, else a row frame.

    A path, never bytes: the crop is written into the draft and the payload
    names it (plan A-4).
    """
    from agent.charsheet.draft import DEFAULT_THUMB_FRAME, DEFAULT_THUMB_SCALE

    scale = DEFAULT_THUMB_SCALE if scale is None else scale
    if direction:
        # A reference holds ONE pose. Ignoring `--frame` here would answer a
        # caller who asked for cell 3 with cell 0 and call it a crop.
        if requested_frame is not None:
            raise ValueError(
                "--frame addresses a cell of a row STRIP; a direction "
                f"reference is one pose, so `--direction {direction}` and "
                "--frame cannot be asked for together"
            )
        return draft.direction_thumb(
            direction, attempt=attempt, scale=scale, square=square
        )
    frame = DEFAULT_THUMB_FRAME if requested_frame is None else requested_frame
    return draft.row_thumb(
        row_key, attempt=attempt, frame=frame, scale=scale, square=square
    )


def draft_summary(draft) -> dict:
    """A list row: identity and shape, without walking the revision store.

    ``baseImage`` answers with the SAME spelling of absence ``status --json``
    uses — a ``str`` or JSON ``null``, never ``""`` — through the one helper
    (``draft.path_or_none``). ``list`` and ``status`` name the same field, and a
    consumer that has to remember which of the two flattens absence is a
    consumer that will get it wrong.

    ``shadows`` is what makes a duplicate ``id`` readable rather than a defect.
    A backup directory is a copy of a draft directory, so it answers the
    ORIGINAL's id and two rows carried one id with nothing to tell them apart.
    The copy stays a row — it is on disk — and names the id it copies, so a
    consumer drops every row carrying ``shadows`` and keeps the un-shadowed one.
    ``str`` or JSON ``null``, the same spelling of absence as its neighbours.
    """
    from agent.charsheet.draft import path_or_none

    spec = draft.spec
    return {
        "id": draft.id,
        "slug": draft.slug,
        "displayName": draft.display_name,
        "concept": draft.concept,
        "style": draft.style,
        "shadows": draft.shadows,
        "authoredBy": draft.authored_by,
        # Beside `authoredBy` in all three payloads that carry provenance —
        # this row, `status --json`, and the `start --json` summary (which is
        # this helper) — so a consumer never has to remember which of the three
        # answers the question. `str` or JSON `null`, never `""`.
        "hermesHome": draft.hermes_home,
        "stage": draft.stage,
        "rows": len(spec.rows()),
        "authoredRows": len(spec.authored_rows()),
        "directions": len(spec.scheme.order),
        "baseImage": path_or_none(draft.base_image),
        "directory": str(draft.directory),
    }


def installed_rows() -> list[dict]:
    """Installed characters: one row per directory carrying a manifest.

    ``handednessAccepted`` rides on every row because the alternative is that a
    character carrying a mirrored row its operator overrode looks IDENTICAL here
    to one that passed clean — which is the shape this whole lane exists to
    retire. It is a list of ``{row, gain, basis}``, empty for nearly every
    character.

    ``palette`` is the compose-time colour table (``#RRGGBBAA``, most-used
    first) and is CONDITIONAL, unlike its neighbours: a character composed
    before the table existed carries no key at all rather than an empty list.
    "Nobody recorded a palette" and "this sheet has no colours" are different
    facts, and the launcher's swatch strip owes an old character a blank strip
    and a colourless one a defect report. See
    ``agent/charsheet/draft.py::read_palette``.
    """
    from agent.charsheet.draft import (
        MANIFEST_FILENAME,
        SHEET_FILENAME,
        _handedness_accepted,
        characters_dir,
        read_palette,
    )

    root = characters_dir()
    rows: list[dict] = []
    for child in sorted(root.iterdir()) if root.is_dir() else []:
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        sheet = child / SHEET_FILENAME
        palette = read_palette(child)
        rows.append(
            {
                "slug": str(manifest.get("slug", "") or child.name),
                "displayName": str(manifest.get("displayName", "") or child.name),
                "draftId": str(manifest.get("draftId", "")),
                "created": str(manifest.get("created", "")),
                "directory": str(child),
                "sheet": str(sheet) if sheet.is_file() else "",
                "installed": sheet.is_file(),
                **({"palette": palette} if palette is not None else {}),
                "handednessAccepted": _handedness_accepted(manifest),
            }
        )
    return rows
