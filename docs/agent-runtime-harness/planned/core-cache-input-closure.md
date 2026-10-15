# Planned — widen the core cache's fingerprint input closure

**Status:** IC-1, IC-2 and IC-3 implemented 2026-08-22; IC-4 not implemented and
now gated on measurement (see below). **Domain:** runtime data and shapes.
**Opened:** 2026-08-22, from live receipts.

**What landed, and where its argument lives.** IC-1 —
`core_cache._EXCLUDED_NESTED_STORE_NAMES` (nested exclusion, `realm_sync/**/.git`
only) plus `_walk_tree`'s `exclude_nested`; the top-level-only doctrine block and
both of its pinning tests are amended, and the four
`realm_sync/<realm>/*_baseline.json` sidecars are pinned INSIDE the closure by
`tests/agent_runtime/test_core_cache_exclusions.py`. IC-2 —
`core_cache._restat_on_post_build_reality`, with the design note answering the
module docstring's validity doctrine written at
`core_cache.SELF_PERTURBED_SESSION_DB`; gated by
`tests/agent_runtime/test_core_cache_post_build_restat.py`, whose safety half
pins that a foreign write is NOT absorbed. IC-3 —
`persona_assignments.ensure_for_persona` splits cold from unreadable and repairs
an unreadable row once per process; gated by
`tests/agent_runtime/test_persona_instance_unreadable_row.py`.

**The gate below is only half-discharged.** The two FIELD conditions — a
shadow-validation window over the live store showing zero divergence, and
`never_converged diff_scope=every_pass` dropping to zero over a week of operator
boots — are unmeasured. IC-4's "measure first" instruction now has an
instrument: `snapshot_core_cache_write ok=true` carries `restat=`,
`self_perturbed_refreshed=` and `foreign_moved=`, so whether a WAL mask is still
needed is a reading of those fields rather than a guess.

## The problem

`agent_runtime/core_cache.py` validates a persisted snapshot core by re-stat'ing
every input the build read and comparing `(path, mtime_ns, size)` triples. When
consecutive write-backs each produce a key that disagrees with the one before
it, no later process can ever be served the cache: the lane costs a write per
build and buys nothing. That state emits
`snapshot_core_cache never_converged` (`core_cache.py:322`).

It is currently the steady state on the operator's machine.

## Evidence

`X:\Eternia\.hermes\profiles\base\logs\agent.log`, 10 firings between
2026-08-20 18:21 and 2026-08-22 13:42:

| When | `diff_scope` | `changed` | Named paths |
| --- | --- | --- | --- |
| 08-20 18:21 | `every_pass` | 60 | `realm_sync/<realm>/.git/index`, `.git/logs/HEAD`, `.git/objects/pack/*.pack`, … |
| 08-20 18:30 | `last_pair` | 2 | `events_archive/events.81417412.jsonl`, `profiles/alice/config.yaml` |
| 08-20 18:38 | `last_pair` | 2 | same pair |
| 08-20 20:37 | `every_pass` | 2 | live events slice, `persona_instances/personainst_neko_supervisor_agent_f6f7a51b.json` |
| 08-21 13:51 | `last_pair` | 1 | `profiles/alice/config.yaml` |
| 08-21 17:18 | `every_pass` | 1 | `profiles/base/state.db` |
| 08-21 17:22 | `every_pass` | 1 | `profiles/base/state.db-wal` |
| 08-21 22:00 | `last_pair` | 1 | live events slice |
| 08-22 10:48 | `last_pair` | 1 | live events slice |
| 08-22 13:42 | `every_pass` | 1 | `profiles/base/state.db-wal` |

Receipt format, verbatim:

```
snapshot_core_cache never_converged builds=3 diff_scope=every_pass changed=1
  diff=X:\Eternia\.hermes\profiles\base\state.db-wal — 3 consecutive write-backs
  each wrote a key that disagreed with the one before it …
```

Demote histogram over the same log: 57 `build_stamp_mismatch`, 24
`fingerprint_mismatch`, 8 `home_mismatch`. Serve outcomes: 50 `core_source=cache`,
41 `core_source=cache stale=true`, 89 `core_source=rebuilt`.

## Reading the evidence

The module's own census rule (`core_cache.py:181`) is the interpretation
authority: `diff_scope=every_pass` means the inputs oscillate — self-perturbation,
the defect worth acting on. `diff_scope=last_pair` means the store is simply
moving and the receipt is true without naming a defect.

Five of the ten firings are `every_pass` (08-20 18:21, 08-20 20:37, 08-21 17:18,
08-21 17:22, 08-22 13:42). Their named paths split two ways:

