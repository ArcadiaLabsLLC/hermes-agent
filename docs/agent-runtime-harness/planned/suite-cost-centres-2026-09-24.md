# Suite cost centres — why a hermes landing's gate run takes ~80 min (2026-09-24)

Lane SPEED, branch `fork/suite-speed-2026-09-24`, fork `main` @ `155c97afbc`,
upstream `upstream/main` @ `7de8728cba`. Owner ask; queue row "Why does a
hermes landing's gate run take so long?" in `fork-hygiene-queue.md`.

**Answer in one line:** it was not the tests. Median per-file start-up
(process create → pytest session start) was **12.2 s in the fork against
1.1 s upstream**, and a median file then spent **1.3 s running its tests**.
Three fork-owned conftest costs paid at import, in every one of ~1,840
per-file processes, were most of the wall. They are fixed in `76e6fb0dc8`.

## How it was measured

- Runner: `scripts/run_tests.sh` (fork) / upstream's own `scripts/run_tests.sh`,
  8 workers both (`HERMES_TEST_WORKERS=8` upstream, whose default is
  `cpu_count*2` = 32), same venv `C:/Users/beast/.venvs/hermes-test`, 16
  logical processors.
- Per-process timings: an uncommitted pytest plugin `-p _lane_timer` (repo root,
  both worktrees) recording process create time (`GetProcessTimes`),
  `pytest_sessionstart`, `pytest_collection_finish`, session end, and every
  test's setup/call/teardown. For the first 814 fork files the create-time
  probe returned 0 (fixed mid-run); those files use the runner's own per-file
  wall (`(…, 18.7s)` in the log) instead. Analysis scripts: `.lane-logs/`
  (never committed) `analyze.py`, `balance.py`.
- Box: the FORK run (01:27→02:49) was **idle**. The UPSTREAM run shared the box
  with the owner's launcher tests (`flutter test -j 14`) from its first minute,
  so its absolute wall is **LOADED — re-take idle**; only per-file structure,
  counts and ranking are compared below.

| run | files | tests | wall | state |
|---|---|---|---|---|
| fork, validated scope `tests/agent_runtime tests/hermes_cli` | 1,839 | 21,802 passed · 242 failed · 431 skipped | **4,904 s (81.7 min)** | idle |
| upstream, full `tests/` | 4,702 discovered (~40,660 tests) | — | re-take idle — the run ended at 1,306 files (25.9 % of tests) with exit 255 and no summary; killed with the lane session, never finished | loaded |

Two of the four directories the landing gate names, `tests/cli` and
`tests/state`, do not exist; the runner accepts them silently. The scope is
really two directories.

## 1. Cost centre #1 — the fork's per-file session start (FIXED)

| per-file median (plugin) | fork before | upstream |
|---|---|---|
| create → session start | **12.23 s** (n = 1,043) | 1.09 s (n = 780) |
| session start → collected | 0.92 s | 1.39 s |
| collected → end (the tests) | 1.32 s | 2.84 s |

Summed over the fork run: 29,384 s of the 37,301 s of runner-reported
subprocess wall (79 %) was spent before pytest's session started; collection
2,007 s (5 %); test execution 5,688 s (15 %). At 8 workers, ~11 s × 1,835
files ÷ 8 ≈ **42 min of the 82**.

Found with `python -m cProfile -m pytest tests/hermes_cli/test_gui_command.py
--co -q -p no:cacheprovider` (fork, then upstream, same minute):

