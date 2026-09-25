"""The persisted core's vocabulary: its file names, the demote reasons, the
receipts and refusals it writes, the diff scopes, the entry bounds, and the
store entries the fingerprint walk excludes.

Strings here are written into receipts on disk and read by the census, so
they are contract: a value changes only with a migration.
"""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Mapping

from agent_runtime.dispatch_delivery import DRAIN_STATE_FILENAME
from agent_runtime.paths import (
    DELETED_ARCHIVE_DIRNAME,
    OFFICE_ARCHIVE_DIRNAME,
    REALM_SYNC_DIRNAME,
)
from agent_runtime.serve_auth import SERVE_AUTH_TOKEN_FILENAME
from agent_runtime.serve_registry import SERVE_INSTANCES_DIRNAME
from agent_runtime.serve_socket import SOCKET_LOCK_FILENAME, SOCKET_OWNER_FILENAME

__layer__ = "models"

__all__ = [
    "CORE_CACHE_DIRNAME",
    "CORE_FILENAME",
    "CORE_SOURCE_CACHE",
    "CORE_SOURCE_REBUILT",
    "DEMOTE_ABSENT",
    "DEMOTE_BUILD_STAMP_MISMATCH",
    "DEMOTE_BUILD_STAMP_UNKNOWN",
    "DEMOTE_CONTRACT_MISMATCH",
    "DEMOTE_CORE_DIGEST_MISMATCH",
    "DEMOTE_FINGERPRINT_MISMATCH",
    "DEMOTE_FINGERPRINT_UNAVAILABLE",
    "DEMOTE_HOME_MISMATCH",
    "DEMOTE_RUNTIME_ROOT_MISMATCH",
    "DEMOTE_UNREADABLE",
    "DIFF_SCOPE_EVERY_PASS",
    "DIFF_SCOPE_LAST_PAIR",
    "DIFF_SCOPE_NONE",
    "DIFF_UNAVAILABLE",
    "DIFF_UNAVAILABLE_ENTRIES_UNBOUND",
    "DIFF_UNAVAILABLE_NO_ENTRIES",
    "DIFF_UNAVAILABLE_NO_ENTRY_DELTA",
    "ENTRIES_FILENAME",
    "MAX_FINGERPRINT_ENTRIES",
    "MAX_SKILL_ENTRIES_PER_ROOT",
    "POINTER_FILENAME",
    "RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE",
    "RECEIPT_FINGERPRINT_REFUSED",
    "RECEIPT_GENERATION_RESIDUE",
    "RECEIPT_NEVER_CONVERGED",
    "REFUSAL_ENTRIES_EXCEEDED",
    "REFUSAL_SCOPE_SKILL_ROOT",
    "REFUSAL_SCOPE_STORE_ROOT",
    "SIDECAR_FILENAME",
    "_DB_SIBLINGS",
    "_DIR_MARK",
    "_EXCLUDED_NESTED_STORE_NAMES",
    "_EXCLUDED_STORE_ENTRIES",
    "_GENERATION_PREFIX",
    "_LEGACY_FLAT_FILENAMES",
    "_NO_GENERATION_DIRNAME",
    "_TMP_SUFFIX",
    "_WAL_SIBLING",
    "logger",
]


logger = logging.getLogger(__name__)


#: The cache's own home under the agent-runtime store root. A DEDICATED
#: directory rather than the existing ``snapshot.json``: that file is
#: ``write_snapshot``'s boot cache and the launcher's cold-paint lane reads it,
#: so two writers with different provenance would share one path and neither
#: could say which one produced the bytes. It is also excluded from the
#: fingerprint below — a cache whose own writes flipped its key would
#: invalidate itself on every build.
CORE_CACHE_DIRNAME = "serve_read_model"


CORE_FILENAME = "core.json"


SIDECAR_FILENAME = "sidecar.json"


#: The stat set the sidecar's digest SUMMARISES, kept beside it so a divergence
#: is diffable at all. Its own file rather than a field on the sidecar: the
#: sidecar is read on the boot path by every consult, and folding megabytes of
#: triples into it would make the cheap half of the judgement pay for the
#: diagnostic half. See :func:`entries_path` for the measured size.
ENTRIES_FILENAME = "entries.json"


#: The ONE file whose replacement publishes a write-back (MCF-21). It names the
#: generation directory holding the trio above; nothing else decides which trio
#: is live. See :func:`_live_generation_dir` for why a pointer and not a
#: directory rename.
POINTER_FILENAME = "live.json"


#: Every generation directory is named with this prefix, and :func:`_is_generation_name`
#: is the only reader of that fact. The prefix is what lets the reaper tell a
#: directory this module owns from anything else that ever lands beside it, and
#: it is what CONTAINS a pointer: a name that does not match is refused rather
#: than joined onto :func:`_cache_dir`, so a corrupt or hostile pointer cannot
#: resolve the live trio outside the cache's own directory.
_GENERATION_PREFIX = "gen-"