- **Runtime-authored** — `state.db`, `state.db-wal`, `persona_instances/*.json`.
  The runtime writes these while a build stats them. This is the actionable
  class.
- **`realm_sync/<realm>/.git/**`** — a git worktree the runtime syncs into,
  under the store root. 60 changed entries in one pass. Git's own index, reflog
  and packfiles are not runtime state the projection reads; they are inside the
  fingerprint walk because the walk is directory-level over the store root.

`state.db-wal` is the subtlest: `core_cache.py:856` already masks a frameless
WAL to `(path, 0, 0)` so that *reading* the database does not look like writing
it. The 08-21 17:22 and 08-22 13:42 firings say the mask is not sufficient for
the way this runtime commits during a build.

## The sanctioned direction

The module docstring states it and this plan must not deviate:

> If a shadow receipt ever shows divergence, the fix is WIDENING the stat set —
> never trusting the cache harder.

Widening means making the closure a function of the store rather than of the
instant, over the *named* inputs. Two candidate moves, neither yet ruled:

1. **Exclude `realm_sync/*/.git/`** from the walk. The projection reads
   `realm_sync_state/<realm>.json`, not the worktree's git internals — so the
   `.git` subtree is arguably outside the input closure entirely, which makes
   this an exclusion rather than a widening. Verify against every reader before
   ruling: an excluded input that *is* read is exactly the failure class
   (unlabeled stale served as authoritative) the lane exists to end.
2. **Extend the SQLite mask** so a WAL that gains and loses frames within a
   build keys identically. `_wal_without_frames_is_content_free`
   (`core_cache.py:856`) is the existing precedent for a content-free WAL state.

## Reader audit — DONE (2026-08-22, read-only evidence lane)

The gate's audit obligation is discharged; the findings reshape the plan.

1. **`realm_sync/*/.git/` has zero build readers** — every section builder
   resolves realm-sync state to `realm_sync_state/<realm>.json`
   (`realm_sync.py:1870`; design intent written at `snapshot.py:2493-2496`:
   the build "must never shell out to git"). BUT the build DOES read two
   siblings one directory up: `realm_sync/<realm>/board_baseline.json`
   (`snapshot.py:1610` → `paths.py:129`) and `office_baseline.json`
   (`snapshot.py:1837` → `paths.py:214`). The exclusion must target the
   literal `.git` name only — and note `_sync_repo_path` keys worktrees by
   SERVER token while baselines key by realm id, so a realm-id-keyed skip
   would be wrong.
2. **The walk excludes top-level names only** (`_walk_tree` `exclude_top`,
   `core_cache.py:830-832`; doctrine pinned at `:638-646` with a test).
   `.git` sits at depth ≥2 — a nested-exclusion mechanism is new code, and
   the doctrine block plus its pinning test must be amended in the same
   commit.
3. **The build is not a pure reader — five proven self-perturbation writes:**
   (a) `snapshot.py:871` → `ensure_for_personas` recreates any
   missing/UNREADABLE persona-instance row on EVERY build
   (`persona_assignments.py:441-454` — the bare `except Exception` means a
   corrupt row re-mints a file write + a `persona_instance.created` event
   per pass, a non-converging trigger); (b) drift rewrites (`:463-465`);
   (c) stale-binding resets stamping fresh `updated_at` (`:2219-2235`);
   (d) the build's own SessionDB close drains token deltas and runs a
   TRUNCATE WAL checkpoint (`snapshot.py:2350-2356` →
   `hermes_state.py:2542-2548`) — moving `state.db`'s main-file triple with
   zero logical change, the 08-21 17:18 shape; (e) DB opens during the build
   flip the stream scope fingerprint, appending synthetic `state.reconciled`
   to the live events slice (`stream.py:1359-1368`; measured 96.9% of all
   events at 9s median spacing, `stream.py:1240-1249`) — a genuine
   build→event→key-flip→demote→build feedback loop.
4. **WAL mask soundness bounds:** collapsing two different UNCHECKPOINTED
   frame sets is forbidden (`core_cache.py:696-698` — hides a commit
   invisible in the main file). Collapsing frames-present with
   post-checkpoint-frameless is sound ONLY because the checkpoint moves
   `state.db`'s own triple. Content-keying the WAL by raw-read frame digest
   (precedent: `_config_input_is_content_keyed`, `:929`) is sound in the
   invalidation direction — but **no WAL mask alone converges this store
   while (d) runs a TRUNCATE checkpoint on every build's close**.