1. **`tests/_downstream/conftest_plugin.py::_maybe_redirect_test_tmp`** — 28.4 s
   of a 67.3 s profiled collect, in 323 `rmtree` calls. With
   `HERMES_TEST_TMP_ROOT` set (the operator's `X:\Eternia\test-tmp`), every
   process scanned the root (14,901 entries) and tried to prune dirs aged over
   7 days. 322 of them held git objects, which git writes read-only;
   `rmtree(ignore_errors=True)` cannot delete a read-only file on Windows, so
   the prune never finished and every process re-failed the same 322 trees
   (`attrib` showed `A R` on `.git/objects/*/*`). Fix: one sweep per hour per
   root (stamp file) and chmod-and-retry.
2. **`tests/_downstream/hermes_cli_conftest.py`** — two host probes at import,
   in all ~1,260 `tests/hermes_cli` processes, for three files: a
   `127.0.0.1:11434` connect with a 2 s timeout (this host drops the SYN, so it
   always pays the full 2 s) and a `node --version` spawn. Fix: both lazy
   (`functools.cache`), run only when a file that consults them is collected.
3. (not per-file, same class) **`tests/scripts/test_doc_cite_adjacency.py`**
   re-walked the live docs canon in six tests, ~6.5 s each. Fix: one walk per
   argument set per file, deep-copied per caller.

Before → after, same loaded box, back to back:

| probe | before | after | upstream, same minute |
|---|---|---|---|
| one-file `--co` (`test_gui_command.py`, runner env), 3 runs | 5.4 / 5.7 / 5.5 s | 3.3 / 3.4 / 3.6 s | 3.3 / 3.1 / 3.4 s |
| sweep old + probes new / sweep new + probes old | 3.3 / 3.2 s | 5.2 / 5.3 s | — |
| 40 `tests/hermes_cli` files, `run_tests.sh`, 8 workers | 170.8 s (P50 31.7 s) | **83.6 s (P50 13.6 s)** | — |
| `test_doc_cite_adjacency.py` alone | 48.5 s | 15.8 s | — |

"Before" in this table is the post-prune root: the first run of the fixed
sweep removed the 321 undeletable trees, so the original state (coordinator's
reading: one-file collect 16.1 s fork vs 2.8 s upstream) can no longer be
re-taken. The full-scope after-wall is a projection (~40 min), not a
measurement; the next landing's gate run is the measurement.

## 2. Fork top 20 files (runner wall, idle run)

| s | tests | file | owner |
|---|---|---|---|
| 287.1 | 78 | `tests/hermes_cli/test_doctor.py` | inherited |
| 203.0 | 332 | `tests/hermes_cli/test_gateway_restart_loop.py` | inherited |
| 162.1 | 9 | `tests/agent_runtime/test_gateway_peer_two_roots_e2e.py` | fork |
| 121.0 | 56 | `tests/hermes_cli/test_worktree.py` | inherited |
| 115.8 | 1,157 | `tests/agent_runtime/test_tombstone_registry.py` | fork |
| 101.5 | 33 | `tests/hermes_cli/test_update_autostash.py` | inherited |
| 98.7 | 108 | `tests/hermes_cli/test_harness_characters_cli.py` | fork |
| 92.2 | 43 | `tests/hermes_cli/test_cli_init.py` | inherited |
| 82.5 | 16 | `tests/hermes_cli/test_worktree_pushed_tier.py` | inherited |
| 76.8 | 3 | `tests/agent_runtime/test_gateway_peer_cross_install_chat_e2e.py` | fork |
| 76.7 | 15 | `tests/agent_runtime/test_s55_registered_events_have_emitters.py` | fork |
| 69.6 | 8 | `tests/agent_runtime/test_serve_socket_child_e2e.py` | fork |
| 67.7 | 4 | `tests/hermes_cli/test_gateway_job_teardown_live.py` | inherited |
| 67.6 | 24 | `tests/hermes_cli/test_plugin_install_ref.py` | inherited |
| 64.4 | — | `tests/hermes_cli/test_web_server.py` (failed) | inherited |
| 63.9 | 84 | `tests/hermes_cli/test_backup.py` | inherited |
| 63.5 | 63 | `tests/agent_runtime/test_realm_sync.py` | fork |
| 61.9 | 10 | `tests/agent_runtime/test_serve_ended_sidecar_child_e2e.py` | fork |
| 61.0 | 72 | `tests/agent_runtime/test_serve_socket_lane.py` | fork |
| 58.8 | 58 | `tests/hermes_cli/test_kanban_db.py` | inherited |

No single file dominates: the top 20 are 2,006 s of 37,301 s (5 %). P50
17.9 s, P90 26.8 s, P99 61.0 s, max 287 s; **no file finished under 2 s** —
the floor was the start-up above.

### Fork top 20 tests (setup + call + teardown)

| s | test |
|---|---|
| 29.1 | `test_gateway_peer_cross_install_chat_e2e.py::test_an_install_that_stops_answering_converges_to_peer_unreachable` |
| 27.5 | `test_discussion_runtime.py::test_twelve_same_profile_instances_run_distinct_sessions_and_end_retains_history` |
| 27.4 | `test_stream_stale_first_routing.py::test_the_pin_covers_every_production_call_site_there_is` |
| 27.0 | `test_gateway_peer_two_roots_e2e.py::test_two_isolated_installs_pair_through_both_verbs_and_ping_across_the_edge` |
| 23.8 | `test_serve_socket_child_e2e.py::test_probe_then_drain_over_the_socket_against_a_real_serve_child` |
| 20.3 | `test_s27_snapshot_orphan_tree_removal.py::test_no_module_level_name_is_unreachable_from_the_external_surface` (deleted 2026-09-24) |
| 18.8 | `test_s49_operator_control_removal.py::test_no_production_module_still_imports_it` (deleted 2026-09-24) |
| 18.7 | `test_gateway_peer_two_roots_e2e.py::test_introduce_on_b_join_on_a_and_the_device_half_redeems` |
| 18.6 | `test_s50_launcher_process_hygiene_removal.py::test_no_production_module_still_imports_it` (deleted 2026-09-24) |
| 18.1 | `test_gateway_peer_cross_install_media_e2e.py::test_a_device_on_A_opens_a_picture_that_exists_only_on_B` |
| 18.0 | `test_s29_snapshot_dead_local_removal.py::test_the_reachability_roots_are_back_to_the_real_external_surface` (deleted 2026-09-24) |
| 17.8 | `test_gateway_peer_cross_install_chat_e2e.py::test_a_chat_turn_crosses_an_operator_approved_install_edge` |
| 17.3 | `test_gateway_peer_two_roots_e2e.py::test_a_peer_code_scoped_to_one_install_is_refused_to_any_other_on_the_wire` |
| 17.3 | `test_serve_ended_sidecar_child_e2e.py::test_a_hard_exit_writes_nothing_and_the_absence_is_the_reading` |
| 17.2 | `test_serve_skill_maintenance.py::test_removed_sessions_keep_profile_idle_watermark` |
| 16.7 | `test_completion_backlog.py::test_ready_completions_share_one_turn_across_interactive_routes` |
| 16.5 | `test_serve_gateway_chat_reply_lanes.py::test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane` |
| 16.4 | `test_gateway_peer_two_roots_e2e.py::test_a_revoke_on_b_reaches_a_as_revoked_you_before_the_next_send` |
| 15.6 | `test_gateway_peer_two_roots_e2e.py::test_the_roster_and_one_far_thread_cross_the_wire_on_real_serves` |
| 15.6 | `test_gateway_peer_two_roots_e2e.py::test_a_join_walks_past_an_unroutable_first_candidate_and_lands_on_the_second` |

All twenty are fork-owned. Two families: real `serve`/gateway-peer e2e files
(setup 5–6 s per test = a serve boot per test), and removal-contract gates
(`test_s27/s29/s49/s50`) that each re-walk production imports once per file.

## 3. Upstream top 20 files (LOADED; first 780 files, `tests/acp_adapter`, `tests/agent`)

| s | tests | file |
|---|---|---|
| 309.8 | 87 | `tests/agent/test_actual_auxiliary_routing.py` |
| 277.5 | 48 | `tests/agent/test_compression_concurrent_fork.py` |
| 248.2 | 7 | `tests/agent/test_compression_boundary_hook.py` |
| 234.1 | 26 | `tests/agent/test_codex_app_server_integration.py` |
| 224.9 | 217 | `tests/agent/test_auxiliary_client.py` |
| 217.5 | 24 | `tests/agent/test_codex_ttfb_watchdog.py` |
| 214.0 | 11 | `tests/agent/lsp/test_client_e2e.py` |
| 207.9 | 18 | `tests/agent/test_provider_fallback.py` |
| 204.9 | 39 | `tests/agent/test_provider_parity.py` |
| 195.4 | — | `tests/agent/test_api_content_sidecar.py` |
| 193.9 | 40 | `tests/agent/test_compression_rotation_state.py` |
| 180.8 | 2 | `tests/agent/test_owned_process_cleanup.py` |
| 163.6 | 23 | `tests/agent/test_primary_runtime_restore.py` |
| 156.8 | 25 | `tests/acp_adapter/test_session.py` |
| 155.4 | 24 | `tests/agent/test_coding_context.py` |
| 152.7 | 8 | `tests/agent/test_provider_projection.py` |
| 152.6 | 11 | `tests/agent/test_compression_attempt_lifecycle.py` |
| 149.8 | 4 | `tests/agent/test_codex_watchdog_reasoning_effort.py` |
| 141.2 | 188 | `tests/agent/test_error_classifier.py` |
| 138.3 | 14 | `tests/agent/test_codex_xai_oauth_recovery.py` |

Absolute seconds are inflated by the concurrent launcher run; the ranking is
the usable part. Upstream's slow files are slow in their TESTS (median
collected → end 2.84 s, and single tests of 45–92 s: `test_owned_process_cleanup`,
`test_codex_watchdog_reasoning_effort`), not in start-up. None of these
directories is in the fork's validated scope.

