# Planned — suite speed: where the Python suite's time goes, and the stages that make the fork gate and the full scope usable

**Status:** PLANNED 2026-10-05 (Fable, lane h-suite-speed, measure + design only; no runner, conftest or production change). Branch `plan/h-suite-speed` from `main` @ `8fdb6b81dc`. Queue row: `Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md`, the owner ask tagged `lane h-suite-speed`; the P0 freeze row is the same file. **Owner docs:** `Harness_Brain/50 — Agent Handoffs/Running the tests.md` (binds every run named here), [`../../downstream-development.md`](../../downstream-development.md) § "The fork landing gate". **Predecessors this plan builds on, not over:** [`hermes-suite-perf.md`](hermes-suite-perf.md) (2026-09-01: Stages 1–7, rulings R1–R6), [`suite-cost-centres-2026-09-24.md`](suite-cost-centres-2026-09-24.md) (the 12 s per-process start-up, fixed), and the bundled runner that followed it (`scripts/run_tests_bundled.py`, 20 files per process). Those three took the gate from ~82 min to ~16.5 min; this note is about the next 16 minutes.

**The ask.** The fork gate ran 872 files / 13,038 tests in ~18 min wall at 8 workers (runner-reported 986.7 s, plus ~90 s of activation, dev-dep install and bytecode pre-compile before it); the launcher's Flutter suite runs ~40,000 tests in 8 min. Make the fork gate and the full scope fast enough to use. **Owner ruling, same day (coordinator, 2026-10-05):** upstream-owned test files that are red on `main` — environmental reds, upstream bugs, and the four P0 freeze files — are SKIPPED by the runner from a committed list, re-checked by the weekly merge lane, never a fork file. That is Stage 1 here.

**The headline, before the tables.** The gate is no longer start-up-bound: the 872 files' own collect+test seconds sum to **5,977 s**, and 5,977 ÷ 8 workers = **747 s is the floor at 8 workers** against the **987 s** observed — the runner is at 76 % of ideal, and the remaining 240 s is process start-up (~93 processes × ~3 s), the first attempts of the 39 files that were re-run alone (~5 min of CPU spent twice), and the idle tail. So the suite is now **test-bound**, and "fast enough" has three independent levers, in this order of yield: (1) **the tail** — 54 files (6 % of files) hold 50 % of the seconds, in four nameable classes (§1.3); (2) **more workers**, which the 2026-09-01 "12 workers rejected" verdict measured in PER-FILE mode with 6 s start-ups the bundled runner no longer pays, so it must be re-taken (§2.2 re-takes it on a sample); (3) **less duplicated CPU** — the rerun-alone pass, the source-walk gates that re-parse the tree once per module inside a bundle, and the 39-file red set that the gate carries every run. The rate the launcher gets (~83 tests/s) is not reachable by scheduling alone: at 13 tests/s today the median fork test costs 0.27 s of CPU against a Flutter unit test's ~0.01 s, and most of that is real work in the tests (store writes, 5 MiB payloads, child processes), not harness overhead. The projected endpoint (§3.9) is a **~6–7 min fork gate** and a **~35–45 min full scope** on this box, both with every number marked for the one run that confirms it.

This note cites SYMBOLS and FILES, never line numbers. Every number has a source: the gate log `gate-w2.log` of landing h-turn1 wave 2 (2026-10-05 20:22–20:40, 8 workers, bundled runner, `main` @ `7ddb6949a1`), the runner's `test_durations.json` from that run, or a sample run this lane took (§2), each named by its script. **Anything not measured is marked UNVERIFIED with the one run that settles it.**

---

## 0. Ground truth — the gate run of 2026-10-05 (`gate-w2.log`)

### 0.1 What the runner reported

`=== Summary: 872 files (52 bundles + 0 re-bundled, 2 solo, 39 re-run alone), 12914 tests passed, 68 failed, 5 errors, 51 skipped in 986.7s (8 workers) ===`, then 36 red files and 3 ISOLATION LEAKS. The log's per-file lines carry the seconds the bundle plugin recorded for that file (collect + every test's setup/call/teardown; NOT the process's start-up); `via` is `bundle` (831 files), `solo` (2, from `scripts/test_bundles_unbundled.txt`) or `rerun` (39, the members of a red bundle re-run one per process).

| quantity | value | how |
|---|---|---|
| wall, runner | 986.7 s | the Summary line |
| wall, outside the runner | ~90 s | the log's head: `activate` (test env already built → ~50 s of pm checks on a fresh worktree, measured 53 s cold by this lane), `ensure_fork_dev_deps.py`, `compileall -j 0` over every tracked `.py` |
| Σ per-file seconds (collect + tests) | 5,977 s | sum of the 872 lines: bundle 5,114 s · rerun 828 s · solo 35 s |
| worker-seconds available | 7,894 s | 8 × 986.7 |
| utilization | 76 % | 5,977 / 7,894 |
| floor at 8 workers | 747 s | 5,977 / 8 (LPT over the 52 real bundles: 744 s — bundling by path costs nothing at 8 workers) |
| floor at 12 / 16 workers, same bundles | 504 s / 474 s | the longest bundle (474 s, `tests/agent_runtime/test_mission_goal.py … test_observability_dev_work.py`) becomes the critical path |
| floor at 12 / 16 workers, per-file LPT | 498 s / 374 s | what duration-aware bundling (§3.3) recovers |
| tests | 13,038 (12,914 pass + 68 fail + 5 err + 51 skip) | the per-line tallies |
| median file / p90 file | 1.4 s / 14.9 s | 362 files < 1 s, 564 < 3 s |

The 240 s between floor and observed decomposes as: **process start-up** ~93 processes (52 bundles + 2 solos + 39 reruns) × ~3 s ≈ 280 worker-s ≈ 35 s wall; **the double-run of red members** — a red bundle's failing members ran once in the bundle (their time is NOT in the 5,977; the file's reported line is the rerun) and once alone: 828 s of rerun lines + their first attempts ≈ 1,600 worker-s ≈ 100 s wall (the rerun lines include the three heaviest reds: `test_native_conversation_roundtrip.py` 147 s, `test_coverage_claims_resolve.py` 128 s, `test_duplicate_helper_bodies.py` 88 s); **the tail** — the last bundles finishing on fewer than 8 workers, ≈ 100 s. The 39 reds are `main`'s own 70-failing-test set (the handoff page: "`main` is not green"), so **every gate run pays ~100 s for reds nobody is fixing** until they close or are skipped (Stage 1 covers only the upstream-owned ones; the fork ones are fixed, by the ruling).

### 0.2 Where the seconds are, by directory

