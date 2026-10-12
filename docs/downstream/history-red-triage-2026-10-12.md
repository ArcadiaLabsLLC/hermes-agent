# Remaining history-qualification reds — triage, 12 October 2026

This is evidence and a repair disposition, not a second backlog. Work remains
in `Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md`. The completed
Console history feature stays closed. No production code, assertions, markers,
timeouts, retry policy or allowlists changed; no upstream submission was made.

## Pins and accounting

Fetched main was `5856b5d4763e7ac024856b24dacd1f43287cd60f`. Triage used a fresh
checkout at `dd95b3cf16` (only the triage claim differs). Subsequent queue commits
do not change source. Python is 3.13.15; runs use the canonical wrappers.

The final feature gate at `292a429351` recorded 19,064 passed, 74 failed,
one setup error and 233 skipped. Its **75 distinct final failure/error nodes**
are in the [node inventory](history-red-triage-2026-10-12.json), with source-log
hashes. Exactly 73 match `history-runtime-current-main-baseline.log` node for
node. The remaining two are H03 and H07 below. Process deaths and recovered
bundle failures are additional evidence, not included in that 75-node count.

P1 means address before the affected safety/release qualification; P2 means a
bounded correctness or verification repair. These are triage priorities, not
claims of a production incident. Baseline reproduction proves age, not cause.

## Dispositions

| ID | Evidence and classification | Priority and next bounded action |
|---|---|---|
| H01 | 68 nodes in ten gateway/TLS files; identical in the untouched-main control. Prior real loopback evidence received a Norton-issued replacement certificate. Local interception is proven; attribution of every node is not. | P1 for paired-device qualification. Use an approved clean host or narrowly excluded test endpoint, then run the same ten files. Preserve pins, permissions and certificate validation. Existing TLS/peer row owns it; do not disable host protection as a test shortcut. |
| H02 | Shared-monkeypatch gate still reports twelve calls in seven inherited test files. Current focused run reproduces exactly the prior violation list. `undo()` unwinds shared environment and sandbox patches, not only the test's stub. This is a test-isolation safety defect; no new live-store damage was observed here. | P1 before broad reruns of those tests. Replace whole-fixture unwinding at the correct test boundary with scoped patch lifetimes, preserving the real-root guards. All seven files are in the upstream manifest: respect that ownership and record any seam; do not widen the gate allowance. Existing shared-monkeypatch row. |
| H03 | Session API commentary test intermittently loses `assistant.commentary`; independently reproduced on pre-feature main `50a9165fc2`. Current isolated file passes 39 tests. A later pass does not diagnose or retire the first failure. | P1 investigation for event-delivery correctness. Instrument the existing `_SessionEventQueue` / worker-completion boundary and retain event order through terminal delivery; establish whether delivery or the fixture loses the event before changing code. Existing Session API row. |
| H04 | PM slow-exit test errors before the worker starts: the staged runtime requires `==3.14.*`, but the selected interpreter is 3.13.15. Exact error also exists on unchanged main. | P2 environment. Provision a lane-owned supported test environment through the existing PM/bootstrap owner, then run this one file. Do not mutate the shared interpreter during other runs or relax the plugin requirement. Existing PM environment row. |
| H05 | Source-grep gate reproduces four positive source assertions in upstream `TestFullLogUploadLabels`; it is one failing gate node, not four runtime bugs. | P2 test quality. Prove the emitted labels behaviorally at the owned test boundary; preserve the no-new-debt gate. Existing debug-share assertion row. |
| H06 | Path-identity gate reproduces raw equality/prefix comparisons in upstream Docker `_is_volatile_mount_spec`. The function explicitly excludes drive-letter hosts; the gate red alone does not prove a Windows restore or mount defect. | P2 contract qualification. Establish whether this is filesystem identity or deliberate POSIX spelling using native mount fixtures, then use the existing path owner or justify the narrow literal exception. Existing path-identity row; no exemption added. |
| H07 | Retired empty `tests/honcho_plugin` directory existed in the long-lived feature worktree. Fresh current-main checkout passes both layout tests. | Disposed as checkout residue, not a source regression. The old worktree was already retired. No source allowance or repair row is needed. |
| H08 | Bot relay delivery remains strict XPASS on current main: the marked scenario succeeds; 21 other tests pass and one separate scenario remains xfailed. | P2 marker retirement. Verify this exact node without its marker and against the original inherited condition; retire only the stale row in `upstream_reds_v0216.py`. Existing bot-relay row. Do not remove the other xfail. |
| H09 | `test_serve_exit_flush.py` dies in a bundle and alone, with no completed test assertion; it is already recorded in the timeout class. | P2 bounded process investigation. Preserve process exit/timeout diagnostics and isolate this file under the existing runner. Do not infer an assertion failure from an empty summary or rerun the full suite. Existing timeout-class row retains ownership. |
| H10 | Declared-scope failure is now reduced from fourteen preceding files to the single compression-worker file. Removing only its context-rebinding test makes the pair pass. See the controlled reduction below. | P2 test-context isolation. Restore the original test ContextVar state or run that scenario in its own copied context. Preserve production `clear_session_vars` semantics and the environment-override assertion. Existing scope/backup qualification row. |
| H11 | Backup reports 19 first-attempt failures in the final gate, then passes alone. Prior exact three-file-prefix control passed on unchanged main; current isolated file passes 82 tests, with ten skips and two xfails. Cause and baseline equivalence remain unproven. | P2 unresolved intermittent. Retain original first-attempt diagnostics through H13, then reproduce the recorded three-member prefix. Do not hide it by listing the file as unbundled without diagnosis. Existing scope/backup row. |
| H12 | Codex Responses process died in bundle 9 and passed alone; current isolated file passes all 69 tests. Original exit details are absent from the retained report. Cause and baseline equivalence remain unproven. | P2 unresolved process failure. H13 first, then exact ordered-bundle reproduction with exit diagnostics. No claim of timeout, resource exhaustion or a history regression is justified yet. Existing Codex Responses row. |
| H13 | Recurring diagnostic loss: `_bundle` drops first-attempt output when the retry passes; `Leak` lacks that output, `Death` lacks exit status/prefix/output, and `run` removes event scratch. Scope, backup and Codex death expose this same weakness. | P2 prerequisite for H11/H12. Extend the existing runner/receipt owner to retain bounded, redacted original output, exit status and ordered members separately from retry outcomes. One new class row was filed on arrival; no parallel runner or blanket retry was introduced. |