#: What :func:`core_path` / :func:`sidecar_path` / :func:`entries_path` resolve
#: to when NO generation is published — a cold store, or the first consult after
#: MCF-21 landed on a store still holding the flat trio.
#:
#: A stable placeholder rather than ``None`` or a raise, because those helpers
#: have dozens of callers that legitimately ask "where would it be" before
#: anything is there (``unlink(missing_ok=True)``, ``_stat_entry``'s
#: absent-is-a-fact triple). Nothing ever WRITES here: a write-back always mints
#: a fresh generation, so a read through this path is an ``OSError`` and the
#: judgement demotes ``absent``, which is the honest answer.
_NO_GENERATION_DIRNAME = f"{_GENERATION_PREFIX}none"


#: The flat trio this module wrote before MCF-21. Read by NOTHING — see
#: :func:`_live_generation_dir` for why a pointerless store demotes rather than
#: adopting these — and reaped by the first successful write-back after landing.
_LEGACY_FLAT_FILENAMES = (CORE_FILENAME, SIDECAR_FILENAME, ENTRIES_FILENAME)


#: ``parity.core_source`` values.
CORE_SOURCE_CACHE = "cache"


CORE_SOURCE_REBUILT = "rebuilt"


#: Why a persisted core was NOT served. Every one of these rides the demote
#: receipt: "the cache did not answer" must never be a silent outcome.
DEMOTE_ABSENT = "absent"


DEMOTE_UNREADABLE = "unreadable"


DEMOTE_CORE_DIGEST_MISMATCH = "core_digest_mismatch"


DEMOTE_FINGERPRINT_UNAVAILABLE = "fingerprint_unavailable"


DEMOTE_FINGERPRINT_MISMATCH = "fingerprint_mismatch"


DEMOTE_BUILD_STAMP_UNKNOWN = "build_stamp_unknown"


DEMOTE_BUILD_STAMP_MISMATCH = "build_stamp_mismatch"


DEMOTE_CONTRACT_MISMATCH = "contract_mismatch"


DEMOTE_RUNTIME_ROOT_MISMATCH = "runtime_root_mismatch"


#: The persisted pair was keyed under a DIFFERENT home than this process
#: resolved, so its digest answers a different QUESTION — it is not evidence that
#: the store moved. Its own reason because the two demand opposite responses: an
#: ordinary ``fingerprint_mismatch`` says go look at the store, and this says go
#: look at who asked. See the channel table row for what it means to a census.
DEMOTE_HOME_MISMATCH = "home_mismatch"


# --------------------------------------------------------------------------- #
# The receipt vocabulary (ML-10)
# --------------------------------------------------------------------------- #
#: Every receipt this module emits rides ONE channel — this module's logger, in
#: the ``snapshot_core_cache`` / ``snapshot_core_shadow`` family — and each one
#: leads with an EVENT TOKEN in the first field after that prefix, exactly as
#: ``snapshot_core_shadow_divergence`` already does. That is what makes a receipt
#: countable: a census greps the token, never the prose after it, and the prose
#: is then free to say whatever an operator needs to read.
#:
#: The two tokens below are ML-10's. They exist because the facts they carry used
#: to be either a bare WARNING sentence (the bound refusal, which never named
#: WHICH root blew the bound) or nothing at all (a cache that never converges,
#: which was silent by construction — the process just kept buying nothing).
RECEIPT_FINGERPRINT_REFUSED = "fingerprint_refused"


RECEIPT_NEVER_CONVERGED = "never_converged"


#: MCF-54(ii), ruled by MCF-59. The generation reap is BEST EFFORT and stays
#: that way - a reader holding files open on Windows makes a removal fail, and a
#: landed write-back must never report failure because its housekeeping did not.
#: What was missing was never strictness, it was ACCOUNTING: a store that kept
#: failing to reap grew generations with nothing counting them, so the failure
#: mode had no observable at all. This receipt is that observable, and per the
#: operator refinement it NAMES the leftover directories rather than merely
#: counting them - a count says a problem exists, the names say WHICH one, and
#: whether it is the same directory every time (a permanently held handle) or a
#: different one each time (transient contention).
RECEIPT_GENERATION_RESIDUE = "generation_residue"


#: HC-1. The fingerprint home was captured LAZILY — on whichever build or
#: consult happened to be first — inside a process that had already NAMED the
#: boot instant which owed that capture (see
#: :func:`declare_fingerprint_home_boot_site`). In a serve that is the
#: `home_mismatch` defect recurring rather than an ordinary cold start: the
#: instant exists precisely so the capture cannot land inside a persona scope,
#: and a lazy capture means it did not run. Its own receipt because the
#: alternative — inferring it from the NEXT boot's ``reason=home_mismatch`` — is
#: a diagnosis that arrives one boot late and only after a write-back.
RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE = "fingerprint_home_lazy_capture"


#: The typed reason on a bound refusal, plus which walk refused. ``scope``
#: matters because the two bounds are different numbers over different trees, and
#: an operator handed only a count cannot tell which tree to go look at.
REFUSAL_ENTRIES_EXCEEDED = "entries_exceeded"


