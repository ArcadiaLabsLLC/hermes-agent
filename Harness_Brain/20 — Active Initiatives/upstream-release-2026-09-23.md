---
type: evidence
program: upstream-sync
status: validated-with-known-reds
tags: [program/upstream-sync, evidence]
---

# Release v2026.9.21 integration — 2026-09-23

Owner request: integrate the 148 release commits missing from the custom fork.
Original main: `923f734feb59005f5ee0cf14d5a6a9de8bfc7477`.
Release: `d337b736aa1e8ebecfab043842d13e4a2d2f48a3` (v0.21.4).
Merge: `b592010a65b731f0ed84e42667b848663f2ef249`.
Before: 95 fork commits ahead, 148 release commits behind. After merge: 96 ahead, 0 behind.

## Resolution and preservation

A real merge preserves both histories. The only conflict was checkpoint cleanup:
use upstream `utils.rmtree_readonly` and retire the equivalent fork helper.
`tools/checkpoint_manager.py` now matches the release. All 57 checkpoint-manager tests pass.
No fork tests were deleted. The two upstream deletions had no fork delta from the merge base.
The AST audit of 29 overlapping files found no lost fork-added definitions except the obsolete checkpoint helpers.
All 116 changed Python files parse. Fork dependency pins survive; package version advances to 0.21.4.
CLI contract check passes (202 paths, fingerprint prefix `d347e98255146d8c`); no Launcher fixture update.
No gateway restart or profile/config migration was performed as part of this integration.

## Validation on Windows

Canonical runner: Git Bash, shared Python 3.12 test venv, bounded runs.
`bash scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/cli tests/state`
completed all 1,815 files: **21,773 passed, 249 failed, 431 skipped**, exit 1, 5,267.8 seconds.
Five additional files reported no-tests-ran/collection or timeout errors; baseline runs reproduce these.
This is NOT a green suite. Failure comparison against original main classifies the 249 failures:

- **233** identical failed test IDs reproduce in detached original-main runs.
- **9** serve boot failures are the previously recorded worktree-name artifact. The exact merge in `hermes-release-proof` passes both complete files: **41 passed**, exit 0.
- **6** newly imported upstream Windows failures: three `test_container_boot.py` cases call unavailable `os.chown`; three `test_update_host_obligation.py` cases assume POSIX permissions/path spelling. Relevant upstream code/tests are unchanged by integration (service manager differs only by a fork comment).
- **1** sidebar-cache concurrency test is flaky: the isolated exact-merge file finishes **10 passed**, exit 0, after the runner's retry. Baseline file also passes; no test-source delta.

An additional socket disconnect flake passed the full runner's retry (72 tests); its first-attempt trace is outside the final 249 count. The stale-first routing timeout also passed bounded retry.
Four final gateway/webserver timeout retries remained red and reproduce on baseline.

Focused release/checkpoint/tooling run: **303 passed, 3 failed, 8 skipped**, exit 1.
All three failures reproduce on original main: late-tool turn-context refresh, stale shipped docket SHAs, and frozen-home gate on the two already-rowed upstream import-time names.
Original-main focused comparison: **34 passed, 3 failed**.
No unexplained deterministic integration regression was found; this does not establish Linux/runtime migration correctness.

## Evidence

Raw logs and test-ID comparison are preserved in the task output bundle `hermes-v0.21.4-validation.zip`.
It contains full/focused candidate logs, valid original-main comparison batches, serve/sidebar proof, and `failure-comparison.json`.
The accidentally mixed initial baseline batch1 log is excluded; its clean replacement is `release-baseline-selected.log`.
Known failures remain scoped to [[fork-hygiene-queue]]; this release sync does not repair unrelated suite debt.
