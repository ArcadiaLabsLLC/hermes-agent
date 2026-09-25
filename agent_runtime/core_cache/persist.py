"""``write_back`` — staging and landing a new generation (core, sidecar,
convergence, entries), and reaping superseded generations.
"""

from __future__ import annotations

import os
import shutil

from utils import atomic_json_write

from agent_runtime.core_cache.vocabulary import (
    CORE_FILENAME,
    ENTRIES_FILENAME,
    RECEIPT_GENERATION_RESIDUE,
    SIDECAR_FILENAME,
    _LEGACY_FLAT_FILENAMES,
    logger,
)
from agent_runtime.core_cache.models import CoreFingerprint, _RestatOutcome
from agent_runtime.core_cache.home import resolved_fingerprint_home
from agent_runtime.core_cache.fingerprint import (
    build_input_fingerprint,
    build_stamp_token,
    contract_versions,
)
from agent_runtime.core_cache.generations import (
    _cache_dir,
    _core_digest,
    _is_generation_name,
    _new_generation_name,
    pointer_path,
)
from agent_runtime.core_cache.restat import (
    _RESTAT_SKIPPED,
    _restat_on_post_build_reality,
)
from agent_runtime.core_cache.convergence import (
    _capture_boot_streak_seed,
    _note_written_key,
)
from agent_runtime.core_cache.read import _runtime_root_for_sidecar

__layer__ = "stores"

__all__ = [
    "_sidecar_for",
    "_stage_and_land",
    "GENERATION_RESIDUE_BOUND",
    "_GENERATION_RESIDUE_NAMES",
    "_entries_payload",
    "_reap_superseded_generations",
    "_receipt_generation_residue",
    "write_back",
]