REFUSAL_SCOPE_STORE_ROOT = "store_root"


REFUSAL_SCOPE_SKILL_ROOT = "skill_root"


#: The never-converged receipt's diff arms. ``every_pass`` names the paths that
#: differed on EVERY pass of the streak — the oscillating inputs, which is the
#: fact worth acting on; ``last_pair`` is the honest fallback when no path
#: differed on all of them (a store that is simply moving, which reads
#: differently and must not borrow the oscillation sentence).
#:
#: The two ``diff_unavailable`` reasons are C16's lesson applied here: an arm that
#: could not compute the diff says SO, in its own words. Silently reusing another
#: arm's sentence is how a fail-quiet default gets read as a measurement.
DIFF_SCOPE_EVERY_PASS = "every_pass"


DIFF_SCOPE_LAST_PAIR = "last_pair"


DIFF_SCOPE_NONE = "none"


DIFF_UNAVAILABLE = "diff_unavailable"


DIFF_UNAVAILABLE_NO_ENTRIES = "no_entries"


DIFF_UNAVAILABLE_NO_ENTRY_DELTA = "digest_without_entry_delta"


#: The persisted entries exist but belong to a DIFFERENT write-back than the
#: sidecar being judged — see :func:`entries_path` for the binding rule. Its own
#: reason rather than ``no_entries`` because the two ask for opposite responses:
#: ``no_entries`` says the diagnostic has not been written yet (an install that
#: predates this stage, or a cold pair) and resolves itself on the next
#: write-back, while this one says the THREE files in the cache directory
#: disagree about which generation they describe, which is the shape a failed
#: entries write (``reason=entries_io``) leaves behind. Diffing across that
#: boundary would name paths from a generation nobody asked about, so it refuses.
DIFF_UNAVAILABLE_ENTRIES_UNBOUND = "entries_unbound"


#: Hard bound on the store-root walk. Reaching it is NOT a partial answer: the
#: fingerprint becomes ``None`` and the caller must treat that as "never
#: cache". A truncated stat set is exactly a missed input.
MAX_FINGERPRINT_ENTRIES = 200_000


#: Per-root bound on the skill-registry walk. Skill packages are small trees
#: (``<root>/<slug>/SKILL.md`` plus package files); a root that blows past this
#: is not a skill registry, and the same refusal applies.
MAX_SKILL_ENTRIES_PER_ROOT = 20_000


