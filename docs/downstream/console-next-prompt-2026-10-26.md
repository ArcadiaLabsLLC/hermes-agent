# Console next-prompt implementation and qualification

Implemented in owned locked worktrees after the owner's 2026-10-26 go-ahead.
The canonical owners are documented in transport, lifecycle and chat canon;
the original design is retained in `../agent-runtime-harness/archive/console-next-prompt-2026-10-26.md`.
The Launcher counterpart is `docs/mission_control/evidence/console-next-prompt-2026-10-26.md`.

The feature remains false by default under Eternia Harness global settings.
Free-form contextual replies, the existing auxiliary facade/routing, and persona
ownership are retained. No live configuration or persona was changed during testing.

## Evidence

- `test_console_suggestions.py`: default/off zero-work, atomic partial CAS,
  invalid saved/unsubmitted tuning, route reset preserving unrelated task fields,
  durable deduplication, source/epoch/disable races, failure sanitization/dismissal,
  actual route/usage reporting, shared-observer recovery.
- `test_console_suggestions_native.py`: actual SessionDB, persona instance,
  native ownership, committed journal, pending clarification, expiry, exact-target
  JSON-RPC dispatch and malformed/stale settings requests.
- `test_console_suggestions_cold.py`: cold plugin manager registration; ambient
  persona override cleared; real PluginLlm and auxiliary routing through a controlled
  HTTP boundary (inherited custom/head-fixture → override aux-fixture → reset
  head-fixture), actual usage 13 fixture tokens per response; bundled MIT notice.
- `test_console_suggestions_scale.py`: 1,000 disabled roots produce no history/store/
  worker work; 64 subscribers retain two actual calls and at most 32 pending subjects
  through off/on; two processes compete for one durable claim; 1,000 completed roots
  retain 256 text payloads and receipts without repeat calls; a real 16-second delay
  completes without a feature-specific 15-second timeout.
- Positive control: the cold-scope test originally read persona-model instead of
  head-model when `scoped_runtime_main(None)` inherited the ambient override. It
  passes with the explicit empty override. This is a routing isolation proof, not
  merely a source spelling assertion.
- Cleanup positive cases retain Chinese/Japanese short replies, literal brackets,
  code expressions and `NULL handling`; exact sentinel/placeholder/oversize outputs
  are rejected. The prompt discourages invented results or approvals without
  converting all replies into questions.

All model responses in this qualification were controlled fixtures; external model
calls and billed cost were zero. The real facade test verifies routing and usage
plumbing, not model-generated quality. No fabrication-rate, false-rejection-rate,
real-provider latency or primary-turn performance claim follows from these fixtures.
Those measurements remain explicitly queued, including an idle-box comparison and
paired Developer/bundled, local/remote native UI acceptance. A clean structural test
run is not a substitute for those measurements.

## Gate receipts

Scoped routing/native/packaging tests passed. Fork-wide duplicate-name gate red is
pre-existing: `_row` in review_skill_pending/workspace_create and `_run` in
skills_pending_commands/generate_agent_runtime_response_fixtures; all four files
and its baseline are byte-identical to claim base ba542d8f. Tracked as
`FORK-NEXT-PROMPT-BASE-DUPLICATES`; no exemption was added.

Final landing counts and paired revisions are recorded at the end of this note.


## Landing reconciliation

The fork-scope runner selected 250 files: 3,215 passed, 15 failed, seven skipped.
This was not a green landing run. The branch-caused layer/ladder/helper-name and
partial-mixin failures were repaired: focused rerun 79 passed, one pre-existing
duplicate-helper failure. No new exemption was added. The real-facade, packaging,
native and 1,000-root tests passed in the broader run.

Canonical `--confirm-red` runs against 105174e2bc establish the CLI dump, stale
PersonaAssignmentStore tombstones, coverage-claim references, store-epoch pins and
JSON-root-observability failures as pre-existing. They are tracked together in
FORK-NEXT-PROMPT-BASE-CONTRACTS, separate from the duplicate-helper row.

The two registered-event emitter/retired-consumer assertions also fail on base 105174e2bc (`--confirm-red`: pre-existing). All remaining broad-run failures are either repaired feature regressions or verified base failures, not unexplained exemptions. Runtime implementation commits: c546882468 and 8dffb5cf04. The follow-up changes were checked with the explicit affected files; the entire broad suite was not rerun.

Paired Launcher implementation: 2082f311b4 plus dd0e80e109, rebased onto d4b799f634. Combined Harness goldens were regenerated after the rebase; the rebased codec/settings/draft/search run passed 29 tests. Runtime landed on main at 3021ee627f, and its primary checkout was fast-forwarded without touching the unrelated web build directory.

