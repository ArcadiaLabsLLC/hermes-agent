# Native Hermes qualification

**Qualification correction:** [lifecycle/reuse audit](native-hermes-lifecycle-audit-2026-09-26.md)
reproduces recovery, unknown Stop and replay gaps. The tests below establish their
recorded scenarios, not complete restart parity or native execution-fenced Stop.

Owner scope: full native Launcher Chat/Compare and non-spatial Discuss; preserve
Mission Control's operator lane. Consumer contract and full receipt table:
`EterniaLauncher/docs/companion/planned/NATIVE_HERMES_QUALIFICATION_2026-09-26.md`.

## Evidence

Sixteen new tests passed before broad qualification: native session/profile/account
isolation, durable dispatch, Stop, restart uncertainty, questions, model scope,
drain, bounded event projection, real worker boot and full skill detail. Real
native A → B → A execution used a loopback HTTP provider stub, separate credentials
and canonical SessionDB histories. No real profiles, credentials or paid calls.
Fifty-nine existing discussion/authorization/drain tests also passed.

The production discussion fixture now includes a non-spatial room. Its two
members use separate auxiliary sessions and the same executor/claims as office
tables; the schema-one upgrade preserves pre-existing runs and claims.

## Recorded mutation controls

Run through `scripts/run_tests.sh <named files> -j 2 -q --file-timeout 150`.
Each mutation below exited 1; restored subjects passed (12 tests across native
conversation, native discussion and generated-wire files).

- `test_native_conversation.py::test_exact_account_profile_home_and_independent_sessions`:
  remove the route-owner comparison in `ConversationStore.get`; wrong actor
  returned data, `DID NOT RAISE ConversationError`.
- `test_native_conversation.py::test_dispatch_is_durable_and_replay_never_resubmits`:
  change `if admitted` to `if True` in `ConversationService.send`; second submit
  hit the durability assertion, `running != dispatching`.
- `test_native_conversation.py::test_stop_during_admission_waits_for_exact_native_terminal`:
  settle STOPPED immediately after `live.stop`; `stopped != dispatching` before
  native acknowledgement. The valid case ignores a foreign terminal and waits
  for the exact session's interrupted completion.
- `test_native_discussion_room.py::test_schema_one_upgrade_preserves_every_run_and_claim`:
  omit the old-row INSERT/SELECT in `initialize_runs`; the assertion returned
  `None != ('old', 'ws', 'table', …)`.

The full validated suite ran: 23,082 passed, 183 failed and 668 skipped, plus
collection/teardown errors. Baseline comparison remains in progress; this is
not a green broad suite. Focused conversation/discussion qualification passed.
After splitting definition/run RPC handlers, 28 duplicate-helper, import-layer,
legibility and dispatch-ladder checks pass with smaller exception baselines.
Definition read/delete/revision and shutdown tests pass. Bypassing the shutdown
guard makes the regression fail with `DID NOT RAISE DiscussionError`; the
restored test passes.

Native Launcher smoke completed on Launcher `b07e9b4311` and Hermes `9ee2da7bfc`:
Direct, Compare, non-spatial Discuss, full skill details, hide-and-continue,
confirmed Stop and a separate Mission Control operator turn. Both operator root
pointers stayed unchanged. Exact receipts are in the consumer note above.
The moved canonical skill-reader import was repaired after rebase; 23 native
tests passed. Probe output/fields/quiet coverage passed 63 tests. Final tooling
passed 45 tests (size, imports, namespace, duplicates, legibility, routing and
payload contract). These receipts are not live-provider acceptance.

## Repository findings outside this integration

The baseline comparison used unchanged `613a04abdd`; completed comparisons
reproduced many failures there. The remaining batch finished with 1,550 passed,
74 failed, 15 skipped. Not every original failure has been classified.

Nine files passed the primary checkout but failed with the borrowed interpreter.
A worktree-local virtual environment fixed seven updater/environment files.
The probe's output-flag failure was ours and is fixed in `9ee2da7bfc`.
Two `test_fleet_matrix_down_state.py` assertions still classify the fixture process
as external rather than current. Their production/test inputs are unchanged;
the dependency-sharing environment remains a hypothesis, not a proven cause.

The doc-cite gate reports seven unwaived citations and one stale waiver: model
persona, canonical skills, shipped patches, compaction, persona toolsets,
office surface coverage and boot timeline. Re-anchor symbols; do not expand the
waiver baseline. Frozen-home checks also fail on unchanged primary for
`gateway/mirror.py::_SESSIONS_INDEX_AT_IMPORT` and
`tui_gateway/server.py::_HERMES_HOME_AT_IMPORT`.
Existing tombstone findings remain queued separately.

The changed-line mutation runner selected two existing claims, but refused to
mutate because `test_console_device_can_configure_only_the_served_host` fails
its baseline with `ServeCertificatePinMismatch`. The exact test also fails on
unchanged primary `613a04abdd`. Neither selected mutation is claimed killed;
the native integration's separately recorded controls above did run and kill.

Raw receipts: `native-suite.log`, `native-baseline.log`, `native-baseline-rest.log`,
`native-localvenv-recheck.log`, `native-doc-cite.log`, `native-mutation-final.log`
and `native-mutation-baseline.log`. No real credentials were used.

## Code shape

New conversation capability: 18 files, 91 functions, maximum 210 raw lines/file,
34 lines/function and nesting 4 (AST census using the repository's unit/depth
instrument). Discussion RPC: 111 → 76 lines; run storage: 342 → 210. Helpers and
wire codecs have focused owners. No size, import or routing ceiling was raised.
The CLI dump is fresh: 204 command paths, digest prefix `341a08107d3438d2`.