#: Store-root entries that are DELIBERATELY not fingerprinted, each because it
#: moves for reasons a read-model core does not depend on. Anything not named
#: here is fingerprinted, so the default posture is inclusion.
#:
#: **A name its writer owns as a constant is IMPORTED here, never spelled.**
#: That is not a style tightening; hand-spelling is the defect this set shipped
#: with. ``"drain_state.json"`` sat in it annotated "per
#: ``dispatch_delivery.DRAIN_STATE_FILENAME``" while that constant read
#: ``dispatch_delivery_drain.json`` — so the exclusion named a file that has
#: never existed, and the real drain mirror, rewritten every
#: ``dispatch_delivery.DRAIN_MIRROR_HEARTBEAT_SECONDS`` for the life of a serve,
#: stayed INSIDE the key. A comment naming a constant is not a reference to it;
#: an import is, and it is the only form the compiler checks.
#:
#: ``serve_socket``'s own module doctrine (its "Fingerprint exclusion" section)
#: already required both socket files to be out of every freshness fingerprint,
#: and cited the same standing precedent this set is built on. It enumerated the
#: ALLOWLIST fingerprints — serve's ``_FINGERPRINT_ROOT_FILES`` /
#: ``_FINGERPRINT_STORE_DIRS`` and ``stream._scope_fingerprint`` — and this walk
#: is a DENYLIST, so "not added" was true there and violated here. Two
#: fingerprint designs with opposite defaults need the doctrine written on both;
#: that paragraph now names this constant too.
#:
#: Measured consequence of the two holes together (2026-08-18): every serve boot
#: rewrote ``serve_socket.owner.json`` and the drain rewrote its mirror within
#: seconds of boot, so no boot's key could describe the store the NEXT boot
#: stat'd. The lane demoted ``fingerprint_mismatch`` on every same-commit boot
#: from the day it shipped.
#:
#: RESIDUAL, stated rather than discovered later. FIVE names below are still
#: literals because no writer module owns them as a constant: ``locks`` and
#: ``snapshot.json`` are spelled inline inside their own path helpers in
#: ``agent_runtime.paths``, and the ``read_model.db`` trio was a CONFIGURABLE
#: default (``runtime_config``'s ``read_model.db_filename``) — an install that
#: renamed it re-opened exactly the hole this comment block is about, one config
#: key away. Both are the same class as the drain defect and neither is fixed
#: here; the gate below can only prove the names a WRITER produces, so it cannot
#: see them either.
#:
#: STAGE 6 (2026-08-22) narrowed the read-model half of that residual without
#: closing it. The lane that WROTE ``read_model.db`` is retired, so no install
#: can produce the file any more and the config key that renamed it is dead —
#: but the three literals stay in the set below, because a root that ran
#: ``harness rebuild-read-model`` before the cut still has the trio on disk, and
#: dropping the exclusion would fold those leftovers into the fingerprint of
#: every such store. They are excluded as LEGACY ARTIFACTS now rather than as
#: live outputs; the count is unchanged at five.
#:
#: (That count read "Four" until MC-8 and was simply wrong — ``locks`` plus
#: ``snapshot.json`` plus a trio is five. Corrected in passing rather than left,
#: because a residual paragraph exists to be counted against the set and one that
#: miscounts invites the reader to conclude a name has already been dealt with.)
#:
#: MC-8's ``deleted_archive`` addition did NOT extend that residual: it was the
#: same class — a name spelled inline in ``agent_runtime.paths`` — and was
#: promoted to ``paths.DELETED_ARCHIVE_DIRNAME`` and imported, rather than
#: re-typed here. That is the precedent for the two that remain; they were left
#: deliberately (out of MC-8's ruled scope), not overlooked.
#:
#: H2's ``office_archive`` addition did not extend it either, and was RE-COUNTED
#: rather than assumed: same class again, promoted to
#: ``paths.OFFICE_ARCHIVE_DIRNAME`` and imported, so the literals below are still
#: ``locks`` + ``snapshot.json`` + the ``read_model.db`` trio — FIVE, unchanged.
#: The count is restated on every addition because this paragraph exists to be
#: counted against the set, and it has been wrong once already.
_EXCLUDED_STORE_ENTRIES = frozenset(
    {
        # The cache's own home (see CORE_CACHE_DIRNAME).
        CORE_CACHE_DIRNAME,
        # Entries appear and vanish at every serve boot/exit, and the auth token
        # appears at first boot. The standing precedent is already recorded at
        # ``agent_runtime/serve_registry.py`` and ``agent_runtime/serve_auth.py``
        # and in the read-cache fingerprint's own comment block.
        SERVE_INSTANCES_DIRNAME,
        SERVE_AUTH_TOKEN_FILENAME,
        # The socket owner sidecar and the lock that elects it. Rewritten at
        # every socket boot and removed on every clean exit — the serve
        # registry's shape exactly, refused for the same reason, and required to
        # be refused by ``serve_socket``'s own doctrine.
        SOCKET_LOCK_FILENAME,
        SOCKET_OWNER_FILENAME,
        # Lock files are created and removed INSIDE a build; a lock in the stat
        # set would make a build's own locking flip the key it just wrote.
        "locks",
        # ``write_snapshot``'s boot cache and the projector's read model were
        # OUTPUTS of the projection, never inputs to it. Stage 6 (2026-08-22)
        # deleted both writers; the names stay excluded because a store written
        # before that cut still holds the files (see the residual paragraph
        # above), and an excluded name that nothing produces costs nothing.
        "snapshot.json",
        "read_model.db",
        "read_model.db-wal",
        "read_model.db-shm",
        # The delivery drain's telemetry mirror: a 60-second oscillator that no
        # projection reads. Same rule as the serve registry.
        DRAIN_STATE_FILENAME,
        # The per-task compaction graveyard. NOT justified by "the runtime
        # rewrites it" — see the first block below, which is the argument rather
        # than a note about it.
        DELETED_ARCHIVE_DIRNAME,
        # The orphaned-office-surface graveyard. The runtime DOES write this one,
        # which is why its argument is a different (and easier) one — see the
        # second block below.
        OFFICE_ARCHIVE_DIRNAME,
    }
)


