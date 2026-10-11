# Console history follow-up verification — 2026-10-11

Read-only product audit of PR #7 at `8cbb135f15b0812c75d772838c31b873974c90dd`,
paired with Launcher PR #55 at `0e9fcd0b448d26ce1f31f67bb4df85749e4933fa`.
No runtime repair was applied. Counterexamples below use disposable files/stores;
they are diagnostic probes, not a full fork-suite or native UI qualification.

## H1 — checkpoint contention leaves an unnecessary Undo fence

`agent_runtime/operator_undo.py::apply_operator_undo` saves `prepared` and fences
sends before calling `CheckpointManager.restore_preview`. Its broad exception
handler converts `CheckpointStoreBusy` into durable `partial` with
`file_result_unconfirmed`. `tools/checkpoint_pruning.py::store_lock` defaults to
zero wait. The standalone restore path in `operator_checkpoints.py` specifically
clears a newly-created fence on this pre-write refusal.

Reproduced using the real Undo RPC, SQLite and Git snapshot fixture in a temporary
home/workspace. A wrapper acquired the real checkpoint store lock immediately
before the original restore-preview call, reproducing another writer winning
after the operation's preview and before restore acquisition. Output:

```text
state=partial reason=file_result_unconfirmed
file_unchanged=true chat_rows=4 pending.action=undo
explicit rollback recovery: state=rolled_back
```

This is an avoidable blocked-chat state, not necessarily permanent. If the store
is already busy during the earlier preview, admission can refuse before creating
this record. Fix the post-preview acquisition window without clearing a fence
that belongs to an earlier partial write. Add a contention-positive control.

The first direct probe omitted the test environment's lazy-install guard and
entered optional dependency setup; it was interrupted after certificate failures.
The successful probe used `HERMES_DISABLE_LAZY_INSTALLS=1`, matching tests/conftest.
That interrupted attempt supplies no correctness evidence.

## H2 — upstream checkpoint behavior changed

Compared with the PR's main merge base, `ensure_checkpoint` moves
`_checkpointed_dirs.add` after `_take` and only records successful takes. Native
Git probe: after a prior checkpoint, `new_turn`, unchanged ensure, write, ensure:

```text
unchanged_attempt=false cached_after_unchanged=false
snapshot_after_first_write=true
```

This changes per-turn deduplication/baseline timing. It still permits at most one
successful snapshot; describing it simply as "more than one snapshot" would be
wrong. Native `_take` still notifies the observer of the existing baseline on an
unchanged tree, so this probe alone does not prove the new turn-attribution
recorder loses its first baseline. Preserve or explicitly justify native semantics
and test existing checkpoint consumers as well as the new observer.

`record_agent_write` now records a missing file as `{sha256: None, deleted: true}`.
Native `_safe_restore_plan` treats a None hash as unowned and skips it. Reproduced
with a checkpoint, an authored write, deletion and a second write-ledger call:

```text
before_deletion_ledger: restore=[file.txt], skipped=[]
after_deletion_ledger: restore=[], skipped=[file.txt]
```

Thus recording deletion overwrites evidence the existing safe restore previously
accepted. This is a real compatibility defect, even though the new reviewed
restore path understands deletion separately. The current upstream-footprint
ledger calls this a held native API expansion; it does not literally say
"additive" on its checkpoint-manager row. The behavioral delta still needs a
specific disposition and proof, not an API-only description.

## H3 — mutation evidence is not recorded as required

CLAUDE's weakness rule requires a named killing mutation and its red in the
commit body. `b920ba2b1b65f8f09ad8a9c846ffc01d34d8abeb`, titled "Record race
killing controls and unchanged-main gate comparisons", has an empty body.
The committed qualification document describes the mutations and names local
`revision-pin-red.log` / `recovery-revision-red.log`; it does not contain the raw
failure excerpt. The tests and claims exist; that is not evidence that the reds
were fabricated, but it does not satisfy the prescribed recorded-proof format.
Record reproducible failure excerpts tied to exact mutations in a new commit;
do not rewrite shared history to repair the old message.