5. `agent_create_reservations/` is unread by the build and low-churn — leave
   it in the walk (excluding it buys nothing and costs an audit obligation).

## Staged implementation (coordinator, 2026-08-22)

- **IC-1 — nested `.git` exclusion.** New nested-exclusion support in
  `_walk_tree` scoped to the literal `.git` name under `realm_sync/*`;
  amend the top-level-only doctrine (`:638-646`) and its pinning test in the
  same commit; add the obligation comment (pattern `:545-552`). Kills the
  60-entry class from the 08-20 18:21 firing. Mechanical.
- **IC-2 — key the write-back on post-build reality.** `write_back` persists
  the CONSULT-time `pre_build_fingerprint` (`core_cache.py:2892-2902`), so
  the build's own writes (3a-3e) guarantee the persisted key disagrees with
  the next consult's stat — the exact `never_converged` mechanism. Re-stat
  the self-perturbed inputs (DB triples, live slice, persona_instances) at
  write-back time, AFTER the SessionDB close, so the persisted key matches
  what the next consult will see. The equivalence golden
  (`test_core_fingerprint_cache.py:1501`) is the authority that this does
  not serve stale: the re-stat happens only on the write path, never widens
  what a consult accepts. Needs a design note answering `core_cache.py:20-40`
  in writing.
- **IC-3 — stop the corrupt-row rebuild loop.** Narrow
  `persona_assignments.py:441`'s bare `except Exception`: an unreadable row
  should surface a warning receipt and re-mint ONCE, not silently re-mint
  every build.
- **IC-4 — WAL raw-content keying** for the mtime-moved-bytes-identical
  class, after IC-2 (measure first — IC-2 may make it unnecessary).
- **Deliberately out of scope:** suppressing the build-close TRUNCATE
  checkpoint (a SessionDB lifecycle change owned elsewhere), and the
  `state.reconciled` feedback loop's stream half (3e) — record its census
  numbers here, but the fix belongs to the stream scope-fingerprint lane.

## 2026-08-23 addendum — the chat-turn sidecar family (NEW churn class, post IC-1..3)

Five `never_converged` firings on 2026-08-23 (10:29, 10:35, 10:40, 10:45, 13:33 local;
first: `diff_scope=every_pass changed=1
diff=…mission_chat_turns\persona_chat_personainst_profile_alice_agent_a408669a_….json`)
name paths the runtime-authored class above never listed: the mission-chat TURN RECORD
itself, `mission_chat_steer/*/active.json`, `persona_chat_leases/*.owner.json`, and
`prompt_observability/*.json` + `prompt_observability_index.json`. All four are written
by the chat lane on every operator turn — and Stage 0 of
[`chat-turn-prep-cost.md`](chat-turn-prep-cost.md) (`60c7f46ec1`) now persists a
`profile_timing` block onto the turn record on every turn, so this family churns at
operator-message cadence by design.

Candidate treatment, NOT yet ruled (the reader-audit obligation above re-arms for any
exclusion): these sidecars are chat-lane state that the snapshot build reads through its
own section builders — whether each is a genuine fingerprint input or an IC-2-style
self-perturbation (re-stat at write-back) must be answered per path family before
anything is excluded. Until then these firings are EXPECTED noise of the same class the
IC-2 re-stat already absorbs for the DB triples; watch whether the weekly census still
counts `every_pass` firings from this family after a week of post-`bfde53b4ae` boots.

## 2026-09-08 addendum — the field half of IC-4's "measure first", partly taken

Read on the operator's `neko` profile (`agent.log` + `errors.log`) and recorded in
full at [`windows-path-syscall-cost-2026-09-08.md`](windows-path-syscall-cost-2026-09-08.md),
"What the measurement did NOT explain" item 2. Three facts, none of which changes
this plan's direction:

- **2,094 `snapshot_core_cache_write` lines, ZERO `core_source=cache` serves.** The
  only 42 `snapshot_core_cache` lines in that log are `never_converged`. The lane is
  costing a write per build and buying nothing, exactly as the receipt says.
- **The same code SERVES on a quiescent COPY of the same store** — 226–241 ms against
  a 1.0–2.2 s cold build, measured under `HERMES_REQUIRE_ISOLATED_ROOT`. So
  convergence is the whole blocker; nothing about the cache's design needs revisiting.
- **The write-back is not itself expensive.** Disabling it entirely bought **4 ms**
  on a 411 ms warm build. That kills "just stop writing" as a remedy: the prize is
  the cold build the cache would replace, not the write it costs.