#: WHY ``deleted_archive/`` IS EXCLUDED, WRITTEN WHERE THE EXCLUSION LIVES.
#:
#: Every other name above earns its place the same way: the RUNTIME rewrites it
#: on a boot or a timer, so keeping it would guarantee a mismatch. This one is
#: different in kind and therefore has to carry its own argument — it is excluded
#: because **the projection does not read it**, which is a claim about the reader
#: set, and a claim about a reader set rots the moment someone adds a reader.
#: Stating it here, at the constant, is the whole of the P12 ruling; the audit
#: that comes after this one is meant to find this paragraph and be able to
#: re-run it.
#:
#: **THE GREP THAT ESTABLISHES IT** (re-run it; do not trust this transcript)::
#:
#:     grep -rn "deleted_archive" agent_runtime/ hermes_cli/ | grep -v tests
#:
#: 2026-08-18, five hits, and every one is accounted for:
#:   * ``paths.DELETED_ARCHIVE_DIRNAME`` / ``paths.deleted_archive_dir`` — the
#:     name and its helper;
#:   * ``paths.events_archive_dir``'s docstring — distinguishing prose only;
#:   * ``event_rotation``'s module docstring — prose only;
#:   * ``migrations.py``'s ``archive_batches`` counter — counts batch dirs for a
#:     migration STATUS payload; a reader, and not the projection;
#:   * ``events.py::_archived_event_slices`` — a genuine READER of
#:     ``deleted_archive/*/manifest.json``. See the exception below.
#:
#: **THE CLAIM IS REPO-SCOPED** (C14: a dead-symbol/no-reader claim from a
#: narrower grep is a claim about that scope and nothing more). It covers
#: ``agent_runtime/`` and ``hermes_cli/`` — this repo's own runtime and CLI. It
#: says nothing about a consumer outside this repo, and does not need to: the
#: fingerprint is an input closure for a build that lives HERE.
#:
#: **THE EXCEPTION, NAMED RATHER THAN OMITTED** (MCF-12 — the correction that had
#: to be made before this landed, because P12 was first written as "zero
#: readers" and that is false). The chain is::
#:
#:     harness_doctor.py::_event_log_report
#:         -> events.py::event_log_health
#:             -> events.py::_archived_event_slices
#:                 -> reads deleted_archive/*/manifest.json
#:
#: So the harness doctor DOES read these manifests, and a comment claiming "no
#: readers" would be found false by the next audit, which would then reasonably
#: conclude this exclusion is wrong. **It is not wrong, and the reason is the
#: word "projection".** This walk is the input closure of the READ-MODEL BUILD
#: (``snapshot.py``) — it exists to answer "may a previously-built core be served
#: as authoritative". ``harness_doctor`` is a separate, operator-invoked
#: diagnostic that builds no core and consults no cache; a file it reads is not
#: thereby an input to the projection, any more than a log file is. Fingerprinting
#: a tree because SOME code in the repo reads it would grow the closure without
#: bound and is exactly the "denylist by hand" instinct this module already paid
#: for once.
#:
#: **NO CURRENT CODE WRITES IT** — stronger than the ruling required, so it is
#: recorded. ``deleted_archive_dir()`` has exactly ONE non-doc caller in the
#: repo, and it is the reader above; the two archivers that used to fill the tree
#: (``archive_task_events`` / ``compact_archived_task_events``) were retired at
#: S54 along with their private helpers, as the tombstone comment above
#: ``_archived_event_slices`` records. What sits under ``deleted_archive/`` on a
#: live root is therefore a graveyard of a retired feature: immutable, and not
#: merely unread but unwritten. An immutable tree contributes a constant to every
#: key it appears in, which is the clearest possible statement that its 18,804
#: stat calls buy nothing.
#:
#: **WHAT IT COSTS TODAY, MEASURED** (2026-08-18, the operator's live root):
#: 18,804 of the store's 23,107 fingerprint entries — 81 % — are under this one
#: directory. That is ~250 ms of every ~300 ms warm walk, paid 4-5 times per boot
#: (once per rider consult plus the leader's pre-build key), and since MC-3 it is
#: also ~81 % of every ``entries.json`` write-back (~3.4 MiB -> ~0.7 MiB). It is
#: additionally the only part of the closure that GROWS without bound against
#: ``MAX_FINGERPRINT_ENTRIES``, which would eventually turn a cost into a refusal.
#:
#: **WHAT WOULD MAKE THIS WRONG, AND THE OBLIGATION THAT FOLLOWS.** If a future
#: projection section reads compaction batches — a snapshot block that surfaces
#: archived-task history, say — then this tree becomes a build input and a stale
#: core could be served across a change to it. **Whoever adds that reader must
#: remove this exclusion in the SAME commit**, and take the walk cost knowingly.
#: The reverse obligation is lighter but real: a new NON-projection reader (a
#: second doctor section, a census) changes nothing here and should not be read
#: as re-admitting the tree.

