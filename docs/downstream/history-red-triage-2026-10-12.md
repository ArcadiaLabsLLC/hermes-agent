# Remaining history-qualification reds — triage, 12 October 2026

This is evidence and a repair disposition, not a second backlog. Work remains
in `Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md`. The completed
Console history feature stays closed. No production code, assertions, markers,
timeouts, retry policy or allowlists changed in the initial triage. Subsequent
repair and submission status is recorded per row below.

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
| H03 | Confirmed fast-worker event ordering race on fork baseline and current upstream. Commentary, deltas and tool events can land after EOS. | Repaired in fork carry `ce3609b4a8`; landing gate passes 13,269 tests without retry on Python 3.14.7. [Upstream PR #137460](https://github.com/NousResearch/hermes-agent/pull/137460) has 184 API passes and all 12 quality checks on the same supported interpreter. [Boundary and proof](stream-delivery-diagnosis-2026-10-12.md); upstream acceptance/CI approval is separate. |
| H04 | The PM slow-exit setup required Python 3.14 while the old shared test interpreter was 3.13.15. | **Qualified:** existing `pm.build_env` provisions a lane-owned 3.14.7 environment; the unchanged slow-exit file passes. No shared-interpreter change or relaxed requirement. The [carry evidence](stream-delivery-diagnosis-2026-10-12.md#fork-carry-qualification) records the reproducible environment and log. |
| H05 | The original source-grep red named four inherited assertions in `TestFullLogUploadLabels`. Correcting the integrated-base attribution in H02 cleared this gate (26 tests pass); the upstream source is unchanged. | P2 inherited test-quality candidate, not an outstanding fork gate failure. Behavioral label proof needs an owned test boundary and a useful coverage gap before implementation. Existing debug-share assertion row. |
| H06 | The original path-identity red named inherited Docker `_is_volatile_mount_spec` comparisons. Correcting H02 attribution cleared this gate (nine tests pass). Drive-letter hosts are explicitly excluded; no mount defect is established. | P2 contract qualification before proposing code: establish filesystem identity versus deliberate POSIX spelling with native mount fixtures. No fork gate repair or new exception is needed. Existing path-identity row. |
| H07 | Retired empty `tests/honcho_plugin` directory existed in the long-lived feature worktree. Fresh current-main checkout passes both layout tests. | Disposed as checkout residue, not a source regression. The old worktree was already retired. No source allowance or repair row is needed. |
| H08 | Native control proves the inherited basename assertion rejects `hermes.EXE`; the old broad Windows marker overstates the condition. | [Upstream PR #137478](https://github.com/NousResearch/hermes-agent/pull/137478) asserts exact resolved argv for three spellings. [Evidence](stream-delivery-diagnosis-2026-10-12.md#h08-cli-spelling-condition-still-exists) records the red, supported-runtime results and unrelated baseline timeout. Fork carry `256c151c76` removes only this marker and lands in the qualified shared-fixture batch alongside H11; upstream acceptance is still pending. |
| H09 | Native upstream reproduces Windows pytest termination from `os.kill(pid, SIGINT)` and the adjacent command-readiness failure. | **Closed for the reported Windows defect:** native `747f657234`, carried as `c3a4f0c3f1`, isolates the signal probe and owns the foreground PID through a ready receipt. Windows 8 passed / 2 POSIX skips; Linux 10 passed on candidate and base; 12 upstream checks pass. The fork gate ends at 12,646 passes with one retained socket-resource intermittent. Upstream PR creation was refused; no submission is claimed. Remaining MSYS and POSIX-fixture observations have separate rows. [Evidence](shutdown-test-repair-2026-10-13.md). |
| H10 | The compression rotation test leaked its ContextVar into the next file. | **Closed:** [PR #8](https://github.com/ArcadiaLabsLLC/hermes-agent/pull/8) merged as `b989d262e5`. Only that test body runs in a copied context through the existing fixture owner; production and upstream tests are unchanged. 59 pair passes without retry, 25 focused passes / 3 existing skips, four recorded killing boundary controls. H11 remains open. |
| H11 | Full original bundle reproduces all 19 failures: a later member imports backup during collection, freezing its native-home resolver before isolation. | Repair [4c440bbdd5](https://github.com/ArcadiaLabsLLC/hermes-agent/commit/4c440bbdd5) uses the existing CLI fixture seam. [Proof](backup-test-isolation-repair-2026-10-12.md): 204 clean first-attempt bundle passes, 69 adjacent passes, registration-removal control restores 19 reds. Lands in the qualified session-chain batch; the combined receipt records baseline failures and unresolved timing findings without claiming a clean upstream suite. |
| H12 | Retained neighborhood evidence exposes a process-wide `time.sleep` override in the native Codex retry fixture. Its removal reuses the existing retry-backoff owner; a behavioral regression fails when the override is restored. The old incident still cannot be attributed exclusively to it. | Native candidate `057b9339c0`: 70 tests and all 12 upstream checks pass. GitHub refused PR creation; no submission is claimed. The fork carry passes the integrated gate and lands in the combined batch. Separate metadata-network timeouts and setup-death attribution are filed with their existing owners. [Scope and receipts](stream-delivery-diagnosis-2026-10-12.md#h12-shared-sleep-override-removed-broader-qualification-remains-open). |
| H13 | Recurring diagnostic loss: `_bundle` drops first-attempt output when the retry passes; `Leak` lacks that output, `Death` lacks exit status/prefix/output, and `run` removes event scratch. Scope, backup and Codex death expose this same weakness. | Repaired through the existing run ledger and gate-store receipt: original diagnostics survive green retries and scratch cleanup. See [the repair evidence](test-safety-evidence-repair-2026-10-12.md). H11 has a qualified fixture repair; H12 has a scoped fixture repair while the wider interruption diagnosis remains open. |

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
by [the repair](test-safety-evidence-repair-2026-10-12.md). H03 has a qualified
fork carry and native upstream submission; H04 is
qualified on the supported interpreter. H08 and H11 land in the qualified
shared-fixture batch. Inherited test-quality reviews remain bounded candidates.
H01's stream intermittent still needs diagnosis.
H11 now has a reproduced cause and a qualified scoped repair.
H12 has a qualified native fixture repair and a landed fork carry. The
original incident and broader neighborhood remain open: the retained output
also exposes live model-catalog reads and incorrect setup-death attribution.
Neither is hidden by the integrated gate's clean result.

The initial triage did not rerun a full suite or change the test installation.
The later H03 carry ran the fork landing gate and built an isolated supported
PM environment, as recorded above. The H08/H11 shared-fixture batch traversed
the complete reached tree on a disposable Windows Actions runner; completed
scoped comparisons reproduce all 159 final candidate failure/error IDs. Two
first-attempt timing failures remain queued with unchanged-code and fixture-scope
evidence. The [combined receipt](stream-delivery-diagnosis-2026-10-12.md#combined-candidate-qualification--2026-10-13)
records the incomplete broad runs and the qualification limits. No whole-tree
run was started on the workstation, and the standing exclusions remain in force. The agent changed no TLS interception
settings or operator stores; the operator-reported setting change is qualified
above. Launcher dispositions live in
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
baseline matches. The initial triage commit contained documentation and queue updates only.
