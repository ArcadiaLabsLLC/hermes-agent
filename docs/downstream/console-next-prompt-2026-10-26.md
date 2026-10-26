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
