---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue


- **`FORK-MACOS-CI-TRIAGE` — Triage upstream/macOS jobs exposed by the subagent-history PR's broader CI matrix.** Run `38832830663`, macOS shards `116755299378` / `116755299386`, fails in update/PM/source-stamp/MCP subprocess fixtures: copied update trees lack `agent_runtime`, import probes hit the live-system guard, and PM/tool fixtures touch the setup environment. These files are outside Step 5's changed paths; Windows fork-scope qualification does not establish a macOS baseline. Reproduce on the same native CI host against the base before attributing or exempting them. Preserve the run logs; do not weaken live-system guards or grow the skip list from this report. · fork / CI · read 2026-10-16 (r-sync, `gh run view --log`): shard 1 = 17 reds in 6 files (update_missing_configured_deps, sessions_held_store_gate, update_import_guard, update_posix_pause, source_build_env, mcp_death_supervisor), shard 2 = 8 errors + ~20 failed (doctor_pm_store_probe, doctor_command_install, update_finish "No module named 'agent_runtime'" from the copied tree, update_pause_step_interruptions, update_post_commit_safety, update_recovery_closure, pm runtime_bootstrap_tls / update_dependency_legs); no `main` push runs the macOS matrix (runs 38884451206, 38976202285 carry no macOS job), so no base exists to compare · BLOCKED 2026-10-16: owner sitting — a macOS CI run on the base (`workflow_dispatch` of CI on `main`, or a Mac host) — triggering one needs the owner's GitHub account

- **`FORK-OWNER-CONTRIBUTOR-IDENTITY` — Resolve the fork owner's existing commit identity in contributor attribution.** PR #11 run `38832830663` rejects the configured owner author email because it has no contributor mapping. Step 5 retains the repository's established author and required co-author footer; no identity is fabricated or rewritten. Confirm the owner account mapping through the existing contributor tooling, with any upstream-file footprint accounted for. · fork / CI · READY 2026-10-16 · **TAKEN 2026-10-16 claude (r-sync)**

- **`FORK-SECOND-WORKSTATION-ENV` — Qualify the canonical shared test environment on the second Windows workstation before treating the PM slow-exit check as covered there.** Baseline re-audit on `5fc3c617df` (2026-10-15): with no explicit `HERMES_PYTHON`, `scripts/run_tests.sh tests/pm/test_worker_slow_exit_downstream.py` refuses before collection because this Windows account has no shared environment with pytest at `~/.venvs/hermes-test`. Explicitly selecting this clone's Python 3.13.15 reproduces the PM fixture's Python 3.14 requirement error; no worker assertion runs. Commit `646acfb921` established a genuine 1/1 pass on another account's shared Python 3.14.5 environment, not this workstation. Use the existing shared-environment setup and runner, then rerun the single file; do not change upstream's fixture, relax the Python requirement, or add another runner. Evidence: `scripts/run_tests.sh`, `tests/pm/_fixtures.py::isolated_python`, `pm/pyproject.toml`; local re-audit receipts retained. Environment setup, not a demonstrated PM or Eternia runtime defect. · BLOCKED 2026-10-16: owner sitting — set up the shared `~/.venvs/hermes-test` (Python 3.14) on the second Windows workstation's account, then rerun the one file



- **`FORK-RESTORE-FULL-LOCAL-LINT` — Restore the full local lint gate on current main.** The October 14 session-controls qualification reproduced `scripts/check --only footguns,no-tmp,ruff` on unchanged main: all three fail, with 2,121 ruff findings. The candidate's changed production modules pass ruff and its health ratchet has zero blocking/advisory findings. Repair the existing footgun diagnostics, literal temporary-path documentation findings and repository-wide typing/style residue without weakening the checks. The Windows output-encoding issue has its own row below. · fork / lint · evidence: `docs/downstream/session-controls-2026-10-14.md` · measured 2026-10-15: 2,080 ruff findings (2,043 in 763 fork files, 37 upstream), 117 footguns (107 fork), 4 no-tmp; the `--fix` sweep touches 763 files every concurrent lane edits; upstream's 37 stay upstream's · RULED 2026-10-15 (owner): keep upstream's lefthook pre-commit and do one clean-up sweep of fork files, as a solo lane straight after the next landing; never `--no-verify` · BLOCKED 2026-10-16: another lane — a solo window straight after the next hermes landing, with no other lane open









## Filed on arrival — 2026-10-16 (landing land-h5, reds proven on `origin/main` `b11585e6424` by `scripts/run_tests.sh` alone)


## Filed on arrival — 2026-10-16 (build lane h-bundle-speed, reds proven on `origin/main` `aba5fec098c`)


## Filed on arrival — 2026-10-16 (build lane h3-runser)

- **`FORK-CHECK-HEALTH-BLE001` — `scripts/check --only health` reds every pre-existing BLE001 in a file the change touches, so a docstring-only edit to `agent_runtime/mcp_admission/registration.py` fails the ratchet on 9 old hits** · fork / tooling · `scripts/code_health/compare.py::_hit_findings` (credit from `_owned_base_hits`) · measured 2026-10-16: a detached worktree at `origin/main` `ab6956f11826` plus one docstring word in `release_mcp_admission` reported all 9 `except Exception` hits in that file as new; the pinned ruff finds the same 9 on both sides · find why the base hits are not credited (owner/rename resolution of the base file?) and add the docstring-only case as a fixture · cause found 2026-10-16 (r-isolation): `scripts/code_health/measure.py::Measurer.measure` runs ruff on the base in a bare temp tree with no `__init__.py`, so a relatively imported `logger` reads as a bare name and BLE001 accepts its `exc_info=True` there but not in place (same bytes: 10 hits in the checkout, 1 outside); the measurer is upstream-owned, so the fix and its fixture test are drafted in `docs/agent-runtime-harness/upstream-prs/code-health-package-markers-body.md` (patched: 0 blocking, killing mutation recorded) · BLOCKED 2026-10-16: upstream — that PR, posted in the owner's next posting sitting

## Filed on arrival — 2026-10-15 (audit lane a1015-hfh)


## Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


## Filed on arrival — 2026-10-15 (lane w1015h-rt-h)


## Filed on arrival — 2026-10-15 (landing land-w1015j-h, reds proven on `origin/main` `88414c8d13e`)


## Filed on arrival — 2026-10-15 (landing land-w1015e, pre-existing reds proven on `origin/main` `ef2a4492272`)


## Filed on arrival — 2026-10-15 (lane w1015b-fh-a)


## Filed on arrival — 2026-10-13 (upstream merge v0.21.7)

- **`FORK-REASONING-CAPS-ROWS-CARRY` — The `reasoning-caps` rows carry a disposition the merge lane wrote, not the feature lane: eight `carry` rows name a PR candidate (provider-declared reasoning efforts + the scoped control-catalog cache) that nobody has cut.** The feature's own lane decides `upstream` vs plugin hook and either opens the PR or re-dispositions the rows. · fork / footprint · evidence: ledger rows stage `reasoning-caps`; `docs/downstream/reasoning-capabilities-2026-10-12.md` · BLOCKED 2026-10-16: owner decision — upstream PR or fork plugin hook for provider-declared reasoning efforts, with no reasoning-capabilities lane open? · Recommend: re-disposition the eight rows as fork-kept behind a plugin hook, since the upstream PR branches are idle

## Filed on arrival — 2026-10-09 (final gates)


## Filed on arrival — 2026-10-08 (lane opus-w1-hermes)


## Filed on arrival — 2026-10-08 GenUI qualification