## 4. Fork-only vs inherited (validated scope, runner wall)

| class (by `tests/fixtures/upstream_manifest.txt`) | files | wall | share |
|---|---|---|---|
| fork-only | 576 | 10,837 s | 29.1 % |
| upstream-inherited | 1,263 | 26,464 s | 70.9 % |

The inherited 71 % is not upstream's cost: the fork's conftest start-up (§1)
was paid by every inherited file too. It is the same per-file tax on more files.

## 5. Tests that spawn a serve, a gateway or a git repo

`grep -rlE` over `tests/agent_runtime tests/hermes_cli` (over-approximating —
a file that only NAMES `serve` counts), weighted by the idle run's walls:

| pattern | files | runner wall | share | median file |
|---|---|---|---|---|
| names `serve` (`"serve"`, `harness serve`, `_spawn_serve`) | 82 | 2,152 s | 5.8 % | 20.7 s |
| gateway `Popen`/`subprocess.run`/`start_gateway` | 34 | 937 s | 2.5 % | 18.8 s |
| `git init` / `init_repo` | 26 | 948 s | 2.5 % | 28.0 s |
| any `subprocess.run/Popen/check_*`, `create_subprocess_exec` | 193 | 5,701 s | 15.3 % | 20.8 s |

(all files: median 17.9 s). Spawning files are a little slower per file, not
the wall's driver; the real-serve e2e family is the exception (§2).