The families in today's firings are the 2026-08-23 chat-turn sidecar family plus
`realm_sync_state/<realm>.json`, `events_archive/events.*.jsonl`,
`gateway/peers_cache.json` and `chat_turn_reservations/*.json`. The per-family reader
audit this plan demands is still owed; nothing is excluded on this reading.

## The gate to open this

- ~~Every candidate exclusion has a named reader audit proving nothing in
  `build_snapshot()` reads it.~~ DONE above for `.git`; any FURTHER exclusion
  re-arms this obligation.
- The equivalence golden stays green —
  `test_the_cache_served_core_equals_the_rebuilt_core_field_for_field`
  (`tests/agent_runtime/test_core_fingerprint_cache.py:1501`, filed under
  "7. The equivalence golden — THE authority guard").
- A shadow-validation window over the live store shows zero divergence.
- `never_converged` with `diff_scope=every_pass` drops to zero over a week of
  operator boots, measured by `scripts/core_cache_demote_census.py`.

## Why it matters

Cold boot currently costs 11,235 ms of re-projection
(`snapshot_build_core role=led caller=prewarm generation=1 build_ms=11235`,
2026-08-22 15:46). The cache exists to replace that reconstruction with
validation. While it never converges, every boot pays the full build *and* a
write-back.

## The module docstring, as core_cache.py carried it

Relocated verbatim by lane R3's MOVE (the single-file module became the `agent_runtime/core_cache/` package; ruling Q3: prose relocates, it is never a reason to split). The package map is `agent_runtime/core_cache/__init__.py`. Its last section, THE RECEIPT CHANNEL TABLE, is not history: `tests/agent_runtime/test_core_cache_channel_table.py` executes it, so it stays in the package docstring and is not copied here.