Final paired Launcher landing is 97f4f93b4f (implementation 2e75042f49 plus f17370d436), after a further docs-only main rebase. Its primary checkout is reconciled. The final optional-capability regression passed in the nine-test client file and failed under the deliberate route-before-capability mutation; the mutation was restored. All owned Dart analysis and the final provider/test analysis are clean. The earlier paired hashes above are historical pre-rebase receipts.

## Completion planning — 2026-10-27

[Completion plan](../agent-runtime-harness/planned/console-next-prompt-completion-2026-10-27.md) separates the remaining recommendations from this built
implementation record. The owner requested plans and rows only, with implementation
deferred. No new runtime, UI, live configuration or provider qualification is claimed.

Final plan audit, 2026-10-27: [completion plan](../agent-runtime-harness/planned/console-next-prompt-completion-2026-10-27.md) now separates stock
parity repairs from native adaptations and new Tab enhancement, limits Tab-only
restrictions, removes optional-framework qualification blockers, and records the
stock/Console auxiliary task-key distinction plus disable-in-flight semantics.
Documentation only; no code rollback, provider call or runtime setting change.

Clean-separation planning, 2026-10-27: [completion plan](../agent-runtime-harness/planned/console-next-prompt-completion-2026-10-27.md)
now requires reusable suggestions outside Agent Console, with Console as the
adapter to existing persona, history, auxiliary routing and draft authorities.
The plan names current seams, proposed homes, extraction order and boundary
acceptance; one implementation and the false-default Eternia Harness setting
remain mandatory. No DM implementation or runtime/code/settings change was made.

Final separation audit, 2026-10-27: [completion plan](../agent-runtime-harness/planned/console-next-prompt-completion-2026-10-27.md)
keeps extraction limited to the shared helpers/contract/presentation used by the
Console adapter. Clarified one eligibility predicate and existing state owners,
disabled versus absent capability, consumer-local disposal, adapter-owned errors,
unchanged free-form text and optional command gaps without an infrastructure mandate.
The existing lifecycle/store, persona and auxiliary authorities and false-default
Harness setting remain. No new rows, code, DM work or live configuration changes;
all nine completion rows retain the owner's implementation hold.


## Authorized completion implementation — 2026-10-27

The owner released the earlier hold. MOVE `2bcb797836` extracts shared generation;
subsequent CHANGE adds the latest-user-language reminder and narrow cleanup.
Console still binds `console_next_prompt` / `console_follow_up` through the existing
plugin facade. Shared code has no persona/history/settings dependency. No live
setting or persona file changed; the Harness false default and auxiliary route
remain the same.

Focused coverage includes the shared helper, Console scope/unload, actual facade
routing, native two-persona isolation, disabled work and stale publication. The
new helper file passed 15 tests; the corrected cold/facade file passed 3. Name
census and tombstone checks passed 35 tests. The broad fork landing run and its
follow-up classification are recorded below.

Red proof: removing `reminder` from the completion message list caused
`test_shared_generation_accepts_only_supplied_context_and_returns_actual_usage`
to fail (1 failed, 14 passed); restored. The cold facade expectation was updated
for the final system reminder after the unchanged user/assistant context.

The [fixed evaluation protocol](console-next-prompt-evaluation-2026-10-27.md) was
frozen before paid samples. Amelia's route preflight found expired authentication;
the owner is reconnecting the provider. Real quality/cost/latency and paired native
qualification are not marked passed by fixture tests.


The full fork gate ran once: 1,330 files, 15,101 passed, 34 failed, 1 error,
52 skipped, 512.7 s (12 workers). Two owned metadata failures were repaired:
shared package layer declaration and claim-account token formatting; their
explicit check passed 64 tests. The remaining failures were compared with the base,
not silently treated as green.

The existing `RT-CONSOLE-SUGGESTIONS-TEST-DOUBLES-RED` follow-up was claimed and
repaired at the shared `tests/agent_runtime/operator_lane_fixture.py::OperatorLane`
fixture: it now initializes the same optional suggestion-service field as a real
serve session, to None. All three importing files pass (49 tests). The broad run
had shown 19 failures across those files before this one-line repair; restoring
the missing field is the red/green proof, with no production fallback. The other
two files named by the row already passed the broad run (94 and 9 tests).

Canonical `--confirm-red` completed for the fourteen remaining failed files against
`6219b86283`. Ten reproduced their same failing nodes on both revisions; three
fixture-dependent files passed after the repair above, and the registered-event
emitter check passed alone after exceeding the broad-run time cap. Existing
runtime/CLI failures are recorded in `RT-WINDOWS-BASELINE-REGRESSIONS`; stale pins
and mutation anchors in `FH-BASELINE-PINS-AND-MUTATION-ANCHORS`. The PM slow-exit
environment requirement already has `FORK-SECOND-WORKSTATION-ENV`. These are
qualification exceptions, not suggestion passes or changes to the assertions.
