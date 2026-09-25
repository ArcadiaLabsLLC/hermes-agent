"""Convergence accounting across write-backs: the streak state (this module is
its only writer), the boot seed, and the never-converged receipt.
"""

from __future__ import annotations

import json
import threading

from agent_runtime.core_cache.vocabulary import (
    DIFF_SCOPE_EVERY_PASS,
    DIFF_SCOPE_LAST_PAIR,
    DIFF_SCOPE_NONE,
    DIFF_UNAVAILABLE,
    DIFF_UNAVAILABLE_NO_ENTRIES,
    DIFF_UNAVAILABLE_NO_ENTRY_DELTA,
    RECEIPT_NEVER_CONVERGED,
    logger,
)
from agent_runtime.core_cache.models import (
    CoreFingerprint,
    FingerprintEntry,
    _StreakSeed,
)
from agent_runtime.core_cache.generations import sidecar_path
from agent_runtime.core_cache.read import (
    _persisted_entries,
    _sidecar_answers_a_different_question,
)

__layer__ = "stores"

__all__ = [
    "NEVER_CONVERGED_BUILDS",
    "_NEVER_CONVERGED_DIFF_PATHS",
    "_boot_streak_seed",
    "_boot_streak_seed_taken",
    "_capture_boot_streak_seed",
    "_changed_paths",
    "_convergence_lock",
    "_diff_detail",
    "_diff_unavailable_detail",
    "_last_written_digest",
    "_never_converged_reported",
    "_note_written_key",
    "_persisted_streak_seed",
    "_receipt_never_converged",
    "_reset_convergence_state",
    "_streak_common_diff",
    "_streak_entries",
    "_streak_last_diff",
    "_streak_length",
    "_streak_seeded",
]


# --------------------------------------------------------------------------- #
# Convergence — whether this process's cache is buying anything (ML-10 / A2)
# --------------------------------------------------------------------------- #
# The cache can fail in a way that costs nothing and says nothing: if some input
# moves on EVERY build, no key a build writes can ever describe the store the
# next build stats, so every process demotes, every process rebuilds, and the
# whole lane silently buys nothing forever. Nothing above detects that — a
# demote is individually legitimate, and the write-back that follows it looks
# exactly like a healthy one.
#
# The measurement is free, because both halves already exist: every build hands
# ``write_back`` the key it would persist, so a process can simply notice that
# its own consecutive write-backs never agree. Past ``NEVER_CONVERGED_BUILDS``
# it says so and NAMES the paths, because the sanctioned response to this — the
# same one the shadow lane's divergence receipt asks for — is to widen the stat
# set's closure over a named input, never to trust the cache harder.
#
# WHAT IS RETAINED, AND WHY IT IS NOT A STAT SET PER PROCESS. The digest of the
# last key written is kept always (a string). The last key's ENTRIES are kept
# only while a streak is live and dropped the moment two write-backs agree, so a
# settled process — which is every healthy one — holds no second stat set for a
# diagnostic that is not going to fire. On a live store an entry list is tens of
# thousands of triples; that is worth one branch to not retain.
#
# This block decides NOTHING. It reads the key the build already computed, and
# every write-back returns exactly what it returned before.

#: How many consecutive write-backs may disagree with the one before them before
#: the cache says out loud that it is buying nothing.
#:
#: THREE, and it is the measured virgin-root convergence rather than a round
#: number. A cold store legitimately fails to settle for a build or two — the
#: build is not a pure reader (``PersonaInstanceStore.ensure_for_personas``
#: materializes instance rows; the chat SessionDB is CREATED by the first process
#: that opens it), and the key is taken pre-build on purpose, so the first
#: write-back describes inputs the build then moved. ``write_back``'s own
#: docstring names that consequence, and the test helper
#: ``converge_persisted_core`` measures it. A bound at the measured convergence
#: is the one number that cannot fire on the healthy shape and does fire on the
#: pathological one, where the disagreement never ends.
NEVER_CONVERGED_BUILDS = 3


#: How many oscillating paths the receipt names. ``changed=`` carries the full
#: count beside them, so the cap can never make a large drift read as a small one.
_NEVER_CONVERGED_DIFF_PATHS = 5


_convergence_lock = threading.Lock()


_last_written_digest: str | None = None


_streak_entries: tuple[FingerprintEntry, ...] = ()


_streak_length = 0


_streak_last_diff: tuple[str, ...] | None = None


_streak_common_diff: frozenset[str] | None = None


_never_converged_reported = False


_boot_streak_seed: _StreakSeed | None = None


_boot_streak_seed_taken = False


#: True when the streak this process is continuing began in an EARLIER one, so
#: some of its passes were never observed here. It exists to stop the receipt
#: over-claiming — see :func:`_note_written_key`.
_streak_seeded = False


