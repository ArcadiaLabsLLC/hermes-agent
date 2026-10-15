"""``CharacterDraft`` — the QA state machine (moved whole for one commit, ruling Q8)."""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

from agent.charsheet._support import safe_segment, slugify, utc_now, write_json_atomic
from agent.charsheet.draft_lock import LOCK_FILENAME, draft_generation_lock
from agent.charsheet.revisions import ImageRevisionStore
from agent.charsheet.spec import CHAR8, SheetSpec
from hermes_constants import get_hermes_home

from .compose import Composer
from .directions import DirectionStage
from .layout import DEFAULT_THUMB_FRAME, DEFAULT_THUMB_SCALE, DRAFT_FILENAME, REVISIONS_DIRNAME, SCHEMA, STAGES, VERB_STAGES, Stage, drafts_dir, spec_from_dict, spec_to_dict
from .rows import RowStage
from .status import StatusReport
from .thumbs import Thumbs

__layer__ = "lanes"

logger = logging.getLogger(__name__)


# ─────────────────────────────── the draft ───────────────────────────────


class CharacterDraft:
    """One in-progress character: its spec, its stage, and its QA history."""

    def __init__(self, directory: Path, data: dict) -> None:
        self.directory = Path(directory)
        self._data = data
        self._directions = DirectionStage(self)
        self._rows = RowStage(self)
        self._thumbs = Thumbs(self)
        self._composer = Composer(self)
        self._status = StatusReport(self)

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

        now = utc_now()
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
        directory = drafts_dir() / safe_segment(draft_id)
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
        if not recorded or safe_segment(recorded) == self.directory.name:
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
        write_json_atomic(self.directory / DRAFT_FILENAME, self._data)
        logger.info("charsheet draft %s: recorded home %s", self.id, self._data["hermes_home"])
        return True

    # ------------------------------------------------------------- internals

    def _save(self) -> None:
        self._data["updated"] = utc_now()
        write_json_atomic(self.directory / DRAFT_FILENAME, self._data)

    def _set_stage(self, stage: Stage) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; expected one of {list(STAGES)}")
        self._data["stage"] = stage
        self._save()

    def _require_stage(self, verb: str) -> None:
        expected = VERB_STAGES[verb]
        if self.stage != expected:
            wanted = repr(str(expected))
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

    # ------------------------------------------ the stages, by composition

    def set_base_image(self, image_path) -> Path:
        """See :meth:`DirectionStage.set_base_image`."""
        return self._directions.set_base_image(image_path)

    def run_turnaround(self, provider=None) -> dict:
        """See :meth:`DirectionStage.run_turnaround`."""
        return self._directions.run_turnaround(provider)

    def reroll_direction(self, direction: str, note: str = "", provider=None) -> dict:
        """See :meth:`DirectionStage.reroll_direction`."""
        return self._directions.reroll_direction(direction, note, provider)

    def approve_direction(self, direction: str, attempt: int = -1) -> dict:
        """See :meth:`DirectionStage.approve_direction`."""
        return self._directions.approve_direction(direction, attempt)

    def approve_all_directions(self) -> dict:
        """See :meth:`DirectionStage.approve_all_directions`."""
        return self._directions.approve_all_directions()

    def run_rows(self, only: list[str] | None = None, provider=None) -> dict:
        """See :meth:`RowStage.run_rows`."""
        return self._rows.run_rows(only, provider)

    def reroll_row(self, row_key: str, note: str = "", provider=None) -> dict:
        """See :meth:`RowStage.reroll_row`."""
        return self._rows.reroll_row(row_key, note, provider)

    def add_state(self, state_text: str) -> dict:
        """See :meth:`RowStage.add_state`."""
        return self._rows.add_state(state_text)

    def row_thumb(
        self,
        row_key: str,
        *,
        attempt: int = -1,
        frame: int = DEFAULT_THUMB_FRAME,
        scale: int = DEFAULT_THUMB_SCALE,
        square: bool = False,
    ) -> dict:
        """See :meth:`Thumbs.row_thumb`."""
        return self._thumbs.row_thumb(row_key, attempt=attempt, frame=frame, scale=scale, square=square)

    def direction_thumb(
        self,
        direction: str,
        *,
        attempt: int = -1,
        scale: int = DEFAULT_THUMB_SCALE,
        square: bool = False,
    ) -> dict:
        """See :meth:`Thumbs.direction_thumb`."""
        return self._thumbs.direction_thumb(direction, attempt=attempt, scale=scale, square=square)

    def reopen(self) -> dict:
        """See :meth:`Composer.reopen`."""
        return self._composer.reopen()

    def compose(self, accept_handedness: Sequence[str] = ()) -> dict:
        """See :meth:`Composer.compose`."""
        return self._composer.compose(accept_handedness)

    def status_payload(self) -> dict:
        """See :meth:`StatusReport.status_payload`."""
        return self._status.status_payload()

    # ------------------------------------------------- stage 1: turnaround


    # ------------------------------------------------------ stage 2: rows

    # ------------------------------------------------------- looking at rows


    # -------------------------------------------------- stage 3: composed

    # ---------------------------------------------------------- reporting