- **`FORK-RUNNING-TURN-STREAM` — Diagnose the running-turn stream intermittent remaining after the HTTPS-scanning control.** After the operator disabled scanning, the ten H01 files pass across controls (96 distinct passes / one existing skip), with certificate and permission assertions unchanged. On `f6c27f4d0b`, `tests/agent_runtime/test_serve_gateway_chat_reply_lanes.py::test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane` fails its six-second start-frame wait under eight-worker load, then both file tests pass serially. The two-roots file also passes all nine when allowed its declared duration; its earlier 120-second cap was a command choice. Trace the start-event publication/fixture boundary before changing behavior or deadlines. The former certificate blocker is qualified; the parallel failure remains evidence. Separate from H03 commentary. · fork / suite · [H01 control and log digests](../../docs/downstream/history-red-triage-2026-10-12.md#https-scanning-control-after-the-operators-setting-change), [H01 diagnosis](../../docs/downstream/stream-delivery-diagnosis-2026-10-12.md#h01-still-open-no-speculative-runtime-change) · no reproduction since `f6c27f4d0b`: the ten-file control passed 96 / one skip three times, the presence repair `911275e641` landed, and the test recorder keeps its reader exception + last 32 frame summaries on a failed wait; keep it as a watch and do not touch deadlines · DEFERRED 2026-10-18: a watch, not lane work — reopen when a landing gate's log reds this node, with the recorder's frame timeline

## Filed on arrival — 2026-10-06 (lane console-generated-content)



The repository AS A FORK: upstream sync and the boundary, CI, the suite and its gates, the god-file refactor, this vault. Runtime and Mission Control rows do NOT go here — the hermes half is [[runtime-queue]], the launcher half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. Rows: one line + a pointer, never a restatement; claim with `**TAKEN <date> <who>**` before starting; a landing deletes its row.

## Filed on arrival — 2026-10-06 (lane h-prereq-window)


## Filed on arrival — 2026-10-05 (owner ask: a usable suite)

- **`FORK-PER-TEST-PLUGIN-LOAD` — Per-test plugin LOAD is what is left of plugin rediscovery: discovery is session-cached since land/q4 (`tests/_downstream/plugin_discovery_cache.py`), but every test still re-imports each plugin and `_resolve_plugin_load_timeout` reads config per plugin; `test_operator_session_models` did not move (64 s)** · fork / suite · q-chain `3adc06ad40` body · Recommend: keep loaded bundled plugin modules across tests and re-run only `register()` against the reset managers, with the cold fixture as the opt-out — re-measured on `9a99d2cc62`: `test_operator_session_models` 33 tests, 35 `discover_plugins` (1,024 `_load_plugin`); a discover is ~0.75 s warm, of which `_resolve_plugin_load_timeout` is 32 calls × 2.6 ms ≈ 0.08 s (the per-plugin config read is not worth an upstream PR alone) and the import + register is the rest — h3-plugins 2026-10-18: built OFF behind `HERMES_TEST_KEEP_PLUGIN_MODULES=1` (`tests/_downstream/plugin_module_keep.py`, contract tests in `tests/test_plugin_module_keep_downstream.py`, branch `q/h3-plugins`); top 15 files, discovery CPU 478 s before → 393 s with the ruling-free deadline memo → 153 s with keep ON (32,451 re-uses, same pass counts in all 15); a multi-home file gains nothing (`test_gateway_migrate_multiplex` 54 → 61 s: per-home module names miss) · RULED 2026-10-18: owner — keep plugin modules loaded across tests (overturns 2026-10-10 "LOAD stays fresh") if a fork gate with `HERMES_TEST_KEEP_PLUGIN_MODULES=1` matches the OFF gate file by file · READY 2026-10-18
- **`FORK-BARE-PYTEST-FILES-SEVERAL` — A bare pytest over files from several test directories hangs `test_gateway_spawn_fence::test_subprocess_run_refuses_the_measured_argv` (the fence is not armed; a real `gateway run` starts) and reddens `test_conftest_isolation_downstream` test_2/test_4; red on main `71079deb70`** · `fork / suite` · evidence: lane h-suite-hermetic report · reproducing it starts a real gateway on the operator's machine · BLOCKED 2026-10-16: owner sitting — a VM or watchdog box off the operator's desktop for the reproduction
- **`FORK-FAST-PARTIAL-FULL-SUITES` — Owner ask: make the partial (fork-scope) and full test suites fast enough to use — the fork gate ran 872 files / ~13k tests in ~18 min wall at 8 workers (per-file seconds summed 5,977; slowest file 233 s), ~13 tests/s, against the launcher's Flutter suite at ~40,000 tests in 8 min (~83 tests/s); the full scope is 6,066 files and on hold for the P0 freeze. Measure where the time goes (interpreter + import cost per process, conftest/fixtures, hermetic env setup, the slow tail, timeouts, Defender, worker count) and write a staged plan** · `fork / suite` · evidence: landing h-turn1 wave 2 gate log (2026-10-05 20:22–20:40 local) · **PLAN `plan/h-suite-speed` `6d2db880cf`; owner took O1–O5 as recommended 2026-10-06; exec lanes h-suite-runner (stages 0–3), h-suite-tail-a / h-suite-tail-b (stage 4); stage 5 after three identical failure sets, 6–7 after** · **Stages 0–4 LANDED `15d4e37d0d` (2026-10-06; full-tree gate 1059 s → 813 s, 99% utilization); open: stage 5 after three identical failure sets, then 6–7** · BLOCKED 2026-10-16: another lane — stage 5 waits on three identical whole-gate failure sets from landing gates

## Filed on arrival — 2026-10-05 (lane h-turn1-title)


## Filed on arrival — 2026-10-05 (lane h-turnws, the workstation freeze)

- **`FORK-P0-VALIDATED-SUITE-FROZE` — P0 — the validated suite froze the operator's workstation twice on 2026-10-05 (hard freeze, reboot both times), and both times the same four files were in flight: `tests/hermes_cli/test_source_check.py`, `test_source_launcher_publication.py`, `test_source_release_channels.py`, `test_source_release_probe.py`. Run 1: `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state`, 8 workers, frozen at 82.5% immediately after `test_source_stamp.py` and `test_spawn_gateway_restart_cooldown.py` reported. Run 2: only the 453 files run 1 never finished, 4 workers, nothing else heavy running, frozen within about a minute, right after `test_source_channel_integration.py` reported (so the in-flight set was a subset of those four). Both runs printed `real store root handed to the gateway fence`, and the operator's own gateway (`hermes_cli.main gateway run`) was up during run 2. NOT reproduced a third time, on purpose. Find which file does it — one at a time, under a watchdog or in a VM, never on the operator's desktop — and until then no lane runs the validated suite on a workstation with these four in scope** · `fork / suite` · the two interrupted run logs are not in the repo; the facts above are their last lines · the 311 `tests/hermes_cli` and 142 `tests/hermes_state` files after that point have NOT run for lane h-turnws · **Added the same day (owner's question):** all four files are UPSTREAM's (listed in `tests/fixtures/upstream_manifest.txt`), so the fork's own landing gate (`scripts/run_tests_bundled.sh …`, `--scope fork`, `docs/downstream-development.md` § "The fork landing gate") would not have run them; the lane ran `scripts/run_tests.sh` over the three directories because `CLAUDE.md` § Commands calls that "THE suite" and its landing discipline says "the validated suite". The two documents disagree about what a landing runs — make `CLAUDE.md` name the fork gate for a landing and keep the full scope for the weekly upstream merge lane · the FOLLOW-UP half landed: `docs/downstream-development.md` names `scripts/run_tests_bundled.sh tests` as the landing gate · BLOCKED 2026-10-16: owner sitting — a watchdog box or disposable VM off the operator's desktop for the one-file-at-a-time freeze bisect
## Filed on arrival — 2026-10-05 (lane h-turnws)


## Filed on arrival — 2026-10-04 (lane hb-a)


## Filed on arrival — 2026-10-03 (resident identity verification)


## Filed on arrival — 2026-10-02 (lane h-rows)


## Filed on arrival — 2026-10-02 (instance foundation)


## Filed on arrival — 2026-10-02 (lane w13-hm, filed by the orchestrator)


## Filed on arrival — 2026-10-02 (lane w10-s7h)


## Filed on arrival — 2026-10-02 (lane w5-fh)


## Filed on arrival — 2026-09-30 (GenUI invocation)


## Filed on arrival — 2026-10-01 (lane w3-turn)


## Filed on arrival — 2026-10-01 (lane w3-perf)


## Release validation — 2026-09-23