def _reset_convergence_state() -> None:
    """Forget this process's convergence history, as a fresh process would.

    The seed is forgotten too, and it must be: a capture surviving into the next
    case would seed that case's streak from a store pytest has already deleted.
    """

    global _last_written_digest, _streak_entries, _streak_length
    global _streak_last_diff, _streak_common_diff, _never_converged_reported
    global _boot_streak_seed, _boot_streak_seed_taken, _streak_seeded
    with _convergence_lock:
        _last_written_digest = None
        _streak_entries = ()
        _streak_length = 0
        _streak_last_diff = None
        _streak_common_diff = None
        _never_converged_reported = False
        _boot_streak_seed = None
        _boot_streak_seed_taken = False
        _streak_seeded = False


def _changed_paths(
    before: tuple[FingerprintEntry, ...], after: tuple[FingerprintEntry, ...]
) -> tuple[str, ...]:
    """Every PATH whose triple differs between two stat sets.

    By path rather than by triple: a file whose mtime moved would otherwise be
    named twice (its old triple and its new one) and read as two inputs. An added
    or removed path differs too — its triple is absent on one side — which is the
    same rule ``_stat_entry`` follows for a missing file.
    """

    left = {entry.path: (entry.mtime_ns, entry.size) for entry in before}
    right = {entry.path: (entry.mtime_ns, entry.size) for entry in after}
    return tuple(
        sorted(path for path in set(left) | set(right) if left.get(path) != right.get(path))
    )


def _capture_boot_streak_seed(key: CoreFingerprint) -> None:
    """Carry the PREVIOUS write-back's answer across the process boundary (A2).

    WHY THIS EXISTS, measured. ``_note_written_key`` used to return early on the
    first write-back of a process, so the receipt fired on the FOURTH consecutive
    disagreeing write-back of ONE process. Boots write back once or twice: the
    receipt was unreachable on every boot shape there is, and the 2026-08-18
    05:33 pair (``9772c7720bef`` → ``d525e554be44``) — which IS the
    self-perturbation the receipt was written to expose — could never be
    reported. A process boundary is not a convergence event, and treating it as
    one is what made the diagnostic dead on arrival.

    **SEED ONLY ON A FINGERPRINT DISAGREEMENT.** This is the correctness point,
    and it is not optional. A ``build_stamp_mismatch`` (the operator upgraded), a
    ``contract_mismatch`` (the schema moved), a ``runtime_root_mismatch`` (a
    different store) and a ``home_mismatch`` (a different question) are all
    LEGITIMATE non-agreements that say nothing whatever about convergence.
    Seeding on those would make a routine upgrade look like an oscillating store
    and fire a WARNING receipt at an operator with a healthy install — the
    expensive direction of error for a diagnostic whose whole value is that it
    only speaks when something is wrong. The judgement is asked of
    :func:`_sidecar_answers_a_different_question`, the read lane's own authority,
    so the two can never drift.

    **Cost, priced.** The sidecar is tiny and is always read. The entries file is
    megabytes and is read ONLY when the digests actually disagree — a converged
    boot, which is every healthy one, pays one small read and stops.
    """

    global _boot_streak_seed, _boot_streak_seed_taken

    with _convergence_lock:
        if _boot_streak_seed_taken or _last_written_digest is not None:
            return
        _boot_streak_seed_taken = True
    seed = _persisted_streak_seed(key)
    with _convergence_lock:
        _boot_streak_seed = seed


