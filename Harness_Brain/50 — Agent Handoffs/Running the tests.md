---
type: handoff
tags: [handoff, process, tests]
---

# Running the tests

Read this before you run any test, gate or suite in this repository, and before you brief a lane
that will. `CLAUDE.md` carries only the pointer and the one rule that does damage before anyone
opens a page (never bare `pytest` over a directory). The fork's gate definition is
`docs/downstream-development.md` § "The fork landing gate"; this page is how a session uses it.

## The commands

```bash
python -m pytest -q -p no:cacheprovider <file>                  # ONE file, debugging only
scripts/run_tests_bundled.sh tests                              # THE LANDING GATE: --scope fork over the whole tree
scripts/run_tests_bundled.sh --scope full tests                 # the weekly merge lane only (skip list applies; P0 row)
scripts/run_tests_bundled.sh --since-merge <merge-sha> tests   # a release merge's landing gate (Merging upstream.md step 7)
scripts/run_tests.sh <file>                                     # the per-file authority: one file, a leak, a disagreement
scripts/run_tests_idle.sh                                       # the timing files, ONLY on an idle box (refuses otherwise)
python scripts/dump_cli_contract.py --check                     # after any argparse change
python scripts/dump_payload_contract.py --check                 # after any character payload change
python scripts/doc_cite_adjacency.py --exclude archive --exclude planned          # the ruled doc-cite scope
python scripts/changed_line_mutation_check.py --list --base origin/main           # mutation inventory (safe unattended)
```

**Upstream-PR and sync lanes pin the base by SHA and own their uv cache.** Run
`UV_CACHE_DIR=<lane scratch>/uv-cache python scripts/check --base <sha>`, with the SHA read once
(`git rev-parse upstream/main`) at the start of the lane. The default base (the merge-base with
`origin/main`) is thousands of commits behind upstream: ~313 blocking findings over 2,756 files and
its 900 s timeout (lanes up-door-*, 2026-10-07). A bare `--base upstream/main` moves when another
lane fetches mid-run and the code-health ratchet reports false `FILE_LINES`/`BLE001` reds
(up-sync-2, 2026-10-08). The shared uv cache locks under concurrent lanes (`os error 32`), hence the
per-lane `UV_CACHE_DIR`; if `uvx ruff@0.15.10` still fails on it, use the test venv's `ruff`.

**The landing gate runs over `tests`, not over three directories.** `--scope fork` (the default)
runs every fork-owned test file plus each upstream test file the change reaches by name, import or
conftest. Given `tests/agent_runtime tests/hermes_cli tests/hermes_state` it only searches those
three, and misses the upstream tests of an upstream file the change edits: on 2026-10-05 (landing
h-turn1, one edit to `agent/conversation_loop.py`) the three-directory form selected 689 files, the
whole tree 908 — 176 more fork files and the 42 `tests/agent/` files that test that function. The
whole tree on that day: 865 fork files (~9,400 test functions), 5,201 upstream (~43,200); the gate
ran 908 files / 13,621 tests in minutes.