# --------------------------------------------------------------------------- #
# Write-back
# --------------------------------------------------------------------------- #
def write_back(core: dict, *, fingerprint: CoreFingerprint | None = None) -> bool:
    """Persist the core, its sidecar and its stat set as ONE generation.

    A failed write logs and changes NOTHING about the build that produced the
    core — the build path is byte-identical whether this succeeds or fails,
    which is what makes the cache safe to add to a hot path (test 9's second
    half is the pin). That outer contract is unchanged by MCF-21.

    **ALL THREE FILES OR NONE (MCF-21).** This used to land three files through
    three independent ``os.replace`` calls: each was atomic alone and the TRIO
    was not, so the property "these three describe one build" was held up by two
    ad-hoc binding guards rather than by one rule — and a fourth file would have
    made a third guard. Now the trio is written into a fresh generation directory
    nothing points at, and the write-back LANDS when the pointer naming it is
    replaced. One atomic act publishes three files; a failure anywhere before it
    publishes nothing at all. See :func:`_live_generation_dir` for why a pointer
    rather than the directory swap MC-3 recorded, and why a store with no pointer
    demotes instead of adopting the flat trio it finds.

    **The arm that retires with it.** The entries write used to sit deliberately
    OUTSIDE the pair's ``try``, so a failed diagnostic left a usable cache behind
    and receipted itself as ``entries=false reason=entries_io``. A published
    generation missing one of its three files is now unrepresentable, so that
    state — and its receipt — are gone from the vocabulary and from the channel
    table. An entries failure aborts the generation and the write-back reports
    the one failure it had: ``ok=false reason=io``. The trade is named rather
    than discovered: the lane loses the ability to keep a cache whose diagnostic
    could not be written, and gains the property that anything published is
    whole. It is the right way round because the diagnostic exists to explain the
    cache, and a cache nobody can explain is the state MCF-14 spent a whole
    investigation in.

    The sidecar still binds to the core BYTES via ``core_sha256``, and that check
    is NOT retired with the torn pair. It convicts a different thing now: a
    hand-edited core, a rollback that dropped an older ``core.json`` into the
    live generation, or bytes that did not come from this module at all — none of
    which a swap can prevent, because they happen to a generation that is already
    published.

    **``fingerprint`` must be the caller's PRE-build stat set.** The direction of
    the error matters and only one direction is safe. A key stat'd AFTER the
    build would absorb any write that landed WHILE the build ran: the core does
    not contain that write, the key says the inputs are unchanged, and the next
    process serves a core missing a write as authoritative — precisely the
    failure this stage exists to prevent. A key stat'd BEFORE the build is at
    worst OLDER than the core, which demotes the next process to a rebuild it
    did not strictly need. ``build_snapshot`` therefore takes the stat
    immediately before ``_build_snapshot_uncoalesced`` and threads it here;
    computing one locally (the ``None`` default) is for callers that hold no
    build, and it accepts that same conservative loss.

    **AND IT IS RE-KEYED ON THE BUILD'S OWN WRITES BEFORE IT IS PERSISTED
    (IC-2).** The paragraph above is still the rule for every input this module
    has no audit for. It could not be the whole rule, because the build is not a
    pure reader: five proven writes (persona-instance rows, the SessionDB close's
    TRUNCATE checkpoint, the ``state.reconciled`` append) move inputs the
    pre-build key already recorded, so the persisted key disagreed with the next
    consult's stat BY CONSTRUCTION — the ``never_converged`` mechanism, measured
    on the operator's store. So the audited self-perturbation set is re-stat'd
    here, after the build and after the SessionDB close, and only those entries
    adopt a fresh triple. Everything else keeps its pre-build triple even when it
    moved, so a concurrent writer still costs the next process a demote. The full
    argument — including why this never widens what a CONSULT accepts, and the
    residual it deliberately takes — is the design note at
    :data:`SELF_PERTURBED_SESSION_DB`; the mechanism is
    :func:`_restat_on_post_build_reality`.

    The cost of this write — and who pays it — and the cold-store convergence
    history are recorded in ``docs/agent-runtime-harness/history/core_cache.md``
    § ``write_back`` (rule 7).
    """

    from ..serde import to_jsonable

    try:
        payload = to_jsonable(core)
    except Exception:
        logger.warning("snapshot_core_cache_write ok=false reason=serialize", exc_info=True)
        return False
    stamp = build_stamp_token()
    if stamp is None:
        logger.info("snapshot_core_cache_write ok=false reason=build_stamp_unknown")
        return False
    key = fingerprint if fingerprint is not None else build_input_fingerprint()
    if key is None:
        logger.info("snapshot_core_cache_write ok=false reason=fingerprint_unavailable")
        return False
    # IC-2. A caller that handed us a PRE-build key gets it re-keyed on what the
    # build left behind, for the audited self-perturbation set and nothing else —
    # the design note is at :data:`SELF_PERTURBED_SESSION_DB`. A caller that
    # handed us NOTHING already has a post-build key (the walk two lines up ran
    # after the build), so there is nothing to refresh and a second walk would be
    # pure cost.
    restat = (
        _restat_on_post_build_reality(key)
        if fingerprint is not None
        else _RestatOutcome(key, 0, 0, _RESTAT_SKIPPED)
    )
    key = restat.key
    sidecar = _sidecar_for(payload, key, stamp)
    # BEFORE the writes, because the pair on disk is about to become this
    # process's own and the previous boot's answer would be unrecoverable after.
    # A process boundary is not a convergence event — see
    # :func:`_capture_boot_streak_seed`.
    _capture_boot_streak_seed(key)
    generation = _new_generation_name()
    if not _stage_and_land(payload, sidecar, key, generation):
        return False
    logger.info(
        "snapshot_core_cache_write ok=true inputs=%d fingerprint=%s offset=%s "
        "restat=%s self_perturbed_refreshed=%d foreign_moved=%d",
        key.count,
        key.digest[:12],
        "unknown" if sidecar["event_offset"] is None else sidecar["event_offset"],
        restat.state,
        restat.refreshed,
        restat.foreign,
    )
    # AFTER the reap, and after the ok=true line above: housekeeping accounting
    # on a write-back that has already landed and already reported success.
    _receipt_generation_residue(_reap_superseded_generations(generation), generation)
    return True


def _entries_payload(key: CoreFingerprint, streak: int) -> dict:
    """The stat set behind the digest, bound to the digest — see :func:`entries_path`."""

    return {
        "fingerprint": key.digest,
        # The convergence streak this write-back left standing, so the NEXT
        # process can carry it instead of restarting from zero. It rides here
        # rather than on the sidecar for two reasons: the sidecar is read by every
        # consult on the boot path and must stay the cheap half of the judgement,
        # and this file already IS "what this write-back knew" — the streak is
        # that, not a property of the cached core. See
        # :func:`_capture_boot_streak_seed`.
        "streak": int(streak),
        "entries": [[entry.path, entry.mtime_ns, entry.size] for entry in key.entries],
    }


