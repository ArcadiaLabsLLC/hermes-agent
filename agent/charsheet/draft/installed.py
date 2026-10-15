"""The installed-sheet readers: ``sprite_payload``, the sheet revision, the accepted-handedness record."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from agent.charsheet._support import safe_segment, slugify
from agent.pet.constants import DEFAULT_SCALE, LOOP_MS

from .layout import MANIFEST_FILENAME, SHEET_FILENAME, characters_dir, spec_from_dict

__layer__ = "stores"


def _row_json(row) -> dict:
    return {
        "row": row.index,
        "state": row.state,
        "direction": row.direction,
        "frames": row.frames,
        "key": row.key,
    }


# ──────────────────────────── installed sheets ────────────────────────────


def sheet_revision(path: Path) -> str:
    """``mtime_ns:size`` — the pet payload's cache key, same meaning."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def sprite_payload(slug: str, *, include_sheet: bool = True) -> dict:
    """The launcher payload for an installed character.

    ``include_sheet=False`` is the METADATA-ONLY shape (``characters sprite
    --no-sheet``, 2026-09-02). It omits ``spritesheetBase64`` — and never reads
    the bytes at all, which is the point — and puts ``sheet``, the absolute
    path, in the same slot, spelled the way ``characters list``'s installed rows
    already spell it so a consumer has ONE name for that file across both verbs.
    ``spritesheetRevision`` stays: it is ``mtime_ns:size`` off a ``stat()``, it
    costs nothing next to the read this mode skips, and it is the field the
    launcher's ``CharaSheetProvenance.contentHash`` hangs on — a metadata read
    that dropped it would be cheap and useless.

    A FLAG and not a second function because every other key is wanted in both
    modes and exactly one is expensive: 468.8 KiB of base64 on the live 3-state
    ``anime-girl``, 107x the event-payload cap and 8.8x the terminal tool's
    output cap. A consumer that wanted ``framesByRow``, ``states`` or ``rows``
    paid all of it and decoded none of it. The default is unchanged to the byte,
    key order included — the two shapes are spelled as one conditional entry in
    the same position rather than an append, so the launcher's shipped
    ``sprite()`` client, which passes no flag, cannot see this change.

    Field names and meanings match the pet sprite payload where they overlap, so
    the Dart client's parse path is unchanged; the additions (``directions``,
    ``states``, ``rows``) are what let a consumer read a directional sheet
    without inferring the taxonomy from its height — the pet inference trap
    (§0.4). There is no ``framesPerState``: character rows carry true per-row
    counts only.

    ``framesByRow``, ``stateRows`` and ``rows`` describe the AUTHORED rows only
    (ten of them for ``CHAR8``), because since ruling 3-B those are the only
    rows in the sheet. ``directions.mirrored`` still names the flips the consumer
    derives: the launcher needs the SECTORS, and the row names carry them.

    Row keys and the ``stateRows`` order follow the launcher spec (EterniaLauncher
    ``docs/spatial/CHARACTER_8WAY_SPRITE_FORMAT_SPEC_2026-08-17.md``): a directional
    row is ``<state>-<direction>``, and row 0 is the front-facing idle.
    """
    safe = safe_segment(slugify(slug))
    directory = characters_dir() / safe
    manifest_path = directory / MANIFEST_FILENAME
    sheet_path = directory / SHEET_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"character {slug!r} is not installed: no manifest at {manifest_path}"
        )
    if not sheet_path.is_file():
        raise FileNotFoundError(
            f"character {slug!r} is installed but has no sheet at {sheet_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"corrupt manifest {manifest_path}: {exc}") from exc

    spec = spec_from_dict(manifest.get("spec") or {})
    rows = [_row_json(row) for row in spec.rows()]
    return {
        "slug": str(manifest.get("slug", safe)),
        "displayName": str(manifest.get("displayName", "") or safe),
        "mime": "image/webp",
        **(
            {
                "spritesheetBase64": base64.standard_b64encode(
                    sheet_path.read_bytes()
                ).decode("ascii")
            }
            if include_sheet
            else {"sheet": str(sheet_path)}
        ),
        "spritesheetRevision": sheet_revision(sheet_path),
        "frameW": spec.frame_w,
        "frameH": spec.frame_h,
        "framesByRow": {row.key: row.frames for row in spec.rows()},
        "loopMs": int(manifest.get("loopMs", LOOP_MS)),
        "scale": float(manifest.get("scale", DEFAULT_SCALE)),
        "directions": {
            "order": list(spec.scheme.order),
            "authored": list(spec.scheme.authored),
            "mirrored": dict(spec.scheme.mirrored),
        },
        "states": [
            {"name": state.name, "frames": state.frames, "directional": bool(state.directional)}
            for state in spec.states
        ],
        "rows": rows,
        "stateRows": [row["key"] for row in rows],
        # The one fact about this sheet the pixels cannot carry: an operator
        # looked at a two-basis mirrored-art refusal and overrode it, per row,
        # with its gain and its bases. Empty for every character composed
        # without an override, which is nearly all of them. It rides here so a
        # consumer that byte-copies the sheet (the launcher's
        # `bundle_character.dart` decodes nothing) can still read it; whether
        # that consumer refuses, warns or records is its own ruling, but it
        # could not make one at all while this lived only inside the manifest.
        "handednessAccepted": _handedness_accepted(manifest),
    }


def _handedness_accepted(manifest: dict) -> list[dict]:
    """The manifest's accepted mirrored-art findings, JSON-safe and total.

    Tolerates the ROUND-TWO spelling — a bare list of row keys — because a
    character installed by that build is still installed, and a payload that
    raised on it would take the whole sprite down over a provenance field.
    """
    raw = manifest.get("handednessAccepted") or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if isinstance(entry, dict):
            out.append(
                {
                    "row": str(entry.get("row", "")),
                    "gain": float(entry.get("gain", 0.0) or 0.0),
                    "basis": str(entry.get("basis", "") or "unrecorded"),
                }
            )
        else:
            out.append({"row": str(entry), "gain": 0.0, "basis": "unrecorded"})
    return out