## 6. Worker balance

Reconstructed from each file's [end − wall, end] interval and a greedy
8-slot assignment: per-worker busy **4,556–4,712 s** over a 4,667 s span; the
last file started 17 s before the run ended. **Evenly loaded, no
serialisation tail.** The runner submits in discovery order, not LPT; with no
file over 5 % of a worker's time that costs nothing today.

## 7. Tooling gates — once per session or once per test?

Each file alone via `HERMES_TEST_WORKERS=1 scripts/run_tests.sh <file>` (after
fixes 1–2, before fix 3; loaded box):

| gate | alone | walks | evidence |
|---|---|---|---|
| `tests/test_no_frozen_hermes_home.py` | 28.0 s | once per file (module fixture, one subprocess importing every `get_hermes_home()` module) | 21.5 s in the first test's setup, 0.02 s each after |
| `tests/agent_runtime/test_tombstone_registry.py` | 156.2 s (115.8 s in the suite) | three walks, each once per session, warmed at import | collect 75.8 s, 1,157 tests in 24.3 s; its own guards assert `cache_info().misses == 1` and pass |
| `tests/scripts/test_check_no_tmp_literals.py` (upstream-owned) | 73.5 s, **RED** | once, in one test — which exceeds the 30 s per-test cap | whole-tree scan measured 175 s upstream tree / 248 s fork tree (6,195 / 6,653 files), loaded; already queued (lane GREEN verdict: early return when a file carries no temp-path token) |
| `tests/test_docket_stage_claims.py` | 7.7 s | git per call, `_in_this_history` memoised | 1.9 s in session |
| `tests/scripts/test_doc_cite_adjacency.py` | 48.5 s → 15.8 s | **once per TEST (six tests)** → once per file | fix 3 above; `assert 2 == 1` when the cache is removed |

## 8. Per-file interpreter + import cost

`python -X importtime -m pytest <file> --co`: `import pytest` 0.37 s fork /
0.36 s upstream; the importtime trace of the collect is the same shape in both
trees. The fork's extra time was never import — it was conftest EXECUTION (§1).
After the fix, per-file start-up is upstream's: ~1.1 s to session start and
~2.6 s to collected (upstream medians). That floor × files is upstream's
design (§9): 1,835 files × ~2.6 s ÷ 8 ≈ 10 min of any fork gate run, and
4,702 × ~2.6 s ÷ 8 ≈ 25 min of upstream's full suite.