**`--scope full` (every file, upstream's included) belongs to the weekly upstream merge lane, and is
not run on a workstation** until the fork-hygiene P0 row closes: on 2026-10-05 the full scope
hard-froze the operator's PC twice with the same four upstream files in flight
(`tests/hermes_cli/test_source_check.py`, `test_source_launcher_publication.py`,
`test_source_release_channels.py`, `test_source_release_probe.py`), the second time at 4 workers
with nothing else running. If a scope is in doubt, list what it will run before running it
(`select_scope` in `scripts/run_tests_bundled.py`). After a freeze or a killed run, read the
interrupted log's last lines before re-running; re-running the remainder without excluding what was
in flight is how the second freeze happened.

**The upstream skip list.** `tests/fixtures/upstream_skip_list.txt` names upstream-owned test files
the bundled runner does NOT run, in either scope: the four P0 freeze files today, and upstream reds
as they are proven (one row per file: `path · why · upstream SHA`, `why` starting `P0`, `env` or
`upstream`). A listed file runs only when NAMED on the command line — reaching it by import, source
or conftest does not (owner ruling O1); the run prints every file it skipped and why. A fork file is
never listed (fork reds are fixed): `tests/scripts/test_upstream_skip_list.py` refuses one. A row is
added only after the file was run once, bare, and seen red on `origin/main`; the weekly merge lane
re-checks the `env`/`upstream` rows (`Merging upstream.md` step 5b). The P0 four on the list do not
lift the workstation ban on `--scope full` above; that waits on the P0 row.

**What a run prints about itself.** After the Summary line, `=== Run cost (Stage 0) ===`: processes
by kind, worker-seconds and utilization, Σ per-file seconds and the floor at that worker count,
start-up seconds, the seconds spent re-running red members, the critical-path process, the idle tail
and the 20 slowest files. The same numbers, with every red file's failing node ids, are appended as
one JSON line to `.pytest_cache/hermes_bundled_runs.jsonl` (git-ignored, per checkout). Quote that
line in a landing report instead of reconstructing timings from the log.

**Bundles are planned by duration.** A bundle closes at `--bundle-size` files (20) or before its
cached seconds pass `--bundle-seconds` (120); a file cached slower than `--solo-seconds` (60) runs
alone, and solos are submitted before bundles. Both read `test_durations.json`, so a fresh
worktree's first run plans by count; pass `0` to either flag to switch it off.

**A red is not paid for twice** (owner ruling O5). A bundle member red with the SAME failing node
set as the last recorded run is reported from its bundle (`known-red` in the progress line; its
failure output says why), not re-run alone. A new red, or one whose failing set changed, is still
re-run alone and an isolation leak is still named. To see a known red alone:
`scripts/run_tests.sh <file>`.

**Bare `pytest` over a directory is forbidden.** It runs the updater tests in-process, and those run
`git branch -f main origin/main`: it detached 11 unpushed commits from the primary checkout on
2026-08-01. The runners isolate files in hermetic subprocesses, find the shared test venv, and run
8 workers — the ruled default (12 measured slower and load-flaked; do not raise
`HERMES_TEST_WORKERS`).

A test whose wait bound exceeds 30 seconds declares `@pytest.mark.timeout(N)`: `addopts` carry
`--timeout=30`, and pytest-timeout kills a longer test before it can say what went wrong.

## Environment notes (carried from the retired "Running the suite" page)

- `tests/acp` cannot collect from a worktree (the editable install resolves to the primary) — run
  it from the primary or name the lanes explicitly.
- `HERMES_TEST_TMP_ROOT` → a Defender-excluded throwaway dir speeds a run; `X:/Eternia` is already
  excluded on this box.
- A failure seen only in a parallel or bundled run is compared as a SET against a serial
  `scripts/run_tests.sh` run of that file before it is believed (the bundled runner names an
  isolation leak itself: red bundled, green alone → `scripts/test_bundles_unbundled.txt`). A
  `known-red` line was NOT run alone this time; it is not evidence of a leak either way.
- Pre-existing reds are never baselined ([[0010 — Stale sweep and ratchets first, never baseline]]).
- A stale `index.lock` after a killed run (zero bytes, no git alive) is `rm`'d once the interrupted
  log's last lines are read. The fork's root `conftest.py` sets `GIT_OPTIONAL_LOCKS=0` for every test
  process, and the bundled runner passes it to its own git, so git's opportunistic index refresh no
  longer takes the lock (design sweep D3.16). To name a test that still runs git against the checkout,
  run the gate with `--git-audit` (`scripts/run_tests_bundled.sh --git-audit tests`) and read
  `.pytest_cache/hermes_git_in_checkout.jsonl` (`{file, nodeid, argv, cwd}` per call; it
  over-approximates — every verb, and a positional repo path is not parsed).

## How to run a heavy command (measured — do not improvise)

The launcher mined 24 days of agent transcripts (`EterniaLauncher/docs/tooling/AGENT_WALL_TIME_2026-09-18.md`):
five habits cost about 390 minutes a day.

- **Pass an explicit `timeout` on every test, build or census call.** The 120-second default killed
  646 calls and returned nothing; 329 more died at the 600-second ceiling.
- **Run a long command as a BACKGROUND task and wait for the completion notification.** Never
  `sleep`, never an `until … grep` loop, never `tail -f | grep -m 1` — 772 polling calls cost 35 hours.
- **Never re-run a byte-identical heavy command with no edit in between.** 731 did; 17 hours.
- **Never pipe a heavy command through `tail` / `head`.** Redirect to a log file, capture the exit
  code UNPIPED (`; rc=$?; exit $rc`), read the log after. Under `pipefail` a gate piped through
  `tail` hides its own red.
- **One heavy run at a time on this box.** Two contend for the same cores; a second landing racing
  the first costs both a re-merge and a second gate run.

## What a lane runs, and what it never runs

- **While implementing:** `ruff` (or `pyflakes`) on the touched modules, foreground, explicit
  timeout. Nothing heavier.
- **At the end of the lane, before the report:** ONLY the test files that import a module you
  touched — `grep -l` the module paths under `tests/` — as one
  `python -m pytest -q -p no:cacheprovider <files>` run, in the background, with a log and the exit
  code captured unpiped, timeout at least 600000. A lane never runs the landing gate, the tooling
  gates, the docs gates or the contract dumps; those are the landing's job, once.
- **Launcher lanes and landings run `*_test.dart` files only.** A `grep -l` under `test/` also
  matches fixtures and helpers; on 2026-10-05 it handed `flutter test` the helper
  `detached_serve_starter.dart` and the run hung ten minutes. Filter the list to `_test.dart`.
- **A fork test never goes inside an upstream test file.** A test of a fork seam in upstream code
  lives in a fork-owned `tests/**/*_downstream.py` that imports upstream's fixtures. Appending to an
  upstream test file adds a file to the fork's upstream footprint (`tests/scripts/test_upstream_footprint.py`);
  landing h-turn1 had to move one (`92be2b3a10`).
- **A CHANGE commit carries its positive control:** the defect planted on a throwaway copy, the red
  pasted into the commit body, reverted. A new gate lands with its killing mutation recorded. A
  control that has not been run is a belief.

## What a landing runs, once

**One whole-tree gate per BATCH, never per lane** (owner ruling 2026-10-06, after waves 11–13 each paid a
15–18 minute gate for a single lane). A finished lane waits for the batch; the landing merges every ready
lane, then runs the gate once. A lane that finishes while a gate is running joins the next batch unless it
touches nothing the running batch touches.

Concurrently: (a) the landing gate `scripts/run_tests_bundled.sh tests` in the one heavy slot;
(b) the tooling gates — `test_no_frozen_hermes_home`, `test_tombstone_registry`,
`test_duplicate_helper_bodies`, `test_cli_contract_dump`, `test_payload_contract_dump`, the
legibility floor, the upstream footprint and the namespace gates (the whole-tree gate already
includes them; run them alone after a re-merge); (c) `changed_line_mutation_check.py` for any new
gate; (d) the docs gates. For the launcher half, `flutter test` on the `*_test.dart` files that
import a touched file. After a re-merge, only (b) re-runs; the gate runs again only if an incoming
commit touches a file the batch touches.

## The idle-box files: after the gate, on an idle box

The timing positive controls and the turn-cost guard keep their absolute budgets and run only on an
idle box, serial, never inside a parallel gate (owner ruling 2026-10-10; design sweep D3.01 / D3.09:
under gate load the OS starves the GIL hog instead of the reader, and a 500 ms stall floor read
76–232 ms). `scripts/test_idle_box_files.txt` lists them; their tests skip unless
`HERMES_TEST_IDLE_BOX=1`, and the bundled gate does not select them unless named (it prints
`idle-box: N file(s) not run`). A lane running `scripts/run_tests.sh` on one of them sees it skipped,
by design.

When a batch touches `agent_runtime/send_window_receipt.py`, `agent_runtime/stream_gap_receipt.py`,
`agent_runtime/transport_phase_trace.py` or the turn-cost path (anything
`tests/agent_runtime/test_turn_cost_guard_downstream.py` imports), the landing runs
`scripts/run_tests_idle.sh` AFTER the gate, with nothing else running. It refuses (exit 3) and names
every live pytest / `run_tests` process while the box is busy; `--check` asks only that. It runs the
list at one worker with `HERMES_TEST_IDLE_BOX=1` and appends `{"kind": "idle", …}` to
`.pytest_cache/hermes_bundled_runs.jsonl` (the known-red read skips that line): quote it in the
landing report. An idle run that still reds is a new row carrying its receipt line
(`stall_samples`, `stall_max_ms`, `max_lag_ms`), never a lowered floor.

## After a landing that touches the chat path: the live latency check

Offline guards pass on small fixtures while live chat regresses on real-sized stores and a real
launcher (2026-10-06: the pre-request window went 0.4 → 1.2 s and the launcher rebuilt the whole page
per turn, with every gate green). So after any landing that touches the chat-turn path (admission,
prewarm, prompt/context build, the provider client, the stream, or the launcher's chat surfaces),
the operator rebuilds, waits about 2 minutes after boot, sends a few turns, and someone runs:

```
hermes harness observe turn-timing --check
```

It reads the last turns' receipts (and the launcher's `[MissionChatTiming]` lines when present),
groups them cold / after-idle / warm, and prints PASS or FAIL per span against the committed budgets
and the 2026-10-07 baseline (exit 1 on any FAIL). Provider spans are reported, never failed. A FAIL
is a regression to row before the next landing, not a number to loosen. The baseline, budgets and
groups are Decision 0014.

## Calling a red pre-existing

`main` is not green: on 2026-10-05 the whole-tree gate read 70 failing tests in 35 files on `main`
itself. A red is pre-existing only when it is PROVEN so:

1. Cut a detached worktree at the merge-base (`git merge-base HEAD origin/main`) — never in the
   primary checkout.
2. Run the SAME failing files there (`scripts/run_tests.sh <files>`, or `flutter test <files>`).
3. Compare test node by test node. A node red only on the branch is the branch's.
4. **For the drift gates, compare the violation lists, not the verdict.** The legibility floor,
   duplicate helpers, doc-cite adjacency, the upstream footprint and the method-lane chokepoint are
   red on `main` already, so a branch can add violations inside a test that was red anyway. Diff
   their `NEW` / `GREW` / cite / file lines between the two logs; landing h-turn1 found three of its
   own violations that way inside tests `main` also failed (`cd2ed22ea8`).

A pre-existing red is named in the report with that proof, never fixed in passing and never
baselined; if it is not already a row, file it in `fork-hygiene-queue.md`.

## The gates are tests, not hooks

There is no pre-push hook (deleted 2026-09-03, `504953f6ad`); nothing gates a push, and every check
above is something someone runs. `main` went red unreported twice because nobody did (`6979bad59`;
2026-09-04). The fork's CI has not fired on `main` since 2026-09-07 and is not evidence until that
queue row closes. `scripts/unattended_suite_run.ps1` is a report the operator may schedule, never a
gate.

**When a contract dump reds, read the diff before regenerating.** A removed command, flag or payload
key is a launcher button that now exits 2 or a stale default acted on; re-vendor the launcher's copy
in the same wave.