#: How many generation directories may sit in the cache before the reap says so.
#: THREE, counting the live one - so the healthy steady state (one live
#: generation, plus at most a couple a concurrent reader briefly held open) is
#: silent, and a store that is actually accumulating is not. Deliberately a
#: bound on the OBSERVATION and not on the removal: nothing here deletes harder
#: because the number is exceeded.
GENERATION_RESIDUE_BOUND = 3


#: How many leftover directories the receipt names. ``leftover=`` carries the
#: full count beside them, so the cap can never make a large residue read as a
#: small one. Oldest first: a generation name leads with a hex nanosecond stamp,
#: so sorting is chronological, and the oldest survivor is the one that has been
#: failing to reap the longest.
_GENERATION_RESIDUE_NAMES = 8


def _reap_superseded_generations(live: str) -> tuple[str, ...]:
    """Drop what the pointer no longer names. BEST EFFORT, and it must stay that way.

    Three things accumulate in :func:`_cache_dir` and all three are reaped by one
    rule — "keep the pointer and the generation it names":

    * the generations this write-back superseded;
    * staging directories stranded by a crash or a failed landing, which never
      served anybody because the pointer never named them;
    * the FLAT trio written before MCF-21, which :func:`_live_generation_dir`
      deliberately refuses to read. This is the only thing that ever removes it,
      and it is a one-time cleanup per store rather than a migration.

    **Why an individual failure is swallowed - and why the ACCUMULATION is not.**
    A reader in another process can be mid-read of a generation this call is
    removing; on Windows that makes the removal fail outright, which is exactly
    the right outcome. The cost of losing one reap is one directory the next
    write-back tries again on; the cost of letting it raise would be a landed
    write-back reporting failure. So the failure stays swallowed and
    ``ignore_errors`` stays on.

    What did NOT follow from that, and used to be claimed here, is that the
    outcome is not an event worth a line in a log an operator reads. A store that
    keeps failing to reap accumulates generations with NOTHING counting them - a
    silent drop with no accounting, which is the one thing this module refuses
    everywhere else (MCF-54(ii), ruled by MCF-59). This function therefore
    RETURNS what it left behind and :func:`write_back` hands that to
    :func:`_receipt_generation_residue`. Counting is not enforcement: the return
    value changes nothing about what was removed, and a write-back that has
    landed still reports success.

    A file it does not recognise is LEFT ALONE — including ``atomic_json_write``'s
    own ``.tmp`` staging files, which live in this directory while the pointer is
    being replaced. Reaping one of those would break a concurrent write-back for
    the sake of tidiness.
    """

    cache_dir = _cache_dir()
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return ()
    for name in names:
        if name == live:
            continue
        if _is_generation_name(name):
            shutil.rmtree(cache_dir / name, ignore_errors=True)
        elif name in _LEGACY_FLAT_FILENAMES:
            try:
                (cache_dir / name).unlink()
            except OSError:
                pass
    # RE-LISTED, not derived from the loop above: ``ignore_errors=True`` makes a
    # removal that failed indistinguishable from one that worked, so the only
    # honest survivor count is the one taken from disk AFTER the pass. A second
    # listdir is the price of the answer being true.
    try:
        survivors = os.listdir(cache_dir)
    except OSError:
        return ()
    return tuple(
        sorted(name for name in survivors if _is_generation_name(name) and name != live)
    )


def _receipt_generation_residue(leftover: tuple[str, ...], live: str) -> None:
    """Say, once per write-back, that the cache directory is not draining.

    NAMES the directories (the operator refinement recorded at MCF-59): a count
    sends them hunting, the names tell them exactly which directory to unlock or
    remove, and reading the same name across two builds is what separates a
    permanently held handle from transient contention.

    ``generations=`` goes LAST, matching :func:`_receipt_never_converged`'s
    ``diff=``, because it is a variable-length list and nothing after a
    variable-length list can be field-parsed.

    Reports, never enforces: this is accounting on a write-back that has already
    landed and already logged ``ok=true``.
    """

    if len(leftover) + 1 <= GENERATION_RESIDUE_BOUND:
        return
    logger.warning(
        "snapshot_core_cache %s present=%d bound=%d live=%s leftover=%d "
        "generations=%s - the reap left superseded generations behind (a reader "
        "holding one open, or a permission the writer does not have), so this "
        "store is accumulating whole cached cores on disk. The write-back "
        "itself SUCCEEDED and nothing was retracted. Unlock or remove the "
        "directories named here under the cache dir - never the live one.",
        RECEIPT_GENERATION_RESIDUE,
        len(leftover) + 1,
        GENERATION_RESIDUE_BOUND,
        live,
        len(leftover),
        ",".join(leftover[:_GENERATION_RESIDUE_NAMES]),
    )