**Provider-boundary qualification, October 1:** the existing TLS setup stall and duplicate-name/routing-ladder gate failures were reproduced, not waived; [evidence](../../docs/downstream/provider-access-boundary-2026-10-01.md#qualification). Native provider, plugin and execution checks pass; this does not certify a whole-repository green run.


- **`FORK-DIAGNOSE-LOCAL-CLI-STARTUP` — Diagnose the local CLI startup stall opening the inherited TLS key-log device target.** · The bounded inspector trace stops at `ssl.create_default_context` assigning `keylog_filename`, reached while `pm/downloader.py` constructs its opener during startup; no chat journal was created. Preserve certificate validation and logging oversight; classify host configuration versus startup handling before changing code. [Preflight evidence](../../docs/downstream/launcher-qa-preflight-2026-09-30.md#local-startup-stall). Filed 2026-09-30 Projects QA. · classified 2026-10-02 (w5-fh): HOST trigger (an inherited `SSLKEYLOGFILE`), UPSTREAM amplifier — `pm/downloader.py` builds `_OPENER` at module scope, so a bad key-log target breaks every CLI start that imports it · RULED 2026-10-15 (owner): open the upstream PR (lazy opener) from branch `upstream-pr/lazy-https-opener` (`95b3221fbec`) under the owner's name, posted together with the others · Recommend: drop the lazy-opener PR as the fix (it only moves the failure to the first HTTPS call) and keep `SSLKEYLOGFILE` out of the launcher-spawned runtime's env, or report it to CPython — any `SSLKEYLOGFILE` aborts stdlib `ssl.create_default_context()` on the test venv's CPython 3.14.5 / OpenSSL 3.5.6 (`OPENSSL_Uplink … no OPENSSL_Applink`, rc 1; 3.12.5 / OpenSSL 3.0.13 is fine); no stall without it — [q-reds receipt](../../docs/downstream/launcher-qa-preflight-2026-09-30.md#q-reds-recheck-2026-10-18) · RULED 2026-10-18: owner — the Launcher strips `SSLKEYLOGFILE` from the spawned runtime's environment · BLOCKED 2026-10-18: launcher — `MC-STRIP-SSLKEYLOGFILE`


**Additional evidence for the claimed validated-suite residuals:** 68 gateway/TLS failures reproduce on clean primary with Python 3.13.15; this does not supersede the separate Python 3.12 green receipt. [Comparison](../../docs/downstream/chat-first-group-qualification-2026-09-29.md#baseline-comparison). Filed 2026-09-29 chat-first-groups.





- **`FORK-WRAPPER-PUBLICATION-TESTS` — Isolate wrapper-publication tests before resuming interrupted desktop qualification.** · Whole-PC freeze during the single-worker continuation; running-wrapper publication is the last surviving fixture, not a proven cause. Preserve evidence; use contained off-desktop reproduction, not an unbounded rerun. [Incident boundary](../../docs/downstream/discussion-qualification-2026-09-28.md#host-freeze--qualification-interrupted). Filed 2026-09-28 Discussion qualification. · static read 2026-09-29: `tests/hermes_cli/test_source_launcher_publication.py::test_running_source_launcher_can_republish_itself` is bounded, a candidate trigger only through the OS/driver side of self-overwrite; the updater-retarget half is fenced by `319c6ff69d` · DEFERRED 2026-10-16: owner 2026-09-29 "park, low priority; needs a disposable VM" — until a disposable Windows VM exists or the next clean desktop qualification



### Filed on arrival — 2026-10-15 (owner screenshot during land-w1015h)


### Filed on arrival — 2026-09-29 (h11-mcp landing)


### Filed on arrival — 2026-09-29 (lane h10-fhrest)


### Filed on arrival — 2026-09-29 (lane h7-phone)


### Filed on arrival — 2026-09-28 (lane w5-hstt)

### Filed on arrival — 2026-09-29 (lane h10b-triage — the three-directory triage, one row per class)


### Filed on arrival — 2026-09-28 (lane w4-hfix2)

### Filed on arrival — 2026-09-27 (Windows console signal safety)

- **`FORK-WINDOWS-SIGNAL-SAFETY-CARRY` — Retire the Windows signal-safety carry when upstream adopts an equivalent fix.** · [[Windows console signal safety]]; held upstream candidate recorded in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`; no parallel supervisor or PID helper added, no PR submitted. · RULED 2026-10-10 (owner): carry stays; re-check at the next release merge · re-checked 2026-10-16: upstream `v0.22.2` `tui_gateway/host_supervisor.py::_pid_alive` still calls `os.kill(pid, 0)` · BLOCKED 2026-10-16: upstream — upstream adopting an equivalent in `tui_gateway/host_supervisor.py::_pid_alive`; re-check at each release merge

### Filed on arrival — 2026-09-26 (native Hermes qualification)


  EVIDENCE 2026-10-06 console-generated-content: the 895-file fork gate's exact
  115 failure/error nodes in 33 files reproduce on unchanged `5c0f130723`;
  the 35 unique helper/legibility/citation violation lines also match.
  [Receipt and remaining native acceptance](../../docs/downstream/console-generated-content-2026-10-06.md).

### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)





## Filed on arrival — 2026-09-30 (Stage 2 G4 landing, filed by the orchestrator)




## Filed on arrival — 2026-09-30 (launcher engine-build diagnosis, filed by the launcher orchestrator)


## Filed on arrival — 2026-09-29 (footprint attribution, filed by the orchestrator)


## Filed on arrival — 2026-09-29 (lane h10-fhrel, filed by the orchestrator)


## Filed on the move — 2026-09-22 (fork rows the launcher queue had carried since 2026-09-02)

Moved verbatim from `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`; they are about the repository as a fork, not about the surface. Upstream-owned ones are tagged so: never patched here, a marker or an upstream issue.

- **`FORK-CI-MAIN-REMAINING-SLICES` — hermes CI on `main`: the runner crash and the 43 lint errors and the mutation job are fixed; what is left is hb's slices 5–8 and the Issues switch** · `hermes` · **NARROWED 2026-09-06 (w18/ha `57b6964b01` (pre-rewrite), w18/hc `2b1f6e849c` (pre-rewrite))** — run 34046863701 (hc's push) is the first with `ruff enforcement (blocking)` and `Changed-line mutation claims` GREEN. **ha, slices 1–4, CLOSED:** all 16 tests across 11 files, one commit per file (`48a690da4c` doc-cite report needs a 4-commit repo under a depth-1 checkout; `188c511bae` + `9765564afa` stale `patch()` targets from `96cfc09a34` (pre-rewrite); `9463780a78` tool-inventory mutations wrote CRLF; `caffc04c1c` a hand-typed Windows byte count; `43cbb598ef` a real duplicate helper (`realm_sync._ledger_time` == `store._stamp`); `30f1ec6635` a BOM on `install.ps1` from the 2026-07-31 upstream merge; `23a90c6063` `test_env_gap_registry` was a DESIGN fault — a green host was read as "every row rotted"; `cee66b50fd` a witness that had not followed its reader; `d2137867b7` a directory-only git exclude that misses POSIX's symlink, which is also why the worktree GC never reaped on Linux; `ce3dc7f465` `os.path.normcase` on Windows-registry PATH data). Six of the eleven reproduced on Windows and were never platform facts — they live outside the four validated test directories and had simply never been run. **hc, CLOSED except Playwright:** ruff's 43 were all genuine `F821` (38 undeclared names in exec-assembled part-file import headers, 5 a missing `typing.Any`), 0 noqa (`fa0fb62788` (pre-rewrite), `f29ad6ca6c` (pre-rewrite), `3af990fca7` (pre-rewrite)); `test_harness_parts_namespace.py` never checked header PRESENCE, ruff is the real gate, said so in `6c629b9122` (pre-rewrite); the mutation job's exit was right and four registered needles had stopped anchoring — re-derived, each proven KILLED, plus `tests/scripts/test_mutation_claims_still_anchor.py` (`abaace6a87` (pre-rewrite), `bbc1caafb0`), and a fifth needle went ambiguous on landing over hd and was fixed forward (`2b1f6e849c` (pre-rewrite)). The notifier `notify-main-red` LANDED (`028aceb9c6` (pre-rewrite)) and FIRED on run 34046863701 — and failed on its own step, because **Issues are disabled on `nekwo/hermes-agent`** (register row). **hb, slices 5–8, CLOSED (hermes `962a10d0fb` (pre-rewrite), 13 commits):** all nine reds and the uncollected `test_tombstone_registry.py` (1,155 tests lost at collection to a `check=True` diff under `fetch-depth: 1`); two were the CI checkout, not the code — `ci.yml` now fetches full history with `filter: blob:none`, and the docket gate had been FALSELY accusing seven backed stages; three were product defects (`_ABS_PATH_RE`'s POSIX branch truncated at the first space, `entrypoint_name` used the host separator, `note_peer_seen` read the clock twice); the eight `stream_frames` goldens were regenerated for a path-tail redaction (`262a165b47`), which the launcher re-vendored 2026-09-06 (w18/lf). **What remains here:** (1) the next main-push run after hb lands must show the eight slices green; (3) the Issues switch, then one red push to prove the notifier end to end; then delete this row. · BLOCKED 2026-10-16: owner decision — turn Issues on for the fork's GitHub repository so `notify-main-red` can file? · Recommend: yes, then one red push proves the notifier end to end
- **`FORK-COVERAGE-CLAIMS-WALL` — `tests/test_coverage_claims_resolve.py` sits on a 180 s wall its own fixture now overruns** · `hermes` · found 2026-09-06 (w18/hd), measured not asserted — the file declares `pytestmark = pytest.mark.timeout(180)` and its comment records `collect_claims()` at 27–31 s over three runs on 2026-09-02; called directly today with nothing else running it took 211.5 s in the primary checkout on unmodified `main` and 279.5 s in a worktree under `X:/wt`, identical corpus census in both (241 md / 4,097 py / 3,089 test / 725 claims). It passed once mid-lane at 176.4 s. The marker was NOT raised. Two questions, one row: did the walk regress (bisect `collect_claims` between 2026-09-02 and today) or did this box's IO, and why is a worktree ~30% slower than the primary (the Defender exclusion covers the primary's drive, not `X:/wt` — check `Get-MpPreference` ELEVATED, it is blind otherwise). Fix the walk or gate the fixture on a cached census; never widen the wall. Agent work. · READY 2026-10-16 · **TAKEN 2026-10-18 w2-speed-b**
- **`FORK-HERMES-PACK-MAINTENANCE` — hermes pack maintenance is a SILENT no-op on git < 2.32** · `hermes` · `_run_bounded_repack` issues `git repack -d --geometric=2 --write-midx`, which exits 129 on older git; the runner sends both streams to DEVNULL and never reads the return code, then `_claim_repack_slot` suppresses retries for 6 hours. Measured on git 2.31.1.windows.1 — this box. Upstream-owned; decide: warn, fall back to `repack -a -d`, or require 2.32. Ruling 1. · `hermes_cli/web_routers/git.py`, upstream-owned · BLOCKED 2026-10-16: upstream — an upstream issue on `hermes_cli/web_routers/git.py::_run_bounded_repack` (warn, fall back to `repack -a -d`, or require git 2.32); none filed
- **`FORK-HERMES-GH-AUTH-STATUS` — hermes `gh_auth_status_route` caches a stale logged-out answer on a coarse clock — upstream race, report upstream** · `hermes` · the stale-probe guard compares two `time.monotonic()` reads with `>=`; Windows resolution is 15.625 ms (10000/10000 back-to-back reads identical, deterministic failure of upstream's own `test_gh_auth_refresh_waits_out_a_probe_started_before_it`), Linux still ties 1009/10000. Operator symptom: dashboard says "not signed in to GitHub" for the 5-minute TTL right after signing in. File is byte-identical to upstream — the fork does not patch it. Ruling 3. · BLOCKED 2026-10-16: upstream — an upstream issue on `gh_auth_status_route`'s `>=` monotonic guard; none filed

- The unrun-gate class on hermes `main`: nothing on any push lane runs the full suites, so reds accumulate silently. Two instances measured and FIXED 2026-08-30 (hermes `00fa94dd75` (pre-rewrite)): `tests/scripts/test_run_tests_script.py` (pins now follow `$RUNNER_PATH` and the import-pytest venv probe) and `tests/hermes_cli/test_error_exit_code_producers.py` (`runtime_unavailable` left `_KEPT_UNSPENDABLE` — the gateway lane mints it at five sites). The CLASS is NARROWED 2026-09-02: hermes' push gate now exists (`fc2e16349e` (pre-rewrite) — Lane B runs the validated 4-dir lane on `main` pushes), so what stays open is only the dirs outside that lane, e.g. `tests/scripts`, home of the first instance. Evidence: the misc-batch landing report (hermes `5fa9000b2`), both fixes `00fa94dd75` (pre-rewrite); hermes `AGENTS.md` §Testing. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16
- Hermes's focused suites cannot be trusted under multi-agent load: the named instance is RETIRED by suite-perf Stage 6 — `test_realm_sync.py` now drives `run_harness_in_process` (`tests/agent_runtime/_harness_cli`) and carries no `timeout` at all (verified 2026-09-01). The CLASS survives: an in-test subprocess cap `--timeout` cannot raise is invisible to the runner. Original filing: it timed out at load average ~400 on a command the diff never touched; fifteen failures across two suites on 2026-08-30 were all this class. Either the in-test cap becomes environment-scalable or the wave serializes pytest across agents. Evidence: the misc-batch landing report. **RULED 2026-09-04 evening (operator, recommended answer adopted):** Option 1. There is no scaling helper anywhere today — a repo-wide grep for `HERMES_TEST_SUBPROCESS_TIMEOUT` / `timeout_scale` finds only an unrelated audio test — while 474 test files carry a `timeout=`, so the class is broad and nothing currently absorbs load. Option 2 needs exactly the cross-agent orchestrator the shared-index row above says does not exist, and serializing test runs is a direct tax on the multi-agent workflow this house runs by default. Next: hermes: add the scaled-timeout helper plus its env knob, convert the subprocess caps in the test tree to use it, and add a gate refusing a bare numeric subprocess `timeout=` in `tests/`. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16

## Filed on arrival — 2026-09-24 (lane CARRY2A)



## Filed on arrival — 2026-09-24 (lanes UPPR2, REDS)


### Filed on arrival — 2026-09-29 (lane h12-upnew)


## Filed on arrival — 2026-09-24 (disposition wave)


## Filed on arrival — 2026-09-23 (seam Stage 0 lanes)


## Filed on arrival — 2026-09-21 (upstream sync assessment)

- **`FORK-PR-RUN-TESTS-PARALLEL` — PR candidate: run_tests_parallel amortised start-up** · `fork / upstream` · after `76e6fb0dc8` the per-file floor is upstream's own (~1.1 s to session start, ~2.6 s to collected, × every file); the five would-be upstream commits (phase timings, LPT order, small-file batching, POSIX fork workers, lazy root-conftest hooks) are outlined one per bullet with saving and isolation trade; the lane that builds it re-takes the upstream full-suite wall IDLE first (lane SPEED's was loaded) · evidence: `docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md` §8–§9 · fork after-fix baseline 40.7 min idle (2026-09-24) · 2026-09-24 (lane SUITE2): the measured PROTOTYPE of the batching bullet is the fork-only `scripts/run_tests_bundled.py` (+ `.sh`, plugin in `scripts/_bundle_plugin/`), core free of fork paths; first idle validated-scope run 1,802 s (30.0 min) vs 2,442.7 s per-file, 91 bundles, reds unchanged — the wall is held up by known-red files whose pytest-timeout kills a whole bundle (see the row below and the cost note §10). Owner decides when the upstream PR series is cut; the lane that cuts it takes the upstream idle wall first. · 2026-09-29 h12-upnew: LEFT, not opened — the series needs the upstream idle full-suite wall first (an exclusive ~40 min box) and our open runner PR #125263 on the same file is unreviewed with a body that describes fork-only code (h10b note 1); fix that body before a second runner PR goes up · RULED 2026-10-10: owner — "parked stays parked" · DEFERRED 2026-10-18: parked until the owner opens the upstream series; the lane that cuts it first re-takes the upstream idle full-suite wall and fixes PR #125263's body (owner 2026-10-10 "parked stays parked") — `docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md` §8–§9

## Filed on arrival — 2026-09-21 (god-file refactor plan)


## Filed on arrival — 2026-09-21 (brain)


## Filed on arrival — 2026-09-24 (lane CARRY2B)


## Filed on arrival — 2026-09-24 (lane REDS2)


## Filed on arrival — 2026-09-24 (lane CARRY3)


## Filed on arrival — 2026-09-24 (lane TESTS)


## Filed on arrival — 2026-09-24 (lane REDS3)

- **`FORK-NOTIFICATION-POLLER-REQUEUE` — `test_tui_gateway_server.py::test_notification_poller_live_loop_requeues_foreign_completion_for_owner` is order/timing-flaky: a stray `session.info` frame (this worktree's cwd and branch) reaches its captured writes** · `fork / suite` · red once in a five-file run on `6251144d09`, green alone and green on the next four-file run; find the emitter that outlives its test (a session-info publish from an earlier test's thread) and join or drain it in teardown · evidence: lane REDS3 `.lane-logs/base.log` (`assert [('session.info', 'msg-id-trunc-sid', {...'branch': 'fork/main-reds-2026-09-24'...})] == []`) · traced 2026-09-24: the only test naming `msg-id-trunc-sid` is `test_prompt_submit_truncates_by_message_id` (upstream bytes), whose daemon `_run_after_agent_ready` thread is never joined, but alone it never calls `server._session_info`; if it reds again, capture the stray's stack with a patched `_emit` in the failing multi-file run · DEFERRED 2026-10-16: owner 2026-10-15 "no decision owed: not reproduced" — a watch until it reds again **TAKEN 2026-10-17 claude (r-gateway)**

## Filed on arrival — 2026-09-24 (lane CLOSE)


## Filed on arrival — 2026-09-24 (program-end gate on `c7652475cd`)


## Filed on arrival — 2026-09-24 (lane LEDGER-DOCS)



## Filed on arrival — 2026-09-24 (lane DOORS-A)


## Filed on arrival — 2026-09-24 (lane W0)


## Filed on arrival — 2026-09-24 (lane MERGE)


## Filed on arrival — 2026-09-24 (lane H1)
## Filed on arrival — 2026-09-25 (lane R4)


## Filed on arrival — 2026-09-25 (lane S2B)


## Filed on arrival — 2026-09-25 (lane S2A)


## Filed on arrival — 2026-09-25 (lane 2B-A)


## Filed on arrival — 2026-09-25 (lane Q-DEAD-A)

## Filed on arrival — 2026-09-25 (lane B2)

- **`FORK-TEST-STAGE42-GLOBAL-FLAG` — `test_every_stage42_global_flag_is_honored` is a source walk keyed on the name `args`: a flag read through `self.args` or a renamed parameter reads as unhonoured, so phase objects must read flags in the handler** · `fork / gates` · a source walk certifying a POSITIVE guarantee ("this flag is honoured") by spelling — the fork CLAUDE.md gate rule says ask the runtime or the element model; re-key it on the parser's `set_defaults` targets and the attribute reads they reach · evidence: B2 gateway_commands CHANGE body · filed by lane B2 2026-09-25 · widening the visitor to `self.args` is another spelling; the re-key is a runtime probe (each `set_defaults(func=…)` handler driven with a recording Namespace under a side-effect fence), which needs the handler fence picked first · RULED 2026-10-10: owner — "parked stays parked" · DEFERRED 2026-10-18: the walk fails CLOSED on an unknown spelling (a `self.args` read reds as unhonoured, never passes) and a recording-Namespace probe reads only the path it drives, so the re-key waits on the owner's handler-fence pick — owner 2026-10-10 "parked stays parked"

## Filed on arrival — 2026-09-25 (lane Q-GATES)

## Filed on arrival — 2026-09-25 (lane B3)


## Filed on arrival — 2026-09-30 (lane h13-test)


## Filed on arrival — 2026-09-26 (lane TRIAGE)


## Filed on arrival — 2026-09-26 (lane ACP-DROP, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (program-end suite on `7df3bee189`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (batch gates on `6bae3f2484`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LAYERS-DESIGN, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LLAMA-ALIAS, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane W3-A)

## Filed on arrival — 2026-09-25 (round-2 gate pass)


## Filed on arrival — 2026-09-25 (lane W3-C)


## Filed on arrival — 2026-09-27 (lane MERGE-0927)

## Filed on arrival — 2026-09-30 (lane h12-upfix)



## Filed on arrival — 2026-10-04 (lane h-qaeff)


## Filed on arrival — 2026-10-05 (lane upstream-PR review replies)


## Filed on arrival — 2026-10-06 (turn-latency session)

- **`FORK-LANE-HOMES-REAL-PATH` — Test and lane homes still land their `bin` on the operator's real user `Path` after the 2026-10-03 PATH fence: 14 of 30 leaked entries were created 2026-10-05 (`stage2-serve-*`, `stage4-gateway-*`, `rb7-identity-flip-*`, `ro9-boot-sweep-*`, `rs7-restart-fence-*`, `p-l-longrun-*`, a lane's `scratchpad/live`); the first one shadowed `hermes` and the operator's `hermes harness observe` died on a deleted interpreter** · fork hygiene / test isolation · evidence: `[Environment]::GetEnvironmentVariable('Path','User')` read 2026-10-06 00:35, dated by each dir's CreationTime; writers are `hermes_cli/_launchers.py` (user-Path merge) and `windows_env.py`, fence `hermes_cli/_registry_write_fence.py` · lane: find the writer the fence misses (a subprocess outside `install_path_fence`, or a root the fence counts as owned), make the gate a positive test, then a one-time cleanup verb the operator runs · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.15; stages 1–2 built (`805f8293c9` `4045fa25c8` `811fc986e7`) · BLOCKED 2026-10-16: owner sitting — on the workstation: stage 0 (Process Monitor on a launcher real-serve sandbox run) and `scripts/prune_user_path.ps1 -Apply` after reading its list; stage 3's -SkipUserPath upstream PR waits with the idle PR branches

## Filed on arrival — 2026-10-06 (lane h-turn1-conn)


## Filed on arrival — 2026-10-07 (owner: upstream integration jobs)


## Filed on arrival — 2026-10-06 (upstream PR triage)


## Filed on arrival — 2026-10-06 (landing w16)


## Filed on arrival — 2026-10-07 (upstream PR lanes up-drafts / up-door-*)


## Filed on arrival — 2026-10-07 (landing prep/hermes-waves-reviewed)


## Found fixing main's reds — 2026-10-07 (lanes h-red-cli/-runtime/-gates/-inherited)


## Filed by isolated lifecycle fixture — 2026-10-07


## Filed on arrival — 2026-10-08 final GenUI gate


Process-dock product-half recurrence, 2026-10-08 GenUI qualification: `tests/gateway/test_abandoned_turn_process_cleanup.py` times out in `test_timed_out_turn_reaps_only_its_own_job_on_a_shared_container_key`, at `tools/process_registry.py::_release_finished_handles` → `stream.close()`. The candidate full gate and isolated run hang; untouched `7ea1c17366` first passes all 15 tests, then an isolated repeat hangs at the identical site. This is additional evidence for the existing process-dock/upstream-PR row above. No timeout, environment fence or production cleanup code was changed.

## Filed on arrival — 2026-10-08 (release merge v0.21.6)


## Filed on arrival — 2026-10-09 (lane opus-fix-toolsets-refusal)


## Filed on arrival — 2026-10-09 (perf programme close-out sweep)


## Filed on arrival — 2026-10-09 (landing lane land-h-toolvis; red on detached origin/main 440cba12ce, after the upstream v0.21.6 merge)


## Filed on arrival — 2026-10-10 (release merge v0.21.6 reds, branch `fix/v0216-fork-reds`)


## Filed on arrival — 2026-10-10 (chat content integrity)


## Filed on arrival — 2026-10-10 (chat-content boundary qualification)




## Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)

- **`FORK-HERMETIC-DEFAULT-DB-PATH` — The hermetic `DEFAULT_DB_PATH` pin depends on import order: `tests/conftest.py` pins it only if `hermes_state` is already imported, so profile-scoped store tests pass alone and red after any importer** · fork / suite · `queue-sweep-2026-10-10/L7-outcomes.md` L7.01 · lane: suite · upstream-owned on both sides (`tests/conftest.py` step 3b, `tests/gateway/test_multiplex_routing_authz.py`), so the answer is an upstream issue/PR · RULED 2026-10-15 (owner, decision sheet w1015i #2): post the upstream ones together in one sitting · BLOCKED 2026-10-18: upstream — the pin's import-order dependence lives in upstream `tests/conftest.py` step 3b; the two known reds are unpinned fork-side by id mark (`ddf83ac62a`, `tests/_downstream/state_db_scope.py`); a fork-side "always import `hermes_state` in the chain" would make the pin order-independent but turn every latent alone-green into a red only a whole-tree run finds (ADR 0016), so it waits on the owner's upstream batch (DEFERRED 2026-10-16)

## Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)

- **`FORK-SHARED-TEST-VENV-SQLITE` — The shared test venv's SQLite 3.50.4 forces `journal_mode=DELETE`, so no WAL-path behaviour (sidecar races, checkpoints) can be exercised live on the workstation** · fork / suite · build-1011-B5 D3.02 stage 3 · lane: test-venv refresh · still true 2026-10-15 (venv Python 3.14.5 links SQLite 3.50.4); WAL needs an interpreter linking SQLite >= 3.51.3 or the 3.50.7 backport · RULED 2026-10-15 (owner): yes, rebuild the shared venv at the next landing · BLOCKED 2026-10-16: another lane — the next hermes landing rebuilds the shared venv

## Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast-gate design, guard fix, build batch 2 C1–C4, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


## Filed on arrival — 2026-10-11 (fast-gate landing, whole-tree gate, filed by the orchestrator)

- **`FORK-THIRTEEN-TIMEOUT-REDS` — Thirteen files go red in the whole-tree gate by timeout rather than assertion — nine also red on a quiet base `828fdb3c0e` (`test_update_ci_routing`, `test_desktop_build_lock`, `test_run_agent`, `test_icon_flavors`, `test_run_tests_parallel`, `test_known_file_write_baseline`, `verify/test_environment_and_runner`, `test_tui_gateway_server`, `test_serve_exit_flush`) and four at the 30 s per-test edge (`test_install_ps1_native_calls` 27.9 s, `test_no_shadowed_test_definitions` 29–31 s, `test_install_clone_throttle_fallback`, `test_web_server::test_concurrent_first_load_reads_all_succeed_on_fresh_store`)** · fork / suite (the CLASS; four of the nine have their own rows) · `queue-sweep-2026-10-10/FG-landing.md` · lane: classify each (Windows upstream red → marker; fork-caused → fix; honest slow test → a per-test timeout) on the idle box · TRIAGE: H09 Windows process death is repaired; other files remain open. [H09 disposition](../../docs/downstream/history-red-triage-2026-10-12.md). · `test_known_file_write_baseline` passed its 1-worker retry 2026-10-15 (slow, not red) · BLOCKED 2026-10-16: owner sitting — the idle workstation (no other lane running) for the classification runs
- **`FORK-LAZY-IMPORT-TURN-COST-CLASS` — CLASS (third instance): a new lazy import on the turn path silently adds first-turn cost until the turn-cost guard catches it, and that guard's IMPORT check runs only on the idle box because its file is idle-only — v0.21.6's three modules (`97b33c3c49`), the capability probe + netrc (`c3894ae54d`), M2.05's `request_effort` (`c835697c3c`)** · fork / suite · `queue-sweep-2026-10-10/idle-box-2026-10-11.md` · lane: split the guard's import-count check (load-independent) out of the idle-only file so every landing gate runs it; the structural answer is the gate, not a fourth warm-list line · read 2026-10-15 (w1015e-fh-h): lift the scenario into `_run_guard(...) -> (violations, budgets, spans)` in the same file, keep the idle test asserting both, add an unlisted `test_turn_cost_guard_counts_downstream.py` asserting `violations` only, after moving the one clock check (`queue_ms > QUEUE_BEHIND_RIDERS_MS`) into `budgets` · BLOCKED 2026-10-16: another lane — one qualification run inside the next loaded bundled landing gate before the counts file joins every landing
- **`FORK-STREAM-GAP-STARVED-READER` — `tests/agent_runtime/test_stream_gap_receipt.py::test_starved_reader_shows_lag_and_late_wakeups` misses its 150 ms lag floor even on the idle box (110 ms on 1 of 2 first attempts, passed on retry); the D3.09 row was closed on the first idle runs too early** · fork / suite · `queue-sweep-2026-10-10/idle-box-2026-10-11.md` · lane: a hog the scheduler cannot skip, or a floor measured on the idle box over ≥10 runs (never lowered to pass) · BLOCKED 2026-10-16: owner sitting — the idle workstation for >= 10 runs (`scripts/run_tests_idle.sh`)


## Filed on arrival — 2026-10-11 (Console history final qualification)

- **`FORK-REQUALIFY-HOST-XFAILS` — Requalify the last two host-sensitive strict xfails from hosted Windows run 38426498916: `tests/scripts/desktop_update/test_desktop_update_windows_marker.py::test_owner_creation_time_is_read_for_system_processes[False|True]` XPASS on the elevated hosted runner and red here with "no process here grants only limited query rights" (unelevated, by the look of it; not demonstrated).** · fork / inherited-test expectations · the other 15 of the 17 nodes are qualified: 5 retired on main earlier (`455ea739f72`, `9effac5d6a2`), `test_source_build` retired and 9 moved to probe-backed env-gap rows (unelevated `sc.exe`, user-vs-system `core.autocrlf`, delivery CLI through PATH) by lane r-isolation 2026-10-16 · move the two ids to the `_unelevated_windows_shell` owner only after one elevated run shows them green; do not make them non-strict · BLOCKED 2026-10-16: owner sitting — one run of the two ids in an elevated shell






## Filed on arrival — 2026-10-13 shutdown-test repair

- **`FORK-QUALIFY-NATIVE-WINDOWS-MSYS` — Qualify native Windows MSYS foreground-child ownership and cleanup.** Three `sleep.exe 3518` children survived the failing inherited shutdown-test setup; adding the executable suffix did not make the ancestry scan find them. They were explicitly reaped. The repaired test owns its Python child by a ready PID receipt, which does not prove MSYS tree cleanup. Reproduce through the existing local-environment process owner before attributing a production defect or proposing a fix; no broad process-name kill or new process registry. · fork / native process qualification · [evidence](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · reproduced 2026-10-16 (r-isolation) through the owner: after `kill_live_foreground_processes(now=True)` (signalled 1, rc 1) the MSYS `usr\bin\sleep.exe` survived with a dead Windows parent, because `_kill_process_windows` -> `terminate_pid` -> `taskkill /T` walks parent links the MSYS spawn already broke; the graceful path signalled 0 (evidence appended to the doc above); both files are upstream-owned · BLOCKED 2026-10-16: upstream — an issue naming the reproduction, filed by the owner, before any fork-side kill change

- **`FORK-QUALIFY-POSIX-EXIT-FLUSH` — Qualify POSIX exit-flush test signal-state restoration.** The unchanged SIGTERM test saves only SIGTERM, while `install_exit_flush_signal_handlers` also replaces SIGINT; `_restore_signal_state` clears the handler map after restoring the supplied entries. Baseline and candidate Linux tests pass but do not inspect the next test's handler state. Use a bounded native before/after probe and repair the existing fixture if confirmed; no runtime redesign or shared fixture duplication. · fork / native test isolation · [source finding](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · confirmed 2026-10-16 (r-isolation) by a before/after probe: SIGTERM restored, SIGINT left as `_handle_exit_flush_signal` with an empty chain map; the test file is upstream-owned, fix drafted in `docs/agent-runtime-harness/upstream-prs/serve-exit-flush-signal-restore-body.md` · BLOCKED 2026-10-16: upstream — that PR, posted in the owner's next posting sitting


## Filed on arrival — 2026-10-15 (land-w1015b)


## Filed on arrival — 2026-10-15 (owner: "testing commands should be optimised")

- **`FORK-SUITE-SPEED-J-REMEASURE` — The rest of the 2026-10-15 suite-speed ask: re-measure `-j` against cores−2 on the idle 16-thread box (CPU 24 % at -j 8 during land-w1015b; the ruled default 8 is the owner's), and speed or split the slow fork files (`tests/agent_runtime/test_gateway_peer_two_roots_e2e.py` 280–587 s, `test_persona_assignments.py` 345 s, `test_serve_socket_child_e2e.py` 315 s)** · fork / suite speed · `X:/Eternia/worktrees/land-w1015b/_land_logs/bundled.log` header; the gate store's `durations.json` · lane: idle-box measurement, then one slow file per lane · RULED 2026-10-15 (owner, decision sheet w1015i #3): measure once on the idle box, then set the default to what the measurement supports · BLOCKED 2026-10-16: owner sitting — the idle 16-thread workstation for the -j measurement

## Filed on arrival — 2026-10-15 (lane w1015h-fh-h)


## Filed on arrival — 2026-10-15 (upstream PR sync lanes up-sync-1015-*)


## Filed on arrival — 2026-10-15 (owner: the footprint ratchet only goes up)

### Filed on arrival — 2026-10-16 (Phase B lanes pb-*, release gate triage rel-0222-reds)

- **`FORK-PATCH-IN-TEARDOWN` — A raising patch from a test body is still live during fixture teardown for every test (the patch-in-teardown CLASS): the structural answer is for the chain to undo the body's patches at the end of the call phase; find the fixture teardowns that read a body patch with one `--scope features` run and its diagnosis, then decide** · fork / suite · q-chain `82e028ecdc` body · NEEDS PLAN 2026-10-18: no safe change without the measurement — undoing at call end every `monkeypatch` entry above the post-setup stack length (the `pytest_pyfunc_call` split the SCOPED_MONKEYPATCH_UNDO mark already does, applied to all) would also drop the patches a fixture pushes when the body requests it late (`request.getfixturevalue`), so the plan needs (a) per-entry provenance (body vs late fixture) and (b) one quiet-box `--scope features` run with the split on, diffing teardown ERRORs and teardown-time reads against a run with it off; the box had 12 lanes on 2026-10-18
- **`FORK-AFFECTED-HUB-MODULES` — `--affected` misses its under-a-minute bar on hub modules: 160 s for an `agent_runtime/locks.py` edit (110 files), 219 s for `tools/checkpoint_manager.py` (59 files); 7 s for `hermes_cli/plugin_host.py`. Still 5-8x faster than the ~1,120-file landing gate, but a 2-hop static reach picks a few 100-240 s files** · fork / suite · q-affected report 2026-10-17 (branch q/affected) · fix: per-file imports (next row) + slowest files last under `--fail-fast` · READY · r-recorder 2026-10-18: per-file `mods_own` landed (locks.py 111 -> 32 files, checkpoint_manager 59 -> 37) but wall time did not fall: tail-bound on 70-177 s files · NEEDS PLAN 2026-10-18: the bar is work-bound, not tail-bound — locks.py selects 107 files / Σ 1,027 s (q-runner: 35 of them were misses), so even -j 8 with shards models 132 s; a plan must cut the per-file cost of the agent_runtime operator files (redo/persona_assignments/turn_undo/session_models, 485 s) or restate the bar for hub modules — measured walls in q-runner 912babdeb9
- **`FORK-CHECKPOINT-MANAGER-TIMEOUT` — `tests/tools/test_checkpoint_manager.py` times out in the 2026-10-17 `--scope features` run (first: `no result before the cap`); fix whether or not it was red before (owner)** · fork / suite · features run 2026-10-17 (gate store runs.jsonl, `features-1`) · BLOCKED 2026-10-18: upstream — issue text: "`tools/checkpoint_manager._init_store` spawns `git init --bare` plus five `git config` per store (222 of `tests/tools/test_checkpoint_manager.py`'s 1,177 git spawns); fold them into `git init -c` or one config write. Every spawn also pays `pm.client.ensure('git')` (see the store_root row in runtime-queue § Upstream-owned)." q-pm 2026-10-18 alone: 93.4 s / 56 passed idle, 140.1 s under load, 1,180 ensure calls = 19.6 s · r-state 2026-10-18: green alone twice on an idle box (run_tests.sh 68.7 s on origin/main, 62.5 s on `q/r-state`; bare 56.9 s, slowest test 4.1 s); the cost is 1,190 git spawns (~47 ms each: `git init --bare` + five `git config` per store, 44 stores) inside upstream `tools/checkpoint_manager.py`, so a loaded box reaches the cap; no fork-only fix (the store init is the subject) — next: an upstream PR folding the five configs into `git init -c`/one `config` call, or a skip-list call by the owner
- **`FORK-NEMO-PYD-OLD-DELETE` — Owner, after a reboot: delete `nemo_relay/_native.pyd.old-0.8.4` from the shared test venv** · fork / box · the 2026-10-16 nemo-relay 0.8.4→0.10.0 swap renamed the held `.pyd` (uv could not replace a loaded file); the old dist-info is parked in the session scratchpad · delete once no process holds it · BLOCKED 2026-10-16: owner sitting — after a reboot of the workstation, delete the file from the shared test venv
- **`FORK-UPSTREAM-DAILY-NO-UPDATER` — `integration/upstream-daily` has no updater: the GPT/Codex daily job is down; the branch was rebuilt by hand on 2026-10-16 (`04c26f21a27`, upstream `e6899c8090d`)** · fork / sync · owner 2026-10-16 "the updater gpt is dead" · until a job is back, a Claude lane rebuilds it per `Merging upstream.md` at each upstream release (with `--merge-base=<last merged tag>`, row above) · BLOCKED 2026-10-16: owner decision — bring a daily updater job back, or keep a Claude lane rebuilding the branch at each upstream release? · Recommend: a Claude lane per upstream release, with `--merge-base=<last merged tag>`
- **`FORK-24-UPSTREAM-PR-BRANCHES` — 24 upstream PR branches are prepared and idle (16 splits, 7 doors, the phone fix `fix/connectors-files-lazy-wire`); the account cannot open PRs upstream** · fork / upstream · bodies kept beside the clone in `worktrees/pr-bodies/`; owner 2026-10-16 "pr branches should remain idle" · owner opens them when upstream accepts PRs again; re-check each against the next release first · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: when upstream takes the owner's PRs again, re-check each against the newest release tag and re-run `check_carried_prs.py` before opening — `worktrees/pr-bodies/`
- **`FORK-18-CARRIED-PR-PAIRS` — 18 carried-PR pairs stopped matching after the 2026-10-15 sync (8 hunk/line DRIFT: #119069 gateway.py, #121226 ×2, #121642 auth_nous.py, #123892 shell_hooks.py, #128652 hermes_state_messages.py, #129414 resolution_allowlist.json, #125261 environments/local.py; 9 fragments the PR branches rewrote: #125259, #125263 ×2, #125264, #128648 ×2, #128651, #128654, #128843): per PR re-cut the branch to the fork's text or adopt the PR's text in the fork, then re-pin** · fork / upstream PR tooling · q/carried `5692a35290f` check run · re-anchored 2026-10-18 on q/q-sync (fork adopts the PR's spelling where only spelling differed; #129414 deferred as a fork relocation): 17 → 9 pairs, `check_carried_prs.py` 4 drift + 5 errors; the nine left differ in logic, not spelling (#119069 gateway.py, #121642 auth_nous.py, #125259 config.py, #125261 local.py, #125263 run_tests_parallel.py, #125264 base.py, #128648 main.py + plugins.py, #128652 hermes_state_messages.py) · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: re-cut those eight PR branches to the fork's text when upstream takes the owner's PRs again; adopting the PR's logic in the fork needs a per-PR review lane
- **`FORK-PR-128648-BRANCH` — #128648's PR branch now lives in `hermes_cli/main_plugin_cli.py` / `plugins_declared_cli.py` while the fork carries an older shape in `plugins_manifest_cli_commands.py`; converge one onto the other, then re-map the carried-PR manifest** · fork / upstream PR tooling · q/carried `5692a35290f` · BLOCKED 2026-10-16: owner decision — converge the fork onto #128648's PR-branch shape, or the PR branch onto the fork's? · Recommend: the fork adopts the PR's shape, so the idle PR branch needs no push



- **`FORK-FULL-RE-AUDIT-FOUND` — The full re-audit found nine fork fixes that have no upstream PR yet (`_codex_pool_row_refused`, the system_prompt anchor repair, the `_sanitize_client_source` NameError, `terminal_tool_result.timed_out`, the tts piper download switch, the live-guard console-event refusal, the relay optional binding, the runtime_provider `auto` re-check, the pyproject F821): give each a prepared branch and a PR body in `pr-bodies`** · fork / upstream PRs · same doc §4 · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: cut the nine branches from the then-current release tag only when upstream takes the owner's PRs again (a branch cut now drifts before it can open) — owner 2026-10-16 deferral



## Filed on arrival — 2026-10-15 (lane w1015j-hermes)

- **`FORK-SHARED-HERMES-CLONE-PACK` — The shared hermes clone's pack directory holds about 40 `.idx` files with no `.pack` and 8 `tmp_pack_*` leftovers from interrupted fetches (`git count-objects -v` warns on each); the likely source of the 2026-10-15 "fetch-pack: invalid index-pack output"** · fork / clone health · measured 2026-10-15 18:45 · lane: an owner/landing step with no lane open — `git -C <clone> fsck --connectivity-only`, then delete the orphan `.idx`/`tmp_pack_*` files (or `git gc --prune=now`); never a lane's repair of a shared object store · BLOCKED 2026-10-16: owner sitting — the shared clone on the workstation with no lane open: `git fsck --connectivity-only`, then remove the orphan `.idx` / `tmp_pack_*` files

## Filed on arrival — 2026-10-16 (h2-redact)

- **`FORK-REBASED-CLAIM-COMMIT` — A claim commit rebased onto a moved `origin/main` came out of `git rebase` "Successfully rebased" with a PEER lane's four fresh `TAKEN 2026-10-16 h4-seeds` marks reverted in `runtime-queue.md` (rerere is on, 424 entries in the shared `rr-cache`); caught only by reading `git diff origin/main HEAD` before the retried push. Queue files are one-line-per-row and every lane edits them, so a recorded resolution replays onto unrelated rows** · fork / clone health · measured 2026-10-16 by h2-redact (never pushed; the claim was rebuilt on a fresh `origin/main` with a temporary index instead of a rebase) · fix shape: claim and file-on-arrival commits are built on the fetched tip (read-tree + update-index + commit-tree), never rebased; or `rerere.enabled=false` for queue paths · filed 2026-10-16 by h2-redact · BLOCKED 2026-10-16: owner decision — turn rerere off on the shared hermes clone, or build every claim and file-on-arrival commit on the fetched tip? · Recommend: `rerere.enabled=false` on the shared clone

## Filed on arrival — 2026-10-16 (land-h234)


- **`FORK-HERMES-TEST-ENTRY-POINTS` — hermes test entry points claim no machine-wide heavy-run slot (the launcher's `tool/heavy_run/slot_lock.dart`), so a hermes suite oversubscribes the 16 processors beside launcher lanes — decide whether `scripts/run_tests.sh` claims a slot** · launcher core-packages-queue row "Only run_tier.dart and verify_stagec_qa_tooling.dart claim a heavy-run slot automatically" · filed 2026-10-16 from the launcher queue relabel · BLOCKED 2026-10-16: owner decision — should hermes test entry points claim the launcher's heavy-run slot? · Recommend: yes, in the fork-owned `scripts/run_tests_bundled.py` (Phase B has landed, so `scripts/run_tests.sh` is unfenced too)

## Filed on arrival — 2026-10-16 (lane h5-deadcode)


## Filed on arrival — 2026-10-17 (footprint audit)


## Filed on arrival — 2026-10-17 (lane r-plugins)


## Filed on arrival — 2026-10-18 land/q6

- **`FORK-GATE-JOBS-DEFAULT` — Fork gate runs at -j 8 on a 16-logical-CPU box with utilization 0.98 (work-bound); measure -j 10/12 on a quiet box (the X: HDD may cap it) and set the default from the result** · fork / suite · same run · READY 2026-10-18



- **`FORK-TEST-OWNED-CHILD-READS` — `tests/agent_runtime/test_subagent_native_roundtrip.py::test_owned_child_reads_across_execution_hosts[*-isolated-compute]` reds `sqlite3.OperationalError: attempt to write a readonly database`: the reopened service's history read (`agent_runtime/conversations/subagent_history.inspect_stored_children` -> `SessionDB(read_only=True)`) opens state.db `mode=ro` right after the stopped compute child's writer exits, and the FTS probe needs WAL/-shm recovery a read-only connection cannot do; `hermes_state.SessionDB._open_read_only` retries only the disk-I/O marker, not this SQLITE_READONLY recovery case** · fork / subagent history (the retry is upstream's: a seam or an upstream PR) · r-quiet 2026-10-18: red 1 of 3 ALONE on a quiet box (load 7, `[stop-isolated-compute]`, 67 s), green the other two; earlier once at load 23 ([[r-perf-2026-10-17]]) · READY 2026-10-18 · **TAKEN 2026-10-18 w2-reds**
## Filed on arrival — 2026-10-18 (lane r-quiet)

## Filed on arrival — 2026-10-18 (lane q-gates)
- **`FORK-TEST-UPSTREAM-SKIP-LIST` — `test_upstream_skip_list` costs 64 s alone and parses nothing: its parametrized `test_a_change_that_reaches_an_unused_file_does_not_select_it` cases each re-run the runner's discovery and `select_scope` (19-20 s per case under load; one hit the 30 s cap in a combined run, `run_tests_bundled_scope._rel_posix` -> `Path.resolve`); compute discovery once per session and hand each case the result** · fork / suite · `docs/agent-runtime-harness/11-gate-directory.md` § Cost (lane q-gates measurement) · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-a**
- **`FORK-TEST-FORK-IMPORT-LAYERS` — `test_fork_import_layers` re-builds the layer census in every parametrized case (~4.6 s each, 8 cases; parses are already shared, 17,983 cache hits): one census per session behind the cases** · fork / suite · same page § Cost · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-a**

## Filed on arrival — 2026-10-18 (lane q-stale)

## Filed on arrival — 2026-10-18 (lane r-turn)

## Filed on arrival — 2026-10-18 (lane h1-setup)
- **`FORK-CHECKPOINT-GIT-ENV-PROBE` — every git call `tools/checkpoint_manager._run_git` makes re-proves the pm-managed git install: `_git_env` → `hermes_cli/_subprocess_compat.selected_git_env` → `pm.client.ensure` → `pm.install.is_installed` (~80 `realpath` per call, ~25 ms CPU); `test_checkpoint_gitlinks.py` setup pays 1,288 of them, 34 s of its 54 s setup CPU** · upstream-owned / pm + checkpoints · cProfile of setup, lane h1-setup branch `q/h1-setup` commit body · BLOCKED 2026-10-18: upstream — issue text: "`selected_git_env()` resolves the pm git install on every subprocess; memoise `_installed_location` per store root (invalidated by install/uninstall) or resolve once per `CheckpointManager`"
- **`FORK-STATE-SCHEMA-AUTOCOMMIT` — a fresh `state.db` build autocommits ~100 DDL statements (`hermes_state_schema._init_schema` on the `isolation_level=None` writer): in `journal_mode=DELETE` each is a rollback-journal create+delete+fsync, 87-110 ms CPU per store even at `synchronous=OFF` (100 statements: 105 ms autocommitted vs 6 ms in one transaction); the fork's tests now dodge it with a stripped template, production first-runs and every DELETE-mode install still pay it** · upstream-owned / hermes_state · lane h1-setup measurement (`tests/_downstream/session_db_template.py` docstring) · BLOCKED 2026-10-18: upstream — issue text: "wrap the fresh-store DDL in `_init_schema` in one `BEGIN`/`COMMIT` (SQLite DDL is transactional); a fresh store becomes one journal cycle instead of ~100"

## Filed on arrival — 2026-10-18 (lane h2-sleep)
- **`FORK-TEST-UPSTREAM-FIXED-WAITS` — The largest suite sleeps left are upstream constants a test cannot shorten: `tools/terminal_tool.py::_run_foreground` retries any backend exception at 2+4+8 s (the five `_LIFECYCLE_SCAN` strict-xfail rows in `test_gateway_restart_loop.py` reach the test double's `execute` on Windows, so each pays 14 s: 70 s per run), `hermes_cli/local_runtime/supervisor.py::unload_model`'s 15 s / 0.3 s poll (44 s in `test_local_runtime.py`), `cron/scheduler.py::_launch_external_cron_worker` (18 s in `test_restart_safe_worker_death_evidence.py`) and `hermes_state._sleep_before_write_retry` (15 s in `test_compression_watermark_commit.py`)** · fork / suite (upstream code) · probe 2026-10-18 lane h2-sleep (main-thread sleep per call site, top 44 files) · BLOCKED 2026-10-18: upstream — issue text: "retry backoffs and poll deadlines in `terminal_tool._run_foreground`, `LocalRuntimeSupervisor.unload_model`, `_launch_external_cron_worker` and `SessionDB` write retry are module literals; make each an injectable interval (constructor or module attribute) so tests set it once, and do not retry an `AssertionError` from a test double as a transient backend error"
- **`FORK-TEST-NATIVE-ROUNDTRIP-PREWARM-PAUSE` — `test_native_conversation_roundtrip.py` sleeps a fixed 1 s after each `open` to "give native prewarming time" (3 per parametrization, 12 s per run): wait on an observable prewarm-settled fact from the worker instead, or state why the pause itself is the scenario** · fork / suite · probe 2026-10-18 lane h2-sleep (12.01 s, 12 calls, main thread) · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-b**

## Filed on arrival — 2026-10-18 (lane h3-plugins)
- **`FORK-DISCOVERY-CACHE-TREE-WALK` — `tests/_downstream/plugin_discovery_cache.py` re-walks the bundled tree signature (3 directory levels) and deep-copies the kept manifests on every discovery, ~13 ms each (13.3 s over 1,002 discoveries in the top 15 files): with plugin modules kept it is the largest fork-owned piece of a ~76 ms discovery; check the signature once per test, not per discovery** · fork / suite · evidence: lane h3-plugins bucket profile (`discovery(manifest scan)` row) · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-a**

## Filed on arrival — 2026-10-18 (lane h6-collect)
- **`FORK-TEST-PRECOMPILE-ARGV` — `scripts/run_tests.sh`'s bytecode pre-compile never runs on Windows: `compileall -- $(git ls-files '*.py')` passes 10,800 paths (456 KB) and dies "Argument list too long" (rc 126), hidden by `>/dev/null 2>&1 || true`; feed the list on stdin (`git ls-files -z` / `compileall -i -`) — upstream line, so an upstream PR or a fork-side pre-compile in the bundled runner** · fork-hygiene / suite runner · h6-collect 2026-10-18: one tiny file cold 3.5 CPU-s vs warm 2.0; `compileall -i <list>` once costs 34 CPU-s cold, 2.2 warm · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-a**
- **`FORK-TEST-LIFESPAN-TEARDOWN` — a `TestClient(web_server.app)` teardown waits on the hosted-room worker's state store (schema init + fsync) and the eager-reconcile join: 0.5 s per test alone, ~12 s per test under 8-way load (`tests/hermes_cli/test_mcp_catalog_env_boundary.py` 108 s teardown, first in its bundle); `tests/pm/_fixtures.py::threaded_server` adds 0.42 s per test (`socketserver` 0.5 s poll on shutdown)** · fork-hygiene / session chain (both files upstream: a chain seam, e.g. the hosted-room store's fsync like `state_db_no_fsync`) · h6-collect teardown profiles 2026-10-18 · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-b**

## Filed on arrival — 2026-10-18 (land h1018)

- **`FORK-TEST-UPSTREAM-PARSE-MEMO` — two upstream re-parses of unchanging bundled files dominate the h4 call-phase profile and need no upstream edit to cut in tests: `agent/i18n._load_bundled` re-parses `locales/<lang>.yaml` per `(HERMES_HOME, lang)` (23.8% of 3,668 profiled s; `RT-I18N-BUNDLED-PER-HOME`) and `gateway/platform_registry._resolve_all` re-imports every platform plugin per profile scope (16.6%); a session-level chain memo keyed on each file's (path, mtime_ns, size), the q-chain `child_startup` pattern** · fork / suite · `Harness_Brain/20 — Active Initiatives/r-perf-2026-10-17.md` § h4-hotpath · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-b**
