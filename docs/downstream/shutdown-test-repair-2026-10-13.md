# Windows shutdown-test repair — 2026-10-13

## Scope and native benefit

H09 is an inherited test defect. On native upstream `8f817911723e`,
`test_ignored_sigint_leaves_terminal_commands_runnable` terminates pytest before
it can report a result. Windows interprets `os.kill(pid, SIGINT)` as
`TerminateProcess`, not delivery to the installed Python signal handler.
See [Python's signal contract](https://docs.python.org/3/library/os.html#os.kill).

The repair is native commit `747f657234`, carried as `c3a4f0c3f1`:

- Deliver SIGINT using `signal.raise_signal` in a bounded child. Retain the real
  terminal-command assertion; a broken handler now fails an assertion in the
  parent instead of killing pytest. The child inherits the test's isolated home.
- Identify the mid-turn command through its own atomic PID receipt, avoiding
  platform-specific process names and unreliable ancestry scans.
- Include process startup and readiness assertions inside cleanup. Reuse the
  existing foreground-process killer, reap the owned child and join its thread.
- Route the existing POSIX trap test with the repository's `platforms` marker.

No production code, shared fixture, runner, runtime timeout or flush/settle
budget changes. All eight existing behavioral cases remain.

## Qualification

Canonical per-file runner, Windows, CPython 3.14.7, retries disabled:

| Check | Result |
|---|---|
| Untouched native SIGINT case | pytest exits before a completed result; runner exits 1 |
| Untouched native mid-tool case | `foreground sleep never started` assertion |
| Fixed shutdown file | 6 passed, 2 existing POSIX-only skips |
| Restore `os.kill` inside the isolated child | 1 failed, 5 passed, 2 skipped; child exit 2 is reported by the parent |
| Remove production `SIG_IGN` early return | 1 failed; parent reports child exit 2 |
| Remove shutdown's `_stop_turns_before_exit` call | 1 failed: `foreground command survived gateway shutdown` |
| Native `scripts/check --base 8f817911723e` | all 12 checks pass |

All mutations were restored; their actual reds are in the native commit body.
The candidate additionally checks the command's output, not just its return code.

Hosted Windows and Linux qualification, including adjacent session persistence,
is [run 38448892243](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38448892243).
All three jobs passed, on Python 3.14.7, without retries:

| Pinned source / host | Result | Gate-log SHA-256 |
|---|---|---|
| `747f657234` / Windows | 8 passed, 2 POSIX skips | `35e017802da1f6cb91c326c1b1b1aba8770a4b4322f0af6722fbbc98542b44e9` |
| `747f657234` / Linux | 10 passed | `527b5e0bc465540e5e1cf5786cdb8a64c647b50ce89f2565ba13eb3a9061aab2` |
| `8f817911723e` / Linux baseline | 10 passed | `cdb9002fdb7cc35933e5892ab20228e5c4fd9ad3aab3e5b1bd58a8ae18867c03` |

The temporary workflow lives only on the evidence branch. The native branch
contains exactly one commit after the pinned upstream base and only the test file.
Fork integration qualification is pending.

## Upstream overlap check

On 2026-10-13, searches for `exit_flush`, `serve_exit_flush` and `ignored_sigint`
found no matching open fix or discussion. A broader SIGINT search found
[PR #127955](https://github.com/NousResearch/hermes-agent/pull/127955), which
changes TUI entry/client signal recovery and a different test file; it does not
repair this file. [Issue #94724](https://github.com/NousResearch/hermes-agent/issues/94724)
is the closed original persistence campaign, not a maintainer request for this
test repair. No maintainer endorsement is claimed. This patch adds no public
API or fork-specific behavior; the native Windows reproduction is its value.

Submission attempted after native checks and hosted proof. GitHub refused
`CreatePullRequest` for the connected account. No upstream PR exists for this
repair. The pushed native branch and review-ready body are retained; no alternate
identity or permission workaround was attempted.

## Remaining observation

Three `sleep.exe 3518` children survived the failed old readiness/setup cases
and were explicitly reaped. Adding the `.exe` spelling alone still failed to
discover the running child. The ready-receipt fix removes that test dependency;
it does not establish native MSYS process-tree cleanup correctness. A separate
queue row calls for a bounded native reproduction before proposing runtime work.
