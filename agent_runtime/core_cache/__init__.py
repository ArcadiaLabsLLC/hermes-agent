"""The persisted read-model core, validated by a stat fingerprint (Plan EG-3.1) — the package map (rule 16).

Entry points (what calls in):

* ``decision.consult`` / ``lane.take_stale_first_core`` — the snapshot builder
  and the stream's stale-first routing ask whether a persisted core may serve.
* ``persist.write_back`` — the builder lands a fresh core.
* ``lane.close_cache_lane`` / ``lane.note_full_build_completed`` /
  ``lane.reset_process_state`` — the process-level lane.
* ``home.declare_fingerprint_home_boot_site`` / ``capture_fingerprint_home`` —
  the serve boot pins the fingerprint home.
* ``shadow.maybe_start_shadow_validation`` — the shadow check.

Modules, lowest layer first (no module imports one above it — W0-G6):

===========  ======  =======================================================
module       layer   owns
===========  ======  =======================================================
vocabulary   models  file names, demote reasons, receipts, refusals, bounds
models       models  the value types passed between stages
walk         stores  the stat walker and its exclusion/content rules
home         stores  the fingerprint home (process state, one writer)
fingerprint  stores  ``build_input_fingerprint``, stamp tokens
generations  stores  the generation layout and paths
restat       stores  the post-build restat
persist      stores  ``write_back``: staging/landing a generation, reaping
convergence  stores  the convergence streak (process state, one writer)
read         stores  reading and judging the persisted pair
lane         lanes   the armed lane and consult memo (process state)
decision     lanes   ``consult``, the demote log line
shadow       lanes   shadow validation
===========  ======  =======================================================

Stores written: ``<store_root>/core_cache/`` (pointer + generations), only
by ``persist.write_back``. The design history this module used to carry as its
docstring is ``docs/agent-runtime-harness/planned/core-cache-input-closure.md``
§ "The module docstring, as core_cache.py carried it". Its receipt channel
table is contract a test executes, so it is below, verbatim.

=============================================================================
THE RECEIPT CHANNEL TABLE (ML-14 / C22)
=============================================================================

Every receipt this lane emits rides ONE channel — this module's logger,
``agent_runtime.core_cache`` — and each line leads with a FAMILY token, then an
event token or ``key=value`` field. That is what makes a receipt countable: a
census greps the tokens, never the prose after them, and the prose is then free
to say whatever an operator needs to read.

**What this table retires is not a missing receipt, it is a missing index.**
Three vocabularies word themselves ``reason=`` on this one logger — the demote
reasons (``DEMOTE_*``), the write refusals, and ML-10's typed bound refusal —
and two spellings COLLIDE ACROSS TWO EVENTS: ``reason=fingerprint_unavailable``
and ``reason=build_stamp_unknown`` are emitted by the WRITE lane
(``snapshot_core_cache_write ok=false``) and by the READ lane's demote
(``snapshot_core_cache core_source=rebuilt``) alike. Grepping a reason without
its family token counts two different facts as one — the launcher-side class
ML-6 retired, where one refusal was worded ``patch_gap:`` on one channel and
``REFUSED gap:`` on the other and a census MEASURED a false zero. The family
token is the discriminator, which is why it leads every row below.

A "second channel" here means a surface OTHER than this logger that carries the
same fact. There is exactly one: the snapshot's own ``parity`` envelope, which
:func:`label_core` stamps. It is named per row rather than assumed.

| receipt (grep this) | second channel | what to grep there |
|---|---|---|
| ``snapshot_core_cache fingerprint_refused`` (WARNING) | none | fields ``reason=entries_exceeded`` ``scope=store_root``/``skill_root`` ``bound=`` ``root=``. The scope is load-bearing: the two bounds are different numbers over different trees |
| ``snapshot_core_cache never_converged`` (WARNING) | none | ``builds=`` then ``diff_scope=`` ``changed=`` ``diff=`` LAST (paths may contain spaces). **CENSUS RULE (C22(i)): read ``diff_scope=`` or the count over-reports.** ``every_pass`` = the inputs oscillate, i.e. self-perturbation, the A2 defect worth acting on; ``last_pair`` = a store that is simply moving, where the receipt is true (the cache IS buying nothing) but names no defect; ``none`` with ``diff=diff_unavailable`` and ``diff_reason=no_entries``/``digest_without_entry_delta`` = the diff could not be computed and says so in its own words |
| ``snapshot_core_cache generation_residue`` (WARNING) | none | ``present=`` ``bound=`` ``live=`` ``leftover=`` then ``generations=`` LAST (a variable-length list, so nothing after it can be field-parsed). **CENSUS RULE (MCF-54(ii)/MCF-59): this line is NOT a failed write-back.** It rides a write-back that already logged ``ok=true``, and reports that the best-effort reap left superseded generation directories on disk - a reader holding one open, or a permission the writer lacks. ``present=`` counts the live generation too; ``leftover=`` does not, and the names in ``generations=`` are leftovers only, oldest first, capped at eight with the true total always in ``leftover=``. The same name across consecutive builds is a permanently held handle; a different name each time is transient contention, and only the first is worth acting on |
| ``snapshot_core_cache core_source=cache`` (INFO) | the snapshot payload | ``parity.core_source == "cache"`` — SAME spelling, no split. The line also carries ``caller=`` ``inputs=`` ``fingerprint=`` ``offset=``, none of which reach the payload |
| ``snapshot_core_cache core_source=cache stale=true`` (INFO) | the snapshot payload | ``parity.core_stale == true`` AND ``parity.freshness.state == "stale"`` — the field the launcher's ``MissionSnapshotEnvelope`` already maps to ``MissionSnapshotHealth.stale``. RESIDUAL SPLIT, named rather than fixed: the log says ``stale=true``, the payload says ``parity.core_stale``/``parity.freshness.state``, and the payload spelling is a consumer contract that predates this lane |
| ``snapshot_core_cache core_source=rebuilt`` (INFO, ``_log_demote``) | the snapshot payload, PARTIALLY | ``parity.core_source == "rebuilt"`` carries THAT the cache was demoted; the ``reason=`` never leaves this logger, and ``CoreDecision.reason`` is read by no caller today. So a field census of WHY a cache demoted has exactly one source: this line. **AND IT NOW HAS A READER (BO-4, 2026-08-21):** ``agent_runtime.core_cache_census`` executes every census rule in this row — the reason histogram, the runtime-authored/store bucketing, the diff-unavailable arms, and the refusal to read a silent window as a clean one — as code rather than as prose, run by ``scripts/core_cache_demote_census.py``. Amending a rule here means amending that module and its tests; a rule that lives only in this sentence is a rule nothing executes, which is how the self-invalidating cache below ran unnoticed for months. Reasons ``unreadable`` ``core_digest_mismatch`` ``fingerprint_unavailable`` ``fingerprint_mismatch`` ``build_stamp_unknown`` ``build_stamp_mismatch`` ``contract_mismatch`` ``runtime_root_mismatch`` ``home_mismatch``. **CENSUS RULE (MC-2): ``home_mismatch`` is not an ordinary miss.** The other reasons say the STORE moved, the install changed, or the pair is unbound — all facts about the thing being cached. This one says the persisted pair was keyed under a different Hermes home than the reading process resolved, i.e. the two runs asked different QUESTIONS, and it is emitted INSTEAD of ``fingerprint_mismatch`` so the distinction is countable rather than inferred. On a multi-home install (an operator who really does run two roots) it is ordinary. On a SINGLE-PROFILE operator boot it is evidence that a persona scope was live while a build stat'd — the capture in ``core_cache.resolved_fingerprint_home`` was taken too late — which is a defect to go fix, not noise to tune out. A pair carrying no ``sidecar.fingerprint_home`` at all (every one written before MC-2) is skipped rather than demoted, so this reason can never fire for an install that simply predates the field. ``absent`` is deliberately NOT logged (the ordinary cold start would print a line on every build in every process), so its only trace is the ABSENCE of a line and a census must not read "no demote line" as "no demote". **CENSUS RULE (MC-3): ``fingerprint_mismatch`` ALONE grows a tail**, and the tail is ``changed=`` then ``diff=`` LAST (paths may contain spaces, so nothing can be field-parsed after it; the tail is additive, so an existing ``reason=`` grep is unaffected). No other reason carries one, deliberately: a diff on a ``build_stamp_mismatch`` would name every file the operator's upgrade touched and read as store churn. **The scope is ``last_pair`` BY CONSTRUCTION and that caveat is the row's most important sentence:** a demote diff is the delta since the LAST WRITE-BACK, so on a busy store it legitimately names files that are simply moving, and the receipt is TRUE without naming a defect. It is self-perturbation evidence — the A1-b/A2 class worth acting on — ONLY when the named paths are ones the runtime itself writes (``dispatch_delivery_drain.json``, ``serve_socket.owner.json``, ``state.db-wal``, ``serve_socket.lock``); when they are store paths the operator's own writes touched, the miss is legitimate and the cache is working as designed. An arm that could not compute the diff says so in its own words rather than emitting an empty list, which would read as "we looked and nothing moved": ``diff_scope=none changed=0 diff_reason=`` ``no_entries`` (nothing persisted yet, or an install predating MC-3) / ``entries_unbound`` (the entries file in the live generation is not the one that write-back put there — MCF-21 made a torn trio unrepresentable, so this now reads as tampering or corruption rather than as a failed diagnostic write) / ``digest_without_entry_delta`` (the digests disagreed and no triple did), then ``diff=diff_unavailable`` |
| ``snapshot_core_cache fingerprint_home_lazy_capture`` (WARNING) | none | ``site=`` ``home=`` ``authoritative=``. **CENSUS RULE (HC-1): this is the row above's defect CAUGHT IN THE ACT, one boot earlier.** ``reason=home_mismatch`` is read off the process that JUDGES a pair; this line is emitted by the process that PRODUCES one, at the moment its home is captured lazily — on whichever build or consult happened to be first — inside a process that had already named the boot instant which owed that capture (``site=`` is that instant, e.g. ``serve_loop:booting_frame_emitted``). A process that never declared an instant (an ordinary short-lived tool, a test) emits nothing here, so a nonzero count is never a cold start: it is a serve whose eager capture did not run, and therefore a serve free to write a sidecar keyed under a persona scope's home. ``authoritative=`` restates :func:`agent_runtime.profile_home.hermes_head_home_is_authoritative` AT CAPTURE TIME — ``authoritative=false`` means the head had already degenerated to the ambient resolution, which is the state in which a live persona override IS the captured home. **NO CENSUS COUNTS THIS LINE TODAY, and that is stated here rather than left to be discovered:** ``agent_runtime.core_cache_census`` reads the demote family and is keyed on ``reason=home_mismatch``, so this receipt is an operator grep on the serve's own log. It is not a rule executed as code, which is the standard the row above is held to, and teaching the census this family is the honest way to retire that gap |
| ``snapshot_core_cache_write ok=true`` (INFO) | none | ``inputs=`` ``fingerprint=`` ``offset=`` ``restat=`` ``self_perturbed_refreshed=`` ``foreign_moved=``. **CENSUS RULE (IC-2): the last three describe the KEY, not the write.** ``restat=`` is one of refreshed / clean / skipped / unavailable — deliberately NOT worded ``reason=``, because this line is a success and a fourth ``reason=`` vocabulary on this logger is the exact defect this table exists to have retired. ``self_perturbed_refreshed=`` counts the entries the build's OWN writes moved and the persisted key therefore adopted fresh (see :func:`_restat_on_post_build_reality`); a healthy store settles to a small steady number and a zero on every build with ``never_converged`` still firing means the oscillating input is NOT in the audited set and the set is what needs widening. ``foreign_moved=`` counts entries that moved during the build and were NOT in that set, i.e. a concurrent writer — those keep their pre-build triple, so a nonzero count predicts the next process's ``fingerprint_mismatch`` and is the honest measure of how much the store is moving under its own builds. a ``restat=`` reading "unavailable" means the re-stat could not be taken at all and the pre-build key was persisted unchanged: not a failure of the write, but a build whose key is knowingly stale |
| ``snapshot_core_cache_write ok=false`` (INFO/WARNING) | none | reasons ``serialize`` ``build_stamp_unknown`` ``fingerprint_unavailable`` ``io``. **COLLISION:** ``build_stamp_unknown`` and ``fingerprint_unavailable`` are ALSO demote reasons on the row above. Grep the family token with them, never the reason alone |
| ``snapshot_core_shadow ok=true`` (INFO) | none | ``caller=`` ``divergence=none`` — the shadow build agreed with the cache. **CENSUS RULE (MCF-Q1): this line ALSO closes the armed window**, exactly as the divergence row below does. It used to be the one full build in the process that changed nothing, and that is what made the memo's boot bound vacuous on a cache-hit boot; counting this line is counting boots whose cache was confirmed, never boots that kept serving it |
| ``snapshot_core_shadow ok=false`` (WARNING) | none | ``caller=`` ``reason=build`` — the shadow build itself raised. Closes the armed window too: a validation that could not run is not a licence to keep serving the core it failed to validate |
| ``snapshot_core_cache_lane_closed`` (WARNING) | none | ``caller=`` ``reason=`` then a free-form detail span LAST. One reason today, ``core_behind_frame``, whose detail is ``core_offset=`` ``frame_offset=``. **CENSUS RULE (MCF-Q1): this line is not a cache miss and must not be counted with the demotes.** A demote is the fingerprint deciding a persisted pair is not current; this is a CONSUMER reporting that a core the lane already served reaches an earlier offset than the frame about to carry it — the "authoritative-for-an-offset-it-predates" shape that erased a just-created agent from Mission Control on 2026-08-21. Its presence means the lane was still armed when a store change raced it, which is expected only inside a boot's shadow-validation window; a nonzero count OUTSIDE that window says the window is not closing and is worth acting on |
| ``snapshot_core_shadow_divergence`` (WARNING) | none | ``caller=`` ``section=`` (the first section that disagreed). Its own family token rather than a field on the row above, because retiring the shadow lane is keyed on counting exactly this |
| ``snapshot_core_shadow adopt failed`` (WARNING) | none | **NO EVENT TOKEN — the one uncountable line in this lane.** It is prose after the family token, so a census can only grep the sentence. Named here rather than quietly renamed: the rename is a one-line change with a consumer question attached, and this row is the record that it is owed |

Adding a receipt here means adding a ROW here.
``tests/agent_runtime/test_core_cache_channel_table.py`` drives both directions
— a token no row names, and a row naming a token no writer emits, each turn it
red — and separately drives the writers to prove the rendered line really
carries the spelling this table tells a census to grep.

**Scope.** This table covers the core-cache lane, which is the vocabulary C22
names. Three other things in ``agent_runtime`` are called receipts and are NOT
in it, deliberately, because they are different artifacts on different channels
rather than log lines: ``persona_chat_mints``' mint receipts (durable JSON files
under ``persona_chat_mint_receipt_path``), ``profile_runner``'s
``CHAT_COMPACTION_RECEIPT_KIND`` (a structured event payload) and
``snapshot.build_receipt_facts`` (a facts dict folded into the frame). Each
would need its own table keyed on its own channel; naming them here is what
stops this one from being read as the whole census.
"""

