"""The value types the cache passes between its stages: fingerprint entries,
the fingerprint, the home capture, the restat and streak outcomes, the
persisted entries, a cache read, the consult memo, and the decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

__layer__ = "models"

__all__ = [
    "CacheRead",
    "CoreDecision",
    "CoreFingerprint",
    "FingerprintEntry",
    "FingerprintHomeCapture",
    "PersistedEntries",
    "_ConsultMemo",
    "_ConsultStamp",
    "_RestatOutcome",
    "_SelfPerturbedInputs",
    "_StreakSeed",
]


class FingerprintEntry(NamedTuple):
    path: str
    mtime_ns: int
    size: int


class CoreFingerprint(NamedTuple):
    """The sorted stat set over every build input, plus its own digest.

    ``entries`` is kept (not just the digest) so a divergence investigation can
    diff two fingerprints and name the file that moved. ``digest`` is what the
    sidecar stores: the entry list on the live store is tens of thousands of
    triples and the sidecar is read on the boot path.
    """

    entries: tuple[FingerprintEntry, ...]
    digest: str

    @property
    def count(self) -> int:
        return len(self.entries)


class FingerprintHomeCapture(NamedTuple):
    """What this process captured, and WHERE it came from.

    ``home`` is ``None`` until something has captured — which is a state worth
    being able to observe rather than a gap: a process that declared a boot
    instant and then reached a request with ``home is None`` is a process whose
    eager capture did not run.
    """

    home: Path | None
    authoritative: bool
    eager: bool
    boot_site: str | None


class _SelfPerturbedInputs(NamedTuple):
    """Which paths the build itself moves, resolved through the SAME authorities.

    ``files`` is exact paths; ``trees`` is directory prefixes (a class whose
    members APPEAR — a newly minted persona-instance row has no pre-build triple
    to compare, so membership cannot be a fixed list of names).

    Resolved rather than spelled, for the reason the closure itself is resolved
    (§6.1's first mitigation): a second hand-written list of store paths is free
    to drift from the one the walk enumerates, and a drifted member here would
    either fail to converge (harmless) or adopt a fresh triple for something the
    build does NOT write (not harmless).
    """

    files: frozenset[str]
    trees: tuple[str, ...]

    def covers(self, path: str) -> bool:
        return path in self.files or self.under_tree(path)

    def under_tree(self, path: str) -> bool:
        """Inside a self-perturbed DIRECTORY — the class whose members appear."""

        return any(path.startswith(prefix) for prefix in self.trees)


class _RestatOutcome(NamedTuple):
    key: CoreFingerprint
    refreshed: int
    foreign: int
    state: str


class _StreakSeed(NamedTuple):
    """The previous write-back's answer, carried across a process boundary."""

    digest: str
    entries: tuple[FingerprintEntry, ...]
    streak: int


class PersistedEntries(NamedTuple):
    """What a write-back recorded beside its digest: the stat set, and the streak.

    Both are read together because they are read from one file in one parse. The
    streak is what lets a never-converged run survive a process boundary — see
    :func:`_capture_boot_streak_seed` — and it is recorded by the write-back
    rather than recomputed by the reader, so there is exactly one rule for the
    number.
    """

    entries: tuple[FingerprintEntry, ...]
    streak: int


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
class CacheRead(NamedTuple):
    """What the persisted pair said, and why it was or was not usable.

    ``core`` is present whenever a decodable core was on disk — INCLUDING the
    mismatch cases, because a mismatch still has something honest to serve while
    the rebuild runs, provided it wears the stale label. ``matched`` is the only
    field that authorizes serving it as authoritative.
    """

    core: dict | None
    matched: bool
    reason: str
    fingerprint: CoreFingerprint | None
    sidecar: dict


# --------------------------------------------------------------------------- #
# One consult per boot, not one per rider (MC-1 / P5)
# --------------------------------------------------------------------------- #
#: A serve boot asks this lane the SAME question four times within about a
#: second: the stream's stale-first read, then the prewarm, hub and cli riders'
#: consults, and then the build leader's pre-build key — five full store walks
#: (measured ~300–355 ms each warm on the operator's drive), four core reads and
#: four digests, all describing one moment. The count is identical on the HIT
#: path, where the answer is by definition the same for every asker.
#:
#: They are one question, so they get one answer. The memo holds the
#: ``CacheRead`` the first asker computed, keyed on the STAT TRIPLES of the
#: persisted pair itself PLUS the event log's logical tail (:class:`_ConsultStamp`),
#: and is dropped when the lane disarms — that is, the moment this process owns
#: its own truth.
#:
#: WHAT THIS DOES NOT CHANGE. A hit still means the fingerprint matched the
#: sidecar; a demote still carries its own reason and its own receipt per caller.
#: Only the number of times the identical computation runs moves.
#:
#: WHAT IT DOES WIDEN, said plainly. The validity of one asker's answer now
#: extends to the other askers in the same window instead of each re-deciding.
#: If a write lands mid-window, a later rider is served the answer computed
#: before it, where today it would have walked again and demoted. Three things
#: bound that, and they are the reason this is sound rather than merely cheap:
#:
#: 1. the window is a BOOT — it ends at the first completed full build of the
#:    process, which is the same instant the lane closes. **That bound is only
#:    true because every full build closes the lane, INCLUDING the shadow
#:    validation's** (:func:`shadow_validate`). While only a DIVERGENT shadow
#:    closed it, this clause was vacuous on precisely the boots this memo
#:    optimizes — a cache-HIT boot completes no build through ``build_snapshot``,
#:    so the window never ended and the memo answered every later build in the
#:    process with the boot-time core. See :func:`shadow_validate` for the
#:    incident and the numbers;
#: 2. the askers were already disagreeing, which is worse. Today rider 1 can be
#:    served the cache while rider 2 walks, misses and pays a full build, on one
#:    store, in one process, seconds apart — the divergence the 2026-08-18
#:    investigation recorded as A1-c. One answer per window retires it;
#: 3. the shadow-validation window is UNTOUCHED. A cache-hit boot still runs the
#:    full build in the background and compares field-for-field, so a write this
#:    memo absorbed surfaces as a divergence receipt and the rebuilt core is
#:    adopted. That mitigation is load-bearing here, not decorative.
#:
#: The stat pair is re-taken on every ask (two stats), so a write-back — this
#: lane's own or another process's — invalidates the memo immediately: the pair
#: is written through ``atomic_json_write``, and a rename always moves mtime.
#:
#: **AND THE STORE'S POSITION IS RE-TAKEN WITH IT (R1, 2026-08-21).** Bound 1
#: above is now true by code, but it bounds the WINDOW, not what may be said
#: inside it: an append that lands between the boot's stale-first read and its
#: riders' consults is still inside the armed window, and a memo keyed on the
#: cached artifact's own stat cannot see it. Keying on the artifact rather than
#: on the source is the mtime anti-pattern one step worse than the classic one,
#: and it is what let a 14:56 core answer "current" at 15:33 while the store had
#: moved 8,000 bytes past it. So the log's logical tail rides in the stamp and
#: any append drops the memo. What the next asker then does is WALK, not
#: rebuild: the fingerprint is still the only validity authority and an append
#: that changed no build input is still a cache hit — see :func:`_store_position`
#: for why this is not the refused event-offset cache key.
#:
#: The lock is held ACROSS the computation, deliberately. Riders arrive within
#: milliseconds of each other; a lock released before the walk would let all of
#: them start their own and the memo would record the last one to finish, buying
#: nothing. Blocking is the mechanism, not a side effect. Nothing inside the
#: computed region takes :data:`_lane_lock`, and no holder of the lane lock takes
#: this one — the two never nest.
class _ConsultStamp(NamedTuple):
    """What the memo was taken against: the cached ARTIFACT and the STORE.

    Two halves because they answer two different questions, and the memo needs
    both. ``pair`` says "the thing I memoised has not been republished under me";
    ``event_offset`` says "the source of truth has not moved since I looked".
    A memo missing the second half answers "current" about a store it never
    consulted — the 2026-08-21 15:33 mechanism, and R1's whole subject.
    """

    pair: tuple[FingerprintEntry, ...]
    event_offset: int | None


class _ConsultMemo(NamedTuple):
    stamp: _ConsultStamp
    raw_core: str
    read: CacheRead


class CoreDecision(NamedTuple):
    """What the cache lane decided, and whether there was a question at all.

    ``demoted`` is the distinction that keeps the committed producer fixtures
    byte-identical. A build in a root that has never held a persisted core
    answers no question about provenance, so nothing is stamped; a build that
    ran BECAUSE a persisted core was rejected answers one, and stamps
    ``core_source=rebuilt``. See :func:`label_core`.
    """

    core: dict | None
    demoted: bool
    reason: str
