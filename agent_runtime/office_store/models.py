"""The office store's value types and caps: the actor-scan result and its
bounded unreadable-name list, the typed per-actor outcome (``OfficeActorOutcome``
— the reference for typed store outcomes, program rule 14), the conflict scan,
the position-policy hook type, and the ledger/item/folder caps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, NamedTuple

from agent_runtime.models import OfficeActor

__layer__ = "models"

__all__ = [
    "ARCHIVED_ACTOR_FILES_RETAIN",
    "ARCHIVED_LEDGER_CAP",
    "MAX_FOLDERS",
    "MAX_ITEMS_PER_ACTOR",
    "MAX_UNREADABLE_ACTOR_FILE_NAMES",
    "NO_UNREADABLE_ACTOR_FILES",
    "OUTCOME_OK",
    "ActorKind",
    "ActorKindInvalid",
    "ActorKindMismatch",
    "ActorScan",
    "ConflictScan",
    "OfficeActorOutcome",
    "OfficePositionPolicy",
    "UnreadableActorFiles",
]


class ActorKind(StrEnum):
    """What an upsert payload's actor IS (``RT-GENERIC-DESK-WRITE-PAYS``, additive wire field
    ``actor_kind``, default ``persona``).

    ``FURNITURE`` is an actor whose ``persona_id`` is an ADDRESS (a generic desk's
    ``desk_<8 base36>``, CONTRACT 43), never a persona class: it has no class to re-key, so the
    class-key fence does not apply to it and its write pays no actor scan. The store refuses a
    furniture payload whose items are not all desks (:class:`ActorKindMismatch`).
    """

    PERSONA = "persona"
    FURNITURE = "furniture"


class ActorKindInvalid(ValueError):
    """``actor_kind`` is neither ``persona`` nor ``furniture``."""

    reason = "actor_kind_invalid"


class ActorKindMismatch(ValueError):
    """A ``furniture`` payload carries an item that is not a desk: the word cannot carry an agent
    placement past the class-key fence."""

    reason = "actor_kind_mismatch"


ARCHIVED_LEDGER_CAP = 5000
#: How many archived actor FILES one workspace keeps under ``office/<ws>/archive/``
#: (owner ruling 2026-10-15, RT-OFFICE-ARCHIVE-DIRECTORY): the newest 20, the
#: same bound the agent archive keeps. The tombstone is the surface's
#: ``archived_actor_keys`` ledger (``ARCHIVED_LEDGER_CAP``), not the file, so a
#: pruned copy never lets a removed key resurrect; what goes is
#: ``actor-restore`` for the 21st-oldest removal and the history an unbounded
#: directory made every reader walk.
ARCHIVED_ACTOR_FILES_RETAIN = 20
MAX_ITEMS_PER_ACTOR = 32
MAX_FOLDERS = 64



# THE ONE-DESK-PER-PERSONA FENCE IS GONE (retired 2026-09-18, owner ruling).
#
# ``DUPLICATE_DESK_REFUSAL_CODE``, ``DuplicateDeskRefused``,
# ``_duplicate_desk_collision``, ``_duplicate_desk_message`` and
# ``OfficeStore._guard_duplicate_desk`` lived here until that date. They enforced
# "one persona holds one live desk on a level" (D6) at the write chokepoint,
# which cost a full ``scan_actors`` per desk write.
#
# The owner's ruling: *"i want desks to just be one type all agents can use, no
# more per persona desk, just one single desk object."* A desk is pure furniture
# — there is no seating, occupancy, home position or pathing to one in either
# repo — so a desk's ``persona_id`` is an ADDRESS (the actor-file key,
# CONTRACT 43) and never an owner. The launcher now mints a generic desk under
# its OWN synthetic id (``desk_<8 base36>``, one actor file per desk, unlimited
# per workspace), which makes "two desks for one persona" the NORMAL shape
# rather than the refused one. A fence for an invariant that no longer exists
# refuses correct writes, so it is deleted rather than re-keyed.
#
# What did NOT change: the class-key fence, the archived-key (tombstone) fence,
# the conflict guard, the revision check and every EventLog emission on the
# write path. Handling of legacy per-persona desks is the LAUNCHER's, at its one
# load chokepoint (drop-and-report) — see the plan
# ``EterniaLauncher/docs/archive/mission_control/generic-desk-and-inspector-tables.md``.


#: The hook :meth:`OfficeStore.upsert_actor` calls INSIDE ``office_lock`` to
#: answer "where does this unaimed placement go".
#:
#: Takes the workspace's live :class:`ActorScan` — the scan itself and not its
#: ``actors`` list, so the policy sees whether the floor it is deciding against
#: was fully readable and can refuse or proceed on its own terms; a store that
#: unwrapped the list here would take that choice away silently, which is the
#: shape ``scan_actors`` exists to end. Returns the point the single item in the
#: payload is written at.
#:
#: The store supplies the SET and the lock; the policy supplies the ARITHMETIC.
#: Neither half is the other's authority — ``office_layout_policy`` stays pure
#: and store-free, and this store stays ignorant of lattices.
OfficePositionPolicy = Callable[["ActorScan"], tuple[float, float]]


#: How many unreadable file names one scan CARRIES before the rest become an
#: overflow count. A store holding a pathological number of undecodable files
#: must not turn every scan — and every shortfall row derived from one — into an
#: unbounded list, and an operator who cannot fix ten of them will not be helped
#: by the eleventh name. The cap is on the NAMES only: ``total`` stays exact.
MAX_UNREADABLE_ACTOR_FILE_NAMES = 10


@dataclass(frozen=True, slots=True)
class UnreadableActorFiles:
    """The actor files a scan could not decode — BY NAME, bounded, and counted.

    ``ActorScan`` carried only a count, so the shortfall row it feeds could say
    "ActorsUnreadable: 3" and nothing more, while ``read_actor_dir`` had the
    paths in its hand and dropped them. A count tells an operator that something
    is wrong; a name tells them which file to open. So the names travel.

    Bounded on purpose (:data:`MAX_UNREADABLE_ACTOR_FILE_NAMES`) with the
    remainder carried as an explicit ``+N more`` rather than silently trimmed:
    a truncated list that describes itself as whole is the exact defect
    ``ActorScan`` was created to close, one layer down.

    ``total`` is the one representation of "how many": :attr:`ActorScan.
    unreadable` reads it rather than keeping a second copy. It is NOT
    ``len(names)`` once the cap bites, which is why the cap has to be visible in
    the rendering.
    """

    #: The file names, at most :data:`MAX_UNREADABLE_ACTOR_FILE_NAMES` of them,
    #: each ``<directory>/<file>.json`` so an ``actors/`` entry and an
    #: ``archive/`` entry with the same token cannot be confused.
    names: tuple[str, ...] = ()
    #: EVERY undecodable file, capped by nothing. The names may be a prefix of
    #: this; the count never is.
    total: int = 0

    @classmethod
    def of(cls, names: Sequence[str]) -> UnreadableActorFiles:
        """THE mint. Caps the names, keeps the count exact."""

        ordered = tuple(str(name) for name in names)
        return cls(names=ordered[:MAX_UNREADABLE_ACTOR_FILE_NAMES], total=len(ordered))

    def merge(self, other: UnreadableActorFiles) -> UnreadableActorFiles:
        """Two directories' shortfalls as one. Re-caps rather than concatenating
        two already-capped lists, so a merge of two full lists is still bounded
        and the count is still the sum of the two totals."""

        return UnreadableActorFiles(
            names=(*self.names, *other.names)[:MAX_UNREADABLE_ACTOR_FILE_NAMES],
            total=self.total + other.total,
        )

    def __bool__(self) -> bool:
        return bool(self.total)

    def describe(self) -> str:
        """One line an operator can act on: the names, then what was elided.

        ``""`` when nothing was unreadable — a caller that renders this into a
        message is asking for the shortfall, and a shortfall of nothing has no
        words.
        """

        if not self.total:
            return ""
        elided = self.total - len(self.names)
        if not self.names:
            return f"{self.total} unnamed"
        rendered = ", ".join(self.names)
        return f"{rendered}, +{elided} more" if elided > 0 else rendered


#: The shortfall of a directory that had nothing to report. One shared value
#: because it is immutable and every empty scan means the same thing.
NO_UNREADABLE_ACTOR_FILES = UnreadableActorFiles()


class ActorScan(NamedTuple):
    """What an actor-directory scan FOUND, beside what it could not read.

    The second field is the whole point. ``read_actor_dir`` has always skipped
    a file it could not decode and returned the rest, so every reader downstream
    received a SHORTER list that described itself as complete — and the office
    projection then computed ``actors_truncated`` from the already-shortened
    list, arriving at 0. A launcher rendering that answer cannot tell a desk that
    was removed from a desk whose file the platform would not open.

    Two fields rather than a bare list because the two facts have to travel
    TOGETHER: any seam that carried only the actors would re-open the hole at
    that seam, which is exactly how the projection acquired it.

    The second field is now the FILES and not a bare count: see
    :class:`UnreadableActorFiles`. :attr:`unreadable` survives as a property
    over ``unreadable_files.total`` — every reader that only wants the number
    keeps its spelling, and there is still exactly one place the number lives.
    """

    actors: list[OfficeActor]
    #: The ``*.json`` files in the scanned directories that existed and did not
    #: decode. NEVER folded into ``actors`` and never silently empty.
    unreadable_files: UnreadableActorFiles = NO_UNREADABLE_ACTOR_FILES

    @property
    def unreadable(self) -> int:
        """How many files did not decode. Derived, never stored twice."""

        return self.unreadable_files.total

    def with_written(self, actor: OfficeActor) -> ActorScan:
        """This scan as it reads once ``actor`` is on disk — the upsert's ONE scan,
        carried past its own write (RT-OFFICE-PATCH-LANE-SCANS-EVERY-UPSERT).

        ``actor`` replaces the row with its ``actor_key`` or joins the set, sorted
        by key as ``OfficeStore.scan_actors`` sorts. ``unreadable_files`` is kept
        as it was: a write that replaced an undecodable file of the same key
        leaves that file counted, which over-reports, the direction that demotes
        the patch lane to ``refresh`` rather than folding a short projection.
        """

        others = [row for row in self.actors if row.actor_key != actor.actor_key]
        return ActorScan(
            sorted([*others, actor], key=lambda row: row.actor_key), self.unreadable_files
        )


#: The one word an outcome that simply WORKED is spelled with. Failures are
#: ``<verb>_failed:<ExceptionClass>`` — the class, never the message, the same
#: disclosure rule the rest of this runtime's receipts follow and the same
#: vocabulary ``office_sync.OfficeArchiveOutcome`` mints on the pull side.
OUTCOME_OK = "ok"


@dataclass(frozen=True, slots=True)
class OfficeActorOutcome:
    """What one of this store's best-effort loops actually DID to one key.

    THE class fix (H-H3), and the local twin of ``office_sync``'s pull-side
    ``OfficeArchiveOutcome``. This store's loops all share one hazard: they
    survive a single bad file on purpose — a prune must not die because one
    actor will not decode, and a whole office must not vanish because one
    conflict sidecar is mid-write — and for a long time each one paid for that
    survival in a different, ad-hoc currency. The prune kept two parallel raw
    dicts; the conflict read kept nothing at all and quietly substituted a
    filename. Three shapes for one question is three places the answer can be
    wrong differently.

    ONE outcome per key the loop REACHED, successes included. A list of only
    failures cannot answer "did this loop reach this key at all", which is the
    question an operator asks after a retire says a desk is gone and the canvas
    still shows it.

    TWO fields carry the verdict, and the split is deliberate:

    * ``outcome`` is what a PROGRAM branches on. It is a token, and a failed one
      names the exception CLASS and never its message — a message can carry a
      path, a display name or a secret-shaped fragment, and these rows ride an
      operator ack and a launcher decode.
    * ``error`` is what a HUMAN reads: the ``class: message`` string this
      store's retire ack has carried to the launcher since before this type
      existed. ``None`` on success. It is kept rather than dropped to satisfy
      the rule above because deleting it would take information away from the
      operator, which is the opposite of what typing the outcome is for; the
      rule it bends is about the TOKEN, and the token stays clean.

    ``actor_key`` is ``None`` for a shortfall that belongs to no actor — the
    same shape ``agent_retire`` already uses when the office projection itself
    will not construct. The unreadable file's own key is precisely what could
    not be decoded, so naming one would be inventing it.
    """

    workspace_id: str
    actor_key: str | None
    outcome: str
    error: str | None = None

    @classmethod
    def archived(cls, workspace_id: str, actor_key: str) -> OfficeActorOutcome:
        return cls(workspace_id=workspace_id, actor_key=actor_key, outcome=OUTCOME_OK)

    @classmethod
    def archive_failed(
        cls, workspace_id: str, actor_key: str, exc: BaseException
    ) -> OfficeActorOutcome:
        return cls(
            workspace_id=workspace_id,
            actor_key=actor_key,
            outcome=f"archive_failed:{type(exc).__name__}",
            error=f"{type(exc).__name__}: {exc}",
        )

    @classmethod
    def scan_unreadable(cls, workspace_id: str, scan: ActorScan) -> OfficeActorOutcome:
        """The shortfall row for a workspace whose actor directory read short.

        NAMES the files, and not only how many there were. The row's job is to
        turn an empty failure list back into the positive claim
        ``agent_retire``'s docstring says it is — a count does that, but a count
        is also the whole of what an operator gets, and "3 files here would not
        open" is not something anyone can act on. ``read_actor_dir`` is standing
        on the paths (:class:`UnreadableActorFiles`), so the row spends them.

        The COUNT stays in ``outcome``, which is the machine-read half and is
        matched on by prefix; the names ride ``error``, which is the half meant
        for a human. Bounded there by the scan, not here — see
        :data:`MAX_UNREADABLE_ACTOR_FILE_NAMES`.
        """

        return cls(
            workspace_id=workspace_id,
            actor_key=None,
            outcome=f"scan_unreadable:{scan.unreadable}",
            error=f"ActorsUnreadable: {scan.unreadable} ({scan.unreadable_files.describe()})",
        )

    @classmethod
    def conflict_read(cls, workspace_id: str, actor_key: str) -> OfficeActorOutcome:
        return cls(workspace_id=workspace_id, actor_key=actor_key, outcome=OUTCOME_OK)

    @classmethod
    def conflict_key_from_filename(
        cls, workspace_id: str, token: str, exc: BaseException
    ) -> OfficeActorOutcome:
        """A conflict sidecar that would not decode, named by its FILENAME.

        The substitution stays — a conflict the operator can half-name beats a
        conflict they cannot see at all — but it stops being silent. The
        filename is ``office_models.actor_file_token(actor_key)``, which is
        sanitised and truncated at 64 characters with a hash suffix, so for a
        long key it is NOT the actor key and ``office resolve-conflict --actor
        <it>`` will not find anything. A caller handed a bare list could not
        tell that entry from a real one.
        """

        return cls(
            workspace_id=workspace_id,
            actor_key=token,
            outcome=f"conflict_unreadable:{type(exc).__name__}",
            error=f"{type(exc).__name__}: {exc}",
        )

    @property
    def succeeded(self) -> bool:
        return self.outcome == OUTCOME_OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "actor_key": self.actor_key,
            "outcome": self.outcome,
        }

    def as_failure_row(self) -> dict[str, Any]:
        """The ``{actor_key, workspace_id, error}`` shape the retire ack carries
        and the launcher decodes (``MissionAgentOfficeArchiveFailure``).

        Derived rather than built beside the outcome, so the ack and the typed
        record cannot disagree about which keys failed — which is the whole
        reason the counts below became lengths instead of their own tallies.
        """

        return {
            "actor_key": self.actor_key,
            "workspace_id": self.workspace_id,
            "error": self.error,
        }


class ConflictScan(NamedTuple):
    """The conflict sidecars a workspace HAS, beside what they cost to read.

    ``ActorScan``'s shape, deliberately, for the same question one directory
    over: what did this read find, and what did it have to guess at. ``keys``
    is complete — every sidecar contributes exactly one entry whether or not it
    decoded — so this is NOT the hazard of a list that is short and says it is
    whole. What was silent is WHICH entries are guesses,
    and that lives in ``outcomes`` — projected by :attr:`guessed_keys` for the
    two readers that hand these keys to an operator.
    """

    keys: list[str]
    outcomes: list[OfficeActorOutcome]

    @property
    def unreadable(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.succeeded)

    @property
    def guessed_keys(self) -> list[str]:
        """The subset of ``keys`` that is a FILENAME token, not a key read out
        of a sidecar payload — the entries ``office resolve-conflict --actor
        <it>`` may not find (RD-5).

        THE derivation, so the snapshot lane and the CLI lane cannot answer
        differently about which of one scan's keys are guesses: both call
        ``scan_conflicts`` ONCE and take both lists off the same result. Derived
        from ``outcomes`` rather than tallied beside them for the reason
        ``as_failure_row`` is derived — two parallel lists are two things free
        to drift.

        ``keys`` and ``outcomes`` are appended in lockstep — exactly one entry
        per sidecar, in every arm — so the pairing is positional and total.
        """

        return [key for key, outcome in zip(self.keys, self.outcomes) if not outcome.succeeded]