```text
The persisted read-model core, validated by a stat fingerprint (Plan EG-3.1).

=============================================================================
WHY THIS EXISTS
=============================================================================

A serve child's first read-model core costs ~20 s of filesystem metadata work,
on EVERY boot — the build is per-process, so a warm machine pays it too
(measured 24.2 s warm, 2026-08-17). Doc 14's own numbers say the cost is not
bandwidth: serializing the core is ~5 ms. The 20 s IS validation, done by
reconstruction.

So make validation cost what validation costs. The core is persisted after
every successful default-store build, together with a sidecar carrying the
**fingerprint of every input the build read**. The next process stats those
inputs again: match → load the core and serve it authoritative in ~2 s;
mismatch → serve the persisted core immediately, LABELED STALE, while the full
build runs, then replace it and write back.

=============================================================================
WHY A STAT FINGERPRINT AND NOT AN EVENT OFFSET
=============================================================================

The refused design (Plan G BW-H1) keyed validity on the event log's offset plus
a tail replay. It stays refused, for cause:

* the events section is 3 ms of a 5,485 ms build — an offset-keyed cache buys
  almost nothing and can only go stale undetectably;
* two shipped incidents came from writers that mutate durable state with NO
  EventLog event (``running_work.py``'s checkpoint, ``board_sync``'s
  materialization), so an offset key cannot see them at all;
* a tail replay would be a SECOND validity authority beside the key, and the
  two would drift. Property 6 (one lane per question), applied to the cache
  itself.

**The fingerprint decides validity, full stop.** There is no event-tail replay
here and there must never be one. ``event_offset`` IS recorded in the sidecar —
as a diagnostic, so a divergence receipt can name the log position the core was
built at — and it is never read as an input to the match decision.

=============================================================================
THE SOUNDNESS GROUND
=============================================================================

A (path, mtime_ns, size) triple is only a change signal if every writer moves
mtime. In this runtime every durable write goes through
:func:`utils.atomic_json_write`, which stages a temp file and ``os.replace``s
it into position — a rename ALWAYS moves the target's mtime, including for a
rewrite that produces byte-identical content. That is what makes the cheap
signal sound here specifically, and it is why the enumeration is
DIRECTORY-LEVEL rather than a list of names: a file that did not exist at the
last build has no previous triple to compare, so the walk has to find it.

Two mtime-blind cases are covered explicitly rather than assumed:

* **SQLite.** A WAL commit that has not checkpointed leaves ``state.db``'s
  mtime untouched, so the ``-wal`` and ``-journal`` siblings are fingerprinted
  beside it — the WAL under a mask that stops READING the database from looking
  like writing it. See :data:`_DB_SIBLINGS` for the mask, its ground, and what
  it deliberately does not cover.
* **In-place rewrites inside a directory.** Replacing an existing entry does
  not move the CONTAINING directory's mtime on NTFS, which is why every file
  is stat'd individually instead of trusting its parent (the same reasoning as
  the boards-tree per-card stat pattern in ``harness_parts/serve/boot.py``).

=============================================================================
THE INPUT CLOSURE — THE ONE THING THIS STAGE CAN GET WRONG
=============================================================================

Plan EG §6.1 names this the plan's single biggest bet: a MISSED input serves
unlabeled stale as authoritative, which is the failure class the plan exists to
end, inverted. Three mitigations are load-bearing, not decorative:

1. **The closure is derived from the build's own readers** — every class below
   resolves through the SAME path authority the projection reads through
   (``paths.store_root``, ``running_work_store_paths``,
   ``chat_session_db_path``, ``_get_profiles_root``, ``get_all_skills_dirs``).
   No second list free to drift. Those authorities are asked under a home this
   process resolved ONCE (:func:`resolved_fingerprint_home`) rather than under
   the ambient ``HERMES_HOME`` the build itself exports per persona — see that
   constant for why "one resolution" and not merely "the head home" is what
   makes the closure a function of the store.
2. **The equivalence golden** (``test_core_fingerprint_cache.py`` test 7) reds
   a gap inside the fixture matrix: for one fingerprint the cache-served core
   must equal the rebuilt core field-for-field.
3. **The shadow-validation window** reds it in the field: a cache-hit boot ALSO
   runs the full build in the background and compares; a divergence is a loud
   receipt naming the section AND the rebuilt core is adopted.

If a shadow receipt ever shows divergence, the fix is WIDENING the stat set —
never trusting the cache harder.

Two more receipts (ML-10) cover the ways this lane can fail QUIETLY rather than
wrongly, both on the same channel and countable by the same census:

* ``fingerprint_refused`` — a walk hit its entry bound, so the fingerprint is
  refused and the cache is off for this install. Unchanged as a decision; it was
  previously a WARNING sentence that did not even name the tree.
* ``never_converged`` — this process's consecutive write-backs never agreed, so
  no later process can be served the cache at all. It names the oscillating
  input paths, because the sanctioned response is again to widen the closure
  over a NAMED input.

=============================================================================
ONE AUTHORITY
=============================================================================

The store decides; the projection serves. A cached or stale-labeled core never
deletes, never refuses a write, and never wins a conflict on its own say-so —
the 2026-08-15 mass archive was a projection that had acquired store powers. A
stale-labeled core is marked ``parity.freshness.state = "stale"``, which is the
signal the launcher's existing stale-banner lane already reads
(``mission_control_snapshot.dart``: ``freshnessState == 'stale'`` →
``MissionSnapshotHealth.stale``), so a stale frame is never ``live`` and
therefore never authoritative. No write-lane predicate is reachable from
either field.

=============================================================================
A WRITE-BACK IS ONE UNIT (MCF-21)
=============================================================================

The cache is three files — the core, the sidecar that binds to its bytes, and
the stat set that makes a later miss diffable. They landed through three
independent ``os.replace`` calls: each atomic alone, the TRIO not. The property
"these three describe one build" was held up by two ad-hoc binding guards
(``core_sha256`` between core and sidecar, ``entries.fingerprint`` between
entries and sidecar) rather than by one rule, and a fourth file would have made
a third guard.

So the unit is now the GENERATION. Every write-back mints ``gen-<stamp>/`` under
:data:`CORE_CACHE_DIRNAME`, writes all three files into it while nothing points
at it, and lands by replacing ONE small pointer file naming it. Atomicity rides
that single replace. A crash or a disk failure at any earlier point leaves a
directory the pointer never named — invisible to every reader, reaped by the
next successful write-back.

Two consequences are worth stating where they can be read rather than derived:

* **The recorded target shape was not implementable and this is not it.** MC-3
  said "``os.replace`` the directory"; ``os.replace`` cannot replace a non-empty
  directory anywhere, and on Windows cannot replace a directory at all. The full
  argument, including why rename-away-then-rename-in is REFUSED, is at
  :func:`_live_generation_dir`.
* **The guards were re-aimed, not deleted.** A swap makes a TORN trio
  impossible. It does nothing about a tampered or hand-restored file inside a
  generation that is already published, which is what ``core_sha256`` convicts
  and what ``entries_unbound`` now convicts. Both stay, documented to their new
  reason. What DID retire is the partial-landing arm: a published pair with no
  entries file, and its ``entries=false reason=entries_io`` receipt, are
  unrepresentable and are gone from the table below.
```