def _sidecar_for(payload: dict, key: CoreFingerprint, stamp: str) -> dict:
    """The sidecar a write-back lands beside the core: WHICH QUESTION the key
    answers (home, stamp, contract versions) and what it answered."""

    parity = payload.get("parity") if isinstance(payload.get("parity"), dict) else {}
    watermark = parity.get("watermark") if isinstance(parity.get("watermark"), dict) else {}
    fingerprint_home, home_authoritative = resolved_fingerprint_home()
    sidecar = {
        "fingerprint": key.digest,
        "fingerprint_entries": key.count,
        # WHICH QUESTION this key answers, not just what it answered. A digest is
        # only comparable between two processes that resolved the same home; a
        # pair written under one and judged under another is a DIFFERENT closure,
        # and ``_judge_persisted_pair`` demotes it as ``home_mismatch`` rather
        # than letting it wear the generic ``fingerprint_mismatch``. The
        # authoritative flag rides beside it because an unauthoritative head is a
        # fact a demote should be able to name — it means the home was the
        # ambient resolution at capture time, so it is only as good as the moment
        # it was taken.
        "fingerprint_home": str(fingerprint_home),
        "fingerprint_home_authoritative": home_authoritative,
        "build_stamp": stamp,
        "contract_versions": contract_versions(),
        # DIAGNOSTIC ONLY. Recorded so a divergence receipt can name the log
        # position the core was built at. It is NEVER an input to the match
        # decision below — see the module header on why an offset key is
        # refused.
        "event_offset": watermark.get("event_offset"),
        "core_sha256": _core_digest(payload),
        "runtime_root": str(_runtime_root_for_sidecar(parity)),
        "generated_at": payload.get("generated_at"),
    }
    return sidecar


def _stage_and_land(payload: dict, sidecar: dict, key: CoreFingerprint, generation: str) -> bool:
    """Write the trio into ``generation`` (a directory nothing points at yet) and
    land it by replacing the pointer; on any failure log ``ok=false reason=io``,
    remove the staging directory and answer False (MCF-21: all three or none)."""

    staged = _cache_dir() / generation
    try:
        # The SAME atomic writer as everything else this module lands
        # (``utils.atomic_json_write``, compact separators for the two large
        # payloads), because one atomic-write authority is this module's rule. It
        # is not what makes the trio atomic — the pointer replace below is — but a
        # second staging convention inside one directory is how a half-written
        # file gets read as a whole one.
        atomic_json_write(
            staged / CORE_FILENAME, payload, indent=None, separators=(",", ":"), sort_keys=True
        )
        atomic_json_write(staged / SIDECAR_FILENAME, sidecar, indent=None, sort_keys=True)
        # The convergence authority runs BEFORE the entries write and hands it
        # the number, rather than the entries write deriving one of its own: the
        # streak is ``_note_written_key``'s to decide, and a second site computing
        # it from the same seed would be two rules for one question (property 6).
        # It sits INSIDE the staging block, after the two files that make a cache
        # exist — see that function's docstring for the one window in which it can
        # now advance for a generation that does not publish, and why that window
        # is narrower than it looks.
        streak = _note_written_key(key)
        atomic_json_write(
            staged / ENTRIES_FILENAME,
            _entries_payload(key, streak),
            indent=None,
            separators=(",", ":"),
            sort_keys=True,
        )
        # THE LANDING. Everything above wrote into a directory nothing points at;
        # this one replace is the write-back.
        atomic_json_write(
            pointer_path(), {"generation": generation}, indent=None, sort_keys=True
        )
    except Exception:
        logger.warning("snapshot_core_cache_write ok=false reason=io", exc_info=True)
        # The pointer never named it, so this is housekeeping and not a retraction
        # — the previous generation is still live and still whole. Best effort by
        # construction: if it fails, the directory is inert residue and the next
        # successful write-back reaps it.
        shutil.rmtree(staged, ignore_errors=True)
        return False
    return True
