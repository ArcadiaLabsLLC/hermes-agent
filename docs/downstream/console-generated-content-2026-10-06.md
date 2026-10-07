# Console generated-content connection repair — 2026-10-06

The chat-open hook refreshed the Launcher catalog, but retained only its refresh
thread. Actor construction ran on a different thread without the opening
LauncherLink. The registry's request-scoped availability check correctly hid
the Launcher tools, and a later linked turn could reuse that incomplete actor.

`launcher_link_prewarm` carries discovery and connection as one typed
preparation. Construction waits boundedly, binds only that item's connection,
and resets it even when construction raises. A boot item explicitly binds None.
`ChatLaneBundle.tool_contract` reads connection availability freshly, outside
its memo, so an unlinked actor cannot substitute for a linked one.

Review found a second lifetime defect in the typed preparation: opening the
same root while construction ran left a late connection in the queue's map.
Completion now releases it under the pending-item lock. A preempted item keeps
it for the queued retry. No authentication, provider, profile-worker, tool
registry, renderer or history authority was replaced.

## Recorded verification

The first regression failed before repair: no callable Launcher tools and no
opening connection. Forcing the connection-availability signature to true
killed the boot-versus-linked assertion. The restored test proves actual
first-turn resident reuse, callable creation during the agent run, one catalog
discovery and exact operator/session/turn/account provenance.

The late-open regression ran red first: 2 passed, 1 failed; later boot work
observed the old LauncherLink instead of None. After cleanup, seven focused
files passed 112 tests, including all 12 import-layer checks. Unconditionally
releasing the late link also killed the retry control: 3 passed, 1 failed;
expected [None, opening link], observed [None, None]. Restored code passes all
four connection-scope tests. Ruff passes on the five touched Python files.

The whole-tree **fork** gate ran once on `87740c54c1`, before the narrow
late-link cleanup. It selected 895 fork files and excluded 5,197 inherited
files and the four workstation-freeze candidates. Commands used the Launcher
heavy-run slot and one worker; no Launcher suite ran alongside them.

```text
=== Summary: 895 files (230 bundles + 0 re-bundled, 2 solo, 32 re-run alone), 11494 tests passed, 110 failed, 5 errors, 49 skipped in 3597.5s (1 workers) ===
processes: 230 bundles, 2 solos, 32 re-runs alone, 0 straggler retries
worker-seconds 3597.0s (1 × 3597.0s); busy 3596.3s = 100% utilization
Σ per-file seconds (collect + tests) 2971.4s = 83% of worker-seconds
start-up (spawn → session start, Σ over processes) 94.2s
re-running red members (their bundle attempt + the run alone) 495.4s
```

Only the 33 failing files were rerun on detached unchanged main `5c0f130723`:

```text
=== Summary: 33 files (12 bundles + 0 re-bundled, 1 solo, 32 re-run alone), 259 tests passed, 110 failed, 5 errors, 1 skipped in 539.7s (1 workers) ===
```

Both receipts contain the exact same 115 failure/error node IDs: zero
branch-only nodes. The 35 unique duplicate-helper, legibility and live-canon
citation violation lines also match, not merely their failing verdicts.
Residuals remain in the existing fork-hygiene classification row; no baseline,
exemption, skip list or workstation policy was expanded.

## Remaining native acceptance

These checks do not prove provider compliance or interactive JavaScript in the
native WebView. Launcher catalog guidance and its real creation-to-shared-
transcript tests are recorded in
`EterniaLauncher/docs/companion/planned/ARTIFACT_PRESENTATION_REVIEW_2026-09-30.md`.
Fresh and existing conversations after restart, editable native output,
interactive WebArtifact behavior and saved-output reopen remain on the
Launcher's existing native artifact qualification row. The process-global
multi-Launcher catalog remains its separately filed runtime ownership issue.