from __future__ import annotations

import shutil
from agent_runtime.core_cache import (  # noqa: F401 — every family, in the original definition order
    vocabulary,
    models,
    walk,
    home,
    fingerprint,
    generations,
    restat,
    persist,
    convergence,
    read,
    lane,
    decision,
    shadow,
)
from agent_runtime.core_cache.vocabulary import (
    CORE_FILENAME,
    CORE_SOURCE_CACHE,
    CORE_SOURCE_REBUILT,
    DEMOTE_ABSENT,
    DEMOTE_BUILD_STAMP_MISMATCH,
    DEMOTE_BUILD_STAMP_UNKNOWN,
    DEMOTE_CONTRACT_MISMATCH,
    DEMOTE_CORE_DIGEST_MISMATCH,
    DEMOTE_FINGERPRINT_MISMATCH,
    DEMOTE_FINGERPRINT_UNAVAILABLE,
    DEMOTE_HOME_MISMATCH,
    DEMOTE_RUNTIME_ROOT_MISMATCH,
    DEMOTE_UNREADABLE,
    DIFF_SCOPE_EVERY_PASS,
    DIFF_SCOPE_LAST_PAIR,
    DIFF_SCOPE_NONE,
    DIFF_UNAVAILABLE,
    DIFF_UNAVAILABLE_ENTRIES_UNBOUND,
    DIFF_UNAVAILABLE_NO_ENTRIES,
    DIFF_UNAVAILABLE_NO_ENTRY_DELTA,
    ENTRIES_FILENAME,
    POINTER_FILENAME,
    RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE,
    RECEIPT_FINGERPRINT_REFUSED,
    RECEIPT_GENERATION_RESIDUE,
    RECEIPT_NEVER_CONVERGED,
    REFUSAL_ENTRIES_EXCEEDED,
    REFUSAL_SCOPE_SKILL_ROOT,
    REFUSAL_SCOPE_STORE_ROOT,
    SIDECAR_FILENAME,
    _DB_SIBLINGS,
    _EXCLUDED_NESTED_STORE_NAMES,
    _EXCLUDED_STORE_ENTRIES,
    _WAL_SIBLING,
)
from agent_runtime.core_cache.models import (
    CacheRead,
    CoreFingerprint,
    FingerprintEntry,
    FingerprintHomeCapture,
)
from agent_runtime.core_cache.walk import (
    _CONFIG_CONTENT_MAX_BYTES,
    _db_entries,
    _receipt_fingerprint_refused,
    _stat_entry,
    sqlite_fingerprint_triples,
)
from agent_runtime.core_cache.home import (
    _pinned_to_fingerprint_home,
    capture_fingerprint_home,
    declare_fingerprint_home_boot_site,
    fingerprint_home_capture,
    reset_fingerprint_home,
    resolved_fingerprint_home,
)
from agent_runtime.core_cache.fingerprint import build_input_fingerprint
from agent_runtime.core_cache.generations import (
    _cache_dir,
    _is_generation_name,
    _live_generation_name,
    core_path,
    entries_path,
    pointer_path,
    sidecar_path,
)
from agent_runtime.core_cache.restat import (
    BUILD_SELF_PERTURBED_CLASSES,
    SELF_PERTURBED_LIVE_EVENTS,
    SELF_PERTURBED_PERSONA_INSTANCES,
    SELF_PERTURBED_SESSION_DB,
    _restat_on_post_build_reality,
    _self_perturbed_inputs,
)
from agent_runtime.core_cache.persist import (
    GENERATION_RESIDUE_BOUND,
    _GENERATION_RESIDUE_NAMES,
    write_back,
)
from agent_runtime.core_cache.convergence import (
    NEVER_CONVERGED_BUILDS,
    _NEVER_CONVERGED_DIFF_PATHS,
    _diff_detail,
    _receipt_never_converged,
)
from agent_runtime.core_cache.read import (
    _persisted_entries,
    _read_pair,
    label_core,
    read_persisted_core,
)
from agent_runtime.core_cache.lane import (
    REFUSAL_CORE_BEHIND_FRAME,
    _pair_stamp,
    _store_position,
    claim_shadow_slot,
    close_cache_lane,
    lane_armed,
    note_full_build_completed,
    pre_build_fingerprint,
    reset_process_state,
    shadow_build_scope,
    take_stale_first_core,
)
from agent_runtime.core_cache.decision import _log_demote, consult
from agent_runtime.core_cache.shadow import (
    _SHADOW_IGNORED_PARITY_KEYS,
    _SHADOW_IGNORED_TOP_KEYS,
    _SHADOW_IGNORED_WATERMARK_KEYS,
    compare_cores,
    iter_fingerprint_paths,
    maybe_start_shadow_validation,
    shadow_validate,
)