## H4 — Undo state transitions have multiple string writers

`agent_runtime/operator_undo.py` writes `prepared`, `partial`, `completed` and
`rolled_back` directly from apply, finish, reconcile and recovery. There are ten
state-writing statements counting initial construction and conditional writes,
not exactly eight. The structural concern is valid: use a typed state plus one
transition/validation owner, keeping the durable coordinator and native file/chat
owners rather than introducing a second state machine.

## Cross-repository identity blocker

`profile_persona_discovery.reconcile_profile_personas` mints `profile_<name>`;
`instance_catalog._project` retains it. The history producer `_history_row`
canonicalizes to `profile:<name>`. Branch apply/status/replay and origin reuse it.
Real producer output for `profile_audit` was `profile:audit`; Launcher's real
codec rejected the result. The Launcher owns the queued consumer repair.
Cancellation cannot discard an applied branch: `cancel_unapplied_history`
returns false when the native history receipt exists. Preserve that safeguard.

The producer module registers 16 history-related methods, matching the adapter's
16 call names. That inventory is narrower than a proof of all wire semantics.
Do not call the contract clean while its persona identity representation differs.

Repair H1 and H2 before landing. Then consolidate H4 and record H3's missing
proof with actual race tests. Preserve the existing native stores and lock owners.

## Architecture and upstream-value follow-up

The subsequent main fetch was `a29548b814`; PR #7 still at `8cbb135f15` lacks
269 main-side commits. Eight paths changed on both sides, including chat_turn,
history curation, profile execution/runner and RPC registration. Main adds native
retry lineage and queue-origin handling; integration must retain them. Fetching
main is not the same as integrating it into the feature. Launcher has its own
larger main delta and must be qualified with this combined runtime.

### Reused versus new behavior

- Rewind calls the existing `SessionDB.rewind_user_turn` authority, with optional
  revision and receipt parameters; no second transcript database was introduced.
- Snapshots, diffs and file restoration remain in the native CheckpointManager
  store. The added turn recorder holds attribution, not a second file snapshot.
- Existing API/CLI fork copies the full history and ends/switches away from the
  source. `SessionHistoryControlsMixin.branch_before_message` selects a precise
  prefix, leaves the source open, checks revision/leases and commits the child plus
  receipt atomically through SessionDB, reusing native `_clone_message_rows`.
  Therefore directly calling the existing API fork is not equivalent behavior.
- Combined chat/files Undo needs coordination: filesystem and SQLite do not form
  one atomic transaction. Durable progress, backup retention and explicit recovery
  have a real purpose. A separate generic workflow engine does not.

### H5 — duplicated restore-write mechanics

Although there is one checkpoint store, `CheckpointManager.restore_preview` and
`resume_restore` separately perform checkout/deletion, ledger update and per-file
receipt writes. Their verification behavior differs: recovery checks the target
blob after a write; initial apply does not use the same step. This is a concrete
maintenance/drift risk, not proof of an additional reproduced corruption.

Consolidate the new paths' common checked file-write and receipt primitive inside
the existing native owner. Keep the reviewed-operation coordinator separate from
the actual file writer. Preserve existing safe-restore semantics and the legacy
CLI behavior; do not turn this into a broad fork refactor or build another manager.
H4 still owns the separate coordinator state-transition cleanup.

### Potential upstream contribution, not submitted work

Generic candidates useful beyond Eternia: revision-pinned transactional prefix
branching, optional atomic operation receipts for rewind, reviewed selected-file
restore with crash recovery and backup retention, and a narrow checkpoint observer
for turn attribution. They should be independently tested and product-neutral
before proposing them upstream. Retain upstream's existing behavior by default.

Persona/install authorization, Mission Control RPC bindings, operator-specific
turn mapping and Launcher presentation stay fork/app responsibilities. These are
consumers of native APIs, not good reasons to put Eternia policy in upstream.
The held ledger entries are candidates; this review does not claim an upstream
PR was opened or accepted. Repair correctness and split a minimal coherent native
API contribution before considering submission. No upstream publication was done.