def _persisted_streak_seed(key: CoreFingerprint) -> _StreakSeed | None:
    """The persisted pair read as "what the last write-back concluded"."""

    try:
        sidecar = json.loads(sidecar_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(sidecar, dict):
        return None
    recorded_digest = sidecar.get("fingerprint")
    if not isinstance(recorded_digest, str) or not recorded_digest:
        return None
    if recorded_digest == key.digest:
        # The boots AGREE. Seeded with no entries and no streak on purpose: the
        # agreement branch below drops both anyway, and reading megabytes of
        # triples to discard them is exactly the cost a healthy boot must not pay.
        return _StreakSeed(recorded_digest, (), 0)
    if _sidecar_answers_a_different_question(sidecar):
        return None
    persisted, _unavailable = _persisted_entries(expect_digest=recorded_digest)
    if persisted is None:
        # The disagreement is real and seeds the streak; only the PATHS are
        # missing, and the receipt says so in its own words rather than
        # pretending the streak did not happen.
        return _StreakSeed(recorded_digest, (), 0)
    return _StreakSeed(recorded_digest, persisted.entries, persisted.streak)


def _note_written_key(key: CoreFingerprint) -> int:
    """Record what this write-back persisted, and report a lane that never settles.

    Returns the streak length this write-back leaves standing (``0`` when the
    lane settled), which ``write_back`` hands to the entries file so the NEXT
    process can continue it. This function stays the ONE authority for that
    number; the file only records what it decided.

    **When it is called, and the one window MCF-21 opened.** It runs once the core
    and sidecar have staged — i.e. once the write-back is going to land unless the
    disk fails twice — and before the entries file that RECORDS its answer, because
    the entries file is now inside the published unit and cannot be written after
    the landing. So the old sentence "called on successful write-backs only" is no
    longer exactly true and is not left standing as if it were: an entries-write or
    pointer-publish failure now advances this process's streak for a generation
    that did not publish.

    That window is narrower than the change makes it sound. Under the OLD ordering
    an entries failure already fired this, so the genuinely new case is a pointer
    replace that fails immediately after three files were written successfully into
    the same directory. And the consequence is bounded by what the streak MEASURES:
    whether consecutive BUILDS produce keys that agree — a property of the store's
    stability, not of what reached the disk. A write-back that failed leaves that
    answer just as true as one that landed.
    """

    global _last_written_digest, _streak_entries, _streak_length
    global _streak_last_diff, _streak_common_diff, _never_converged_reported
    global _streak_seeded

    with _convergence_lock:
        previous_digest = _last_written_digest
        previous_entries = _streak_entries
        if previous_digest is None:
            seed = _boot_streak_seed
            if seed is not None:
                # The first write-back of a process has nothing IN MEMORY to
                # agree with — but the previous boot left its answer on disk, and
                # that is what a store which never converges ACROSS boots
                # disagrees with. Continuing the count is the whole of A2's fix.
                previous_digest = seed.digest
                previous_entries = seed.entries
                _streak_length = seed.streak
                _streak_seeded = seed.streak > 0
        _last_written_digest = key.digest
        if previous_digest is None:
            # Nothing persisted and nothing in memory: "one build" is never
            # evidence of non-convergence.
            return 0
        if previous_digest == key.digest:
            # Settled: two consecutive write-backs wrote the same key, so the
            # store the next process stats is the store this one described.
            _streak_entries = ()
            _streak_length = 0
            _streak_last_diff = None
            _streak_common_diff = None
            _streak_seeded = False
            return 0
        _streak_length += 1
        _streak_entries = key.entries
        if previous_entries and key.entries:
            changed = _changed_paths(previous_entries, key.entries)
            _streak_last_diff = changed
            _streak_common_diff = (
                frozenset(changed)
                if _streak_common_diff is None
                else _streak_common_diff & frozenset(changed)
            )
        streak = _streak_length
        if _streak_length < NEVER_CONVERGED_BUILDS or _never_converged_reported:
            return streak
        # Once per process. The receipt names an input to go widen the closure
        # over; repeating it every build afterwards would bury that under its own
        # noise without adding a fact.
        _never_converged_reported = True
        builds = _streak_length
        # ``every_pass`` claims a path differed on EVERY pass of the streak, and
        # a SEEDED streak began before this process did — the intersection here
        # spans only the passes observed here. Claiming it anyway would push a
        # cross-boot streak into the arm C22(i) reserves for self-perturbation,
        # inflating exactly the count an operator is meant to act on. A seeded
        # streak reports ``last_pair``, which is the strongest true thing it can
        # say about a diff it did not watch accumulate.
        common = None if _streak_seeded else _streak_common_diff
        last = _streak_last_diff
    _receipt_never_converged(builds=builds, common=common, last=last)
    return streak


def _receipt_never_converged(
    *, builds: int, common: frozenset[str] | None, last: tuple[str, ...] | None
) -> None:
    """The A2 receipt: this process's cache has never agreed with itself.

    Rides the same channel and the same ``snapshot_core_cache`` family as the
    shadow lane's divergence receipt, and asks for the same response: widen the
    input closure over the paths named here.

    ``diff=`` goes LAST on purpose — it is a variable-length list and a path may
    contain spaces, so anything after it could not be field-parsed.
    """

    if last is None:
        detail = _diff_unavailable_detail(DIFF_UNAVAILABLE_NO_ENTRIES)
    elif common:
        detail = _diff_detail(DIFF_SCOPE_EVERY_PASS, sorted(common))
    elif last:
        detail = _diff_detail(DIFF_SCOPE_LAST_PAIR, list(last))
    else:
        detail = _diff_unavailable_detail(DIFF_UNAVAILABLE_NO_ENTRY_DELTA)
    logger.warning(
        "snapshot_core_cache %s builds=%d %s — %d consecutive write-backs each "
        "wrote a key that disagreed with the one before it, so no process can "
        "ever be served this cache: it is costing a write per build and buying "
        "nothing. Widen the fingerprint's input closure over the paths named "
        "here (agent_runtime/core_cache.py), never trust the cache harder.",
        RECEIPT_NEVER_CONVERGED,
        builds,
        detail,
        builds,
    )


def _diff_detail(scope: str, paths: list[str]) -> str:
    return "diff_scope={} changed={} diff={}".format(
        scope, len(paths), ",".join(paths[:_NEVER_CONVERGED_DIFF_PATHS])
    )


def _diff_unavailable_detail(reason: str) -> str:
    """The one spelling for "a diff was owed here and could not be computed".

    Its own function so the two receipts that can owe a diff — the never-converged
    warning and the fingerprint demote — word the refusal IDENTICALLY. Two
    hand-written copies of a census instruction is the C22 defect itself, one
    level down: a census greps ``diff_reason=`` and a second spelling measures a
    false zero on whichever copy it did not know about.

    ``changed=0`` rides along rather than being omitted, so the field set is the
    same on every arm and a parser never has to branch on presence. ``diff=`` is
    LAST here for the same reason it is last on a computed diff.
    """

    return (
        f"diff_scope={DIFF_SCOPE_NONE} changed=0 "
        f"diff_reason={reason} diff={DIFF_UNAVAILABLE}"
    )