__layer__ = "wiring"

__all__ = [
    "BUILD_SELF_PERTURBED_CLASSES",
    "CORE_FILENAME",
    "CORE_SOURCE_CACHE",
    "CORE_SOURCE_REBUILT",
    "CacheRead",
    "CoreFingerprint",
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
    "FingerprintEntry",
    "FingerprintHomeCapture",
    "GENERATION_RESIDUE_BOUND",
    "NEVER_CONVERGED_BUILDS",
    "POINTER_FILENAME",
    "RECEIPT_FINGERPRINT_HOME_LAZY_CAPTURE",
    "RECEIPT_FINGERPRINT_REFUSED",
    "RECEIPT_GENERATION_RESIDUE",
    "RECEIPT_NEVER_CONVERGED",
    "REFUSAL_CORE_BEHIND_FRAME",
    "REFUSAL_ENTRIES_EXCEEDED",
    "REFUSAL_SCOPE_SKILL_ROOT",
    "REFUSAL_SCOPE_STORE_ROOT",
    "SELF_PERTURBED_LIVE_EVENTS",
    "SELF_PERTURBED_PERSONA_INSTANCES",
    "SELF_PERTURBED_SESSION_DB",
    "SIDECAR_FILENAME",
    "_CONFIG_CONTENT_MAX_BYTES",
    "_DB_SIBLINGS",
    "_EXCLUDED_NESTED_STORE_NAMES",
    "_EXCLUDED_STORE_ENTRIES",
    "_GENERATION_RESIDUE_NAMES",
    "_NEVER_CONVERGED_DIFF_PATHS",
    "_SHADOW_IGNORED_PARITY_KEYS",
    "_SHADOW_IGNORED_TOP_KEYS",
    "_SHADOW_IGNORED_WATERMARK_KEYS",
    "_WAL_SIBLING",
    "_cache_dir",
    "_db_entries",
    "_diff_detail",
    "_is_generation_name",
    "_live_generation_name",
    "_log_demote",
    "_pair_stamp",
    "_persisted_entries",
    "_pinned_to_fingerprint_home",
    "_read_pair",
    "_receipt_fingerprint_refused",
    "_receipt_never_converged",
    "_restat_on_post_build_reality",
    "_self_perturbed_inputs",
    "_stat_entry",
    "_store_position",
    "build_input_fingerprint",
    "capture_fingerprint_home",
    "claim_shadow_slot",
    "close_cache_lane",
    "compare_cores",
    "consult",
    "core_path",
    "declare_fingerprint_home_boot_site",
    "entries_path",
    "fingerprint_home_capture",
    "iter_fingerprint_paths",
    "label_core",
    "lane_armed",
    "maybe_start_shadow_validation",
    "note_full_build_completed",
    "pointer_path",
    "pre_build_fingerprint",
    "read_persisted_core",
    "reset_fingerprint_home",
    "reset_process_state",
    "resolved_fingerprint_home",
    "shadow_build_scope",
    "shadow_validate",
    "shutil",
    "sidecar_path",
    "sqlite_fingerprint_triples",
    "take_stale_first_core",
    "write_back",
]