#: WHY ``office_archive/`` IS EXCLUDED — A DIFFERENT, AND EASIER, ARGUMENT.
#:
#: ``deleted_archive/`` above needed a reader-set claim because nothing writes it
#: any more. This one is the opposite shape and is settled by the ordinary rule
#: the rest of the set runs on: **the runtime WRITES this tree, and the projection
#: does not read it.** ``paths.office_surface_archive_root()`` is
#: ``store_root()/office_archive`` — the destination
#: ``office_store.archive_orphaned_surface`` RENAMES a whole orphaned office
#: surface into, via ``office_store._free_surface_archive_dir``, driven by the
#: operator verb ``harness office archive-surface``
#: (``hermes_cli/harness_parts/office.py::_cmd_office_archive_surface``). It grows
#: without bound against :data:`MAX_FINGERPRINT_ENTRIES` — the destination helper
#: appends ``-2``, ``-3`` … suffixes so a re-archived orphan lands beside the
#: previous one rather than refusing — which is the same unbounded-growth
#: objection the graveyard block raises, on a tree that is still being written.
#:
#: **THE NEAR-NAME TRAP, FIRST, because getting it wrong inverts the argument.**
#: ``paths.office_archive_dir(workspace_id)`` is ``office/<ws>/archive/``: a
#: DIFFERENT tree, per-workspace, holding archived ACTOR placements, and READ by
#: ``OfficeStore`` — ``read_actor_dir`` on the actor-listing seam
#: (``scan_actors(include_archived=True)``), and ``office_archived_actor_path`` on
#: the archived-actor lookups that ``upsert_actor`` / ``remove_actor`` /
#: ``restore_actor`` and the class-key fence depend on. That tree is a projection
#: INPUT and **stays in the walk**. Only the store root's own ``office_archive``
#: entry is excluded, which is exactly what ``exclude_top`` filters and what the
#: nesting note below pins.
#:
#: **THE GREP THAT ESTABLISHES IT** (re-run it; do not trust this transcript)::
#:
#:     grep -rn "office_archive" agent_runtime/ hermes_cli/ | grep -v tests
#:     grep -rn "office_surface_archive_root\|office_archived_surface_dir" \
#:         agent_runtime/ hermes_cli/ | grep -v tests
#:
#: 2026-08-18. Every hit, and which of the two trees it names:
#:
#: THIS tree (``store/office_archive/``) — one writer chain and no reader:
#:   * ``paths.OFFICE_ARCHIVE_DIRNAME`` / ``paths.office_surface_archive_root`` /
#:     ``paths.office_archived_surface_dir`` — the name and its two helpers;
#:   * ``office_store._free_surface_archive_dir`` — the ONLY code that touches the
#:     tree at all: it ``.exists()``-probes for a free slot and returns the
#:     destination. A probe belonging to the writer, not a reader of content;
#:   * ``office_store.archive_orphaned_surface`` — the WRITER
#:     (``paths.office_dir(wsid).rename(destination)``), plus its docstring naming
#:     the helper, plus its ``AlreadyExists("office_archive:<ws>")`` — an error
#:     TOKEN, not a path;
#:   * ``hermes_cli/harness.py``'s four ``office_archive_surface`` lines — an
#:     argparse local variable holding the ``archive-surface`` subparser; no path;
#:   * ``hermes_cli/harness_parts/office.py`` — ``_cmd_office_archive_surface``
#:     (the verb), its docstring, and the ``"office_archived"`` envelope kind, a
#:     wire event name;
#:   * this comment.
#: THE NEAR NAME (``office/<ws>/archive/``), all genuine readers/writers of the
#: per-workspace actor archive, none of them this tree:
#:   * ``paths.office_archive_dir`` / ``paths.office_archived_actor_path``;
#:   * ``office_store`` at the actor-listing scan, the two archived-actor
#:     existence+revision lookups, ``remove_actor``'s archived read-back,
#:     ``restore_actor``'s source path, and ``_archive_actor_locked``'s write.
#:
#: **NOTHING PROJECTS IT.** ``snapshot._offices_summary`` reads through
#: ``OfficeStore.list_workspaces()``, which enumerates ``office_root()``'s
#: children by the presence of ``office.json`` — and
#: ``office_surface_archive_root()`` is deliberately a SIBLING of ``office_root()``
#: rather than a child, precisely so an archived surface stops being projected
#: (its own docstring records that as the load-bearing reason). A tree the
#: projection is designed not to see is not an input to it. There is no restore
#: verb either: recovery is an operator moving the directory back by hand, which
#: is a store change the walk sees on the ``office/`` side when it happens.
#:
#: **THE CLAIM IS REPO-SCOPED** (C14), covering ``agent_runtime/`` and
#: ``hermes_cli/`` — the same scope, and the same reasoning, as the block above.
#:
#: **THE HALF THIS DOES NOT RETIRE, STATED SO NOBODY READS IT AS A BUG.** The
#: archive gesture MOVES the surface OUT of ``office/<ws>/``, which IS
#: fingerprinted, so the gesture itself still flips the key exactly once. That is
#: a real input change and it should flip the key. What leaves the closure here is
#: the graveyard's CONTINUING contribution: its size, its walk cost, its unbounded
#: growth, and any churn inside it after the move.
#:
#: **WHAT WOULD MAKE THIS WRONG, AND THE OBLIGATION THAT FOLLOWS.** If a future
#: projection section reads archived surfaces — an "archived offices" block, an
#: operator restore lane that projects what is recoverable — this tree becomes a
#: build input and a stale core could be served across a change to it. **Whoever
#: adds that reader must remove this exclusion in the SAME commit.**

