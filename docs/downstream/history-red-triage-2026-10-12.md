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
| H01 | The operator reported disabling antivirus HTTPS scanning. All ten files now pass across the controls below: 96 distinct passes, one existing skip. The eight-worker attempt also exposed a turn-start delivery failure that passes serially; its cause is unresolved. | Certificate-blocked qualification cleared on this host with pins and permissions unchanged. The existing row now owns the remaining running-turn stream intermittent; a serial pass does not retire it. No whole-repository green claim. |
| H02 | The twelve-call gate red was reproduced, but the repair audit corrected its attribution: the clone's `upstream/main` was July's `ac0cfa7db9`, while the integrated manifest base was October's `818c13be1d`. All twelve calls are inherited; the existing collection hook scopes their undo to body patches. The structural red did not prove a sandbox escape. | Repair the shared attribution helper to consume the footprint's validated release base. Prove fork-added lines still fail and the existing scoped-undo hook preserves fixture pins. See [the repair evidence](test-safety-evidence-repair-2026-10-12.md). No upstream-test rewrite or allowance. |
| H03 | Confirmed fast-worker event ordering race on fork baseline and current upstream. Commentary, deltas and tool events can land after EOS. | [Deterministic diagnosis and tested upstream candidate](stream-delivery-diagnosis-2026-10-12.md): 184 distinct passes, 12 quality checks. Coordinate with upstream PR #89748 before another submission; candidate is not on fork main. |
| H04 | PM slow-exit test errors before the worker starts: the staged runtime requires `==3.14.*`, but the selected interpreter is 3.13.15. Exact error also exists on unchanged main. | P2 environment. Provision a lane-owned supported test environment through the existing PM/bootstrap owner, then run this one file. Do not mutate the shared interpreter during other runs or relax the plugin requirement. Existing PM environment row. |
| H05 | The original source-grep red named four inherited assertions in `TestFullLogUploadLabels`. Correcting the integrated-base attribution in H02 cleared this gate (26 tests pass); the upstream source is unchanged. | P2 inherited test-quality candidate, not an outstanding fork gate failure. Behavioral label proof needs an owned test boundary and a useful coverage gap before implementation. Existing debug-share assertion row. |
| H06 | The original path-identity red named inherited Docker `_is_volatile_mount_spec` comparisons. Correcting H02 attribution cleared this gate (nine tests pass). Drive-letter hosts are explicitly excluded; no mount defect is established. | P2 contract qualification before proposing code: establish filesystem identity versus deliberate POSIX spelling with native mount fixtures. No fork gate repair or new exception is needed. Existing path-identity row. |
| H07 | Retired empty `tests/honcho_plugin` directory existed in the long-lived feature worktree. Fresh current-main checkout passes both layout tests. | Disposed as checkout residue, not a source regression. The old worktree was already retired. No source allowance or repair row is needed. |
| H08 | Bot relay delivery remains strict XPASS on current main: the marked scenario succeeds; 21 other tests pass and one separate scenario remains xfailed. | P2 marker retirement. Verify this exact node without its marker and against the original inherited condition; retire only the stale row in `upstream_reds_v0216.py`. Existing bot-relay row. Do not remove the other xfail. |
| H09 | `test_serve_exit_flush.py` dies in a bundle and alone, with no completed test assertion; it is already recorded in the timeout class. | P2 bounded process investigation. Preserve process exit/timeout diagnostics and isolate this file under the existing runner. Do not infer an assertion failure from an empty summary or rerun the full suite. Existing timeout-class row retains ownership. |
| H10 | The compression rotation test leaked its ContextVar into the next file. | **Closed:** [PR #8](https://github.com/ArcadiaLabsLLC/hermes-agent/pull/8) merged as `b989d262e5`. Only that test body runs in a copied context through the existing fixture owner; production and upstream tests are unchanged. 59 pair passes without retry, 25 focused passes / 3 existing skips, four recorded killing boundary controls. H11 remains open. |
| H11 | Backup reports 19 first-attempt failures in the final gate, then passes alone. Prior exact three-file-prefix control passed on unchanged main; current isolated file passes 82 tests, with ten skips and two xfails. Cause and baseline equivalence remain unproven. | P2 unresolved intermittent. Retain original first-attempt diagnostics through H13, then reproduce the recorded three-member prefix. Do not hide it by listing the file as unbundled without diagnosis. Existing scope/backup row. |
| H12 | Codex Responses process died in bundle 9 and passed alone; current isolated file passes all 69 tests. Original exit details are absent from the retained report. Cause and baseline equivalence remain unproven. | P2 unresolved process failure. H13 first, then exact ordered-bundle reproduction with exit diagnostics. No claim of timeout, resource exhaustion or a history regression is justified yet. Existing Codex Responses row. |
| H13 | Recurring diagnostic loss: `_bundle` drops first-attempt output when the retry passes; `Leak` lacks that output, `Death` lacks exit status/prefix/output, and `run` removes event scratch. Scope, backup and Codex death expose this same weakness. | Repaired through the existing run ledger and gate-store receipt: original diagnostics survive green retries and scratch cleanup. See [the repair evidence](test-safety-evidence-repair-2026-10-12.md). H11/H12 remain investigations; retaining evidence does not diagnose their cause. |

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

### HTTPS scanning control after the operator's setting change

Source was `f6c27f4d0b` (runtime bytes unchanged from the prior qualification).
The operator reported disabling HTTPS scanning; the agent changed no antivirus,
TLS, permission or test settings in source. The ten H01 files in the existing
JSON inventory were named explicitly through `scripts/run_tests.sh`:

- Eight workers, `--file-timeout 120 --file-retries 0`: 86 passed, one failed,
  one skipped, plus one file timeout; exit 1, 242.1 seconds. Eight files passed
  completely. The two-roots file completed six tests before the too-short
  command-level cap and seven on the runner's automatic isolated retry.
- Serial control of `test_gateway_peer_two_roots_e2e.py` and
  `test_serve_gateway_chat_reply_lanes.py`, `-j 1 --file-timeout 600
  --file-retries 0`: all 11 passed, exit 0, 189.6 seconds. Two roots took 161.4
  seconds, longer than the initial command allowed. Its existing per-test
  allowance is 600 seconds; no test deadline was edited.

Together the successful file runs cover 96 distinct tests and one existing
skip. This clears the certificate blocker for these ten files, not the first
attempt's stream failure: `test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane`
waited six seconds for its start frame under parallel load and passed serially.
Do not label that as TLS, claim a proven product race, or increase its deadline
without tracing the event path. It is separate from H03's Session API commentary.

Retained logs (SHA-256):

| Log | Digest |
|---|---|
| `h01-https-scanning-off.log` | `3bfafde95b01c567ed70372ef17cfd04299a2d2d90629929737293705dc07902` |
| `h01-https-idle-control.log` | `a1e1d3cf9af95a80a386f23a3b10f9c731d4860d1c1d4d5a523e4a62e69c6ff1` |

## Scope and next work

H02 attribution/isolation qualification and H13 diagnostic retention are closed
by [the repair](test-safety-evidence-repair-2026-10-12.md). H03 event delivery,
the stale marker and inherited test-quality reviews
remain separate bounded work. H01's stream intermittent needs diagnosis; H04
still needs the correct execution environment.
H11/H12 can now be investigated with retained first-attempt evidence.

No full suite was rerun. The workstation-freeze files were not selected. The agent changed no TLS
interception settings, test installation or operator stores; the later
operator-reported HTTPS-scanning change is qualified above. Launcher dispositions live in
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