| directory | files | Σ s | share |
|---|--:|--:|--:|
| `tests/agent_runtime` | 554 | 3,822 | 64 % |
| `tests/hermes_cli` | 135 | 747 | 12.5 % |
| `tests/agent` | 51 | 740 | 12.4 % |
| `tests/scripts` + `tests/tooling` + `tests/test_coverage_claims_resolve.py` | 40 | 389 | 6.5 % |
| everything else (tools, tui_gateway, gateway, root files) | 92 | 279 | 4.7 % |

### 0.3 The slow tail (the 40 files that are half the suite)

Top 10 = 24 % of the seconds, top 40 = 51 %. Full ranking in the lane's tsv (`gate-w2-files.tsv`, scratch); the ones a stage names:

| s | tests | file | class (§1.3) |
|--:|--:|---|---|
| 232.8 | 281 | `tests/agent/test_run_agent.py` | D agent-loop unit file |
| 182.5 | 9 | `tests/agent_runtime/test_gateway_peer_two_roots_e2e.py` | A e2e child |
| 161.7 | 112 | `tests/agent/test_charsheet_pipeline.py` | E charsheet |
| 146.8 | 4 | `tests/agent_runtime/test_native_conversation_roundtrip.py` (rerun) | C native in-process |
| 135.7 | 1,228 | `tests/agent_runtime/test_tombstone_registry.py` | B gate |
| 129.4 | 6 | `tests/agent_runtime/test_embedded_phone_session.py` | A e2e child |
| 127.6 | 4 | `tests/test_coverage_claims_resolve.py` (rerun) | B gate |
| 114.5 | 108 | `tests/hermes_cli/test_harness_characters_cli.py` | E charsheet |
| 110.5 | 2 | `tests/agent_runtime/test_native_large_recovery.py` | C native in-process |
| 108.4 | 8 | `tests/agent_runtime/test_discussion_runtime.py` | C |
| 103.1 | 132 | `tests/agent_runtime/test_persona_assignments.py` | F store-heavy |
| 93.1 | 67 | `tests/agent/test_run_agent_codex_responses.py` | D |
| 91.5 | 154 | `tests/agent/test_charsheet_draft.py` | E |
| 87.7 | 5 | `tests/agent_runtime/test_duplicate_helper_bodies.py` (rerun) | B gate |
| 79.6 | 8 | `tests/agent_runtime/test_serve_socket_child_e2e.py` | A |
| 72.7 | 3 | `tests/agent_runtime/test_gateway_peer_cross_install_chat_e2e.py` | A |
| 69.6 | 5 | `tests/agent_runtime/test_discussion_group_recovery.py` | C |
| 66.6 | 10 | `tests/agent_runtime/test_serve_ended_sidecar_child_e2e.py` | A |
| 65.2 | 64 | `tests/agent_runtime/test_relay_session_lifecycle.py` | C |
| 60.9 | 56 | `tests/agent_runtime/test_s56_runtime_config_reader_gate.py` | B gate |
| 60.6 | 4 | `tests/agent_runtime/test_native_app_functions.py` | C |
| 53.9 | 1 | `tests/agent_runtime/test_discussion_group_native.py` | C |
| 51.8 | 65 | `tests/agent_runtime/test_realm_sync.py` | F |
| 47.1 | 15 | `tests/agent_runtime/test_s55_registered_events_have_emitters.py` | B gate |

---

## 1. The causes, ranked by wall-time share

### 1.1 Per-process cost (M1, this lane, `m1_startup.py`, serial, idle box, the activated 3.14.7 test env)

| probe | s |
|---|--:|
| bare interpreter | 0.07 |
| `import pytest` | 0.40 |
| the conftest chain as plain imports (`conftest`, `tests.conftest`, `tests._downstream.conftest_plugin`) | 0.65 |
| `pytest --collect-only` of one 2-test file (process create → collected) | 1.2 |
| `pytest` full run of that 2-test file | 2.8–3.5 |
| `--collect-only` of a real 20-file bundle (`tests/agent_runtime` bundle 1) | 9.6 (≈ 0.45 s / file) |
| `--collect-only` of the 48-file median sample | 15.7 (≈ 0.31 s / file) |

