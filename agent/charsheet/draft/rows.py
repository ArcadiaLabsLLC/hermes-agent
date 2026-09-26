"""The animation rows: generate, re-roll, add a state (``RowStage``)."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.charsheet import pipeline
from agent.charsheet.spec import SheetSpec, parse_states

from .layout import _strip_filename, row_item, spec_to_dict, turnaround_item

__layer__ = "lanes"

logger = logging.getLogger(__name__)


class RowStage:
    """The animation rows: generate, re-roll, add a state — one stage of :class:`CharacterDraft`, by composition."""

    def __init__(self, draft) -> None:
        self.draft = draft

    def run_rows(self, only: list[str] | None = None, provider=None) -> dict:
        """Generate the animation strips for the authored rows.

        Each accepted strip is proposed AND approved — see the module docstring:
        the mechanical gate already ran, so what is left is a visual judgement the
        operator makes from the status payload.

        *only* restricts the run to the given row keys (``["walk-e"]``).

        Locked for the WHOLE batch, not per row (:meth:`generation_lock`). Rows
        land one at a time and are visible to ``status`` as they do, which is
        the resume story; but a second batch admitted between two rows would
        regenerate the ones this one already approved and race the attempt
        numbering on the ones it has not reached.
        """
        draft = self.draft
        with draft.generation_lock("rows"):
            draft._require_stage("run_rows")
            spec = draft.spec
            rows = spec.authored_rows()
            if only is not None:
                wanted = [str(key) for key in only]
                known = {row.key for row in rows}
                unknown = [key for key in wanted if key not in known]
                if unknown:
                    raise ValueError(
                        f"unknown row key(s) {unknown}; authored rows: {sorted(known)}"
                    )
                rows = [row for row in rows if row.key in set(wanted)]

            store = draft.store
            out: dict[str, dict] = {}
            for row in rows:
                ref = self._row_reference(row)
                key = row_item(row.key)
                attempts = len(store.history(key))
                out_path = draft.directory / "strips" / _strip_filename(row.key, attempts + 1)
                path = pipeline.generate_row_strip(
                    row,
                    draft.concept,
                    ref,
                    style=draft.style,
                    provider=provider,
                    out=out_path,
                )
                attempt = store.propose(key, path)
                store.approve(key, attempt)
                out[row.key] = {
                    "attempt": attempt,
                    "path": str(path),
                    "approved": True,
                    "reference": str(ref),
                }
            draft._save()
            return {"stage": draft.stage, "rows": out}

    def _row_reference(self, row) -> Path:
        """What a row is grounded on: its approved direction ref, else the base."""
        draft = self.draft
        if row.direction is None:
            return draft._require_base()
        ref = draft.store.current(turnaround_item(row.direction))
        if ref is None:
            raise ValueError(
                f"row {row.key!r} needs the approved {row.direction!r} turnaround "
                "reference, which is not approved"
            )
        return ref

    def reroll_row(self, row_key: str, note: str = "", provider=None) -> dict:
        """Re-generate one row strip; the new strip is auto-approved.

        Same reason as :meth:`run_rows`: a re-roll always replaces what the sheet
        will use, and the operator's gate is visual (look at the strip, re-roll
        again if it is still wrong).
        """
        draft = self.draft
        with draft.generation_lock("reroll-row"):
            draft._require_stage("reroll_row")
            row = draft._authored_row(row_key)
            store = draft.store
            key = row_item(row.key)
            attempts = len(store.history(key))
            ref = self._row_reference(row)
            out_path = draft.directory / "strips" / _strip_filename(row.key, attempts + 1)
            path = pipeline.generate_row_strip(
                row,
                draft.concept,
                ref,
                style=draft.style,
                note=note,
                provider=provider,
                out=out_path,
            )
            attempt = store.propose(key, path, note=note)
            store.approve(key, attempt)
            draft._save()
            return {
                "row": row.key,
                "attempt": attempt,
                "attempts": attempt + 1,
                "path": str(path),
                "note": note,
                "approved": True,
            }

    def add_state(self, state_text: str) -> dict:
        """Grow the sheet by ONE state. No approved row is touched.

        The owner ask this exists for: add ``jumping:6`` to a character that is
        already composed and installed, without re-authoring it. The operator
        sequence is ``reopen`` -> ``add-state`` -> ``rows --only <the new rows>``
        -> QA -> ``compose``, and the recomposed manifest carries the new state.

        **Stage ``rows`` only, which is why this verb has no stage logic of its
        own.** :meth:`reopen` is the one door back from ``composed``; refusing
        every other stage here means the two verbs cannot disagree about when a
        spec may change. At ``turnaround`` the answer is ``--states`` on
        ``start``, which has not been spent yet.

        **The spec is REPLACED, never mutated.** :class:`SheetSpec` and
        :class:`StateSpec` are frozen on purpose, and the new state is APPENDED,
        so :meth:`SheetSpec.rows` — which is state-major — keeps every existing
        row at the index the installed manifest already published. The sheet
        grows downward; nothing above the new rows moves.

        **Nothing is written into the revision store.** A row is "seeded" by
        appearing in the spec: its store key has no history, so the status
        payload reports ``attempts: 0`` and lists it under ``missing.rows``,
        which is exactly what an un-generated row looks like everywhere else.
        Writing a placeholder attempt would invent an image nobody drew.

        **What a new row is grounded on depends on the state, and
        :meth:`_row_reference` decides it — not this verb.** A DIRECTIONAL
        state's rows ground on the turnaround reference the operator already
        APPROVED for that direction (``store.current``, never ``store.latest``:
        an operator who rerolls a direction and then keeps the older attempt has
        to get the older attempt). The stage machine guarantees each of those is
        approved, because that approval is the only thing that advances a draft
        to ``rows``. A ``:fixed`` state has ONE row with no direction at all, so
        it grounds on the BASE image, exactly as a fixed row declared at
        ``start`` does. This paragraph said "the turnaround references" for every
        row until 2026-08-25 — ``:fixed`` is advertised in the CLI help and in
        the skill's verb table, and it has never used one.

        **Add only** (owner decision 8). Removing a state would delete approved
        attempts and the operator notes stored with them — the durable QA record
        — for the benefit of a coverage number. If it is ever wanted it is its
        own ``--confirm`` verb, never a flag here.

        *state_text* is parsed by :func:`~agent.charsheet.spec.parse_states`, so
        the grammar, the reserved ``-``, the name shape and the frame range are
        one authority shared with ``start --states``; a state below
        :data:`~agent.charsheet.spec.MIN_FRAMES_PER_ROW` frames is refused HERE,
        rather than four generations later at ``rows``.
        """
        draft = self.draft
        draft._require_stage("add_state")
        # The grammar stays in ONE place; only the SPELLING of the flag being
        # refused travels, because `--states` (plural, with a two-state example)
        # is not a flag this verb has and `add-state` refuses a list one check
        # later. A refusal that names a flag the caller cannot pass is worse
        # than no refusal message at all.
        added = parse_states(state_text, flag="--state", example="jumping:6")
        if len(added) != 1:
            # `--state` is singular and the launcher registry renders one value
            # for it. A comma-separated list would make this a second, quieter
            # spelling of `start --states`, and it would apply half an operator's
            # request under one review. Two states are two calls.
            raise ValueError(
                f"--state takes ONE state, got {len(added)} "
                f"({', '.join(state.name for state in added)}); add them one "
                "call at a time so each new state's rows are reviewed on their own"
            )
        state = added[0]
        spec = draft.spec
        existing = [current.name for current in spec.states]
        if state.name in existing:
            raise ValueError(
                f"state {state.name!r} is already on this sheet "
                f"(states: {', '.join(existing)}); add-state only ADDS — to "
                f"redraw its strips use `reroll-row`, and to change its frame "
                "count start a new draft"
            )
        grown = SheetSpec(
            states=spec.states + (state,),
            scheme=spec.scheme,
            frame_w=spec.frame_w,
            frame_h=spec.frame_h,
        )
        draft._data["spec"] = spec_to_dict(grown)
        draft._save()
        new_rows = [row.key for row in grown.authored_rows() if row.state == state.name]
        logger.info(
            "charsheet draft %s: state %r added (%d frames) → %d new row(s): %s",
            draft.id,
            state.name,
            state.frames,
            len(new_rows),
            ", ".join(new_rows),
        )
        return {
            "state": {
                "name": state.name,
                "frames": state.frames,
                "directional": bool(state.directional),
            },
            "states": [current.name for current in grown.states],
            "rows": new_rows,
        }
