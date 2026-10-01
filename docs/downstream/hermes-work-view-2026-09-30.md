# Hermes-backed Work view

Owner-approved slice: authenticated task observations and submission through the
Eternia harness. Native Kanban remains the only task store and dispatcher.
`agent_runtime/work/native.py` uses two public native task APIs; neither the
Companion engine nor its daemon is imported. Phone bundles omit this capability.

The contract is [Native Work methods](../agent-runtime-harness/03-transport-and-wire.md#native-work-methods).
Launcher presentation and its source-parity receipts are recorded in
`EterniaLauncher/docs/companion/planned/HERMES_WORK_VIEW_2026-09-30.md`.

## Guarantees and limits

Installation, board, profile and resolved storage identity qualify every task.
Authorization runs inside the service as well as the console-private RPC tier.
Submission replay is serialized in the native database, includes archived tasks,
and refuses changed payloads. Deleting the native task removes replay evidence.
Read-only requests do not create an absent database. Unknown native statuses stay
unknown. Responses bound task pages and text; the public native list API currently
materializes matching rows before keyset slicing.

The native dispatcher must already be running to execute queued work. This slice
does not auto-start it, expose Stop/redirect/retry, or create another scheduler.

## Validation

- Native/RPC scope, replay, concurrent submission, pagination and projection tests,
  import-layer checks, the narrow native-import fence and generated RPC manifest
  checks: **153 passed** after repairs. Ruff F checks pass.
- Full canonical suite: **2,176 files; 24,703 passed, 42 failed, 734 skipped**.
  Seven failures were the old blanket native-import fence and stale generated RPC
  manifest; both were repaired and their files passed in the 153-test run.
- Remaining 35 failed assertions: **31 reproduce on clean primary** `a6001fb44e`.
  Four differ by checkout: two fleet identity assertions see the shared interpreter
  as external; two updater probes redirect to that interpreter's primary checkout
  before reaching their mocked hook. Those source files are unchanged by Work.
  Primary also reports two additional live-process holder assertions. All 14
  collection/teardown failure files reproduce on primary.
- Tooling initially found the missing package layer declaration (fixed), plus two
  existing discussion ladder failures (also reproduced on primary). Citation
  adjacency retains its already-queued Toolsets citation failure. No waiver added.

Positive controls, restored before validation:

1. Replacing service authorization with `if False` makes
   `test_private_service_refuses_unknown_caller_and_scopes_request_keys` fail:
   `DID NOT RAISE WorkRefused`.
2. A disposable tree with the two permitted native imports passes the boundary
   gate; placing `from hermes_cli import kanban_db` in `work/service.py` fails it.
3. Launcher's removal of `await store.save(intent)` fails its persistence-failure
   test: expected no calls, received a `WorkStartRequest`.

Local logs are retained under ignored `qa-artifacts/hermes-work-view/`.