#: :data:`_EXCLUDED_STORE_ENTRIES` is keyed to TOP-LEVEL names only —
#: ``_walk_tree``'s ``exclude_top`` filters the store root's own entries and
#: nothing deeper — so a directory that happens to be called ``deleted_archive``
#: or ``office_archive`` NESTED inside another store subtree still contributes in
#: full. That is the correct reading of every argument above (they are all about
#: the one graveyard each at the store root, which is the only place
#: ``paths.deleted_archive_dir()`` and ``paths.office_surface_archive_root()`` can
#: put theirs) and both are pinned by test, so the comment cannot quietly grow
#: into a claim about the names everywhere.
#:
#: **AMENDED BY IC-1 (2026-08-22): "top-level only" is now a property of THAT
#: SET, not of the walk.** ``_walk_tree`` gained a SECOND, separately-argued
#: mechanism — ``exclude_nested`` / :data:`_EXCLUDED_NESTED_STORE_NAMES` — which
#: skips a named child ANYWHERE below one named top-level subtree. The two are
#: deliberately different shapes and must not be merged: a name filter applied at
#: every depth over the whole store is the mutant the two cases above exist to
#: kill (it drops unrelated data out of the closure — a missed input, the failure
#: direction this module calls the worst one), whereas a nested exclusion that
#: must name BOTH the top-level subtree it applies inside AND the child name it
#: skips cannot reach a tree its author did not audit. Every entry in the nested
#: mapping carries its own reader audit and its own removal obligation, exactly
#: like every entry in the top-level set.

#: The NESTED exclusions: ``{top-level store entry: names skipped anywhere below
#: it}``. Read the amendment above first — this is a different mechanism from
#: :data:`_EXCLUDED_STORE_ENTRIES` and it is deliberately harder to widen.
#:
#: ONE ENTRY TODAY: ``realm_sync/**/.git``.
#:
#: **WHY IT IS AN EXCLUSION AND NOT A NARROWING.** ``realm_sync/<server>/`` is a
#: git WORKTREE the runtime syncs into, under the store root. Its ``.git``
#: subtree — index, reflog, packfiles — is git's own bookkeeping, rewritten by
#: every fetch/checkout the sync verbs run, and the PROJECTION has no reader for
#: any of it. Every section builder resolves realm-sync state to
#: ``realm_sync_state/<realm>.json`` instead (``realm_sync.realm_sync_sidecar_path``
#: -> ``read_realm_sync_sidecar``), and ``snapshot.py``'s own design note at the
#: realm row states the rule the whole tree rests on: ``build_snapshot`` "must
#: never shell out to git or resolve artifacts" (Stage 43, Decision 7). A tree the
#: build is FORBIDDEN to read is not an input to it.
#:
#: **WHAT IT COSTS TODAY, MEASURED.** The ``never_converged`` firing of 2026-08-20
#: 18:21 named 60 changed entries in one pass, every one of them under
#: ``realm_sync/<realm>/.git/`` (``index``, ``logs/HEAD``, ``objects/pack/*.pack``).
#: That is the single largest oscillating class in the whole receipt series, and
#: it is oscillating because the walk is DIRECTORY-LEVEL over the store root, not
#: because anything wanted those triples.
#:
#: **WHAT STAYS IN, AND WHY THE KEY IS THE LITERAL NAME ``.git``.** The build DOES
#: read two files one directory up from the worktree's ``.git``:
#: ``realm_sync/<realm>/board_baseline.json`` (``snapshot.py`` ->
#: ``board_sync.read_board_baseline`` -> ``paths.board_baseline_path``) and
#: ``realm_sync/<realm>/office_baseline.json`` (``snapshot.py`` ->
#: ``office_sync.read_office_baseline`` -> ``paths.office_baseline_path``), plus
#: their two siblings ``persona_config_baseline.json`` and
#: ``profile_artifact_baseline.json``. Those ARE projection inputs and a
#: fingerprint that ignored a baseline change would serve a stale publication
#: verdict as authoritative — the exact failure class this lane exists to end, so
#: it is pinned by its own test rather than left to this paragraph.
#:
#: The trap that makes the literal name the only safe key: ``_sync_repo_path``
#: keys a worktree directory by the realm's SERVER token, while the four baseline
#: helpers key their sidecars by the REALM ID. The two vocabularies are not the
#: same and neither is a prefix of the other, so "skip the realm's directory" and
#: "skip everything but the baselines" are both unimplementable without a second
#: name authority that could drift. Skipping the one literal child name ``.git``
#: needs no such authority: nothing this runtime writes under ``realm_sync/`` is
#: called ``.git`` except a git worktree's own bookkeeping.
#:
#: **SCOPE, stated so it cannot be read wider than it is.** ``.git`` is skipped
#: ONLY below ``realm_sync/``. A ``.git`` at the store root, or under any other
#: store subtree, is stat'd in full — it is not this tree and it carries no
#: audit.
#:
#: **WHAT WOULD MAKE THIS WRONG, AND THE OBLIGATION THAT FOLLOWS** (the same
#: obligation the two graveyard blocks above carry). If a future projection
#: section reads a synced worktree's git internals — a snapshot block surfacing
#: the realm's real HEAD, an in-build ``git status`` replacing the sidecar — then
#: this subtree becomes a build input and a stale core could be served across a
#: change to it. **Whoever adds that reader must remove this exclusion in the SAME
#: commit**, and take the walk cost knowingly. A non-projection reader (an
#: operator verb, a doctor section, a census) changes nothing here and must not be
#: read as re-admitting the tree.
_EXCLUDED_NESTED_STORE_NAMES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        REALM_SYNC_DIRNAME: frozenset({".git"}),
    }
)


