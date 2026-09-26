# Native Hermes qualification — work branch

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

Native Launcher smoke and final qualification are still pending. The
working branch is not a main landing, and these receipts are not live-provider
acceptance. Upstream Hermes ACP remains unchanged.
