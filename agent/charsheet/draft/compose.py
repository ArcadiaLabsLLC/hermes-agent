"""Compose, validate and install the sheet; reopen a composed draft (``Composer``, as phases)."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from agent.charsheet import pipeline
from agent.charsheet._support import safe_segment, slugify, utc_now, write_bytes_atomic, write_json_atomic
from agent.pet.constants import DEFAULT_SCALE, LOOP_MS

from .installed import _row_json
from .layout import MANIFEST_FILENAME, PALETTE_FILENAME, SCHEMA, SHEET_FILENAME, Stage, characters_dir, row_item, spec_to_dict, turnaround_item

__layer__ = "lanes"

logger = logging.getLogger(__name__)


class Composer:
    """Compose, validate and install the sheet; reopen a composed draft — one stage of :class:`CharacterDraft`, by composition."""

    def __init__(self, draft) -> None:
        self.draft = draft

    def reopen(self) -> dict:
        """Reopen a composed draft for fixes; returns to stage ``rows``.

        Nothing is deleted and the installed sheet stays installed: compose
        always re-runs from the approved strips, so the next ``compose`` after
        a fix simply overwrites the install. Without this verb the only path
        back was hand-editing ``draft.json`` (proven live on 2026-08-24).
        """
        draft = self.draft
        draft._require_stage("reopen")
        draft._set_stage(Stage.ROWS)
        return {"stage": draft.stage}

    def compose(self, accept_handedness: Sequence[str] = ()) -> dict:
        """Compose, validate and install the sheet; advances to ``composed``.

        Refuses unless every authored row has an approved strip: composing from a
        partially approved draft would install a sheet with blank rows that the
        consumer's spec claims are filled.

        *accept_handedness* names ``<row>:<basis>`` tokens whose mirrored-art
        REFUSAL the operator has looked at and is overriding — see
        :func:`pipeline.validate_sheet`, and take the spelling from the refusal
        itself (:func:`pipeline.accept_basis_token`). It is per ROW and never
        blanket, and it applies to both refusing shapes: a row BOTH passes agree
        about (``<row>:rotation+states``) and a row carried by a whole mirrored
        STATE (``<row>:states``), the latter accepted one row at a time like any
        other. A single-basis finding about a single row is a warning and does
        not block, so there is nothing to accept about it; an accepted row that
        was not flagged is itself a refusal; and the honoured list is written
        into the installed manifest as ``{row, gain, basis}`` so the override
        survives as a fact about the character rather than as a refusal nobody
        can see any more.
        """
        draft = self.draft
        draft._require_stage("compose")
        spec = draft.spec
        strips, palette_sources = self._collect(spec)
        sheet, validation = self._validate(spec, strips, palette_sources, accept_handedness)
        directory = self._guard_slug()
        sheet_path = self._write_sheet(directory, sheet)
        manifest, rows = self._manifest(spec, directory, validation)
        draft._set_stage(Stage.COMPOSED)
        logger.info(
            "charsheet draft %s composed → %s (%dx%d)",
            draft.id,
            sheet_path,
            validation["width"],
            validation["height"],
        )
        return {
            "slug": manifest["slug"],
            "displayName": manifest["displayName"],
            "directory": str(directory),
            "sheet": str(sheet_path),
            "manifest": str(directory / MANIFEST_FILENAME),
            "validation": validation,
            "rows": rows,
            "stage": draft.stage,
        }

    def _collect(self, spec) -> tuple[dict[str, Path], list[Path]]:
        """Every authored row's approved strip, and the approved direction
        references the palette is taken from — or a refusal naming what is missing."""
        draft = self.draft
        store = draft.store
        strips: dict[str, Path] = {}
        missing: list[str] = []
        for row in spec.authored_rows():
            current = store.current(row_item(row.key))
            if current is None:
                missing.append(row.key)
            else:
                strips[row.key] = current
        if missing:
            raise ValueError(
                f"cannot compose draft {draft.id}: {len(missing)} row(s) have no "
                f"approved strip ({', '.join(missing)})"
            )

        palette_sources: list[Path] = []
        for direction in pipeline.turnaround_order(spec.scheme.authored):
            ref = store.current(turnaround_item(direction))
            if ref is None:
                raise ValueError(
                    f"cannot compose draft {draft.id}: direction {direction!r} has "
                    "no approved reference to take the palette from"
                )
            palette_sources.append(ref)
        return strips, palette_sources

    def _validate(self, spec, strips, palette_sources, accept_handedness):
        """Compose the sheet and validate it; a failed validation refuses, scope first."""
        draft = self.draft
        cells = pipeline.compose_draft_frames(spec, strips, palette_sources)
        sheet = pipeline.compose_sheet(spec, cells)
        validation = pipeline.validate_sheet(
            spec, sheet, accept_handedness=accept_handedness
        )
        if not validation["ok"]:
            # The handedness accounting rides on the REFUSAL too. Without it the
            # payload carrying "and here are the six rows nobody judged" is
            # discarded at exactly the moment an operator is deciding whether to
            # trust the check.
            # SCOPE FIRST, then the findings, one block apiece. The accounting
            # used to trail a semicolon-joined run-on, so the sentence saying
            # how much of the sheet was actually judged was the last thing on a
            # 1200-character line — furthest from the eye on the surface with
            # the least room. A consumer that shows only the head of this now
            # shows what failed and how far the check could see.
            raise ValueError(
                f"composed sheet for draft {draft.id} failed validation.\n"
                + pipeline.handedness_summary(validation["handedness"])
                + "; a refusal is not a full audit.\n\n"
                + "\n\n".join(validation["errors"])
            )
        return sheet, validation

    def _guard_slug(self) -> Path:
        """The install directory, refused when a DIFFERENT draft owns the slug."""
        draft = self.draft
        directory = characters_dir() / safe_segment(slugify(draft.slug))
        # Clobber guard: re-composing THIS draft may overwrite its own install,
        # but a colliding slug from a different draft is a different character.
        existing_manifest = directory / MANIFEST_FILENAME
        if existing_manifest.is_file():
            try:
                prior = json.loads(existing_manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = {}
            prior_draft = str(prior.get("draftId", "")) if isinstance(prior, dict) else ""
            if prior_draft and prior_draft != draft.id:
                raise ValueError(
                    f"slug {slugify(draft.slug)!r} is already installed from draft "
                    f"{prior_draft}; composing draft {draft.id} over it would replace "
                    "a different character — pick another slug"
                )
        return directory

    def _write_sheet(self, directory: Path, sheet) -> Path:
        """The sheet bytes and the colour table, written to the install and the draft."""
        draft = self.draft
        directory.mkdir(parents=True, exist_ok=True)
        sheet_path = directory / SHEET_FILENAME
        write_bytes_atomic(sheet_path, pipeline.atlas_to_webp_bytes(sheet))

        # The colour table, measured ONCE off the sheet that is being written
        # and copied to both homes. The producer knows this at write time; a
        # consumer deriving it would decode a 1536x2080 WebP per character on a
        # surface that asks this process even for a cropped thumbnail. Both
        # directories get it because they are different objects: the draft's
        # copy is what `status --json` answers with while the operator is still
        # working, and the install's is what `characters list` answers with
        # after — and a recompose over a slug another draft owns is refused
        # above precisely because the two cannot stand in for each other.
        palette = pipeline.palette_table(sheet)
        write_json_atomic(directory / PALETTE_FILENAME, palette)
        write_json_atomic(draft.directory / PALETTE_FILENAME, palette)
        return sheet_path

    def _manifest(self, spec, directory: Path, validation: dict) -> tuple[dict, list]:
        """The installed ``character.json`` — including the honoured acceptances."""
        draft = self.draft
        rows = [_row_json(row) for row in spec.rows()]
        manifest = {
            "schema": SCHEMA,
            "slug": slugify(draft.slug),
            "displayName": draft.display_name,
            "concept": draft.concept,
            "style": draft.style,
            "spec": spec_to_dict(spec),
            "rows": rows,
            "frameW": spec.frame_w,
            "frameH": spec.frame_h,
            "loopMs": LOOP_MS,
            "scale": DEFAULT_SCALE,
            "generator": "charsheet",
            "draftId": draft.id,
            "created": utc_now(),
        }
        if validation["handedness"].get("accepted"):
            # ``{row, gain, basis}``, not bare row keys: accepting a +40% finding
            # and an +8.1% one used to be indistinguishable the moment the
            # compose was over, and this manifest is the only place the fact
            # survives. ``sprite_payload`` and ``characters list`` both republish
            # it, so no consumer has to open this file to learn that a character
            # carries a mirrored row its operator looked at and accepted.
            manifest["handednessAccepted"] = [
                dict(entry) for entry in validation["handedness"]["accepted"]
            ]
        write_json_atomic(directory / MANIFEST_FILENAME, manifest)
        return manifest, rows