#: ``atomic_json_write`` stages ``.<stem>_*.tmp`` beside its target. A staged
#: temp file that a crash stranded is not an input; a live one belongs to a
#: write that will move the real file anyway.
_TMP_SUFFIX = ".tmp"


#: SQLite's mtime-blind siblings. A WAL commit that has not checkpointed leaves
#: the main database file untouched, so the journal files are stat'd beside it.
#:
#: ``-shm`` IS NOT HERE, and the ``-wal`` entry wears a mask. Both are the same
#: correction: the build OPENS these databases, and an open is not a write.
#:
#: What was measured (2026-08-18, live root and reproduced in the fixture): with
#: a connection held, opening the SessionDB a second time moves ``-wal``'s mtime
#: while leaving it at SIZE 0 — the closing connection checkpoints, so the file
#: is re-created empty at open time — and rewrites ``-shm``. Both moved DURING
#: the boot build that was reading them. The key is taken pre-build by design, so
#: the build's own read guaranteed the next process a ``fingerprint_mismatch``:
#: the cache could not converge inside one process, let alone across two.
#:
#: THE MASK, and why each half is sound:
#:
#: * ``-shm`` carries no content signal at all. SQLite documents it as a
#:   non-persistent shared-memory index, rebuilt from the WAL by whichever
#:   process opens the database, and deleted when the last connection closes. Its
#:   mtime is an open-time artefact of a READER. Anything it could indicate is
#:   already carried by ``-wal`` (the frames it indexes) or by the main file (the
#:   checkpoint that retired them). ``stream._scope_fingerprint`` — the other
#:   fingerprint in this runtime that stats these siblings — has always used
#:   ``("", "-wal", "-journal")``, so dropping it here CONVERGES the two
#:   conventions rather than forking them.
#: * ``-wal`` is keyed on ``(path, 0, 0)`` in EVERY state that holds no frames —
#:   absent and present-at-zero-length alike — and on its full stat'd triple the
#:   instant a frame lands. A frameless WAL holds nothing for the projection to
#:   read, and neither its mtime nor its existence says anything about content:
#:   both are artefacts of when some process last opened or closed the database.
#:   The instant an uncheckpointed commit lands the file is non-empty and the
#:   full triple counts again, so the WAL-commit signal EG-3.1 requires is
#:   untouched for every state the signal can actually be in. See
#:   :func:`_wal_without_frames_is_content_free` for why absence and emptiness
#:   are ONE fact rather than two — the half that took a second field
#:   investigation to see, after the first mask deliberately kept them apart.
#:
#: WHAT THE MASK DOES NOT COVER, stated rather than discovered later. A
#: checkpoint that truncates the WAL to zero AFTER writing its frames into
#: ``state.db`` leaves a zero-length WAL whose mtime this ignores — and a clean
#: last-close, which checkpoints and then UNLINKS the file, leaves no WAL at all.
#: Both are invisible here and both are carried anyway: the checkpoint moved
#: ``state.db``'s own mtime and size, and the main file is the FIRST entry in
#: this tuple. The uncovered case would be a commit that is invisible in the main
#: file AND invisible in the WAL's size, which SQLite's own durability rules do
#: not admit.
_DB_SIBLINGS = ("", "-wal", "-journal")


#: The sibling that is masked while it holds no frames. Named rather than
#: spelled at the call site so the mask and the enumeration cannot drift, and
#: named for the SIBLING rather than for the state so that widening the mask to
#: another suffix takes a deliberate edit here — the main file's absence and
#: ``-journal``'s absence are real information and must stay keyed.
_WAL_SIBLING = "-wal"


#: A DIRECTORY contributes its PATH and nothing else — never a timestamp, never
#: a present/absent distinction.
#:
#: Not an optimization; a correctness requirement, and it cost a false demote to
#: learn. Two independent reasons, both measured on this runtime's platform:
#:
#: 1. **A directory's own signal is perturbed by the children this fingerprint
#:    deliberately excludes.** The cache writes ``serve_read_model/`` INTO the
#:    store root, so a root whose existence-or-mtime counted made the very write
#:    that persisted a core invalidate the key it had just persisted — a
#:    guaranteed miss on every boot. Same hole for ``locks/``, the serve
#:    registry, and ``atomic_json_write``'s staged temp files.
#: 2. **A directory's mtime is not a reliable add signal anyway.** Measured on
#:    NTFS: creating a FILE inside a directory left the directory's ``mtime_ns``
#:    unchanged, while a later ``mkdir`` moved it. So it is noise in one
#:    direction and silence in the other — the worst combination for a change
#:    key.
#:
#: Nothing is lost. The enumeration is directory-LEVEL: an added file arrives as
#: its own new triple and a removed one takes its triple with it, so the parent's
#: timestamp is strictly redundant with the walk that produced it. That is the
#: same reasoning as the boards-tree per-card stat pattern in
#: ``harness_parts/serve/boot.py``, taken one step further.
_DIR_MARK = -2