So a bundle process pays **~1.2 s before collection and ~2 s of session-level work after it** (basetemp relocation and prune, the first use of the 35 autouse fixtures — 16 in `tests/conftest.py`, 11 in the fork plugin, 7 in `tests/agent_runtime/conftest.py`, 1 in `_fixtures/live_system_guard.py` — and session teardown), i.e. **~3 s × 93 processes ≈ 35 s of wall at 8 workers**. Collection is **0.3–0.45 s per file** (the test module's imports, which for the first file of a bundle include `agent_runtime`/`hermes_cli` themselves), **≈ 300 s of CPU over 872 files ≈ 40 s of wall**. Start-up is now **~8 % of the gate**; the 2026-09-24 note's 12 s per file is gone. `-X importtime` of a collect-only shows 0.50 s of self time over 417 modules with `_pytest`/`anyio`/`pygments` at the top and no hermes module above 0.02 s — there is no import-cost cut worth a stage.

### 1.2 Worker-count curve, bundling and the temp root (M2, this lane, `m2_workers.py`, 48-file median sample of `tests/agent_runtime`, gate-time 76.1 s of tests, idle box)

| run (48 files, 759 tests, Σ gate test-time 76.1 s) | wall | reads as |
|---|--:|---|
| per-file, 4 workers | 76.0 s | 304 worker-s ÷ 48 = 6.3 s/file for 1.6 s of tests: ~4.7 s/file of start-up+collect under 4-way contention |
| per-file, 8 workers | 51.3 s (64.4 s on a repeat) | the gate's old shape; 8.5 s/file of worker time |
| per-file, 12 workers | 45.5 s | still scaling — the 2026-09-01 "12 is slower" was a 1,089-process run on a loaded box |
| per-file, 16 workers | 38.9 s | 4× the workers of the first row buys 1.95× — contention on 8 physical cores |
| **bundles of 6, 8 workers** (8 bundles) | **22.0 s** | the bundling win: 2.3× over per-file at the same worker count |
| bundles of 20, 8 workers (3 bundles) | 34.3 s | only 3 of 8 workers busy — the shape of the §0.1 tail |
| bundles of 6, 12 workers (8 bundles) | 27.1 s | 8 bundles cannot load 12 workers; NOT a 12-worker measurement — AND one load-flake (below) |
| bundles of 4, 12 workers (12 bundles) | 24.2 s | same flake again |
| per-file, 8 workers, `HERMES_TEST_TMP_ROOT=X:/Eternia/worktrees/_ss_tmp` (excluded drive) | 55.0 s | within the 51–64 s noise of the two unset runs: **the temp root does not move the median file** (the 2.3–2.9× of 2026-09-01 was on raw file churn; a median test's churn is small) |
| per-file, 1 worker (serial reference, idle) | 268.0 s | 5.6 s/file for 1.6 s of tests: **~4 s per process of start-up + collect + session teardown even uncontended** — the per-file runner's floor, which bundling divides by the bundle size |

**Both 12-worker bundled runs flagged `tests/agent_runtime/test_work_service.py::test_concurrent_retry_admits_one_native_task` red in its bundle, green alone**, in two different bundle compositions; at 8 workers the file was green in both bundle shapes. That is not an isolation leak (the composition changed, the worker count did not) — it is the load-flake class of 2026-09-01's 12-worker probe (`test_serve_rpc_office_subscribe_live_hub.py` then), and the runner's ISOLATION LEAK report cannot tell the two apart. Stage 5 carries that distinction; the test itself is rowed (a concurrency test whose admission window is wall-clock) in the report.

What the curve says for the gate: the per-file numbers are the START-UP curve (48 processes), the bundled numbers the TEST curve; with ~93 processes the gate is on the second, where the median work scales with workers until the A/C classes' sockets and SQLite locks contend. The 12/16-worker question for the gate is therefore NOT answerable on a 48-file sample (eight bundles cannot load twelve workers) — it is Stage 5's own measurement on the full gate, after Stage 3 makes bundle count ≫ worker count.

### 1.3 The classes (name-based census over the 872 lines; the share is of the 5,977 s)

| class | files | Σ s | share | tests | s/test | what the time is |
|---|--:|--:|--:|--:|--:|---|
| **A — e2e with real serve/gateway CHILD processes** (`*_e2e.py`, `gateway_peer_*`, `serve_socket_child`, `embedded_phone`) | 14 | 638 | 10.7 % | 231 | 2.76 | process spawn of `hermes harness serve`/gateway children, their boot, port/socket readiness polls, orderly shutdown waits |
| **B — gates: source walks / AST / contract dumps** (`test_sNN_*`, tombstone, coverage claims, duplicate helpers, doc-cite, `tests/tooling`, `tests/scripts`) | 102 | 901 | 15.1 % | 2,246 | 0.40 | parsing the production tree; `tests/agent_runtime/_tree_index.py` memoizes it but `_drop_tree_index_between_modules` CLEARS it at every module teardown, so inside a 20-file bundle each gate module re-parses; the tombstone registry keeps its own parse by design (docstring stripping) and re-renders per row |
| **C — in-process native/discussion runtime** (`test_native_*`, `test_discussion_*`, `operator_session`, `relay_session`) | 38 | 1,053 | 17.6 % | 311 | 3.39 | real `ConversationService` runs with a local fake provider, 5–10 MiB payloads (`test_native_large_recovery.py`: `randbytes(5 MiB).hex()` rendered and persisted, "takes longer under suite CPU load", `until(..., timeout=90)` at a 50 ms poll), compute-child variants, restart-and-recover loops |
| **D — agent-loop unit files** (`test_run_agent.py`, `test_run_agent_codex_responses.py`) | 2 | 326 | 5.5 % | 348 | 0.94 | 0.8–1.4 s per test for an in-process `AIAgent` turn against a fake client; UNVERIFIED which phase (setup vs call) — M3 settles it |
| **E — charsheet pipeline/draft** (`test_charsheet_*`, `test_harness_characters_cli.py`) | 13 | 379 | 6.3 % | 632 | 0.60 | image generation/validation per test (PIL), 39–62 `tmp_path` sites per file |
| **F — store-heavy unit files** (`test_persona_assignments.py`, `test_realm_sync*.py`, `*realm*`) | 18 | 273 | 4.6 % | 445 | 0.61 | `PersonaInstanceStore` / realm sync with real on-disk stores per test |
| **G — the rest** | 685 | 2,407 | 40.3 % | 8,825 | 0.27 | median file 1.3 s, p90 10 s; 409 files under 2 s hold only 256 s — the long thin tail of ordinary unit tests |

Three things this table says. **(i)** Classes A+C — real runtime work with waits — are 28 % of the seconds in 52 files; they are the critical path at any worker count above 8 and the first thing a scheduler must start. **(ii)** Class B is 15 % and is pure duplication: the same tree parsed ~100 times per run. **(iii)** Class G's 0.27 s/test is the per-test floor of this suite — 35 autouse fixtures, a fresh `tmp_path` HERMES_HOME per test, `_close_leaked_session_dbs`, `_moa_caches_isolated`, the kanban/state-db write guards — and it is NOT where the next ten minutes are; the 2026-09-01 field notes already took that floor from 28 ms to ~8 ms/test and the rest is the tests' own work.

### 1.4 What is NOT a cause (measured absent, so no stage is spent on it)

- **Import cost of hot modules:** §1.1 — 0.50 s self time at collection, nothing hermes-owned above 20 ms.
- **Defender on the temp root:** the 2026-09-01 field notes measured 2.3–2.9× on file churn under `%TEMP%`; the landing gate did not export `HERMES_TEST_TMP_ROOT` (nothing in `gate-w2.log` says so, and the operator's `X:\Eternia\test-tmp` is an opt-in). §1.2's A/B row says what it is worth on the median sample; it is a one-line change to how the landing invokes the gate, not a stage.
- **Timeouts firing:** no `(timed out after` line in the gate log; `--timeout=30` per test killed nothing. The 25 unmarked + 32 marked `@pytest.mark.timeout` sites (45–300 s) are ceilings, not costs.
- **The hermetic env:** `env -i` + the conftest's env scrub are microseconds; `compileall` before the run is ~10 s once.

---

## 2. Measurements this lane took (how; re-takeable without this session)

All from `X:/Eternia/worktrees/hermes-suite-speed` under the worktree's own activated test environment (`./activate --`, 53 s cold; it built `X:/Eternia/.hermes/installs/<key>/test-environment`, the pm install-state store, nothing under the live store root), scripts in the lane's scratch dir, one run at a time after `wmic process` showed no other `pytest`/`run_tests` process. The four P0 files were never in any list; `--scope full` was never run.

### 2.1 M1 — per-process (`m1_startup.py`): §1.1.

### 2.2 M2 — worker curve (`m2_workers.py`): 48 files sampled (seed 7) from the 247 `tests/agent_runtime` files whose gate line read 0.5–4 s, i.e. the median population, NOT the tail; `--file-retries 0`.

The table is §1.2; the per-run logs are `m2-<label>.log` (scratch). The 12-worker rows are NOT a 12-worker measurement of the gate — eight bundles cannot load twelve workers — and the load-flake they surfaced (`test_work_service.py::test_concurrent_retry_admits_one_native_task`, red in two different bundle compositions at 12, green at 8 in both shapes) is rowed in the report.

### 2.3 M3 — the slow tail, one file per process, serial, `--durations=40 --durations-min=0.3` (`m3_slowtail.sh`)

Serial, idle box, one file per process, bare `pytest` from this lane's shell (which carries the operator's `HERMES_HOME`, so the real-home I/O guard `tests/conftest.py::_forbid_real_hermes_home_io` — `tests/home_io_guard.py::HomeIOGuard`, installed by monkeypatch, raises BEFORE the call — refused two tests that write under `<HERMES_HOME>/logs` and the shared character drafts: `test_run_agent.py::test_aiagent_reuses_existing_errors_log_handler`, `test_charsheet_pipeline.py::test_the_shipped_walk_e_row_crops_whole_frames`; both were green in the gate under `env -i`, the named paths' mtimes are unchanged, and this is the guard working, not a finding). `test_duplicate_helper_bodies.py`'s 2 reds are `main`'s (in the gate's 36). Session seconds are the file's `in Ns` line; "listed" is Σ of the `--durations` items ≥ 0.3 s, so session − listed is the sub-0.3 s floor.

| file | session s | gate s | listed ≥0.3 s | where it goes |
|---|--:|--:|--:|---|
| `test_gateway_peer_two_roots_e2e.py` (9 t) | 265.8 | 182.5 | 265 | **setup 55 s + teardown 9 s + call 201 s**: `two_installs` is a FUNCTION-scoped fixture (`tests/agent_runtime/_serve_fixtures.py`) that boots two real `harness serve` children per test; each call is 22–40 s of CLI invocations against them ("two real serve boots plus five CLI invocations, each a cold interpreter start", the file's own comment) |
| `test_native_conversation_roundtrip.py` (4 t) | 234.5 | 146.8 | 234 | call 232 s: four 46–69 s real native A→B→A turns with persistent sessions, parametrized shared/private profile |
| `test_native_large_recovery.py` (2 t) | 146.8 | 110.5 | 146 | call 144 s: 80 s (compute-child) + 64 s (inline) for the 5 MiB payload |
| `test_embedded_phone_session.py` (6 t) | 136.2 | 129.4 | 132 | call 131 s, in two parametrizations of ONE test (95 s + 34 s): sign-in and one chat turn through a real child |
| `test_charsheet_pipeline.py` (112 t) | 136.3 | 161.7 | 124 | call 121 s in ~40 tests of 3–8 s each: real art generation/validation per test, setup only 2.5 s |
| `test_run_agent.py` (281 t) | 173.8 | 232.8 | 65 | 40 tests of 1.3–4.8 s hold 65 s; **the other 241 tests average 0.45 s each (109 s)** — a per-test floor in this file four times the suite's, in CALL not setup (setup 0.0 s listed): `AIAgent` construction inside the test body |
| `test_persona_assignments.py` (132 t) | 99.6 | 103.1 | 52 | 40 tests of 0.9–3.6 s = 52 s; the other 92 average 0.5 s: a store per test |
| `test_tombstone_registry.py` (1,228 t) | 89.5 | 135.7 | 5.3 | **84 s is 1,224 tests under 0.3 s each — ≈ 0.07 s/test, which is THE SUITE'S PER-TEST FLOOR (35 autouse fixtures + tmp_path + guards), not parsing**; the scan cache works as designed (`test_the_scan_path_cache_is_keyed_so_repeat_scans_are_free` 2.4 s) |
| `test_coverage_claims_resolve.py` (4 t) | 87.8 | 127.6 | 87.5 | **setup 83.5 s in ONE module-scoped fixture `scan` = `collect_claims()`** (a collection of every test id the claims name), call 4 s |
| `test_relay_session_lifecycle.py` (64 t) | 87.3 | 65.2 | 66 | 40 tests of 1.3–2.6 s: a relay round-trip per test |
| `test_harness_characters_cli.py` (108 t) | 85.3 | 114.5 | 70 | call 67 s: 3–6 s CLI flows |
| `test_discussion_runtime.py` (8 t) | 80.4 | 108.4 | 77 | one test is 47 s (`test_twelve_same_profile_instances_run_distinct_sessions…`), the rest 3–6 s |
| `test_duplicate_helper_bodies.py` (5 t) | 46.4 | 87.7 | 45 | call 41 s: four fork-wide AST walks of 8–14 s each (the same walk, four times) |
| `test_s56_runtime_config_reader_gate.py` (56 t) | 39.5 | 60.9 | 11.7 | setup 6.5 s once (the walk), call 4.4 s; the other 28 s is 54 tests at the floor |

Gate seconds exceed the idle serial seconds by 1.2–1.5× for the CPU-bound files (8-way contention) and are LOWER for the two e2e/native files whose gate line was a `rerun` on an idle tail. Two corrections to §1.3 fall out: class B's biggest file is floor-bound (tombstone: 1,228 tests × 0.07 s), and its second is one fixture (coverage claims: 83 s of `collect_claims()`); the duplicated parse is real but smaller than the class total (≈ 150 s across `test_duplicate_helper_bodies`, the `test_sNN_*` setups and the tooling gates).

---

## 3. The stages

Order: cheapest and safest first, each landable alone, each with its measurement in the gate's own log (Stage 0 makes that log say the numbers this note had to reconstruct). Expected savings are against the 987 s runner wall of §0.1 and are **projections** until the gate confirms them; the risk column names what each stage can break.

### Stage 0 — the gate measures itself (instrument; no behaviour change)

**What:** `scripts/run_tests_bundled.py::_print_summary` prints, after the Summary line, the breakdown §0.1 had to reconstruct: Σ per-file seconds, worker-seconds, utilization, the critical-path bundle (index, wall, first/last member), start-up seconds (Σ over processes of session-start − process-create, which `hermes_bundle_report.py` can record from `time.time()` at `pytest_sessionstart` against the runner's spawn time), the seconds spent re-running red members (their bundle attempt AND the rerun), and the slow tail (the 20 slowest files with their class, when Stage 4's marks exist). The same numbers go into `test_durations.json`'s sidecar as one JSON line per run so a landing's report can quote them.
**Expected saving:** none. **Risk:** none (a print). **Why first:** every later stage's "saving" is otherwise a reconstruction from a log; the rule is that a control not run is a belief.

### Stage 1 — the committed upstream-red skip list (owner ruling 2026-10-05)

**What exists.** Three things already carry upstream-red knowledge, each at a different grain: `tests/_downstream/id_markers/upstream_reds.py` (86 `_up_red` / `_up_red_skip` / `_up_red_when` rows by TEST ID, win32-only, applied at collection by `id_markers/hooks.py`; a row for an id that no longer exists is a UsageError, which is how a fixed upstream red retires); `scripts/test_bundles_unbundled.txt` (files that run ALONE, with the observed leak line; a format with one path per line and a `#` reason — the shape to copy); `tests/fixtures/upstream_manifest.txt` (the 16,794-path list of what is upstream's, base `ee5f49b943`, read by `load_manifest`). What none of them does is keep a whole upstream FILE out of a run: an `_up_red_skip` row still collects the file (the P0 freeze happens in flight, with the whole-file module imported and its fixtures running), and the manifest says what is upstream's, not what is red.

**The list.** `tests/fixtures/upstream_skip_list.txt`, beside the manifest it is a subset of. One row per upstream test file, three fields separated by ` · ` after the path, so a reader and the runner parse the same line:

```
# path · why (the red it shows, or the host condition) · upstream SHA it was recorded at
tests/hermes_cli/test_source_check.py · P0: in flight at both 2026-10-05 workstation hard freezes (fork-hygiene-queue P0 row); run only under a watchdog/VM · ee5f49b943
tests/hermes_cli/test_source_launcher_publication.py · P0: same; republishes the running hermes.exe (h10-fhrel verdict) · ee5f49b943
tests/hermes_cli/test_source_release_channels.py · P0: same · ee5f49b943
tests/hermes_cli/test_source_release_probe.py · P0: same · ee5f49b943
tests/agent/test_run_agent.py · (example only — NOT on the list: the file is upstream's but its reds are the fork's codex seam, fixed not skipped)
```

A row's `why` starts with a class word the merge lane keys its re-check on: `P0` (freeze candidate: re-run only under the watchdog/VM the P0 row names), `env` (environmental: a provider-network hang, a WSL bash shadow, a missing `acp`/`ripgrep` — re-run bare, expect the same red), `upstream` (an upstream bug with its issue/PR link — re-run bare, drop when green). The `upstream SHA` is the `upstream/main` tip the red was recorded against; the merge lane compares it to the merge's incoming tip to know which rows it owes a re-check (all of them, the first time).

**How the runner reads it.** `scripts/run_tests_bundled.py::select_scope` gains one input, `skipped: set[str]` (loaded by a `load_skip_list(path)` twin of `load_manifest`, same comment rules, the three fields split on ` · `), and one more bucket on `ScopeSelection`: `skipped_red: List[Path]`. A discovered file on the list goes there and nowhere else, in BOTH scopes — `fork` and `full` — and is printed in the scope report (`select_scope`'s listing already prints each bucket) with its `why`, so a run says what it did not run. A file named explicitly on the command line (`named`) still runs: that is how the merge lane re-checks one (and how a P0 file is run under the watchdog on purpose). `scripts/run_tests_parallel.py` (the per-file authority) is untouched: `scripts/run_tests.sh <file>` is the deliberate way to run a listed file alone.

**The gate that refuses a fork file.** `tests/scripts/test_upstream_skip_list.py`, beside `test_upstream_footprint.py`: every path on the list is in the manifest (an upstream file), exists in the tree, parses into three fields, carries a class word and a 10-hex SHA; and — the positive guarantee — `select_scope` over the real tree with the real list puts no fork-only file in `skipped_red` (build the selection and read it). Killing mutation, recorded in the landing commit: append a fork-owned path (`tests/agent_runtime/test_config.py`) to a copy of the list → the gate reds on "fork files are fixed, never skipped".

**The merge-lane re-check step.** One line in `Harness_Brain/50 — Agent Handoffs/Merging upstream.md`, as Step 5b after "Touched tests directly": *"5b. Re-check the skip list: `scripts/run_tests_bundled.sh --scope full --files-from tests/fixtures/upstream_skip_list.txt`-shaped — i.e. name every `env`/`upstream` row's file explicitly (named files always run), background, log, unpiped exit code; a file green on the merge candidate leaves the list in the merge commit, a file still red keeps its row with the SHA advanced to the incoming upstream tip; `P0` rows are NOT run here — they wait on the P0 row's watchdog/VM precondition and keep their SHA."* And Step 7's gate command becomes `scripts/run_tests_bundled.sh --scope full tests` (the skip list applies; the stale `run_tests.sh` three-directory form on that page is the same disagreement the P0 row names in `CLAUDE.md`).

**Seeding the list.** From the two sources on record: the four P0 files; the handoff's "~142 environmental reds on a green `main`" triage of 2026-09-01 (`hermes-suite-perf.md` § Follow-ups: provider-network hangs, WSL bash shadowing, `acp`/`ripgrep` holes) — each file re-run ONCE, bare, on the seeding lane's box before it is rowed (a row is evidence, not a memory); and the upstream-owned members of the gate's 36 red files (`tests/agent/test_run_agent_codex_responses_downstream.py` is fork-owned; the 35 others are in `tests/agent_runtime`, `tests/hermes_cli`, `tests/scripts`, `tests/tooling`, i.e. FORK files that the ruling says get fixed — the seeding lane confirms each against the manifest and files a fork-hygiene row per fork red it cannot fix, never a skip row).

**Expected saving.** Fork gate: **0 s today** (none of the 872 files is on the list; the listed files reach the fork scope only when a change touches them by name/import/conftest, and then they run — a named-or-reached listed file is UNVERIFIED territory: the plan recommends `skipped_red` wins over `importer`/`source`/`conftest` but NOT over `named`; OPEN RULING O1). Full scope: the four P0 files out of flight is what makes `--scope full` runnable on a workstation at all (the P0 row's precondition for lanes), and every `env` row removes a file that today either hangs to its 300 s file timeout or reds — at ~35 such files × up to 300 s ÷ 8 workers that is **up to ~20 min of a full-scope run** (UNVERIFIED: the first full-scope run under Stage 7's watchdog is the measurement). **Risk:** a skipped upstream file hides an upstream regression the fork would have caught — bounded by the merge lane's re-check (every `env`/`upstream` row runs again every week) and by the rule that a fork file is never listed.

### Stage 2 — stop paying twice for the red set

**What:** (a) a red bundle re-runs ONLY the members that recorded a failure (already so, `members_to_rerun`) — but the gate log shows the rerun lines include the three heaviest reds (147 + 128 + 88 s) whose first attempt was paid in the bundle too. Make the rerun conditional on the member's failure being POSSIBLY an isolation leak: a member whose failing node ids are in the run's own `test_durations.json` sidecar as "failed alone last run" (Stage 0 records failed node ids per file) is reported red from its bundle result without a rerun; the rerun is reserved for a member that is newly red. (b) Submit solos and known-slow reds first (the LPT already orders bundles longest-first; the reruns are the problem because they come LAST, after the bundles, on a nearly idle pool — the log shows the 39 reruns as items 834–872).
**Expected saving:** ~100 s of wall (§0.1's decomposition: ~1,600 worker-s of double-run, most of it at the tail where fewer than 8 workers are busy). **Risk:** an isolation leak that persists two runs is reported from the bundle, never confirmed alone — mitigated by keeping the rerun for any member whose failing set CHANGED between runs. UNVERIFIED: Stage 0's "seconds spent re-running" line on the next two gates is the measurement.

### Stage 3 — duration-aware bundles and a solo-first tail (scheduling)

**What:** `assign_bundles` cuts bundles by path order and count (20); replace the count with a duration budget — members are added in path order until the bundle's Σ cached duration would exceed `--bundle-seconds` (default 120 s; a member alone over the budget is its own bundle) — and put every file whose cached duration is over `--solo-seconds` (default 60 s; today 24 files) into `solos`, submitted FIRST. Bundles stay within a top-level directory (the leak-isolation property the unbundled list depends on). The per-bundle timeout rule (`bundle_timeout`, 3 × Σ estimates) and `Death` handling are unchanged.
**Expected saving:** at 8 workers, ~0 (§0.1: LPT of the path bundles is 744 s against a 747 s floor). At 12 workers the floor moves from 504 s to 498 s, at 16 from 474 s to 374 s — this stage is what Stage 5's worker increase buys from. The 24 solos also remove the §0.1 tail (a 474 s bundle whose last member is a 180 s e2e file finishing alone).
**Risk:** more processes (24 solos + ~50 bundles) → +~70 s of start-up CPU, ~10 s of wall. A file whose cached duration is missing is estimated at 30 s (existing `_UNCACHED_ESTIMATE_SECONDS`). **Positive control** for the landing commit: feed `assign_bundles` the gate's durations and assert the longest bundle ≤ 120 s + the largest single member.

### Stage 4 — the tail, by class (the test files themselves)

Each sub-stage is its own lane and lands alone; each starts from M3's per-test phase durations (§2.3) and names its before/after from the file's gate line. The marks below are registered in `tests/_downstream/conftest_plugin.py` (the fork's marker home), so Stage 0's tail report can name a file's class.

- **4B — the gate class (901 s ≈ 15 %), three different fixes because M3 (§2.3) found three different costs.** (i) **The tombstone registry is floor-bound, not parse-bound:** 1,228 parametrized tests at ≈ 0.07 s each = 84 of its 89 s; the scan caches already make repeat scans free. The fix is fewer pytest items: one test per ROW FORM (`MODULE`, `ATTR`, `CLASS_ATTR`, `EVENT`, `CODE`, `PATH`) that walks its rows and reports every failing row's label in one assertion message (the table stays the authority; what changes is that 1,228 fixture stacks become 6). Saves ~80 s of CPU. (ii) **`test_coverage_claims_resolve.py` is one 83 s module fixture** (`scan` = `collect_claims()`, which resolves every test id a coverage claim names): cache its result on disk keyed by the tree's `git ls-files` hash of `tests/` + the claims' sources (the inputs are the tree; a cache hit is proven by the key) — ~80 s per run, every run. (iii) **The duplicated fork-wide AST walk** — `test_duplicate_helper_bodies.py` walks the fork four times (8–14 s each), the `test_sNN_*` gates once per module (6.5 s setup in `test_s56…`), `tests/tooling` and `tests/scripts` gates once each — is ≈ 150 s: route every walk through `tests/agent_runtime/_tree_index.py` (the tombstone registry's docstring-stripping render keeps its own parse, as designed) and replace `_drop_tree_index_between_modules`'s clear-at-every-teardown with a bound: text cache kept, parsed ASTs behind an LRU of ~200 files (the 2026-09-01 note's 785 MB / 839 files ≈ 0.94 MB per AST), and a `gate` bundle key in Stage 3 so the gate modules share one process and one warm cache. **Expected saving:** ~300 s of CPU ≈ 40 s of wall at 8 workers; (i) and (ii) are each one fork-owned file. **Risk:** (iii)'s memory in the gate bundle — the 30 s per-test timeout was the 2026-09-01 symptom; the LRU bound is the guard and Stage 0's peak-RSS line (`psutil.Process().memory_info()` at session end in the plugin) is the measurement. Ruling R4 (2026-09-01) already allows a shared materialization with the sabotage round-trip per ported file; (iii) is the same ruling, wider lifetime; (i) and (ii) change no gate's reach.
- **4A — the e2e child class (638 s ≈ 11 %, 14 files).** Mark `e2e_child`; Stage 3 solos them first. M3 (§2.3) settles where the seconds are in the heaviest file: `test_gateway_peer_two_roots_e2e.py` pays **55 s of setup + 9 s of teardown for 9 tests** — `two_installs` (`tests/agent_runtime/_serve_fixtures.py`) is FUNCTION-scoped and boots two real `harness serve` children per test — and 201 s of call that is 5 cold CLI interpreter starts per test against those children. The cut with no fidelity loss is the CLI side: the file's own comment names "five CLI invocations, each a cold interpreter start" — drive the verbs in-process through `dispatch_argv` where the test asserts the VERB's effect on the serves (most of them) and keep the child CLI only where the test asserts the process boundary (R5's 2026-09-01 criterion, applied per site). A module-scoped `two_installs` is allowed only for tests whose assertions do not depend on a fresh pair (the pairing tests do; the roster/thread/revoke tests may not — a read of each test says). **Expected saving:** ~40 % of the class ≈ 250 s CPU, and — since these files are the critical path at any worker count — most of it is wall. **Risk:** the e2e files exist to prove the process boundary; every converted site names which assertion it keeps.
- **4C — the native/discussion in-process class (1,053 s ≈ 18 %, 38 files).** M3: the time is real native turns — `test_native_conversation_roundtrip.py` is four 46–69 s A→B→A turn sequences, `test_native_large_recovery.py` is 64 + 80 s for the 5 MiB payload (compute-child slower than inline), `test_embedded_phone_session.py` is one test's two parametrizations (34 + 95 s), `test_discussion_runtime.py` has one 47 s test (twelve same-profile instances). Three cuts: (i) size the payload to the THING UNDER TEST — `test_native_large_recovery.py` wants "a response larger than the disposable replay ring"; parametrize the ring size down (a 512 KiB ring with a 1 MiB payload proves the same property) — UNVERIFIED that the ring is parametrizable, the file's docstring says the ring is "disposable", which is the knob; (ii) the 95 s phone parametrization and the 47 s twelve-instance test get `@pytest.mark.timeout` already — mark them `slow_native` and let Stage 3 solo them FIRST, which is where the wall goes; (iii) `until`'s `timeout=90` ceilings were raised "under suite CPU load" — soloed first, they no longer run under it. **Expected saving:** ~25 % of the class ≈ 250 s CPU; the wall saving is Stage 3's.
- **4D — `test_run_agent.py` (233 s gate / 174 s idle, 281 tests) and `test_run_agent_codex_responses.py` (93 s / 67).** M3: setup is 0.0 s listed and CALL carries it — 40 tests of 1.3–4.8 s (65 s) and **241 tests at ≈ 0.45 s each (109 s), a per-test floor six times the suite's 0.07 s, inside the test bodies**: `AIAgent(...)` built in each test (`agent/agent_init.py` walks toolsets, skills and MCP catalogs per instance; `discover_plugins()` is process-once at 0.78 s). The fix is a prebuilt, module-scoped agent TEMPLATE the fork's `tests/_downstream/agent_conftest.py` offers and the upstream file does not request — so it helps only the fork's `_downstream.py` siblings — OR an autouse fork fixture that pre-warms the pure caches `AIAgent.__init__` reads (skills index, MCP catalog, toolset manifest) so each construction is cheap (OPEN RULING O3: it changes nothing a test asserts, but it is an effect on an upstream file's tests without an edit). **Expected saving:** ~0.3 s × 348 ≈ 100 s CPU ≈ 12 s wall. **Risk:** `test_run_agent.py` is UPSTREAM's; an edit there is a footprint.
- **4E — charsheet (379 s ≈ 6 %, 3 files hold 368 s).** 0.6 s/test with 39–62 `tmp_path` sites per file: generated art per test. Session-scoped generated fixtures (`tmp_path_factory`-backed, read-only, copied into the test's `tmp_path` only where a test writes). **Expected saving:** ~40 % ≈ 150 s CPU ≈ 20 s wall. **Risk:** low (fork-owned files, pure fixtures).
- **4F — store-heavy (273 s ≈ 5 %).** `test_persona_assignments.py` 0.78 s/test over 132 tests: a `PersonaInstanceStore` per test on disk. Same shape as 4E (a seeded store template copied per test). ~100 s CPU ≈ 12 s wall. **Risk:** low.

Together, Stage 4 is projected at **~1,300 s of CPU ≈ 160 s of wall at 8 workers**, and — more important for Stages 5–6 — it flattens the tail that caps the worker count.

### Stage 5 — re-take the worker count under the bundled runner (the 2026-09-01 "12 rejected" verdict is pre-bundling)

**What:** `HERMES_TEST_WORKERS` is ruled at 8 (`CLAUDE.md`: "12 measured slower and load-flaked; do not raise"). That measurement (`hermes-suite-perf-field-notes-2026-09-01.md` §14) was PER-FILE mode: 1,089 processes paying ~6 s of start-up each under 8-way contention, where 12 workers inflated the start-up faster than they divided the work. The bundled runner spawns ~93 processes. §1.2 is the re-take on the median sample; the box has 8 physical / 16 logical cores and 32 GB. The stage is: after Stages 3–4, run the gate at 8, 12 and 16 (one at a time, idle box, Stage 0's utilization line read each time) and change the ruled default to the fastest STABLE count — "stable" = the failure SET is identical across the three runs (the 2026-09-01 criterion). **Projected:** with Stage 3's per-file LPT, 12 workers → ~500 s floor, 16 → ~375 s, against 747 s at 8 — i.e. the single largest lever after the tail, **IF** the work is CPU-bound rather than I/O- or lock-bound (classes A and C hold sockets and SQLite WAL files; 16 of them at once is the load that flaked `test_serve_rpc_office_subscribe_live_hub.py` in 2026-09-01's probe). §1.2's curve says which. **Risk:** load-flakes in classes A/C → mitigated by Stage 3 (solos first, so at most ~24 of them overlap, and only at the start). **OPEN RULING O2.**

### Stage 6 — test-impact selection for the LANE run (not the landing)

**What:** the handoff tells a lane to `grep -l` the modules it touched under `tests/` and run those files. Mechanize it as `--scope impact` on the bundled runner: `select_scope` already computes `importer`/`source`/`conftest` reach for UPSTREAM files; `impact` applies the same reach to EVERY file (fork-owned too) — a file runs if it changed, its convention-mapped source changed, it imports a changed module (transitively, one level: the changed module's own importers via the `imported_modules` AST read over `tests/` and the production packages), or a conftest above it changed. The landing keeps `fork` (every fork file). **Expected saving:** none on the gate; a lane's end-of-lane run drops from "whatever grep said" to a computed set, typically 20–80 files ≈ 1–3 min. **Risk:** a transitive import the one-level walk misses — the landing gate still runs everything fork-owned, so the miss costs a landing red, not a shipped defect.

### Stage 7 — the full scope, safely (the weekly merge lane's run)

**What it is:** `--scope full` over `tests` = 6,066 files (865 fork + 5,201 upstream, ~52,600 tests). It froze the workstation twice on 2026-10-05 with the four P0 files in flight. Order of operations: (1) Stage 1 lands with the four P0 rows → the files are out of every run; (2) the watchdog the P0 row asks for is the RUNNER's own: `--file-timeout` already kills a process tree at 300 s, but a hard freeze is the OS, not pytest — so the full scope runs with `-j 4`, `--bundle-seconds 120`, Stage 0's log line flushed per bundle (so the interrupted log names what was in flight, which the P0 row says is how the second freeze was avoidable), and never with the operator's gateway up (the P0 row's one recorded difference between run 1 and run 2); (3) the first run is the measurement of upstream's per-file cost on this box — the 2026-09-24 note has only a LOADED upstream number (session start → end median 4.2 s/file: 1.39 s collect + 2.84 s tests), and the 2026-09-25 `test_durations.json` in the primary holds 173 upstream files at a median 31 s of per-file WALL in per-file mode (start-up included), neither usable for a projection better than ±50 %. **Projected (UNVERIFIED — the first run settles it):** 5,201 upstream files × ~4.2 s ≈ 22,000 s of CPU + the fork's 5,977 s ≈ 28,000 s → **~58 min at 8 workers, ~40 min at 12, ~35 min at 16** after Stages 1–5; before them, with the ~35 `env` reds each hanging to a timeout, over 80 min. **Sharding** across the two machines is already in the runner (`--slice i/n` with LPT over cached durations); the merge lane's job description can run the Mac half with `--slice 1/2` once the Mac has a durations cache — OPEN RULING O4.

### 3.9 Projected wall after each stage (fork gate at 8 workers; UNVERIFIED until Stage 0 prints it)

| after | fork gate (runner wall) | what moved | full scope |
|---|--:|---|--:|
| today (2026-10-05) | 987 s (16.5 min) + ~90 s outside | — | not runnable (P0) |
| Stage 0 | 987 s | instrumented | — |
| Stage 1 | 987 s | 0 on the gate; full scope becomes runnable | ~80 min (-j 4, UNVERIFIED) |
| Stage 2 | ~890 s | the double-run of reds (~100 s) | — |
| Stage 3 | ~870 s | the tail at 8 workers (~20 s); enables 5 | — |
| Stage 4 (all six) | ~710 s (12 min) | ~160 s of wall from ~1,300 s of CPU | ~70 min |
| Stage 5 at 12 workers | ~470 s (8 min) | IF the §1.2 curve holds past 8 | ~45 min |
| Stage 5 at 16 workers | ~380 s (6.5 min) | IF CPU-bound | ~35 min |

The launcher's 8 min for 40,000 tests is not a comparable floor: it is ~0.012 s per test of pure in-process unit work on a VM-hosted runtime. The equivalent fork number is class G's 0.27 s/test of real store and process work; the stages above do not change the tests' nature, they stop paying for the same work twice and start the long work first.

---

## 4. OPEN RULINGS (operator decisions; none pre-empted) and recommendations

| # | question | trade | recommendation, with numbers |
|---|---|---|---|
| O1 | **Stage 1 precedence:** when a listed upstream file is REACHED by a change (its source changed, it imports a changed module, its conftest changed) but not named, does it run? | missing an upstream regression the change caused vs re-freezing a workstation from a lane that touched `hermes_cli/source_*` | **Skip wins over reach; only `named` runs it.** A lane that touches a P0 file's source names it on purpose and runs it under the watchdog; everything else waits for the merge lane's re-check. The scope report prints the reached-but-skipped files so the lane knows. |
| O2 | **Stage 5:** raise the ruled default from 8 if the gate at 12/16 is faster with an identical failure set on three runs? | wall vs the 2026-09-01 load-flake class in A/C | **Yes, conditionally** — after Stages 3–4 only (solos first bound the A/C overlap), three identical failure sets, and the Stage 0 utilization line above 85 %. The 2026-09-01 verdict stands until then; it measured a runner that no longer exists. |
| O3 | **Stage 4D:** `test_run_agent.py` is upstream's; may the fork add a session-scoped agent template through `tests/_downstream/agent_conftest.py` (a fixture the file does not request → no effect) or through an autouse fork fixture that pre-warms what `AIAgent.__init__` walks (an effect on an upstream file's tests without editing it)? | 233 s vs an invisible behaviour change under upstream's tests | **Autouse pre-warm only for walks that are pure caches (skills index, MCP catalog), never for state the tests assert on; if M3 says the cost is the turn itself, leave the file alone and row it as an upstream-owned slow file (Stage 1's `upstream` class does not apply — it is green).** |
| O4 | **Stage 7 sharding across the Mac:** run the weekly full scope as two `--slice` halves on two machines (one durations cache shared through the repo? it is git-ignored today) | a ~35–45 min run vs a second machine's time and a committed durations file | **Not now.** Land Stages 1 + 7 single-machine first and read the number; commit a `tests/fixtures/test_durations.baseline.json` (slow-tail only, >30 s files) if sharding is wanted — the runner's `_load_durations` reads one file, so this is a small change. |
| O5 | **Stage 2's rerun policy:** report a repeat-red from its bundle without the solo confirmation? | ~100 s per gate vs the leak diagnosis the bundled runner exists to give | **Yes for a member whose failing node set is identical to the last recorded run; the rerun stays for anything new.** The ISOLATION LEAK report is unchanged for new reds. |

**Recommended dispatch order:** Stage 0 + Stage 1 as ONE lane (the list's seeding needs the instrumented log to prove each `env` row); Stage 2 + Stage 3 as one lane (both are `run_tests_bundled.py` scheduling, one CHANGE commit); Stage 4 as six lanes (4B first — largest and purely fork-owned — then 4C, 4E, 4F, 4A, 4D last pending O3); Stage 5 as a measurement lane after 4B/4C land; Stage 6 whenever; Stage 7's first run as the next weekly merge lane's step, after Stage 1. Every CHANGE commit carries its positive control (the defect planted on a throwaway copy, the red pasted into the body); every projected saving above is replaced by Stage 0's printed line in the landing report.

---

## 5. Field notes (what this lane ran, in order; tool-call count in the report)

1. Worktree `X:/Eternia/worktrees/hermes-suite-speed` at `8fdb6b81dc`; read the handoff, the two queue rows, both runners, the wrapper, the bundle plugin, the conftests, pyproject's `[tool.pytest.ini_options]`.
2. Parsed `gate-w2.log` (872 per-file lines) → `gate-w2-files.tsv`; reconstructed the 52 bundles with `assign_bundles`' rule and simulated LPT at 8/12/16 (§0.1).
3. `./activate --` on the worktree: 53 s cold (the gate log's own activation line is the same cost a landing pays on a fresh worktree). `scripts/ensure_fork_dev_deps.py` once (the fresh env lacked `pytest-timeout`, which is why a first probe collected nothing).
4. M1 (`m1_startup.py`): §1.1. The `-X importtime` log is `m1-importtime.log`.
5. M2 (`m2_workers.py`, one run at a time, no other pytest on the box by `wmic`): §1.2.
6. M3 (`m3_slowtail.sh`): §2.3. **Incident, filed as a row (report):** M3 ran bare `python -m pytest <file>` from this lane's shell, which carries the operator's `HERMES_HOME=X:\Eternia\.hermes`. The pytest PROCESS was sandboxed (`tests/conftest.py` mints a session home at import; the real-home I/O guard refused the two in-process writes named in §2.3) — but the real `agent.log` gained 142 lines between 21:31 and 21:46 from the tests' CHILD processes: the two-roots `harness serve` children and the native-conversation compute children, logging turns against their fake codex providers on `127.0.0.1:<ephemeral>` (sessions `20261005_2131…`, `_2132…`, `_2140…`, `_2146…`), plus one pm `sync` receipt at 21:38:48. No state write was found (`errors.log`, the character drafts and the named paths are untouched). The mechanism is the gap the handoff's "ONE file, debugging only" rule leaves open: a child that rebuilds its env from the platform default, or strips `HERMES_HOME`, resolves the real home. The row: **a test's child process can log to the operator's real `agent.log` when the parent pytest was launched from a shell with the live `HERMES_HOME`** · `fork / suite` · this note §5 step 6 · UNCLAIMED — the fix is the runner's `env -i` applied to the single-file path too (`scripts/run_tests.sh <file>` is the per-file authority for exactly this reason), and a child-side check that `HERMES_TEST_ISOLATION` is honoured by `setup_logging`, not only by the state-db guard.
7. Static censuses: autouse fixtures per conftest; `time.sleep` (52 files / 132 calls in `tests/agent_runtime`; 17 in `agent_runtime/` source); `@pytest.mark.timeout` (25 unmarked, 32 at 45–300 s); `_tree_index` users (4 test files + the conftest); the two `scope="session"`/`"module"` fixtures in `tests/agent_runtime/conftest.py`.
