"""The identity gate: base image, turnaround, per-direction re-roll and approval (``DirectionStage``)."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.charsheet import pipeline
from agent.charsheet._support import write_bytes_atomic

from .layout import Stage, turnaround_item

__layer__ = "lanes"

logger = logging.getLogger(__name__)


class DirectionStage:
    """The identity gate: the base image, the turnaround and its per-direction re-rolls and approvals — one stage of :class:`CharacterDraft`, by composition."""

    def __init__(self, draft) -> None:
        self.draft = draft

    def set_base_image(self, image_path) -> Path:
        """Copy *image_path* into the draft as its identity anchor."""
        draft = self.draft
        source = Path(image_path)
        if not source.is_file():
            raise ValueError(f"base image {source} is not an existing file")
        suffix = source.suffix.lower() or ".png"
        target = draft.directory / f"base{suffix}"
        # Bytes are copied verbatim rather than re-encoded: the base is what the
        # provider is shown, and a re-encode would change what identity is
        # grounded on.
        write_bytes_atomic(target, source.read_bytes())
        draft._data["base_image"] = target.name
        draft._save()
        return target

    def run_turnaround(self, provider=None) -> dict:
        """One strip → an unapproved reference per authored direction.

        Re-running proposes a fresh attempt for every direction and clears the
        approvals (the revision store's rule), which is the intended behaviour for
        "the whole turnaround was bad".

        Locked for the whole run (:meth:`generation_lock`): the stage read, the
        provider call and every ``propose`` are one writer's work, and the stage
        is read INSIDE the lock so a second writer cannot advance it in between.
        """
        draft = self.draft
        with draft.generation_lock("turnaround"):
            draft._require_stage("run_turnaround")
            spec = draft.spec
            base = draft._require_base()
            refs = pipeline.generate_turnaround(
                spec,
                draft.concept,
                base,
                style=draft.style,
                provider=provider,
                out_dir=draft.directory / "turnaround",
            )
            store = draft.store
            out: dict[str, dict] = {}
            for direction in pipeline.turnaround_order(spec.scheme.authored):
                path = refs[direction]
                attempt = store.propose(turnaround_item(direction), path)
                out[direction] = {"attempt": attempt, "path": str(path), "approved": False}
            draft._save()
            return {"stage": draft.stage, "turnaround": out}

    def reroll_direction(self, direction: str, note: str = "", provider=None) -> dict:
        """Re-generate ONE direction reference on a square canvas, with *note*.

        Proposed unapproved: this is the identity gate, and a re-roll is a new
        candidate for the operator to look at.

        Locked like the batch verbs, and for a reason of its own beyond "it
        generates": the attempt count is READ to name the output file and then
        WRITTEN by ``propose``, so two re-rolls of one direction racing here
        pick the same filename and the second overwrites the first's bytes.
        """
        draft = self.draft
        with draft.generation_lock("reroll-direction"):
            draft._require_stage("reroll_direction")
            draft._require_authored_direction(direction)
            base = draft._require_base()
            store = draft.store
            key = turnaround_item(direction)
            attempts = len(store.history(key))
            out_path = draft.directory / "turnaround" / f"reroll-{direction}-{attempts + 1}.png"
            path = pipeline.generate_direction_view(
                direction,
                draft.concept,
                base,
                style=draft.style,
                note=note,
                provider=provider,
                out=out_path,
            )
            attempt = store.propose(key, path, note=note)
            draft._save()
            return {
                "direction": direction,
                "attempt": attempt,
                "attempts": attempt + 1,
                "path": str(path),
                "note": note,
                "approved": False,
            }

    def approve_direction(self, direction: str, attempt: int = -1) -> dict:
        """Approve a direction reference; advances the stage once all are approved.

        The receipt carries ``faceOffset``: the approved reference's own measured
        facing (:func:`pipeline.face_offset`), signed, positive to the right of
        frame. It is here because approving a turnaround certified NOTHING about
        the direction it approved — measured on the live ``anime-girl`` draft,
        the approved ``e`` reference is a west-facing profile (``-44.8``) while
        all three ``e`` rows drawn from it face east (``+10.9 / +9.9 / +10.5``).
        The reference carries identity, the row prompt carries facing, and
        nothing said so at the moment an operator was asked to say yes.

        A number, not a gate: nothing is refused on it, because what a correct
        offset is for a given sector of an unknown character is not something
        this code knows — the front and back views measure near zero legitimately.
        ``null`` when the approved attempt has no image on disk to measure.
        """
        draft = self.draft
        draft._require_stage("approve_direction")
        draft._require_authored_direction(direction)
        index = draft.store.approve(turnaround_item(direction), attempt)
        advanced = self._advance_if_directions_approved()
        return {
            "direction": direction,
            "approved": index,
            "faceOffset": self._face_offset(direction),
            "stage": draft.stage,
            "advanced": advanced,
        }

    def _face_offset(self, direction: str) -> float | None:
        """The APPROVED reference's measured facing.

        Called only just after ``store.approve``, which refuses an attempt whose
        file is missing — so there is always an image here to open, and the only
        ``None`` this answers is :func:`pipeline.face_offset`'s own "nothing is
        drawn on it", which is what a generation that came back as a bare chroma
        field looks like. A second existence check here would be a branch no
        input can reach.
        """
        draft = self.draft
        return pipeline.face_offset(draft.store.current(turnaround_item(direction)))

    def approve_all_directions(self) -> dict:
        """Approve the latest attempt of every authored direction, then advance."""
        draft = self.draft
        draft._require_stage("approve_all_directions")
        store = draft.store
        approved: dict[str, int] = {}
        for direction in draft.spec.scheme.authored:
            key = turnaround_item(direction)
            if not store.history(key):
                raise ValueError(
                    f"direction {direction!r} has no attempt to approve; run the "
                    "turnaround first"
                )
            approved[direction] = store.approve(key)
        advanced = self._advance_if_directions_approved()
        return {
            "approved": approved,
            # Per direction, on THIS arm too: `--all` is the path `auto` takes
            # and the path the anime-girl draft was approved through, so a
            # measurement that only rode on the single-direction arm would be
            # absent from every run that actually goes wrong unattended.
            "faceOffsets": {
                direction: self._face_offset(direction) for direction in approved
            },
            "stage": draft.stage,
            "advanced": advanced,
        }

    def _advance_if_directions_approved(self) -> bool:
        draft = self.draft
        store = draft.store
        pending = [
            direction
            for direction in draft.spec.scheme.authored
            if store.current(turnaround_item(direction)) is None
        ]
        if pending:
            return False
        draft._set_stage(Stage.ROWS)
        logger.info("charsheet draft %s: all directions approved → stage 'rows'", draft.id)
        return True
