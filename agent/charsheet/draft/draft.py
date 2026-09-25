"""``CharacterDraft`` — the QA state machine (moved whole for one commit, ruling Q8)."""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

from agent.charsheet import pipeline
from agent.charsheet._support import _safe_segment, _utc_now, _write_bytes_atomic, _write_json_atomic, slugify
from agent.charsheet.draft_lock import LOCK_FILENAME, draft_generation_lock
from agent.charsheet.revisions import ImageRevisionStore
from agent.charsheet.spec import CHAR8, SheetSpec, parse_states
from agent.pet.constants import DEFAULT_SCALE, LOOP_MS
from hermes_constants import get_hermes_home

from .installed import _row_json
from .layout import DEFAULT_THUMB_FRAME, DEFAULT_THUMB_SCALE, DRAFT_FILENAME, MANIFEST_FILENAME, PALETTE_FILENAME, REVISIONS_DIRNAME, SCHEMA, SHEET_FILENAME, STAGES, THUMBS_DIRNAME, _strip_filename, characters_dir, drafts_dir, path_or_none, read_palette, row_item, spec_from_dict, spec_to_dict, turnaround_item

__layer__ = "lanes"

logger = logging.getLogger(__name__)


# ─────────────────────────────── the draft ───────────────────────────────


class CharacterDraft:
    """One in-progress character: its spec, its stage, and its QA history."""

    def __init__(self, directory: Path, data: dict) -> None:
        self.directory = Path(directory)
        self._data = data

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def create(
        cls,
        *,
        concept: str,
        slug: str = "",
        display_name: str = "",
        style: str = "auto",
        spec: SheetSpec = CHAR8,
        base_image=None,
        authored_by: str = "",
    ) -> CharacterDraft:
        """Start a draft at stage ``turnaround``.

        *base_image* is the identity anchor everything is grounded on; it is
        copied into the draft so a later stage can never be invalidated by the
        caller moving or deleting the original. It may be supplied later
        (:meth:`set_base_image`) — the base-draft pick flow has not chosen one
        yet at ``characters start`` time — but no generation verb runs without it.

        *authored_by* is PROVENANCE and nothing else (launcher companion doc §13
        decision 6, which is the single statement of the home rule — this
        docstring points at it and does not restate it): it records which persona
        drove the authoring run so a later reader can ask "whose draft is this".
        It does not scope where the draft lives — nothing does any more: the
        library is install-wide (:func:`characters_dir`), one directory per
        hermes root, whatever persona or profile runs the authoring turn. It is
        not an owner, and no verb checks it. What it does make possible is
        checking: a consumer resuming a draft can ask whether the persona it is
        about to open is bound to the profile that authored it, instead of
        discovering the mismatch as an empty ``status``. Nothing infers it: a
        caller that does not say stores nothing, because a guessed author is
        worse than an absent one.

        "Stores nothing" is literal — the KEY is absent, not present-and-empty.
        An empty string would be a third spelling of "no author" that reads as a
        value, and it is the spelling that survives ``.get(..., "")`` all the way
        into the payload, where a consumer can no longer tell a draft with no
        author recorded from one authored by ``""`` and a backfill can no longer
        select the drafts that need filling in.

        ``hermes_home`` is the OTHER provenance field, and it is written every
        time because nobody has to supply it: it is ``str(get_hermes_home())``,
        the home this run RESOLVED. It is provenance of the run and not a
        locator — the draft sits in the install-wide library, which is not under
        the home this key names, and the library address is a constant every
        reader already knows. What no other record carries is which profile turn
        authored the draft: ``authored_by`` names the persona, this names the
        profile side of the same turn. See :attr:`hermes_home` for what the
        value means once it is stale, and :meth:`record_home` for the drafts
        that arrive without it.
        """
        concept = str(concept or "").strip()
        if not concept:
            raise ValueError("a draft needs a concept: the character description to generate")
        # Validate the anchor BEFORE any directory exists: a bad path must fail
        # the start cleanly, not leave an orphan draft dir behind (CS-5 finding).
        if base_image is not None and not Path(base_image).is_file():
            raise ValueError(f"base image {Path(base_image)} is not an existing file")
        display = str(display_name or "").strip() or concept
        chosen_slug = slugify(slug or display)
        draft_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        directory = drafts_dir() / draft_id
        directory.mkdir(parents=True, exist_ok=False)

        now = _utc_now()
        data = {
            "schema": SCHEMA,
            "id": draft_id,
            "slug": chosen_slug,
            "display_name": display,
            "concept": concept,
            "style": str(style or "auto"),
            "stage": STAGES[0],
            "created": now,
            "updated": now,
            "spec": spec_to_dict(spec),
            "base_image": "",
        }
        author = str(authored_by or "").strip()
        if author:
            data["authored_by"] = author
        # Written UNCONDITIONALLY, unlike `authored_by`: there is no caller to
        # withhold it and nothing to guess — hermes asks its own resolver which
        # home this turn answered and records that. The draft does NOT sit under
        # it (the library is install-wide, `directory` is under
        # `<root>/shared/characters`), and that divergence is the field's
        # re-derived meaning rather than a defect: provenance of the RUN, not a
        # locator. It is still a first-party fact hermes states about itself,
        # never a path a consumer sliced a profile name out of.
        data["hermes_home"] = str(get_hermes_home())
        draft = cls(directory, data)
        draft._save()
        if base_image is not None:
            draft.set_base_image(base_image)
        logger.info("charsheet draft %s created (slug %r)", draft_id, chosen_slug)
        return draft

    @classmethod
    def load(cls, draft_id: str) -> CharacterDraft:
        """Load a draft by id, or raise :class:`FileNotFoundError` with the path."""
        directory = drafts_dir() / _safe_segment(draft_id)
        path = directory / DRAFT_FILENAME
        if not path.is_file():
            raise FileNotFoundError(f"no draft {draft_id!r}: {path} does not exist")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"corrupt draft file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"corrupt draft file {path}: expected a JSON object")
        return cls(directory, data)

    @classmethod
    def list_drafts(cls) -> list[CharacterDraft]:
        """Every readable draft, oldest id first (ids sort chronologically)."""
        out: list[CharacterDraft] = []
        root = drafts_dir()
        for child in sorted(root.iterdir()) if root.is_dir() else []:
            if not (child / DRAFT_FILENAME).is_file():
                continue
            try:
                out.append(cls.load(child.name))
            except (OSError, ValueError) as exc:
                logger.warning("skipping unreadable draft %s: %s", child.name, exc)
        return out

    # ------------------------------------------------------------ accessors

    @property
    def id(self) -> str:
        return str(self._data.get("id", self.directory.name))

    @property
    def shadows(self) -> str | None:
        """The draft id this directory is a COPY of, or ``None`` for a real draft.

        A backup is made by copying a draft directory beside itself
        (``<id>.backup-<date>-<reason>``), so its ``draft.json`` still carries
        the ORIGINAL's ``id`` and :attr:`id` answers it. Two rows of
        ``harness characters list --json`` therefore answered ONE id, and no
        consumer could tell which was the live draft.

        Ruled 2026-09-04: the copy stays a row — it is a directory that exists
        on disk, and a list that hides it lies about the library — but it names
        what it shadows, so a consumer dedupes by dropping every row carrying
        this field and keeping the un-shadowed one.

        DERIVED, never stored. Nothing in this module writes a backup, so there
        is no writer to teach and no backfill to run: the fact is already on
        disk in the disagreement between the directory name and the recorded
        id, and reading it there cannot go stale. :meth:`create` puts a draft at
        ``drafts_dir() / <id>``, so agreement is the invariant a real draft
        holds by construction and a copy necessarily breaks.
        """
        recorded = str(self._data.get("id", "") or "").strip()
        if not recorded or _safe_segment(recorded) == self.directory.name:
            return None
        return recorded

    @property
    def slug(self) -> str:
        return str(self._data.get("slug", ""))

    @property
    def display_name(self) -> str:
        return str(self._data.get("display_name", "") or self.slug)

    @property
    def concept(self) -> str:
        return str(self._data.get("concept", ""))

    @property
    def style(self) -> str:
        return str(self._data.get("style", "auto") or "auto")

    @property
    def stage(self) -> str:
        return str(self._data.get("stage", STAGES[0]))

    @property
    def authored_by(self) -> str | None:
        """The persona this draft was authored by, or ``None`` — provenance only.

        ``None`` and not ``""``: absence is a fact a consumer must be able to
        read. It travels to the payload as JSON ``null``, so B2/P1 can render
        "unattributed" honestly and a later backfill can select exactly the
        drafts that carry no author — neither of which is possible once absence
        has been flattened into an empty string.
        """
        author = str(self._data.get("authored_by", "") or "").strip()
        return author or None

    @property
    def hermes_home(self) -> str | None:
        """The home the authoring RUN resolved, or ``None``.

        ``None`` and not ``""``, for exactly the reason ``authored_by`` gives
        above: the drafts written before this key existed have to stay
        selectable by the backfill, and a consumer has to be able to READ that
        no home was ever recorded rather than receive a value that renders as a
        blank path.

        **It is not an address, and asking it for one gets the wrong answer by
        construction.** The draft lives in the install-wide library
        (:func:`characters_dir`) whatever home created it, so this key answers
        "which profile turn authored this" — the profile-side complement of
        ``authored_by``'s persona. Where the file is, is ``directory``.

        **What it means when it disagrees with the home resolving now.** It is
        provenance about a PAST fact — the home hermes recorded when the draft
        was created, or the source home a ``migrate-home`` run stamped it with
        on the way into the library. A draft authored under one profile still
        names that profile when read from every other one, and that is the field
        being honest. Nothing rewrites a value once it is here.
        """
        home = str(self._data.get("hermes_home", "") or "").strip()
        return home or None

    @property
    def spec(self) -> SheetSpec:
        return spec_from_dict(self._data.get("spec") or {})

    @property
    def base_image(self) -> Path | None:
        name = str(self._data.get("base_image", "") or "")
        if not name:
            return None
        path = self.directory / name
        return path if path.is_file() else None

    @property
    def store(self) -> ImageRevisionStore:
        return ImageRevisionStore(self.directory / REVISIONS_DIRNAME)

    # ----------------------------------------------------------- exclusion

    @contextlib.contextmanager
    def generation_lock(self, verb: str, *, stale_after_seconds: float | None = None) -> Iterator[dict]:
        """Hold this draft against every other writer for the length of *verb*.

        The draft owns the lock, so a caller that reaches the backend directly
        is covered exactly as the CLI verb is; and the file lives in the draft
        directory, so it travels with a copied or quarantined draft rather than
        being stranded in a lock directory that draft never had.

        Re-entrant for the SAME thread, which is what lets ``characters auto``
        take it once around its whole plan and still call
        :meth:`run_turnaround` and :meth:`run_rows`, each of which takes it
        again. A second THREAD — the serve pool's other worker — is a second
        writer and is refused. See :mod:`agent.charsheet.draft_lock`.
        """

        with draft_generation_lock(
            self.directory / LOCK_FILENAME,
            draft_id=self.id,
            verb=verb,
            stale_after_seconds=stale_after_seconds,
        ) as holder:
            yield holder

    # --------------------------------------------------------- provenance

    def record_home(self) -> bool:
        """Fill in a missing ``hermes_home``; return whether anything was written.

        The stamp path for a draft that arrives in the library without the key
        — one restored from quarantine, one hand-copied in — and the second site
        that writes it (``create`` is the first). Two rules, and both are
        load-bearing:

        **It never rewrites.** A draft that already states a home keeps it, even
        when that home is not the one resolving now — see :attr:`hermes_home`.
        Stamping unconditionally would overwrite the history the field exists to
        keep, silently, on every run, and it is the copied and backed-up drafts
        — the ones whose recorded home is most interesting — that it would
        destroy first. A present-but-blank value counts as absent, because the
        accessor already rules that ``""`` is not a home.

        **It does not go through :meth:`_save`.** ``_save`` stamps ``updated``
        with "now", and the drafts this exists for are dormant exhibits whose
        timeline is evidence: a backfill that bumped every one of them to the
        moment an operator ran it would falsify exactly what those drafts are
        kept to show. This writes the file directly, so every other byte —
        ``updated`` and ``authored_by`` included — is left as it was found.
        """
        if self.hermes_home is not None:
            return False
        self._data["hermes_home"] = str(get_hermes_home())
        _write_json_atomic(self.directory / DRAFT_FILENAME, self._data)
        logger.info("charsheet draft %s: recorded home %s", self.id, self._data["hermes_home"])
        return True

    # ------------------------------------------------------------- internals

    def _save(self) -> None:
        self._data["updated"] = _utc_now()
        _write_json_atomic(self.directory / DRAFT_FILENAME, self._data)

    def _set_stage(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; expected one of {list(STAGES)}")
        self._data["stage"] = stage
        self._save()

    def _require_stage(self, verb: str, *expected: str) -> None:
        if self.stage not in expected:
            wanted = " or ".join(repr(name) for name in expected)
            raise ValueError(
                f"{verb} requires draft stage {wanted}, but draft {self.id} is at "
                f"stage {self.stage!r} (stage order: {' -> '.join(STAGES)})"
            )

    def _require_base(self) -> Path:
        base = self.base_image
        if base is None:
            raise ValueError(
                f"draft {self.id} has no base image; pick one before generating "
                "(every direction and row is grounded on it)"
            )
        return base

    def _require_authored_direction(self, direction: str) -> str:
        authored = self.spec.scheme.authored
        if direction not in authored:
            raise ValueError(
                f"direction {direction!r} is not authored for this sheet "
                f"(authored: {', '.join(authored)}); mirrored directions are "
                "never drawn and never composed, so they are never QA items"
            )
        return direction

    def _authored_row(self, key: str):
        for row in self.spec.authored_rows():
            if row.key == key:
                return row
        raise ValueError(
            f"{key!r} is not an authored row of this sheet (authored rows: "
            f"{', '.join(row.key for row in self.spec.authored_rows())})"
        )

    def set_base_image(self, image_path) -> Path:
        """Copy *image_path* into the draft as its identity anchor."""
        source = Path(image_path)
        if not source.is_file():
            raise ValueError(f"base image {source} is not an existing file")
        suffix = source.suffix.lower() or ".png"
        target = self.directory / f"base{suffix}"
        # Bytes are copied verbatim rather than re-encoded: the base is what the
        # provider is shown, and a re-encode would change what identity is
        # grounded on.
        _write_bytes_atomic(target, source.read_bytes())
        self._data["base_image"] = target.name
        self._save()
        return target

    # ------------------------------------------------- stage 1: turnaround

    def run_turnaround(self, provider=None) -> dict:
        """One strip → an unapproved reference per authored direction.

        Re-running proposes a fresh attempt for every direction and clears the
        approvals (the revision store's rule), which is the intended behaviour for
        "the whole turnaround was bad".

        Locked for the whole run (:meth:`generation_lock`): the stage read, the
        provider call and every ``propose`` are one writer's work, and the stage
        is read INSIDE the lock so a second writer cannot advance it in between.
        """
        with self.generation_lock("turnaround"):
            self._require_stage("run_turnaround", "turnaround")
            spec = self.spec
            base = self._require_base()
            refs = pipeline.generate_turnaround(
                spec,
                self.concept,
                base,
                style=self.style,
                provider=provider,
                out_dir=self.directory / "turnaround",
            )
            store = self.store
            out: dict[str, dict] = {}
            for direction in pipeline.turnaround_order(spec.scheme.authored):
                path = refs[direction]
                attempt = store.propose(turnaround_item(direction), path)
                out[direction] = {"attempt": attempt, "path": str(path), "approved": False}
            self._save()
            return {"stage": self.stage, "turnaround": out}

    def reroll_direction(self, direction: str, note: str = "", provider=None) -> dict:
        """Re-generate ONE direction reference on a square canvas, with *note*.

        Proposed unapproved: this is the identity gate, and a re-roll is a new
        candidate for the operator to look at.

        Locked like the batch verbs, and for a reason of its own beyond "it
        generates": the attempt count is READ to name the output file and then
        WRITTEN by ``propose``, so two re-rolls of one direction racing here
        pick the same filename and the second overwrites the first's bytes.
        """
        with self.generation_lock("reroll-direction"):
            self._require_stage("reroll_direction", "turnaround")
            self._require_authored_direction(direction)
            base = self._require_base()
            store = self.store
            key = turnaround_item(direction)
            attempts = len(store.history(key))
            out_path = self.directory / "turnaround" / f"reroll-{direction}-{attempts + 1}.png"
            path = pipeline.generate_direction_view(
                direction,
                self.concept,
                base,
                style=self.style,
                note=note,
                provider=provider,
                out=out_path,
            )
            attempt = store.propose(key, path, note=note)
            self._save()
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
        self._require_stage("approve_direction", "turnaround")
        self._require_authored_direction(direction)
        index = self.store.approve(turnaround_item(direction), attempt)
        advanced = self._advance_if_directions_approved()
        return {
            "direction": direction,
            "approved": index,
            "faceOffset": self._face_offset(direction),
            "stage": self.stage,
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
        return pipeline.face_offset(self.store.current(turnaround_item(direction)))

    def approve_all_directions(self) -> dict:
        """Approve the latest attempt of every authored direction, then advance."""
        self._require_stage("approve_all_directions", "turnaround")
        store = self.store
        approved: dict[str, int] = {}
        for direction in self.spec.scheme.authored:
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
            "stage": self.stage,
            "advanced": advanced,
        }

    def _advance_if_directions_approved(self) -> bool:
        store = self.store
        pending = [
            direction
            for direction in self.spec.scheme.authored
            if store.current(turnaround_item(direction)) is None
        ]
        if pending:
            return False
        self._set_stage("rows")
        logger.info("charsheet draft %s: all directions approved → stage 'rows'", self.id)
        return True

    # ------------------------------------------------------ stage 2: rows

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
        with self.generation_lock("rows"):
            self._require_stage("run_rows", "rows")
            spec = self.spec
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

            store = self.store
            out: dict[str, dict] = {}
            for row in rows:
                ref = self._row_reference(row)
                key = row_item(row.key)
                attempts = len(store.history(key))
                out_path = self.directory / "strips" / _strip_filename(row.key, attempts + 1)
                path = pipeline.generate_row_strip(
                    row,
                    self.concept,
                    ref,
                    style=self.style,
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
            self._save()
            return {"stage": self.stage, "rows": out}

    def _row_reference(self, row) -> Path:
        """What a row is grounded on: its approved direction ref, else the base."""
        if row.direction is None:
            return self._require_base()
        ref = self.store.current(turnaround_item(row.direction))
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
        with self.generation_lock("reroll-row"):
            self._require_stage("reroll_row", "rows")
            row = self._authored_row(row_key)
            store = self.store
            key = row_item(row.key)
            attempts = len(store.history(key))
            ref = self._row_reference(row)
            out_path = self.directory / "strips" / _strip_filename(row.key, attempts + 1)
            path = pipeline.generate_row_strip(
                row,
                self.concept,
                ref,
                style=self.style,
                note=note,
                provider=provider,
                out=out_path,
            )
            attempt = store.propose(key, path, note=note)
            store.approve(key, attempt)
            self._save()
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
        self._require_stage("add_state", "rows")
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
        spec = self.spec
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
        self._data["spec"] = spec_to_dict(grown)
        self._save()
        new_rows = [row.key for row in grown.authored_rows() if row.state == state.name]
        logger.info(
            "charsheet draft %s: state %r added (%d frames) → %d new row(s): %s",
            self.id,
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

    # ------------------------------------------------------- looking at rows

    def row_thumb(
        self,
        row_key: str,
        *,
        attempt: int = -1,
        frame: int = DEFAULT_THUMB_FRAME,
        scale: int = DEFAULT_THUMB_SCALE,
        square: bool = False,
    ) -> dict:
        """Write a card-size QA crop of ONE frame of ONE row attempt.

        The §F.2 looking procedure as a verb, and the procedure is *crop, then
        upscale* — in that order, because the crop is the half that removes
        pixels. A row strip shown whole in a chat column is a false negative
        machine: the 2026-08-24 seam was invisible at fit-to-window scale in the
        very strip that carried it, and "I looked at the strip and it's fine" was
        reliably wrong. Enlarging that same strip does not fix it — measured
        live, a whole-strip 2x thumb and the raw attempt are the same picture at
        card width (≤2/255 per channel), while costing 24 MiB decoded against
        the 12 MiB installed sheet the crop exists to avoid decoding.

        So the default is ONE frame cell (:data:`DEFAULT_THUMB_FRAME`), sliced
        from the strip by the row's own frame count, and only then upscaled with
        NEAREST (no filter averages the defect away) onto a flat dark backdrop
        with the chroma field keyed out (a seam over magenta reads as nothing,
        and so does one over transparency). The whole-strip view still exists and
        needs no verb: it is the attempt file itself, which the payload names as
        ``source``.

        Stage-free on purpose: looking is never out of order. A composed draft is
        exactly when an operator goes back to find what went wrong, and refusing
        to render a picture at that point is the wall ``reopen`` was built to
        remove.

        **Two bounds, two booleans, and the payload carries both.** A crop is
        weighed against two different things and they disagree on real drafts,
        so one boolean could never have answered for both — it answered for one
        and was READ as the other:

        * ``withinConsoleBudget`` — the crop is under
          :data:`pipeline.MAX_CONSOLE_CARD_PIXELS`, a FIXED console decode
          ceiling sized once from ``CHAR8``. It does not move with a spec. This
          is the bound that is ENFORCED: a crop taken at
          :data:`DEFAULT_THUMB_SCALE` or below — the crop a caller gets by
          asking for a picture, and the one an agent declares with a ``MEDIA:``
          line — is REFUSED when it exceeds it. A deliberate deeper zoom is a
          different artifact with a different reader: allowed up to the write
          ceiling and labelled ``withinConsoleBudget: false``. A boolean rather
          than a silent clamp, because a caller who asked for 8x wants 8x — they
          just must not be told it is a card.
        * ``withinOwnSheet`` — the crop is no larger than the sheet THIS draft
          composes, from its own ``spec.sheet_size()``
          (:func:`pipeline.fits_own_sheet`). It moves with the draft. Nothing is
          refused on it; it is reported at every scale, because a crop heavier
          than its own sheet is a legal picture that simply mitigated nothing.

        **THE CONSUMER RULE, for the launcher card (B2) and for any agent
        declaring a crop: draw it inline ONLY when BOTH are true. Otherwise
        route it to the fullscreen viewer** — ``withinConsoleBudget: false``
        because the decode would sink the surface, ``withinOwnSheet: false``
        because cropping bought nothing and the card may as well have opened
        the sheet.

        Measured both ways, which is why they are two: a ``--directions 4``,
        ``idle:2`` draft's default crop came back 1774x1774 = 3,147,076 px —
        ``withinConsoleBudget: true``, ``withinOwnSheet: false`` at 13.1x its
        239,616-px sheet; and an ``add-state``-grown sheet (1536x3120 =
        4,792,320 px, 1.50x the fixed budget) can take a crop the other way
        round, over the console ceiling and still lighter than the sheet that
        draft will compose. ``cardSafe``, which this payload carried until
        2026-08-25, was the first of these two wearing the second one's name.

        **``square`` is the hero-card shape, and it is opt-in.** The console
        card is a fixed 1:1 centre-cover square (§13.17, ruled: the card is not
        moving), and a character cell is taller than it is wide — so the default
        crop renders there as a torso zoom, which is real confusion even though
        the card was never the verdict surface. With *square*, the finished crop
        is centred on a square field of the same flat dark backdrop
        (:func:`pipeline.pad_to_square`, side = the longer edge) so the card
        draws the whole frame; the filename gains ``-sq`` and the payload says
        ``square: true``. The DEFAULT stays tall: a compare pair aligns its
        panes, and padding changes the aspect the compare guidance assumes. Use
        ``--square`` for a card, bare crops for a comparison.

        **Both bounds are weighed on the PADDED output**, because padding adds
        pixels and the file a consumer decodes is the padded one. A square crop
        can therefore be refused at the default scale where the bare crop of the
        same cell is fine — the refusal names the padded size, since arguing
        about the unpadded one would be arguing about a file nobody asked for.

        Returns a PATH and never bytes (plan A-4): the launcher runs on this
        machine, and the trace lane that would carry an inline image is capped at
        4 KiB.
        """
        row = self._authored_row(row_key)
        store = self.store
        key = row_item(row.key)
        if not store.history(key):
            raise ValueError(
                f"row {row.key!r} has no attempt to crop yet; generate it first "
                f"(`characters rows --only {row.key}`)"
            )
        # The store resolves -1 → the newest index and refuses out-of-range, so
        # the number in the filename is the number the payload reports.
        index = store.attempt_index(key, attempt)
        source = store.attempt_path(key, index)
        if source is None or not source.is_file():
            raise ValueError(
                f"attempt {index} of row {row.key!r} has no image on disk"
                + (f" at {source}" if source is not None else "")
            )
        cell = pipeline.frame_cell(source, frame=frame, frames=row.frames)
        crop = self._finish_thumb(
            cell,
            scale=scale,
            square=square,
            stem=f"{row.key}-attempt-{index + 1}-frame-{frame + 1}",
            subject=f"frame of row {row.key!r}",
            remedies=("a row with more frames to slice",),
        )
        logger.info(
            "charsheet draft %s: row %s attempt %d frame %d cropped at %dx%d → %s",
            self.id,
            row.key,
            index,
            frame,
            crop["width"],
            crop["height"],
            crop["path"],
        )
        return {
            "row": row.key,
            "attempt": index,
            "attempts": len(store.history(key)),
            "frame": frame,
            "frames": row.frames,
            "source": str(source),
            **crop,
        }

    def direction_thumb(
        self,
        direction: str,
        *,
        attempt: int = -1,
        scale: int = DEFAULT_THUMB_SCALE,
        square: bool = False,
    ) -> dict:
        """Write a card-size QA crop of ONE turnaround DIRECTION reference.

        The same verdict :meth:`row_thumb` publishes for a row, for the other
        kind of QA item — and it exists because the ABSENCE of a verdict, not
        any weight, is what made the launcher's card draw a tile through the
        whole turnaround stage. A reference is generated on a SQUARE canvas by
        :func:`pipeline.generate_direction_view` and is comfortably inside both
        bounds at the default scale; there was simply nothing to publish.

        Everything :meth:`row_thumb`'s docstring says about the two bounds and
        the consumer rule — draw it inline only when BOTH booleans are true,
        otherwise route it to the fullscreen viewer — holds here unchanged, and
        holds because it is the same code: one helper weighs, keys, upscales,
        pads and writes for both kinds.

        **No frame keys, rather than frame keys faked to 0-of-1.** A row strip
        holds several poses side by side and a reference holds one, so there is
        nothing to slice and :func:`pipeline.frame_cell` is never called. A
        payload that answered ``frame: 0, frames: 1`` would be inviting a
        consumer to offer a frame picker for a picture that has no frames.

        Stage-free for the reason the row crop is: a composed draft is exactly
        when an operator goes back to ask what the reference looked like, and
        the references are never deleted.
        """
        self._require_authored_direction(direction)
        store = self.store
        key = turnaround_item(direction)
        if not store.history(key):
            raise ValueError(
                f"direction {direction!r} has no attempt to crop yet; generate it "
                f"first (`characters turnaround` or `characters reroll-direction "
                f"--direction {direction}`)"
            )
        index = store.attempt_index(key, attempt)
        source = store.attempt_path(key, index)
        if source is None or not source.is_file():
            raise ValueError(
                f"attempt {index} of direction {direction!r} has no image on disk"
                + (f" at {source}" if source is not None else "")
            )
        crop = self._finish_thumb(
            # The reference IS the cell — `reference_cell` is the "nothing to
            # slice" counterpart of `frame_cell`, and naming it keeps every
            # decode of a QA source in the module that owns pixels.
            pipeline.reference_cell(source),
            scale=scale,
            square=square,
            # `turnaround-` prefixed because a direction is a bare compass
            # sector: `e-attempt-1-x2.png` beside `walk-e-attempt-1-frame-1-x2`
            # reads as a truncated row key, and the store's own item key is
            # `turnaround@e` for the same reason.
            stem=f"turnaround-{direction}-attempt-{index + 1}",
            subject=f"reference for direction {direction!r}",
            remedies=(),
        )
        logger.info(
            "charsheet draft %s: direction %s attempt %d cropped at %dx%d → %s",
            self.id,
            direction,
            index,
            crop["width"],
            crop["height"],
            crop["path"],
        )
        return {
            "direction": direction,
            "attempt": index,
            "attempts": len(store.history(key)),
            "source": str(source),
            **crop,
        }

    def _finish_thumb(
        self,
        cell,
        *,
        scale: int,
        square: bool,
        stem: str,
        subject: str,
        remedies: tuple[str, ...],
    ) -> dict:
        """Weigh, key, upscale, pad and write ONE crop; the half both kinds share.

        *cell* is the finished source region — a sliced frame for a row, the
        whole reference for a direction. *subject* and *remedies* are the only things the
        two kinds say differently, and they are both refusal prose: WHAT was too
        big, and which other shapes the caller could ask for instead.

        Split out when the direction arm landed. The two bounds, the refusal
        threshold, the two backdrops and the pad order are one implementation on
        purpose — a second copy is how ``cardSafe`` came to mean two different
        things in two places.
        """
        # Both bounds are read off the OUTPUT size before anything is allocated:
        # the write ceiling inside `upscale_on_backdrop`, the card budget here,
        # where the default is known. Refusing after the resize would already
        # have paid for the picture nobody may use. The scale is gated first
        # through the same helper `upscale_on_backdrop` uses — weighing an
        # output means multiplying by it, and `512 * "2"` is a string.
        scale = pipeline.require_scale(scale)
        square = bool(square)
        # This draft's OWN spec, which is the whole point of the second bound:
        # the sheet a crop is weighed against is the one THIS draft composes,
        # never the package's largest.
        spec = self.spec
        out_w, out_h = cell.width * scale, cell.height * scale
        # The PADDED size when one is coming: `--square` adds margin to the
        # shorter axis, and every number below — both booleans, the refusal, the
        # payload — is about the file a consumer will decode, not about the
        # intermediate crop that is never written.
        if square:
            out_w = out_h = max(out_w, out_h)
        within_console_budget = pipeline.fits_console_budget(out_w, out_h)
        within_own_sheet = pipeline.fits_own_sheet(out_w, out_h, spec)
        if not within_console_budget and scale <= DEFAULT_THUMB_SCALE:
            raise ValueError(
                f"scale {scale} on this {cell.width}x{cell.height} {subject} "
                "would write "
                + ("a square " if square else "")
                + f"{out_w}x{out_h} "
                f"= {out_w * out_h:,} pixels, over the "
                f"{pipeline.MAX_CONSOLE_CARD_PIXELS:,}-pixel console budget — the "
                "fixed ceiling on what a chat card may decode, which is NOT a "
                "comparison against this draft's own sheet (the payload answers "
                "that separately as withinOwnSheet); "
                "ask for --scale 1, "
                + "".join(f"or {remedy}, " for remedy in remedies)
                + "or --scale 3 or more to take it as a viewer artifact carrying "
                "withinConsoleBudget: false"
                + (", or drop --square to take the cell unpadded" if square else "")
            )
        # Two grounds for two consumers (operator ruling 2026-08-29): the
        # `--square` CARD crop keeps the keyed sprite's transparency — the
        # console draws its own ground (checkerboard) behind it — while the
        # bare COMPARE crop keeps the flat dark looking-procedure ground,
        # where a 1-px seam must not vanish into a viewer's flatten color.
        backdrop = (
            pipeline.TRANSPARENT_BACKDROP if square else pipeline.QA_BACKDROP
        )
        image = pipeline.upscale_on_backdrop(cell, scale=scale, backdrop=backdrop)
        if square:
            # ONE pad step, last: the crop is finished before the margin is
            # added, so nothing the looking procedure did is enlarged, keyed or
            # resampled a second time.
            image = pipeline.pad_to_square(image, backdrop=backdrop)
        # The filename is a HUMAN surface — an operator correlating a crop back
        # to the attempt it came from — so it counts the way the store's own
        # filenames count: `walk-n-attempt-3-frame-1-x2.png` sits beside
        # `revisions/row@walk-n/attempt-3.png`. The payload below stays 0-based
        # machine truth. A QA surface relabels; it never renumbers.
        # `-sq` because the two shapes are two artifacts of the same cell: a card
        # crop and a compare crop must be able to sit in the thumbs directory at
        # once, and an operator must be able to tell which is which by name.
        out = self.directory / THUMBS_DIRNAME / f"{stem}-x{scale}{'-sq' if square else ''}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(out, format="PNG")
        return {
            "scale": scale,
            # Unconditional, like the two booleans below and for the same
            # reason: a consumer deciding WHERE to draw a crop cannot infer the
            # shape from a filename, and the default is a shape too.
            "square": square,
            "path": str(out),
            "width": image.width,
            "height": image.height,
            # Both, always, at every scale — see the docstring's consumer rule.
            # A consumer that reads one and infers the other is the defect this
            # split exists to retire.
            "withinConsoleBudget": within_console_budget,
            "withinOwnSheet": within_own_sheet,
        }

    # -------------------------------------------------- stage 3: composed

    def reopen(self) -> dict:
        """Reopen a composed draft for fixes; returns to stage ``rows``.

        Nothing is deleted and the installed sheet stays installed: compose
        always re-runs from the approved strips, so the next ``compose`` after
        a fix simply overwrites the install. Without this verb the only path
        back was hand-editing ``draft.json`` (proven live on 2026-08-24).
        """
        self._require_stage("reopen", "composed")
        self._set_stage("rows")
        return {"stage": self.stage}

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
        self._require_stage("compose", "rows")
        spec = self.spec
        store = self.store

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
                f"cannot compose draft {self.id}: {len(missing)} row(s) have no "
                f"approved strip ({', '.join(missing)})"
            )

        palette_sources: list[Path] = []
        for direction in pipeline.turnaround_order(spec.scheme.authored):
            ref = store.current(turnaround_item(direction))
            if ref is None:
                raise ValueError(
                    f"cannot compose draft {self.id}: direction {direction!r} has "
                    "no approved reference to take the palette from"
                )
            palette_sources.append(ref)

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
                f"composed sheet for draft {self.id} failed validation.\n"
                + pipeline.handedness_summary(validation["handedness"])
                + "; a refusal is not a full audit.\n\n"
                + "\n\n".join(validation["errors"])
            )

        directory = characters_dir() / _safe_segment(slugify(self.slug))
        # Clobber guard: re-composing THIS draft may overwrite its own install,
        # but a colliding slug from a different draft is a different character.
        existing_manifest = directory / MANIFEST_FILENAME
        if existing_manifest.is_file():
            try:
                prior = json.loads(existing_manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = {}
            prior_draft = str(prior.get("draftId", "")) if isinstance(prior, dict) else ""
            if prior_draft and prior_draft != self.id:
                raise ValueError(
                    f"slug {slugify(self.slug)!r} is already installed from draft "
                    f"{prior_draft}; composing draft {self.id} over it would replace "
                    "a different character — pick another slug"
                )
        directory.mkdir(parents=True, exist_ok=True)
        sheet_path = directory / SHEET_FILENAME
        _write_bytes_atomic(sheet_path, pipeline.atlas_to_webp_bytes(sheet))

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
        _write_json_atomic(directory / PALETTE_FILENAME, palette)
        _write_json_atomic(self.directory / PALETTE_FILENAME, palette)

        rows = [_row_json(row) for row in spec.rows()]
        manifest = {
            "schema": SCHEMA,
            "slug": slugify(self.slug),
            "displayName": self.display_name,
            "concept": self.concept,
            "style": self.style,
            "spec": spec_to_dict(spec),
            "rows": rows,
            "frameW": spec.frame_w,
            "frameH": spec.frame_h,
            "loopMs": LOOP_MS,
            "scale": DEFAULT_SCALE,
            "generator": "charsheet",
            "draftId": self.id,
            "created": _utc_now(),
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
        _write_json_atomic(directory / MANIFEST_FILENAME, manifest)
        self._set_stage("composed")
        logger.info(
            "charsheet draft %s composed → %s (%dx%d)",
            self.id,
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
            "stage": self.stage,
        }

    # ---------------------------------------------------------- reporting

    def status_payload(self) -> dict:
        """Everything a QA UI needs: stage, spec summary, per-item history.

        JSON-safe by construction. ``current`` is the approved image when there is
        one and the latest attempt otherwise, so a pending item is still
        displayable.

        **Every path in this payload is a ``str`` or JSON ``null``** — including
        ``baseImage``, which is the one ``path_or_none`` did NOT reach when the
        rule was first written. It answered ``""`` for a draft with no base image
        beside ``authoredBy: null`` and ``history[].path: null`` in the same
        response, which is exactly the two-spellings defect the helper exists to
        retire, one field later. ``list`` carries the same field
        (``_characters_draft_summary``) and answers the same way.
        """
        spec = self.spec
        store = self.store
        width, height = spec.sheet_size()
        base = self.base_image

        turnaround = {
            direction: self._item_status(store, turnaround_item(direction))
            for direction in pipeline.turnaround_order(spec.scheme.authored)
        }
        rows = {
            row.key: self._item_status(store, row_item(row.key))
            for row in spec.authored_rows()
        }
        # ABSENT, not empty, when this draft has not composed. The key is spelled
        # as a conditional entry in a fixed position rather than appended, so a
        # consumer reading key order sees one shape; and an uncomposed draft is
        # not the same fact as a sheet with no colours (`read_palette`).
        palette = read_palette(self.directory)
        return {
            "schema": SCHEMA,
            "id": self.id,
            "slug": self.slug,
            "displayName": self.display_name,
            "concept": self.concept,
            "style": self.style,
            "authoredBy": self.authored_by,
            # The two provenance fields travel together, and both spell absence
            # `null`. `hermesHome` is a PATH field, so it is also bound by the
            # rule this docstring states: a `str` or JSON `null`, never `""`.
            "hermesHome": self.hermes_home,
            "stage": self.stage,
            "stages": list(STAGES),
            "created": str(self._data.get("created", "")),
            "updated": str(self._data.get("updated", "")),
            "baseImage": path_or_none(base),
            **({"palette": palette} if palette is not None else {}),
            "spec": {
                **spec_to_dict(spec),
                "rows": [_row_json(row) for row in spec.rows()],
                "sheetWidth": width,
                "sheetHeight": height,
            },
            "turnaround": turnaround,
            "rows": rows,
            "pending": {
                "turnaround": [
                    direction for direction, item in turnaround.items() if item["approved"] is None
                ],
                "rows": [key for key, item in rows.items() if item["approved"] is None],
            },
            "missing": {
                "turnaround": [
                    direction for direction, item in turnaround.items() if not item["attempts"]
                ],
                "rows": [key for key, item in rows.items() if not item["attempts"]],
            },
        }

    @staticmethod
    def _item_status(store: ImageRevisionStore, key: str) -> dict:
        """One QA item: its counts, its current image, and every attempt's file.

        ``history[].path`` is the store's own answer for that index, not a
        filename re-derived from the attempt number — a QA surface that wants to
        show attempt 2 beside attempt 3 has to address them individually, and
        re-spelling the store's layout here is how the two would drift apart.

        **Every path here is a ``str`` or JSON ``null``, never ``""``.** Same
        reasoning as ``authored_by`` above, and the same payload: absence is a
        fact a consumer must be able to READ. An empty string is not a path, and
        a consumer that receives one cannot tell "no image was recorded for this
        attempt" from any other empty value — while an agent following the
        ``MEDIA:<path>`` protocol interpolates it and emits a bare ``MEDIA:``
        line. ``attempt_path``/``current``/``latest`` all return a typed
        ``Path | None``; flattening that at the payload boundary destroyed the
        only distinction the store took care to make.
        """
        history = store.history(key)
        approved = store.approved_index(key)
        approved_path = store.current(key)
        # A pending item's newest attempt is what QA has to look at.
        current = approved_path if approved_path is not None else store.latest(key)
        return {
            "key": key,
            "attempts": len(history),
            "approved": approved,
            "approvedPath": path_or_none(approved_path),
            "current": path_or_none(current),
            "rejected": [i for i, record in enumerate(history) if record.get("rejected")],
            "history": [
                {
                    "attempt": index,
                    "path": path_or_none(store.attempt_path(key, index)),
                    "note": str(record.get("note", "")),
                    "created": str(record.get("created", "")),
                    "rejected": bool(record.get("rejected")),
                }
                for index, record in enumerate(history)
            ],
        }