## 9. PART 2 — upstream runner, amortised start-up (NOT built here)

Owner ruling: build later as small upstream PRs, so the fork inherits them on
merge-back. `scripts/run_tests_parallel.py` and `scripts/run_tests.sh` are
upstream-manifest files; nothing in them was changed by this lane. The later
lane takes its own idle before/after baseline (and re-takes the upstream wall
this note could not). One bullet per would-be commit:

- **Record per-file phase timings in the runner output.** Changes: the runner
  asks each child for create/session-start/collected/end (a tiny built-in
  plugin, like `_lane_timer`), prints the start-up vs run split next to the
  existing "Per-file subprocess time distribution", and caches it with the
  durations. Saves: nothing directly — it is the measurement every later
  commit is judged by. Trades: nothing; one plugin import per child.
- **Submit in LPT order from the durations cache.** Changes: the pool is fed
  longest-first (the cache already exists for `--slice`). Saves: the tail
  (17 s today; larger when a 300 s file lands last). Trades: nothing.
- **Batch small files into one child (`--batch-under=<s>`).** Changes: files
  whose cached duration is under a threshold are grouped N per `python -m
  pytest a.py b.py …` process. Saves: (N−1) × start-up per batch — at the
  upstream medians, ~2.6 s per absorbed file, ~15 of 25 min on the full
  suite. Trades: file-level isolation inside a batch (module-level dicts,
  ContextVars, `sys.modules` leak between files — the reason the runner is
  per-file); mitigate with an opt-in allowlist or a failure → re-run-alone
  rule, and keep flaky/isolation-sensitive files out by marker.
- **Forked workers (POSIX `fork` after conftest import).** Changes: a warm
  parent imports pytest + root conftest once and `fork()`s per file. Saves:
  nearly all start-up on Linux/macOS CI. Trades: no Windows support (spawn
  only), fork-safety of whatever the conftest imported (threads, sockets);
  the Windows path stays per-file.
- **Cheaper collection hooks.** Changes: upstream's root conftest work that
  runs per process but is session-invariant (hermetic-home skeleton,
  `_capture_real_kanban_root`, env snapshots) moves behind lazy accessors.
  Saves: the ~1.5 s collection median, measured per hook first. Trades:
  nothing if each accessor keeps its current first-use semantics.

## Fixes landed in this lane

`76e6fb0dc8 perf(suite): retire the fork's per-file session-start cost` —
fixes 1–3 above, with the four killing mutations and their reds recorded in
the commit body.

## Measured after the fix

2026-09-24 04:33–05:14, idle box, X:/wt/h-suite @ 1b6349e88f, `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli`, 8 workers: 2,442.7 s (40.7 min), 1,840 files, 21,761 passed / 242 failed / 431 skipped — the same 242 known reds as the 82-min before-run (4,904 s, 21,802/242/431).

## 10. Lane SUITE2 — bundled runner, measured (2026-09-24)

Branch `fork/suite-bundled-2026-09-24`. What changed before the run: the
bundled runner (`scripts/run_tests_bundled.py`, 20 files per pytest process,
failing bundles re-run their unclean members one file per process); a green
test process removes its own TMP run-dir, old ones kept 1 day instead of 7;
the gateway-peer pairs boot side by side (sharing one serve per module was
examined and refuted — the tests assert on state outside `gateway/`, event-log
tail included); and the 30 `test_s*_removal.py` gates deleted by owner ruling
2026-09-24, with their live-behaviour checks moved first into
`tests/agent_runtime/test_retired_surfaces_live_behaviour.py`.