## Current-main controls

`scripts/run_tests.sh -j 2 --file-timeout 120 --file-retries 0` named exactly:

```text
tests/agent_runtime/test_no_midtest_monkeypatch_undo.py
tests/test_no_source_grep_assertions.py
tests/test_path_identity_gate.py
tests/test_tests_tree_layout_downstream.py
tests/tui_gateway/test_bot_relay_methods.py
tests/gateway/test_session_api.py
tests/agent/test_declared_conversation_scope.py
tests/hermes_cli/test_backup.py
tests/agent/test_run_agent_codex_responses.py
```

Result: **323 passed, four failed, ten skipped**, exit 1, 68.7 seconds. The four
reds are H02/H05/H06/H08. They match the original nodes; no assertion changed.
The four currently passing intermittent files are not declared fixed.

### Controlled scope reduction

Both calls used `scripts/run_tests_bundled.sh --no-cache --bundle-size 20
--bundle-seconds 0 --solo-seconds 0 --file-timeout 120 --file-retries 0 -j 1`
with `tests/agent/test_compression_worker_isolation.py` followed by
`tests/agent/test_declared_conversation_scope.py` (one shared process).

1. Pair unchanged: declared-scope reports **54 passed / one failed**, then
   passes alone. Final runner summary is 59 passed, exit 0, **with one explicit
   isolation leak**. That final zero is not a clean first attempt.
2. Same pair with only `-k 'not test_f5_session_contextvar_rebound_after_rotation'`:
   **58 passed, no rerun and no leak**, exit 0. This is a diagnostic control,
   not an exclusion committed to the suite.

The compression test binds session variables then calls `clear_session_vars`.
That production function deliberately clears them to empty strings rather than
restoring the original `_UNSET` value. Empty session context masks the next
test's `monkeypatch.setenv('HERMES_SESSION_SOURCE', 'override-src')`; the source
resolver reads the task-local context before environment fallback. The pair
reproduction plus single-test exclusion identifies the test-context boundary;
it does not justify changing production session-clearing behavior.

## Scope and next work

Prioritize H02 safety, H13 diagnostic retention and H03 event delivery. Then
repair the identified context leak, stale marker and gate-quality findings in
bounded ownership-aware changes. H01/H04 need the correct execution environment;
H11/H12 remain investigations until their first-attempt evidence survives.

No full suite was rerun. The workstation-freeze files were not selected. TLS
interception settings, test installation and the operator's stores were not
changed. Launcher dispositions live in
`EterniaLauncher/docs/mission_control/evidence/history-red-triage-2026-10-12.md`.
The earlier feature qualification and native acceptance remain valid within
their stated limits; this report does not certify a green whole repository.

Upstream preparation remains a separate step: native-user benefit, maintainer
demand and overlapping work must be checked. The restore extraction and busy
errors are held candidates; retention pins remain coupled to resumable restore.
These triage classifications do not authorize or qualify an upstream PR.

Documentation validation: the canonical citation gate
(`scripts/doc_cite_adjacency.py --exclude archive --exclude planned`) passes.
The inventory was checked against the saved logs: 75 unique nodes, 73 exact
baseline matches. Staged changes contain documentation and queue updates only.