Run: 06:29–06:59, box idle (no `flutter_tester`, no other lane's python),
`scripts/run_tests_bundled.sh tests/agent_runtime tests/hermes_cli`, 8 workers,
durations cache seeded from the primary checkout's Sep 21 file.

| run | files | tests | wall |
|---|---|---|---|
| per-file, after the §1 fix (reference) | 1,840 | 21,761 passed · 242 failed · 431 skipped | 2,442.7 s (40.7 min) |
| bundled, this lane | 1,811 in 91 bundles, 0 solo; 146 re-run alone | 21,494 passed · 232 failed · 7 errors · 426 skipped | **1,802 s (30.0 min)** |

Reconciliation: the 30 deleted gates held 276 tests; 21,761 − 276 + 12 moved
= 21,497 expected passes, 21,494 observed. Reds 239 against 242. All 87 red
files were red on the per-file baseline scope; the only red file this lane
touched (`test_goal_workspace_realm_stage42.py`, a CLI-wording assertion) is red
on `origin/main` @ `37ca422c25` too.

Where the bundled wall went. Per-file seconds the plugin could attribute sum
to 8,298 s of 14,432 s worker capacity (8 × 1,804 s):

| class (by `tests/fixtures/upstream_manifest.txt`) | files | attributed s | share | re-run alone |
|---|---|---|---|---|
| fork-only | 548 | 2,753 s | 33.2 % | 18 files, 283 s |
| upstream-inherited | 1,263 | 5,546 s | 66.8 % | 121 files, 2,754 s |

The rest is the bundles that failed: a failing bundle's own time is not
attributed per file for the members that are re-run, and the re-runs happen
after it. Six bundles DIED mid-run — pytest-timeout's thread method kills the
whole process when a known-red file times out (`test_web_server.py`,
`test_gateway.py`, `test_process_identity.py`, …) — and 52 members that never
ran in them were re-run alone; the runner labelled them isolation leaks in this
run, which was wrong and is fixed (`4e1a2a099b`: "unreached", with the file the
bundle died in named). True isolation leaks: 5. The 11 files are now in
`scripts/test_bundles_unbundled.txt` with their observed lines. The slowest
bundles ran 332 s and 302 s (both green), so the tail is set by bundle length,
not by one file. The next lever is the re-run strategy (queue row: re-bundle a
dead bundle's remainder instead of running it one file at a time), not bundle
size.

## 11. The fork-only gate (lane POLISH, 2026-09-24)

Branch `fork/suite-polish-2026-09-24`. The landing gate stops running
upstream's tests. Owner ruling 2026-09-24: the fork keeps a baseline of its
own; the full inherited set runs at the weekly upstream merge.

What changed. `scripts/run_tests_bundled.py --scope fork` (the default) runs
every discovered file absent from `tests/fixtures/upstream_manifest.txt`, plus
each inherited file the change reaches: the test file itself changed, its
upstream-convention source (`tests/<pkg>/test_<mod>.py` → `<pkg>/<mod>.py`)
changed, it imports a changed module, or a `conftest.py` above it changed. The
change is `git diff --name-only origin/main...HEAD` (or `--since <ref>`) plus
working-tree edits. `--scope full` is the old behaviour, for the weekly merge
lane. A bundle process that dies now runs the file it died in alone and
re-bundles the members behind it (§10's 52 one-file re-runs). The signal
timeout method is not an option: the test venv has no `SIGALRM` on Windows,
and pytest-timeout's default there is `thread`.

Scope at the lane tip, validated directories: 1,819 discovered, **548
fork-only**, 0 inherited reached by the lane's own diff, 1,271 left to `--scope
full`. For comparison: a diff touching `hermes_cli/gateway.py` reaches 61
inherited files, one touching `hermes_cli/config.py` 164, and one touching
`tests/conftest.py` all 1,271. The selection costs ~5 s.

Known reds in fork scope, probed file by file on this tree. The 2026-09-23
class-(b) rows were already green on `main`. Two classes were still red, and
both are fixed rather than xfailed: the serve boot's own-row refusal (class (c),
9 tests), and the whole-tree parse in `test_stream_stale_first_routing.py`
that killed its bundle. The red inventory of the fork-only files that neither
source names comes from the gate run below.

**The measurement — owner-run at the landing, once, idle box.** Before it
starts, check that no `pytest` is running and no orphaned `python.exe` from
`hermes-pytest` temp dirs is left:

```
HERMES_TEST_VENV=C:/Users/beast/.venvs/hermes-test scripts/run_tests_bundled.sh --scope fork tests/agent_runtime tests/hermes_cli > .lane-logs/gate-fork.log 2>&1; echo "EXIT=$?" >> .lane-logs/gate-fork.log
```

Record the header's `Scope fork` line, the summary line (files, bundles +
re-bundled, passed/failed/errors/skipped, wall) and the bundle-death lines here,
against §10's 1,802 s (30.0 min) for the whole validated scope. Take that as
the fork gate's baseline. Classify any red that is left.

Commits: `c1c1b8cbc1` (scope), `46c664dd04` (re-bundle), `bc499262d2` (the two red fixes), `030668cf4e` (quiet parse); each body carries its killing mutation and recorded red.
