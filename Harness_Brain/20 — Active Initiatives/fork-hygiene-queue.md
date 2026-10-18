---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue


- [ ] **Triage upstream/macOS jobs exposed by the subagent-history PR's broader CI matrix.** Run `38832830663`, macOS shards `116755299378` / `116755299386`, fails in update/PM/source-stamp/MCP subprocess fixtures: copied update trees lack `agent_runtime`, import probes hit the live-system guard, and PM/tool fixtures touch the setup environment. These files are outside Step 5's changed paths; Windows fork-scope qualification does not establish a macOS baseline. Reproduce on the same native CI host against the base before attributing or exempting them. Preserve the run logs; do not weaken live-system guards or grow the skip list from this report. · fork / CI · read 2026-10-16 (r-sync, `gh run view --log`): shard 1 = 17 reds in 6 files (update_missing_configured_deps, sessions_held_store_gate, update_import_guard, update_posix_pause, source_build_env, mcp_death_supervisor), shard 2 = 8 errors + ~20 failed (doctor_pm_store_probe, doctor_command_install, update_finish "No module named 'agent_runtime'" from the copied tree, update_pause_step_interruptions, update_post_commit_safety, update_recovery_closure, pm runtime_bootstrap_tls / update_dependency_legs); no `main` push runs the macOS matrix (runs 38884451206, 38976202285 carry no macOS job), so no base exists to compare · BLOCKED owner: a macOS CI run on the base (`workflow_dispatch` of CI on `main`, or a Mac host) — triggering one needs the owner's GitHub account

- [ ] **Resolve the fork owner's existing commit identity in contributor attribution.** PR #11 run `38832830663` rejects the configured owner author email because it has no contributor mapping. Step 5 retains the repository's established author and required co-author footer; no identity is fabricated or rewritten. Confirm the owner account mapping through the existing contributor tooling, with any upstream-file footprint accounted for. · fork / CI · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-sync)**

- [ ] **Qualify the canonical shared test environment on the second Windows workstation before treating the PM slow-exit check as covered there.** Baseline re-audit on `5fc3c617df` (2026-10-15): with no explicit `HERMES_PYTHON`, `scripts/run_tests.sh tests/pm/test_worker_slow_exit_downstream.py` refuses before collection because this Windows account has no shared environment with pytest at `~/.venvs/hermes-test`. Explicitly selecting this clone's Python 3.13.15 reproduces the PM fixture's Python 3.14 requirement error; no worker assertion runs. Commit `646acfb921` established a genuine 1/1 pass on another account's shared Python 3.14.5 environment, not this workstation. Use the existing shared-environment setup and runner, then rerun the single file; do not change upstream's fixture, relax the Python requirement, or add another runner. Evidence: `scripts/run_tests.sh`, `tests/pm/_fixtures.py::isolated_python`, `pm/pyproject.toml`; local re-audit receipts retained. Environment setup, not a demonstrated PM or Eternia runtime defect. · BLOCKED 2026-10-16: owner sitting — set up the shared `~/.venvs/hermes-test` (Python 3.14) on the second Windows workstation's account, then rerun the one file

- [ ] **Repair the existing import-layer violations without widening the exception set.** Unchanged main `024e92d2f9` reproduces two unrecorded private imports (`_codex_snapshot_identity`, `_decode_jwt_claims`) and the upward edges `mission_chat_outcome` → `provider_health`, `harness_parts.usage.providers` → `provider_account_metadata` (the latter reported twice). Subagent qualification compares the exact violation list and leaves these unrelated entries untouched. · `tests/tooling/test_fork_import_layers.py` · evidence: `docs/downstream/agent-console-subagents-foundation-2026-10-14.md` · the three upward edges are fixed on main (`5f497c030e7` MOVE ProviderDependencyError to a models module; `9d214f7035f` provider_account_metadata declares policy) · RULED 2026-10-15 (owner): allow the two private imports (`_codex_snapshot_identity`, `_decode_jwt_claims` in `agent_runtime/_upstream_doors.py::codex_account_claims`) as named exceptions, each pointing at an upstream request · the two exceptions, their ledger rows and the drafted request ("Public Codex credential claims door") are on main (`b273f4a005a`) · qualified 2026-10-16 (r-isolation): the two exceptions landed on main (`b273f4a005a`) and cannot be doored in fork code — the only public neighbour, `agent.credential_pool.label_from_token`, reads top-level `email` only (the Codex address sits under the `https://api.openai.com/profile` claim) and nothing public answers the snapshot identity, so a fork door would be a copy of `_decode_jwt_claims` · BLOCKED 2026-10-16: upstream — the "Public Codex credential claims door" request (`upstream-footprint-ledger.md`), posted with the idle PR branches


- [ ] **Restore the full local lint gate on current main.** The October 14 session-controls qualification reproduced `scripts/check --only footguns,no-tmp,ruff` on unchanged main: all three fail, with 2,121 ruff findings. The candidate's changed production modules pass ruff and its health ratchet has zero blocking/advisory findings. Repair the existing footgun diagnostics, literal temporary-path documentation findings and repository-wide typing/style residue without weakening the checks. The Windows output-encoding issue has its own row below. · fork / lint · evidence: `docs/downstream/session-controls-2026-10-14.md` · measured 2026-10-15: 2,080 ruff findings (2,043 in 763 fork files, 37 upstream), 117 footguns (107 fork), 4 no-tmp; the `--fix` sweep touches 763 files every concurrent lane edits; upstream's 37 stay upstream's · RULED 2026-10-15 (owner): keep upstream's lefthook pre-commit and do one clean-up sweep of fork files, as a solo lane straight after the next landing; never `--no-verify` · BLOCKED 2026-10-16: another lane — a solo window straight after the next hermes landing, with no other lane open







- [ ] **Diagnose the Codex responses test process death in a completed fork gate.** On `292a429351` (2026-10-12), bundle 9 dies in `tests/agent/test_run_agent_codex_responses.py`, then that file passes alone and three following members are re-bundled. The full gate finishes, but the green isolated run does not qualify the crash. **TRIAGE 2026-10-12:** the existing runner discards the original bundle output when an isolated retry passes (`run_tests_bundled.run._bundle`), `Death` retains neither exit status nor prefix/output, and `run` removes the event scratch directory. Preserve first-attempt diagnostics through this same runner before attempting the exact-prefix reproduction; do not build a parallel runner or infer a timeout from the missing output. Current-main isolated control passes 69 tests. Evidence: named test and runner symbols, local `history-native-runtime-final-gate.log` and `history-red-triage-hermes-focused.log`. · fork / suite · partial repair LANDED 2026-10-13 (the redundant global sleep override; `_model_catalog_is_offline` in `tests/_downstream/agent_conftest.py`; the bundle plugin's `begin` record and `BundleEvents.last_begun`) and the runner keeps first-attempt diagnostics and classifies abnormal exits (`143f7d2855f`); the original interruption on `292a429351` is still unattributed — replay the exact bundle-9 prefix there under the runner · [H12/H13](../../docs/downstream/history-red-triage-2026-10-12.md), `docs/downstream/stream-delivery-diagnosis-2026-10-12.md` · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**


## Filed on arrival — 2026-10-16 (landing land-h5, reds proven on `origin/main` `b11585e6424` by `scripts/run_tests.sh` alone)


## Filed on arrival — 2026-10-16 (build lane h-bundle-speed, reds proven on `origin/main` `aba5fec098c`)


## Filed on arrival — 2026-10-16 (build lane h3-runser)

- [ ] **`scripts/check --only health` reds every pre-existing BLE001 in a file the change touches, so a docstring-only edit to `agent_runtime/mcp_admission/registration.py` fails the ratchet on 9 old hits** · fork / tooling · `scripts/code_health/compare.py::_hit_findings` (credit from `_owned_base_hits`) · measured 2026-10-16: a detached worktree at `origin/main` `ab6956f11826` plus one docstring word in `release_mcp_admission` reported all 9 `except Exception` hits in that file as new; the pinned ruff finds the same 9 on both sides · find why the base hits are not credited (owner/rename resolution of the base file?) and add the docstring-only case as a fixture · cause found 2026-10-16 (r-isolation): `scripts/code_health/measure.py::Measurer.measure` runs ruff on the base in a bare temp tree with no `__init__.py`, so a relatively imported `logger` reads as a bare name and BLE001 accepts its `exc_info=True` there but not in place (same bytes: 10 hits in the checkout, 1 outside); the measurer is upstream-owned, so the fix and its fixture test are drafted in `docs/agent-runtime-harness/upstream-prs/code-health-package-markers-body.md` (patched: 0 blocking, killing mutation recorded) · BLOCKED 2026-10-16: upstream — that PR, posted in the owner's next posting sitting

## Filed on arrival — 2026-10-15 (audit lane a1015-hfh)


## Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


## Filed on arrival — 2026-10-15 (lane w1015h-rt-h)

- [ ] **`tests/agent_runtime/test_native_conversation_in_process.py::test_a_b_a_turns_sessions_and_recovery_with_no_child_process[shared-provider]` reds (`ConversationError: native_refusal` on `service.skills(..., "list")` after a completed turn) when it runs after `test_native_worker_app_function_lifetime.py`, `test_tool_blocks.py` and `tests/tui_gateway/test_contract_catalog.py` in one process; 4 passed alone. Reproduced on `origin/main` `0917affed5a` with no lane change applied: a process-global leak from one of those three into the in-process worker's skills inspection** · `fork / suite` · lane: bisect the three, then restore the leaked global in that test's teardown · bisected 2026-10-15 (w1015j-hermes): only `tests/agent_runtime/test_native_worker_app_function_lifetime.py` + the node reds, about 1 run in 5, and the one red's traceback was not kept — loop the pair with full output until it reds, then read the refusal · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**

## Filed on arrival — 2026-10-15 (landing land-w1015j-h, reds proven on `origin/main` `88414c8d13e`)

- [ ] **Four fork tests time out under the -j 8 gate load and red on `origin/main` too: `tests/agent_runtime/test_operator_redo.py` (subprocess `communicate` timeout, red alone on BOTH main and the landing tree), `test_workspace_lifecycle.py::test_cli_delete_requires_yes_and_deletes_with_yes` and `test_operator_session_models.py` (the latter a real `urlopen` to the model catalog that hangs to the pytest timeout — a hermetic-net leak), plus `test_read_model_slo.py::test_synthetic_snapshot_full_build_within_rd0_slo` (wall-clock SLO)** · first triage: `test_operator_session_models` should never open a socket; the other three need their budget measured under gate load, not raised blind. Evidence: landing log of land-w1015j-h; `run_tests.sh` reruns of those files on `88414c8d13e` (4 red) vs the landing tree (redo only). · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**

## Filed on arrival — 2026-10-15 (landing land-w1015e, pre-existing reds proven on `origin/main` `ef2a4492272`)

- [ ] **`tests/hermes_cli/test_web_memory_provider_setup_install.py` (6 `test_setup_admits_real_provider_union_and_keeps_selection_on_failure[...]`) and `tests/hermes_cli/test_memory_dependency_admission.py` (2 `test_setup_requires_dependencies_and_keeps_the_existing_union[...]`) red on `main`: the plugin candidate's `uv` resolve fails ("depends on provider-dep==1.0 and provider-dep==2.0 … unsatisfiable") where the test expects setup to admit the union** · same node ids red under `scripts/run_tests.sh` on a detached `origin/main` worktree and on the landing tree · decide whether the fixture or the admission is wrong · fix HELD in `c94055924e2` on `origin/wave/w1015h-fh-h` (not on main): the 8 ids were stale strict xfails in `upstream_reds_v0217.py`, now XPASS(strict); the quoted "unsatisfiable" text is the tests' expected failure-path stderr — land it in a session-chain landing, then delete this row · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**

## Filed on arrival — 2026-10-15 (lane w1015b-fh-a)


## Filed on arrival — 2026-10-13 (upstream merge v0.21.7)

- [ ] **Three carried PRs drifted from their reviewed heads at the v0.21.7 merge: `agent/shell_hooks.py` (PR #123892) and `tools/terminal_tool_backends.py` (PR #128843) by upstream's ruff sweep inside auto-merged regions, `plugins/dashboard_auth/_shared.py` (PR #125259) because the footprint ratchet made the lane take upstream's bytes on a typing-only line; `scripts/check_carried_prs.py` on `main` reports 6 drift (3 pre-existing) and 5 errors.** The fix is on the PR branches (re-cut on v0.21.7, re-pin `reviewed_head` in `tests/fixtures/carried_prs.json`), not in the fork tree. · fork / carried PRs · evidence: `scripts/check_carried_prs.py` on `8e97c0efd6` vs `25f893f03d` · RULED 2026-10-15 (owner): yes, re-cut them — they are ours · the 2026-10-16 carried-PR drift row below carries the current measurement · DEFERRED 2026-10-16: owner "pr branches should remain idle" — until upstream accepts the owner's PRs again
- [ ] **The v0.21.7 landing gate ran the whole tree (a chain edit: the new `upstream_reds_v0217.py` table) and surfaced 23 inherited files the fork gate had never run on this box: 22 red on the fork's own main tip too (`scripts/run_tests.sh` baseline 2026-10-13), one new in v0.21.7 (`tests/ci/test_prompt_surface.py`, red on the pure tag, rowed). 35 nodes are strict `_up_red` rows. Still open, none the merge's: six nodes green on the pure tag but red here (`tests/ci/test_update_ci_routing.py`, `tests/hermes_cli/test_plugin_dependency_consent.py` x3, `tests/hermes_cli/test_venv_sync_currency.py`, `tests/scripts/test_powershell_script_syntax.py`); two files that die on the 30 s per-test timeout (`tests/pm/test_downloader.py`, `tests/scripts/test_release_handoff.py`); and the runner's eight bundle-process deaths, four red alone (`tests/hermes_cli/test_desktop_build_lock.py`, `tests/scripts/test_icon_flavors.py`, `tests/scripts/test_release_r2.py`, `tests/verify/test_environment_and_runner.py`) and four green alone (`tests/agent/test_overflow_partial_terminal.py`, `tests/pm/test_download_state.py`, `tests/scripts/install/test_install_ps1_native_calls.py`, `tests/scripts/test_release_entrypoint.py`), all unbundled-list candidates by the runner's own line. A retry that passes closes nothing here.** Classify the deaths and timeouts (skip-list `env` vs `upstream` with the tag reproducing them bare), fix or row the six. · fork / suite · evidence: v0.21.7 landing-gate log summary (69,982 passed, 24 failed, 20 errors, 42 re-run alone, 8 deaths); `scripts/classify_reds_on_tag.py` second run · the runner prints abnormal-exit members apart from leaks (`143f7d2855f`), which this classification needs · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**
- [ ] **The `reasoning-caps` rows carry a disposition the merge lane wrote, not the feature lane: eight `carry` rows name a PR candidate (provider-declared reasoning efforts + the scoped control-catalog cache) that nobody has cut.** The feature's own lane decides `upstream` vs plugin hook and either opens the PR or re-dispositions the rows. · fork / footprint · evidence: ledger rows stage `reasoning-caps`; `docs/downstream/reasoning-capabilities-2026-10-12.md` · BLOCKED 2026-10-16: owner decision — upstream PR or fork plugin hook for provider-declared reasoning efforts, with no reasoning-capabilities lane open? · Recommend: re-disposition the eight rows as fork-kept behind a plugin hook, since the upstream PR branches are idle

## Filed on arrival — 2026-10-09 (final gates)


## Filed on arrival — 2026-10-08 (lane opus-w1-hermes)


## Filed on arrival — 2026-10-08 GenUI qualification

- [ ] **Diagnose the running-turn stream intermittent remaining after the HTTPS-scanning control.** After the operator disabled scanning, the ten H01 files pass across controls (96 distinct passes / one existing skip), with certificate and permission assertions unchanged. On `f6c27f4d0b`, `tests/agent_runtime/test_serve_gateway_chat_reply_lanes.py::test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane` fails its six-second start-frame wait under eight-worker load, then both file tests pass serially. The two-roots file also passes all nine when allowed its declared duration; its earlier 120-second cap was a command choice. Trace the start-event publication/fixture boundary before changing behavior or deadlines. The former certificate blocker is qualified; the parallel failure remains evidence. Separate from H03 commentary. · fork / suite · [H01 control and log digests](../../docs/downstream/history-red-triage-2026-10-12.md#https-scanning-control-after-the-operators-setting-change), [H01 diagnosis](../../docs/downstream/stream-delivery-diagnosis-2026-10-12.md#h01-still-open-no-speculative-runtime-change) · no reproduction since `f6c27f4d0b`: the ten-file control passed 96 / one skip three times, the presence repair `911275e641` landed, and the test recorder keeps its reader exception + last 32 frame summaries on a failed wait; keep it as a watch and do not touch deadlines · BLOCKED 2026-10-16: another lane — the next landing gate whose log reds this node, with the recorder's frame timeline

## Filed on arrival — 2026-10-06 (lane console-generated-content)



The repository AS A FORK: upstream sync and the boundary, CI, the suite and its gates, the god-file refactor, this vault. Runtime and Mission Control rows do NOT go here — the hermes half is [[runtime-queue]], the launcher half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. Rows: one line + a pointer, never a restatement; claim with `**TAKEN <date> <who>**` before starting; a landing deletes its row.

## Filed on arrival — 2026-10-06 (lane h-prereq-window)


## Filed on arrival — 2026-10-05 (owner ask: a usable suite)

- [ ] **Per-test plugin LOAD is what is left of plugin rediscovery: discovery is session-cached since land/q4 (`tests/_downstream/plugin_discovery_cache.py`), but every test still re-imports each plugin and `_resolve_plugin_load_timeout` reads config per plugin; `test_operator_session_models` did not move (64 s)** · fork / suite · q-chain `3adc06ad40` body · upstream PR candidate for the per-plugin config read; the re-import half needs a ruling · READY
- [ ] **A bare pytest over files from several test directories hangs `test_gateway_spawn_fence::test_subprocess_run_refuses_the_measured_argv` (the fence is not armed; a real `gateway run` starts) and reddens `test_conftest_isolation_downstream` test_2/test_4; red on main `71079deb70`** · `fork / suite` · evidence: lane h-suite-hermetic report · reproducing it starts a real gateway on the operator's machine · BLOCKED 2026-10-16: owner sitting — a VM or watchdog box off the operator's desktop for the reproduction
- [ ] **Owner ask: make the partial (fork-scope) and full test suites fast enough to use — the fork gate ran 872 files / ~13k tests in ~18 min wall at 8 workers (per-file seconds summed 5,977; slowest file 233 s), ~13 tests/s, against the launcher's Flutter suite at ~40,000 tests in 8 min (~83 tests/s); the full scope is 6,066 files and on hold for the P0 freeze. Measure where the time goes (interpreter + import cost per process, conftest/fixtures, hermetic env setup, the slow tail, timeouts, Defender, worker count) and write a staged plan** · `fork / suite` · evidence: landing h-turn1 wave 2 gate log (2026-10-05 20:22–20:40 local) · **PLAN `plan/h-suite-speed` `6d2db880cf`; owner took O1–O5 as recommended 2026-10-06; exec lanes h-suite-runner (stages 0–3), h-suite-tail-a / h-suite-tail-b (stage 4); stage 5 after three identical failure sets, 6–7 after** · **Stages 0–4 LANDED `15d4e37d0d` (2026-10-06; full-tree gate 1059 s → 813 s, 99% utilization); open: stage 5 after three identical failure sets, then 6–7** · BLOCKED 2026-10-16: another lane — stage 5 waits on three identical whole-gate failure sets from landing gates

## Filed on arrival — 2026-10-05 (lane h-turn1-title)


## Filed on arrival — 2026-10-05 (lane h-turnws, the workstation freeze)

- [ ] **P0 — the validated suite froze the operator's workstation twice on 2026-10-05 (hard freeze, reboot both times), and both times the same four files were in flight: `tests/hermes_cli/test_source_check.py`, `test_source_launcher_publication.py`, `test_source_release_channels.py`, `test_source_release_probe.py`. Run 1: `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state`, 8 workers, frozen at 82.5% immediately after `test_source_stamp.py` and `test_spawn_gateway_restart_cooldown.py` reported. Run 2: only the 453 files run 1 never finished, 4 workers, nothing else heavy running, frozen within about a minute, right after `test_source_channel_integration.py` reported (so the in-flight set was a subset of those four). Both runs printed `real store root handed to the gateway fence`, and the operator's own gateway (`hermes_cli.main gateway run`) was up during run 2. NOT reproduced a third time, on purpose. Find which file does it — one at a time, under a watchdog or in a VM, never on the operator's desktop — and until then no lane runs the validated suite on a workstation with these four in scope** · `fork / suite` · the two interrupted run logs are not in the repo; the facts above are their last lines · the 311 `tests/hermes_cli` and 142 `tests/hermes_state` files after that point have NOT run for lane h-turnws · **Added the same day (owner's question):** all four files are UPSTREAM's (listed in `tests/fixtures/upstream_manifest.txt`), so the fork's own landing gate (`scripts/run_tests_bundled.sh …`, `--scope fork`, `docs/downstream-development.md` § "The fork landing gate") would not have run them; the lane ran `scripts/run_tests.sh` over the three directories because `CLAUDE.md` § Commands calls that "THE suite" and its landing discipline says "the validated suite". The two documents disagree about what a landing runs — make `CLAUDE.md` name the fork gate for a landing and keep the full scope for the weekly upstream merge lane · the FOLLOW-UP half landed: `docs/downstream-development.md` names `scripts/run_tests_bundled.sh tests` as the landing gate · BLOCKED 2026-10-16: owner sitting — a watchdog box or disposable VM off the operator's desktop for the one-file-at-a-time freeze bisect
## Filed on arrival — 2026-10-05 (lane h-turnws)


## Filed on arrival — 2026-10-04 (lane hb-a)


## Filed on arrival — 2026-10-03 (resident identity verification)


## Filed on arrival — 2026-10-02 (lane h-rows)


## Filed on arrival — 2026-10-02 (instance foundation)

- [ ] **Resolve intermittent realm-history ordering and validated-suite residuals without declaring retry passes stable.** · `fork / suite` · `test_realm_sync_history.py::test_history_lists_local_and_upstream_versions_with_their_items` fails on candidate and clean main `6c5cc00678`; download-pause assertions and three Git fixture setup errors pass isolated reruns. Raw receipts: `resume-hermes-validated.log`, `resume-main-hermes-residuals.log`, `resume-hermes-final-focused.log`, `resume-main-realm-history.log`. Includes `test_local_download_jobs`, `test_local_models_routes`, `test_delivery_directive`, `test_realm_revert_version`, `test_source_channel_integration`; cause not established. · reproduced on unchanged main `541f497902` (2026-10-03) and after `test_realm_sync_eol.py` in a bundle (2026-10-07, `e357dec49a`); `test_realm_sync_history.py` green alone 2026-10-15 (2 passed) · protocol: `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.12 (bundle-prefix bisect) · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**

## Filed on arrival — 2026-10-02 (lane w13-hm, filed by the orchestrator)


## Filed on arrival — 2026-10-02 (lane w10-s7h)


## Filed on arrival — 2026-10-02 (lane w5-fh)


## Filed on arrival — 2026-09-30 (GenUI invocation)


## Filed on arrival — 2026-10-01 (lane w3-turn)


## Filed on arrival — 2026-10-01 (lane w3-perf)


## Release validation — 2026-09-23


**Provider-boundary qualification, October 1:** the existing TLS setup stall and duplicate-name/routing-ladder gate failures were reproduced, not waived; [evidence](../../docs/downstream/provider-access-boundary-2026-10-01.md#qualification). Native provider, plugin and execution checks pass; this does not certify a whole-repository green run.


- [ ] **Diagnose the local CLI startup stall opening the inherited TLS key-log device target.** · The bounded inspector trace stops at `ssl.create_default_context` assigning `keylog_filename`, reached while `pm/downloader.py` constructs its opener during startup; no chat journal was created. Preserve certificate validation and logging oversight; classify host configuration versus startup handling before changing code. [Preflight evidence](../../docs/downstream/launcher-qa-preflight-2026-09-30.md#local-startup-stall). Filed 2026-09-30 Projects QA. · classified 2026-10-02 (w5-fh): HOST trigger (an inherited `SSLKEYLOGFILE`), UPSTREAM amplifier — `pm/downloader.py` builds `_OPENER` at module scope, so a bad key-log target breaks every CLI start that imports it · RULED 2026-10-15 (owner): open the upstream PR (lazy opener) from branch `upstream-pr/lazy-https-opener` (`95b3221fbec`) under the owner's name, posted together with the others · DEFERRED 2026-10-16: owner "pr branches should remain idle" — until upstream accepts the owner's PRs again


**Additional evidence for the claimed validated-suite residuals:** 68 gateway/TLS failures reproduce on clean primary with Python 3.13.15; this does not supersede the separate Python 3.12 green receipt. [Comparison](../../docs/downstream/chat-first-group-qualification-2026-09-29.md#baseline-comparison). Filed 2026-09-29 chat-first-groups.





- [ ] **Isolate wrapper-publication tests before resuming interrupted desktop qualification.** · Whole-PC freeze during the single-worker continuation; running-wrapper publication is the last surviving fixture, not a proven cause. Preserve evidence; use contained off-desktop reproduction, not an unbounded rerun. [Incident boundary](../../docs/downstream/discussion-qualification-2026-09-28.md#host-freeze--qualification-interrupted). Filed 2026-09-28 Discussion qualification. · static read 2026-09-29: `tests/hermes_cli/test_source_launcher_publication.py::test_running_source_launcher_can_republish_itself` is bounded, a candidate trigger only through the OS/driver side of self-overwrite; the updater-retarget half is fenced by `319c6ff69d` · DEFERRED 2026-10-16: owner 2026-09-29 "park, low priority; needs a disposable VM" — until a disposable Windows VM exists or the next clean desktop qualification



### Filed on arrival — 2026-10-15 (owner screenshot during land-w1015h)


### Filed on arrival — 2026-09-29 (h11-mcp landing)


### Filed on arrival — 2026-09-29 (lane h10-fhrest)


### Filed on arrival — 2026-09-29 (lane h7-phone)


### Filed on arrival — 2026-09-28 (lane w5-hstt)

### Filed on arrival — 2026-09-29 (lane h10b-triage — the three-directory triage, one row per class)


### Filed on arrival — 2026-09-28 (lane w4-hfix2)

### Filed on arrival — 2026-09-27 (Windows console signal safety)

- [ ] **Retire the Windows signal-safety carry when upstream adopts an equivalent fix.** · [[Windows console signal safety]]; held upstream candidate recorded in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`; no parallel supervisor or PID helper added, no PR submitted. · RULED 2026-10-10 (owner): carry stays; re-check at the next release merge · re-checked 2026-10-16: upstream `v0.22.2` `tui_gateway/host_supervisor.py::_pid_alive` still calls `os.kill(pid, 0)` · BLOCKED 2026-10-16: upstream — upstream adopting an equivalent in `tui_gateway/host_supervisor.py::_pid_alive`; re-check at each release merge

### Filed on arrival — 2026-09-26 (native Hermes qualification)

- [ ] **Finish classifying the validated-suite residuals, including the two worktree-only fleet identity assertions and baseline gateway certificate mismatch blocking registered mutations.** · [Native qualification evidence](../../docs/downstream/native-hermes-qualification-2026-09-26.md); [[Windows console signal safety]] adds an incomplete one-hour run and failures reproduced on primary in 33 of 35 files; no baseline expansion or unrelated runtime repair was made. · 2026-09-29 h10b-triage: both named residuals are green in a worktree — `test_fleet_matrix_down_state.py` 7/7, `test_local_llama_adapter_gateway.py` 2/2 ([triage note](../../docs/downstream/triage-561-2026-09-29.md)); the rest of the validated-suite residual population is outside the three-directory run and still needs the validated suite, so the claim stays · EVIDENCE 2026-09-30 unified-genui: completed 2,173-file run; 101/108 failed assertions and 14 collection/exit failures reproduce on primary; [comparison](../../docs/downstream/unified-document-native-tools-2026-09-30.md#qualification--2026-09-30). · EVIDENCE 2026-09-30 hermes-work-view: 2,176-file run, 31/35 residual assertions and all 14 collection/teardown failure files reproduce on primary; four checkout-dependent fleet/updater assertions remain. [Receipt](../../docs/downstream/hermes-work-view-2026-09-30.md#validation). · EVIDENCE 2026-10-03 resident identity: reproduced again on unchanged main `541f497902`; `identity-baseline-suite-2026-10-03.log`, exact failure-set comparison in the [repair note](../../docs/agent-runtime-harness/planned/instance-conversations-2026-10-01.md#resident-identity-repair-october-3). · EVIDENCE 2026-10-06 operator Stop audit: the whole-tree fork gate selected 891 files; all 113 failure/error nodes in 31 files reproduced on clean pre-fix main, with zero branch-only nodes. Current-main legibility/duplicate-helper/doc-cite drift was also qualified after rebase; [receipt](../../docs/downstream/operator-stop-audit-2026-10-06.md). · EVIDENCE 2026-10-07 console relay: 117 residual failure/error nodes in 35 files match detached unchanged `8a5c19d412`; drift diagnostics also match. The one branch-only plain-head admission regression was fixed and the final 14-file run passed 238 tests. Fork-only scope, exact commands, node-set digest and red/green proof are recorded in `e357dec49a`; no full upstream suite was run. · EVIDENCE 2026-10-10 result-authority: whole-tree fork scope selected 941 files, 11,888 passes; after removing this lane's stale wording-test waiver, all 97 remaining failing/error nodes in 25 files match untouched `d2cb51d7af`. [Exact node sets and controls](../../docs/downstream/native-result-policy-2026-10-10.json). No baseline was expanded. · EVIDENCE 2026-10-10 native representation: all 97 residual nodes reproduce on untouched `f43ffb8efe`; this change's two routing violations were repaired, final focused/structure selection 163 passed. [Review and qualification](../../docs/downstream/native-representation-2026-10-10.json). · protocol: `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.14 (`scripts/classify_reds_on_tag.py` automates it) · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**

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

- **hermes CI on `main`: the runner crash and the 43 lint errors and the mutation job are fixed; what is left is hb's slices 5–8 and the Issues switch** · `hermes` · **NARROWED 2026-09-06 (w18/ha `57b6964b01` (pre-rewrite), w18/hc `2b1f6e849c` (pre-rewrite))** — run 34046863701 (hc's push) is the first with `ruff enforcement (blocking)` and `Changed-line mutation claims` GREEN. **ha, slices 1–4, CLOSED:** all 16 tests across 11 files, one commit per file (`48a690da4c` doc-cite report needs a 4-commit repo under a depth-1 checkout; `188c511bae` + `9765564afa` stale `patch()` targets from `96cfc09a34` (pre-rewrite); `9463780a78` tool-inventory mutations wrote CRLF; `caffc04c1c` a hand-typed Windows byte count; `43cbb598ef` a real duplicate helper (`realm_sync._ledger_time` == `store._stamp`); `30f1ec6635` a BOM on `install.ps1` from the 2026-07-31 upstream merge; `23a90c6063` `test_env_gap_registry` was a DESIGN fault — a green host was read as "every row rotted"; `cee66b50fd` a witness that had not followed its reader; `d2137867b7` a directory-only git exclude that misses POSIX's symlink, which is also why the worktree GC never reaped on Linux; `ce3dc7f465` `os.path.normcase` on Windows-registry PATH data). Six of the eleven reproduced on Windows and were never platform facts — they live outside the four validated test directories and had simply never been run. **hc, CLOSED except Playwright:** ruff's 43 were all genuine `F821` (38 undeclared names in exec-assembled part-file import headers, 5 a missing `typing.Any`), 0 noqa (`fa0fb62788` (pre-rewrite), `f29ad6ca6c` (pre-rewrite), `3af990fca7` (pre-rewrite)); `test_harness_parts_namespace.py` never checked header PRESENCE, ruff is the real gate, said so in `6c629b9122` (pre-rewrite); the mutation job's exit was right and four registered needles had stopped anchoring — re-derived, each proven KILLED, plus `tests/scripts/test_mutation_claims_still_anchor.py` (`abaace6a87` (pre-rewrite), `bbc1caafb0`), and a fifth needle went ambiguous on landing over hd and was fixed forward (`2b1f6e849c` (pre-rewrite)). The notifier `notify-main-red` LANDED (`028aceb9c6` (pre-rewrite)) and FIRED on run 34046863701 — and failed on its own step, because **Issues are disabled on `nekwo/hermes-agent`** (register row). **hb, slices 5–8, CLOSED (hermes `962a10d0fb` (pre-rewrite), 13 commits):** all nine reds and the uncollected `test_tombstone_registry.py` (1,155 tests lost at collection to a `check=True` diff under `fetch-depth: 1`); two were the CI checkout, not the code — `ci.yml` now fetches full history with `filter: blob:none`, and the docket gate had been FALSELY accusing seven backed stages; three were product defects (`_ABS_PATH_RE`'s POSIX branch truncated at the first space, `entrypoint_name` used the host separator, `note_peer_seen` read the clock twice); the eight `stream_frames` goldens were regenerated for a path-tail redaction (`262a165b47`), which the launcher re-vendored 2026-09-06 (w18/lf). **What remains here:** (1) the next main-push run after hb lands must show the eight slices green; (3) the Issues switch, then one red push to prove the notifier end to end; then delete this row. · BLOCKED 2026-10-16: owner decision — turn Issues on for the fork's GitHub repository so `notify-main-red` can file? · Recommend: yes, then one red push proves the notifier end to end
- **Three hermes tests the CI runner reports FLAKY, which AGENTS.md calls bugs** · `hermes` · found 2026-09-06 (w18/ha) in run 33969282189's slice logs — `tests/agent_runtime/test_serve_stream_lane_parity.py`, `tests/run_agent/test_run_agent.py::TestExecuteToolCalls::test_sequential_tool_calls_run_without_delay`, `tests/tools/test_browser_eval_supervisor_path.py::TestEvaluateRuntimeDomNodeCrashRetry::test_reference_chain_crash_retries_without_by_value`. All three read as timing-sensitive: convert to controlled time at the mechanism, never a longer deadline; `tests/agent_runtime/test_realm_sync_eol.py` also hit the 30 s per-test cap under contention on this box (36 s alone). Agent work. · READY 2026-10-16
- **`tests/test_coverage_claims_resolve.py` sits on a 180 s wall its own fixture now overruns** · `hermes` · found 2026-09-06 (w18/hd), measured not asserted — the file declares `pytestmark = pytest.mark.timeout(180)` and its comment records `collect_claims()` at 27–31 s over three runs on 2026-09-02; called directly today with nothing else running it took 211.5 s in the primary checkout on unmodified `main` and 279.5 s in a worktree under `X:/wt`, identical corpus census in both (241 md / 4,097 py / 3,089 test / 725 claims). It passed once mid-lane at 176.4 s. The marker was NOT raised. Two questions, one row: did the walk regress (bisect `collect_claims` between 2026-09-02 and today) or did this box's IO, and why is a worktree ~30% slower than the primary (the Defender exclusion covers the primary's drive, not `X:/wt` — check `Get-MpPreference` ELEVATED, it is blind otherwise). Fix the walk or gate the fixture on a cached census; never widen the wall. Agent work. · READY 2026-10-16
- **Desktop E2E on Linux: the sentinel background command is stopped by a terminal-command approval prompt, so no background process ever spawns** · `hermes` (desktop app + E2E harness) · found 2026-09-06 (w18/hg) while closing the "polls the background dot as a turn-is-running signal" row (fixed in hermes `b4c9dfbd56` (pre-rewrite): `sessionDotState` is right, all three E2E call sites now poll the `Session running` label, plus a unit case pinning working-over-background with its recorded killing mutation). That fix does NOT make the job green. Evidence is the failing run's own page snapshot (`playwright-test-results` artifact of run 34051553815, `error-context.md` of the sidebar-states spec): at the 30 s timeout the sidebar row shows `status "Session running"`, and the tool row shows `Running echo "long bg output" + 6 commands` with 27 s elapsed on a `background=true` call plus a `Run` / `More approval options` / `Reject` approval bar. A background terminal call returns immediately, so the tool never executed: no `running` item, no subagent row, the composer still "Waking up". The gated command is `sidebarCrossBgCommand(releasePath)` in `apps/desktop/e2e/mock-server.ts` (an `echo` then a `for`/`seq`/`sleep 0.1` poll loop on a release file), introduced by `3a3bc41c7e`; the `sleep 5` fallback the other two specs use is never gated. Ruled out from Windows: `tools.approval.detect_dangerous_command` returns `(False, None, None)` for BOTH forms. NOT ruled out: `tools.tirith_security.check_command_security` returns `allow` for both locally, but tirith is not installed on that box, so it is a fail-open, not a verdict; on a CI runner tirith auto-installs from GitHub releases and is enabled by default, and `check_all_command_guards` sends any tirith `warn`/`block` to the same approval gate. Two things to settle, in order: (1) read the approval's `description`/`pattern_key` from the backend on a Linux run (it sits in a collapsed disclosure and is NOT in the Playwright trace DOM) and name the flagging rule; (2) decide whether the fix is reshaping the sentinel command or making the E2E sandbox hermetic (a harness that auto-downloads a third-party scanner binary at test time is a network-dependent input to every terminal-using spec). Do NOT guess a command reshape without (1). The next CI run after `b4c9dfbd56` (pre-rewrite) is the proof, and it will fail at `waitForFunction(finalText)` rather than at the dot poll. Agent work. · READY 2026-10-16
- **hermes pack maintenance is a SILENT no-op on git < 2.32** · `hermes` · `_run_bounded_repack` issues `git repack -d --geometric=2 --write-midx`, which exits 129 on older git; the runner sends both streams to DEVNULL and never reads the return code, then `_claim_repack_slot` suppresses retries for 6 hours. Measured on git 2.31.1.windows.1 — this box. Upstream-owned; decide: warn, fall back to `repack -a -d`, or require 2.32. Ruling 1. · `hermes_cli/web_routers/git.py`, upstream-owned · BLOCKED 2026-10-16: upstream — an upstream issue on `hermes_cli/web_routers/git.py::_run_bounded_repack` (warn, fall back to `repack -a -d`, or require git 2.32); none filed
- **hermes `gh_auth_status_route` caches a stale logged-out answer on a coarse clock — upstream race, report upstream** · `hermes` · the stale-probe guard compares two `time.monotonic()` reads with `>=`; Windows resolution is 15.625 ms (10000/10000 back-to-back reads identical, deterministic failure of upstream's own `test_gh_auth_refresh_waits_out_a_probe_started_before_it`), Linux still ties 1009/10000. Operator symptom: dashboard says "not signed in to GitHub" for the 5-minute TTL right after signing in. File is byte-identical to upstream — the fork does not patch it. Ruling 3. · BLOCKED 2026-10-16: upstream — an upstream issue on `gh_auth_status_route`'s `>=` monotonic guard; none filed
- **hermes kanban worktree teardown on Windows: does cleanup move out of the directory before removing it?** · `hermes` · `test_cleanup_proceeds_when_cwd_was_deleted` is `linux_only` as of hermes `3de9a499d3` because its premise is POSIX (Windows answers WinError 32) — the Windows behaviour of that path is untested, not proven safe. Ruling 2. Related vocabulary gap: only three OS markers exist, so POSIX-generic tests are spelled `linux_only` and drop out of macOS; a `posix_only` marker is the honest fix. · `hermes_cli/worktree_ops.py` is upstream-owned; the `posix_only` marker is fork tooling · READY 2026-10-16

- The unrun-gate class on hermes `main`: nothing on any push lane runs the full suites, so reds accumulate silently. Two instances measured and FIXED 2026-08-30 (hermes `00fa94dd75` (pre-rewrite)): `tests/scripts/test_run_tests_script.py` (pins now follow `$RUNNER_PATH` and the import-pytest venv probe) and `tests/hermes_cli/test_error_exit_code_producers.py` (`runtime_unavailable` left `_KEPT_UNSPENDABLE` — the gateway lane mints it at five sites). The CLASS is NARROWED 2026-09-02: hermes' push gate now exists (`fc2e16349e` (pre-rewrite) — Lane B runs the validated 4-dir lane on `main` pushes), so what stays open is only the dirs outside that lane, e.g. `tests/scripts`, home of the first instance. Evidence: the misc-batch landing report (hermes `5fa9000b2`), both fixes `00fa94dd75` (pre-rewrite); hermes `AGENTS.md` §Testing. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16
- Hermes's focused suites cannot be trusted under multi-agent load: the named instance is RETIRED by suite-perf Stage 6 — `test_realm_sync.py` now drives `run_harness_in_process` (`tests/agent_runtime/_harness_cli`) and carries no `timeout` at all (verified 2026-09-01). The CLASS survives: an in-test subprocess cap `--timeout` cannot raise is invisible to the runner. Original filing: it timed out at load average ~400 on a command the diff never touched; fifteen failures across two suites on 2026-08-30 were all this class. Either the in-test cap becomes environment-scalable or the wave serializes pytest across agents. Evidence: the misc-batch landing report. **RULED 2026-09-04 evening (operator, recommended answer adopted):** Option 1. There is no scaling helper anywhere today — a repo-wide grep for `HERMES_TEST_SUBPROCESS_TIMEOUT` / `timeout_scale` finds only an unrelated audio test — while 474 test files carry a `timeout=`, so the class is broad and nothing currently absorbs load. Option 2 needs exactly the cross-agent orchestrator the shared-index row above says does not exist, and serializing test runs is a direct tax on the multi-agent workflow this house runs by default. Next: hermes: add the scaled-timeout helper plus its env knob, convert the subprocess caps in the test tree to use it, and add a gate refusing a bare numeric subprocess `timeout=` in `tests/`. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16

## Filed on arrival — 2026-09-24 (lane CARRY2A)



## Filed on arrival — 2026-09-24 (lanes UPPR2, REDS)


### Filed on arrival — 2026-09-29 (lane h12-upnew)


## Filed on arrival — 2026-09-24 (disposition wave)


## Filed on arrival — 2026-09-23 (seam Stage 0 lanes)


## Filed on arrival — 2026-09-21 (upstream sync assessment)

- [ ] **PR candidate: run_tests_parallel amortised start-up** · `fork / upstream` · after `76e6fb0dc8` the per-file floor is upstream's own (~1.1 s to session start, ~2.6 s to collected, × every file); the five would-be upstream commits (phase timings, LPT order, small-file batching, POSIX fork workers, lazy root-conftest hooks) are outlined one per bullet with saving and isolation trade; the lane that builds it re-takes the upstream full-suite wall IDLE first (lane SPEED's was loaded) · evidence: `docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md` §8–§9 · fork after-fix baseline 40.7 min idle (2026-09-24) · 2026-09-24 (lane SUITE2): the measured PROTOTYPE of the batching bullet is the fork-only `scripts/run_tests_bundled.py` (+ `.sh`, plugin in `scripts/_bundle_plugin/`), core free of fork paths; first idle validated-scope run 1,802 s (30.0 min) vs 2,442.7 s per-file, 91 bundles, reds unchanged — the wall is held up by known-red files whose pytest-timeout kills a whole bundle (see the row below and the cost note §10). Owner decides when the upstream PR series is cut; the lane that cuts it takes the upstream idle wall first. · 2026-09-29 h12-upnew: LEFT, not opened — the series needs the upstream idle full-suite wall first (an exclusive ~40 min box) and our open runner PR #125263 on the same file is unreviewed with a body that describes fork-only code (h10b note 1); fix that body before a second runner PR goes up · DEFERRED 2026-10-16: owner 2026-10-10 "parked stays parked" — until the owner's go on the upstream series

## Filed on arrival — 2026-09-21 (god-file refactor plan)


## Filed on arrival — 2026-09-21 (brain)


## Filed on arrival — 2026-09-24 (lane CARRY2B)


## Filed on arrival — 2026-09-24 (lane REDS2)


## Filed on arrival — 2026-09-24 (lane CARRY3)


## Filed on arrival — 2026-09-24 (lane TESTS)


## Filed on arrival — 2026-09-24 (lane REDS3)

- [ ] **`test_tui_gateway_server.py::test_notification_poller_live_loop_requeues_foreign_completion_for_owner` is order/timing-flaky: a stray `session.info` frame (this worktree's cwd and branch) reaches its captured writes** · `fork / suite` · red once in a five-file run on `6251144d09`, green alone and green on the next four-file run; find the emitter that outlives its test (a session-info publish from an earlier test's thread) and join or drain it in teardown · evidence: lane REDS3 `.lane-logs/base.log` (`assert [('session.info', 'msg-id-trunc-sid', {...'branch': 'fork/main-reds-2026-09-24'...})] == []`) · traced 2026-09-24: the only test naming `msg-id-trunc-sid` is `test_prompt_submit_truncates_by_message_id` (upstream bytes), whose daemon `_run_after_agent_ready` thread is never joined, but alone it never calls `server._session_info`; if it reds again, capture the stray's stack with a patched `_emit` in the failing multi-file run · DEFERRED 2026-10-16: owner 2026-10-15 "no decision owed: not reproduced" — a watch until it reds again **TAKEN 2026-10-17 claude (r-gateway)**

## Filed on arrival — 2026-09-24 (lane CLOSE)


## Filed on arrival — 2026-09-24 (program-end gate on `c7652475cd`)

- [ ] **`tests/hermes_cli/test_minimax_oauth.py::test_refresh_error_body_bounded_and_readable_with_real_client` is red in its bundle and green on the rerun alone** · `fork / suite` · a co-member leaves a client or transport patched; bisect the bundle pairwise (REDS2 method, `016a6cd71e`) and fix the leak or add the observed pair to `scripts/test_bundles_unbundled.txt` · evidence: `X:/wt/_holds/gate-final-2026-09-24.log` ("red in bundle" line) · not a co-member leak: the gate's exact bundle passed as one process (236 passed); the test streams a 64 KB body over a real loopback socket (upstream bytes `d10bb2ab6f`), so the fix is upstream (read to EOF / body under one socket buffer) or a load-timing id-mark · DEFERRED 2026-10-16: owner 2026-10-15 "hold until it fails a second time"

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

- [ ] **`test_every_stage42_global_flag_is_honored` is a source walk keyed on the name `args`: a flag read through `self.args` or a renamed parameter reads as unhonoured, so phase objects must read flags in the handler** · `fork / gates` · a source walk certifying a POSITIVE guarantee ("this flag is honoured") by spelling — the fork CLAUDE.md gate rule says ask the runtime or the element model; re-key it on the parser's `set_defaults` targets and the attribute reads they reach · evidence: B2 gateway_commands CHANGE body · filed by lane B2 2026-09-25 · widening the visitor to `self.args` is another spelling; the re-key is a runtime probe (each `set_defaults(func=…)` handler driven with a recording Namespace under a side-effect fence), which needs the handler fence picked first · DEFERRED 2026-10-16: owner 2026-10-10 "parked stays parked"

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

- [ ] **Test and lane homes still land their `bin` on the operator's real user `Path` after the 2026-10-03 PATH fence: 14 of 30 leaked entries were created 2026-10-05 (`stage2-serve-*`, `stage4-gateway-*`, `rb7-identity-flip-*`, `ro9-boot-sweep-*`, `rs7-restart-fence-*`, `p-l-longrun-*`, a lane's `scratchpad/live`); the first one shadowed `hermes` and the operator's `hermes harness observe` died on a deleted interpreter** · fork hygiene / test isolation · evidence: `[Environment]::GetEnvironmentVariable('Path','User')` read 2026-10-06 00:35, dated by each dir's CreationTime; writers are `hermes_cli/_launchers.py` (user-Path merge) and `windows_env.py`, fence `hermes_cli/_registry_write_fence.py` · lane: find the writer the fence misses (a subprocess outside `install_path_fence`, or a root the fence counts as owned), make the gate a positive test, then a one-time cleanup verb the operator runs · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.15; stages 1–2 built (`805f8293c9` `4045fa25c8` `811fc986e7`) · BLOCKED 2026-10-16: owner sitting — on the workstation: stage 0 (Process Monitor on a launcher real-serve sandbox run) and `scripts/prune_user_path.ps1 -Apply` after reading its list; stage 3's -SkipUserPath upstream PR waits with the idle PR branches

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


- [ ] **Supersession pass owed for the v0.21.6 release merge: the merge (`3002eaa067`) recorded drop 7 / extract 0 / upstream 0 / kept 21 but no supersession count (runbook `Merging upstream.md` Steps 4-6). For each of the 21 kept fork hunks in upstream files: is it now redundant with v0.21.6 (drop), movable behind a door upstream now offers (extract), or still needed (kept, reason); report the `[up-fp]` line before/after** · fork / upstream sync · merge commit body `3002eaa067`; `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` · the v0.21.6 pass is overtaken by later merges (v0.21.7 `3c5936ba96a` recorded per-hunk reasons; v0.22.2 since); a whole-ledger supersession pass belongs to the next release merge (`Harness_Brain/50 — Agent Handoffs/Merging upstream.md` Steps 4–6) · BLOCKED 2026-10-16: another lane — the next release-merge lane
## Filed on arrival — 2026-10-10 (chat content integrity)


## Filed on arrival — 2026-10-10 (chat-content boundary qualification)




## Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)

- [ ] **The hermetic `DEFAULT_DB_PATH` pin depends on import order: `tests/conftest.py` pins it only if `hermes_state` is already imported, so profile-scoped store tests pass alone and red after any importer** · fork / suite · `queue-sweep-2026-10-10/L7-outcomes.md` L7.01 · lane: suite · upstream-owned on both sides (`tests/conftest.py` step 3b, `tests/gateway/test_multiplex_routing_authz.py`), so the answer is an upstream issue/PR · RULED 2026-10-15 (owner, decision sheet w1015i #2): post the upstream ones together in one sitting · DEFERRED 2026-10-16: owner "pr branches should remain idle" — until upstream accepts the owner's PRs again

## Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)

- [ ] **`run_tests.sh` re-runs a red file alone, so a test whose red writes real machine state (registry, user PATH) writes it twice; a destructive-on-red test has no opt-out from the retry** · fork / suite · build-1011-B5 D3.15 mutation (2 PATH entries from 1 run) · lane: runner · `scripts/run_tests.sh` is upstream-owned, so a destructive-on-red opt-out needs a fork-owned runner door · NEEDS PLAN 2026-10-16: where the fork-owned door lives (a bundled-runner flag or a test marker the retry honours) and how a destructive-on-red test declares itself
- [ ] **The shared test venv's SQLite 3.50.4 forces `journal_mode=DELETE`, so no WAL-path behaviour (sidecar races, checkpoints) can be exercised live on the workstation** · fork / suite · build-1011-B5 D3.02 stage 3 · lane: test-venv refresh · still true 2026-10-15 (venv Python 3.14.5 links SQLite 3.50.4); WAL needs an interpreter linking SQLite >= 3.51.3 or the 3.50.7 backport · RULED 2026-10-15 (owner): yes, rebuild the shared venv at the next landing · BLOCKED 2026-10-16: another lane — the next hermes landing rebuilds the shared venv

## Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast-gate design, guard fix, build batch 2 C1–C4, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


## Filed on arrival — 2026-10-11 (fast-gate landing, whole-tree gate, filed by the orchestrator)

- [ ] **Thirteen files go red in the whole-tree gate by timeout rather than assertion — nine also red on a quiet base `828fdb3c0e` (`test_update_ci_routing`, `test_desktop_build_lock`, `test_run_agent`, `test_icon_flavors`, `test_run_tests_parallel`, `test_known_file_write_baseline`, `verify/test_environment_and_runner`, `test_tui_gateway_server`, `test_serve_exit_flush`) and four at the 30 s per-test edge (`test_install_ps1_native_calls` 27.9 s, `test_no_shadowed_test_definitions` 29–31 s, `test_install_clone_throttle_fallback`, `test_web_server::test_concurrent_first_load_reads_all_succeed_on_fresh_store`)** · fork / suite (the CLASS; four of the nine have their own rows) · `queue-sweep-2026-10-10/FG-landing.md` · lane: classify each (Windows upstream red → marker; fork-caused → fix; honest slow test → a per-test timeout) on the idle box · TRIAGE: H09 Windows process death is repaired; other files remain open. [H09 disposition](../../docs/downstream/history-red-triage-2026-10-12.md). · `test_known_file_write_baseline` passed its 1-worker retry 2026-10-15 (slow, not red) · BLOCKED 2026-10-16: owner sitting — the idle workstation (no other lane running) for the classification runs
- [ ] **CLASS (third instance): a new lazy import on the turn path silently adds first-turn cost until the turn-cost guard catches it, and that guard's IMPORT check runs only on the idle box because its file is idle-only — v0.21.6's three modules (`97b33c3c49`), the capability probe + netrc (`c3894ae54d`), M2.05's `request_effort` (`c835697c3c`)** · fork / suite · `queue-sweep-2026-10-10/idle-box-2026-10-11.md` · lane: split the guard's import-count check (load-independent) out of the idle-only file so every landing gate runs it; the structural answer is the gate, not a fourth warm-list line · read 2026-10-15 (w1015e-fh-h): lift the scenario into `_run_guard(...) -> (violations, budgets, spans)` in the same file, keep the idle test asserting both, add an unlisted `test_turn_cost_guard_counts_downstream.py` asserting `violations` only, after moving the one clock check (`queue_ms > QUEUE_BEHIND_RIDERS_MS`) into `budgets` · BLOCKED 2026-10-16: another lane — one qualification run inside the next loaded bundled landing gate before the counts file joins every landing
- [ ] **`tests/agent_runtime/test_stream_gap_receipt.py::test_starved_reader_shows_lag_and_late_wakeups` misses its 150 ms lag floor even on the idle box (110 ms on 1 of 2 first attempts, passed on retry); the D3.09 row was closed on the first idle runs too early** · fork / suite · `queue-sweep-2026-10-10/idle-box-2026-10-11.md` · lane: a hog the scheduler cannot skip, or a floor measured on the idle box over ≥10 runs (never lowered to pass) · BLOCKED 2026-10-16: owner sitting — the idle workstation for >= 10 runs (`scripts/run_tests_idle.sh`)


## Filed on arrival — 2026-10-11 (Console history final qualification)

- [ ] **Requalify the last two host-sensitive strict xfails from hosted Windows run 38426498916: `tests/scripts/desktop_update/test_desktop_update_windows_marker.py::test_owner_creation_time_is_read_for_system_processes[False|True]` XPASS on the elevated hosted runner and red here with "no process here grants only limited query rights" (unelevated, by the look of it; not demonstrated).** · fork / inherited-test expectations · the other 15 of the 17 nodes are qualified: 5 retired on main earlier (`455ea739f72`, `9effac5d6a2`), `test_source_build` retired and 9 moved to probe-backed env-gap rows (unelevated `sc.exe`, user-vs-system `core.autocrlf`, delivery CLI through PATH) by lane r-isolation 2026-10-16 · move the two ids to the `_unelevated_windows_shell` owner only after one elevated run shows them green; do not make them non-strict · BLOCKED 2026-10-16: owner sitting — one run of the two ids in an elevated shell




- [ ] **Qualify the two inherited first-attempt timing failures retained by hosted triage.** `test_run_agent.py::TestRunConversation.test_redirect_from_input_thread_cancels_live_model_request` misses its two-second entry event during plugin discovery; `test_stream_consumer_wecom_native.py::TestClarifyEagerReseed.test_double_clarify_boundary_reseed_chain` reads the seed count after a fixed 50 ms drain. Both pass isolated recovery in [candidate run 38427670480](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38427670480), and neither assertion reproduced in [baseline run 38439426620](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38439426620). Production, these tests and their fixture owners are byte-identical between `958e574c2e` and `3c2ba45c4b`; collected fixture bindings exclude the backup fixture in both and include it in the backup control (`triage-fixture-exposure.jsonl`, SHA-256 `42bd97d5eea58c2ac864ede993c3146c388e2b4eb044245b19b4c891f30d3f6f`). Preserve these as unresolved intermittents, not a clean first-attempt result. Investigate completion-based synchronization and cleanup on early assertion failure through existing test owners; do not widen deadlines or modify runtime behavior without reproduction. · fork / inherited-test qualification · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**

- [ ] **Give the ACP stdio-registration test a real temporary workspace.** `tests/acp_adapter/test_server.py::TestRegisterSessionMcpServers.test_registers_stdio_servers` declares `/tmp` and asserts it is a resolved local directory. On hosted Windows, `resolve_context_cwd` correctly returns `None` when that directory does not exist. The exact assertion fails on both `3c2ba45c4b` and untouched `958e574c2e` in runs 38427670480 / 38439426620. Use the existing `tmp_path` fixture and keep the working-directory propagation assertion; no production resolver change. · fork / inherited-test qualification · upstream main still declares `/tmp`: an upstream PR, or a skip-list row once it is red bare on origin/main here · RULED 2026-10-15 (owner, decision sheet w1015i #2): post the upstream ones together in one sitting · DEFERRED 2026-10-16: owner "pr branches should remain idle" — until upstream accepts the owner's PRs again

## Filed on arrival — 2026-10-13 shutdown-test repair

- [ ] **Qualify native Windows MSYS foreground-child ownership and cleanup.** Three `sleep.exe 3518` children survived the failing inherited shutdown-test setup; adding the executable suffix did not make the ancestry scan find them. They were explicitly reaped. The repaired test owns its Python child by a ready PID receipt, which does not prove MSYS tree cleanup. Reproduce through the existing local-environment process owner before attributing a production defect or proposing a fix; no broad process-name kill or new process registry. · fork / native process qualification · [evidence](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · reproduced 2026-10-16 (r-isolation) through the owner: after `kill_live_foreground_processes(now=True)` (signalled 1, rc 1) the MSYS `usr\bin\sleep.exe` survived with a dead Windows parent, because `_kill_process_windows` -> `terminate_pid` -> `taskkill /T` walks parent links the MSYS spawn already broke; the graceful path signalled 0 (evidence appended to the doc above); both files are upstream-owned · BLOCKED 2026-10-16: upstream — an issue naming the reproduction, filed by the owner, before any fork-side kill change

- [ ] **Qualify POSIX exit-flush test signal-state restoration.** The unchanged SIGTERM test saves only SIGTERM, while `install_exit_flush_signal_handlers` also replaces SIGINT; `_restore_signal_state` clears the handler map after restoring the supplied entries. Baseline and candidate Linux tests pass but do not inspect the next test's handler state. Use a bounded native before/after probe and repair the existing fixture if confirmed; no runtime redesign or shared fixture duplication. · fork / native test isolation · [source finding](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · confirmed 2026-10-16 (r-isolation) by a before/after probe: SIGTERM restored, SIGINT left as `_handle_exit_flush_signal` with an empty chain map; the test file is upstream-owned, fix drafted in `docs/agent-runtime-harness/upstream-prs/serve-exit-flush-signal-restore-body.md` · BLOCKED 2026-10-16: upstream — that PR, posted in the owner's next posting sitting

- [ ] **Qualify Windows socket exhaustion during the fork gate.** Shutdown-repair qualification retained `WinError 10055` from `socket.socketpair()` while `_ensure_current_event_loop` set up `test_launcher_app_functions.py::test_an_entry_the_launcher_drops_is_deregistered_once_the_connection_lists_afresh`; isolated recovery passed. The runner labels red-in-bundle/green-alone an isolation leak, which does not establish fixture leakage or the resource-exhaustion cause. The changed shutdown file ran in a different process; no shared fixtures or runners changed. The original 20-file group passes without retries on base 25f893f03d and candidate 1f200eae63 (139 tests each); the initial error did not reproduce. Retain it as unresolved, not a proven baseline red; investigate resource ownership/load before changing retries, budgets or antivirus settings. · fork / suite resource qualification · [evidence](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · READY 2026-10-16 · BLOCKED quiet box: a timeout/flake judgment, run as lane r-reds-b once the box is idle (owner 2026-10-16) **TAKEN 2026-10-18 r-quiet**

## Filed on arrival — 2026-10-15 (land-w1015b)


## Filed on arrival — 2026-10-15 (owner: "testing commands should be optimised")

- [ ] **The rest of the 2026-10-15 suite-speed ask: re-measure `-j` against cores−2 on the idle 16-thread box (CPU 24 % at -j 8 during land-w1015b; the ruled default 8 is the owner's), and speed or split the slow fork files (`tests/agent_runtime/test_gateway_peer_two_roots_e2e.py` 280–587 s, `test_persona_assignments.py` 345 s, `test_serve_socket_child_e2e.py` 315 s)** · fork / suite speed · `X:/Eternia/worktrees/land-w1015b/_land_logs/bundled.log` header; the gate store's `durations.json` · lane: idle-box measurement, then one slow file per lane · RULED 2026-10-15 (owner, decision sheet w1015i #3): measure once on the idle box, then set the default to what the measurement supports · BLOCKED 2026-10-16: owner sitting — the idle 16-thread workstation for the -j measurement

## Filed on arrival — 2026-10-15 (lane w1015h-fh-h)


## Filed on arrival — 2026-10-15 (upstream PR sync lanes up-sync-1015-*)


## Filed on arrival — 2026-10-15 (owner: the footprint ratchet only goes up)

### Filed on arrival — 2026-10-16 (Phase B lanes pb-*, release gate triage rel-0222-reds)

- [ ] **Queue cleanup (owner-authorised 2026-10-16, do when next touching these queues): delete 6 done rows, 2 duplicates, 2 obsolete; fold 4 pairs** · fork / vault · read-only triage 2026-10-16 (rows cited by first words; re-verify each before deleting) · DONE: runtime "A realm-synced LEVEL has no revert arm" (`6b452452474`), "The bundle packager computes the import closure 11" and "Bundle packager's closure step fails a build outright" (`e14ea4459e3`); fork "`_without_python_c_argv`'s docstring still says" (`a433a3ccbed`), "Record: the landing gate's green cache was OFF" (`04e328efc8b`), the import-layer repair row (judge: two private imports still grandfathered). DUPLICATE: runtime "`tests/conftest.py` step 3b pins `DEFAULT_DB_PATH`" = fork "The hermetic `DEFAULT_DB_PATH` pin"; fork "A carried-PR test in an upstream file hits" = the isolation-retry row. OBSOLETE: "Three carried PRs drifted … v0.21.7" (superseded by the 18-pairs row), "Supersession pass owed for the v0.21.6 release merge". FOLD: the two plugin-rediscovery rows; the NUL-byte row into the 17-reds row; the #128843 row into the 18-pairs row; the lefthook row into the lint-gate row · READY
- [ ] **Flake: `tests/agent_runtime/test_subagent_native_roundtrip.py::test_owned_child_reads_across_execution_hosts[steer-isolated-compute]` and `[stop-isolated-compute]` red `sqlite3.OperationalError: attempt to write a readonly database` once (load 23), file green alone straight after** · fork / suite · [[r-perf-2026-10-17]] · BLOCKED quiet box **TAKEN 2026-10-18 r-quiet**
- [ ] **`tests/scripts/test_run_tests_bundled_leftovers.py::test_scan_finds_a_real_orphan_of_the_shape` is flaky alone** · fork / runner tests · red then green alone at `a29bec7e2d8`, file untouched · BLOCKED quiet box **TAKEN 2026-10-18 r-quiet**
- [ ] **A raising patch from a test body is still live during fixture teardown for every test (the patch-in-teardown CLASS): the structural answer is for the chain to undo the body's patches at the end of the call phase; find the fixture teardowns that read a body patch with one `--scope features` run and its diagnosis, then decide** · fork / suite · q-chain `82e028ecdc` body · NEEDS RULING
- [ ] **The runner never discovers `tests/e2e`, so 10 unused e2e files (kanban, platforms, windows_update) cannot be skip-listed and a row for one fails the validator** · fork / suite · q-unused `47fd1f1055` · READY
- [ ] **Program classification has two owners: `hermes_dep_trail._popen_program` splits a quoted Windows command line on spaces (a Python child at a spaced path counts as non-Python and drags its file onto the ALL sentinel); `hermes_bundle_report.program_kind` was fixed — one owner** · fork / gate cache · q-runner step 6 · READY
- [ ] **Every dependency record lists the repo root `.` as a plain listing, so any new top-level file misses every green** · fork / gate cache · q-runner scratch-store records 2026-10-17 · READY
- [ ] **`tests/hermes_cli/test_version_info.py` leaves the process version identity in a test state: `test_fireworks_profile::test_user_agent_identifies_hermes` and `test_provider_attribution_headers` (2) fail when run after it in one session (reproduced on `8a648c203e`)** · fork / suite isolation · q-version report · restore `_cached_version_info` per test · READY
- [ ] **338 upstream files import an unused feature and also shipped code (q-unused kept them); an 8-agent read gave each a skip / keep / split verdict in the Hermes Test Catalogue artifact; the owner's Keep/Skip marks there become skip-list rows** · fork / suite · q-unused `unsure.json`, catalogue `https://claude.ai/artifact/FYxV8WcPiiMFLJJ8M3hvmG` · READY
- [ ] **Rerere trainer cannot record a daily resolution that deletes a conflicted file, and its clean fallback runs reset.** Handle absent committed blobs as deletions and replace the reset fallback with a clean-state assertion for no-reset automation. · fork / sync · evidence: `docs/downstream/upstream-integration-2026-10-14.md`; `scripts/rerere_train.sh` failed at deleted `tools/tirith_security.py` in `40ff6034ae20` · lane: unclaimed · carried from origin/merge/upstream-v0.22.0 b4248b3 (2026-10-17 harvest)
- [ ] **`--affected` misses its under-a-minute bar on hub modules: 160 s for an `agent_runtime/locks.py` edit (110 files), 219 s for `tools/checkpoint_manager.py` (59 files); 7 s for `hermes_cli/plugin_host.py`. Still 5-8x faster than the ~1,120-file landing gate, but a 2-hop static reach picks a few 100-240 s files** · fork / suite · q-affected report 2026-10-17 (branch q/affected) · fix: per-file imports (next row) + slowest files last under `--fail-fast` · READY · r-recorder 2026-10-18: per-file `mods_own` landed (locks.py 111 -> 32 files, checkpoint_manager 59 -> 37) but wall time did not fall: tail-bound on 70-177 s files
- [ ] **Every test lists its own directory (pytest collection) and the session lists `scripts/` (6,166 records), so a new file still invalidates every sibling's green** · fork / gate cache · `run_tests_bundled_affected._listed` docstring (q/affected) · READY
- [ ] **`tests/tools/test_checkpoint_manager.py` times out in the 2026-10-17 `--scope features` run (first: `no result before the cap`); fix whether or not it was red before (owner)** · fork / suite · features run 2026-10-17 (gate store runs.jsonl, `features-1`) · READY · r-state 2026-10-18: green alone twice on an idle box (run_tests.sh 68.7 s on origin/main, 62.5 s on `q/r-state`; bare 56.9 s, slowest test 4.1 s); the cost is 1,190 git spawns (~47 ms each: `git init --bare` + five `git config` per store, 44 stores) inside upstream `tools/checkpoint_manager.py`, so a loaded box reaches the cap; no fork-only fix (the store init is the subject) — next: an upstream PR folding the five configs into `git init -c`/one `config` call, or a skip-list call by the owner
- [ ] **Orphan pm install-state reclaim never fires on the fork's worktree layout: `pm/install_states.py::_provably_deleted` trusts only checkouts under the data root or a literal `.worktrees` parent, so every `X:\Eternia\worktrees\*` / `X:\wt\*` checkout leaves its ~0.8 GB `installs/<key>` behind (340 orphans, ~264 GB apparent, ~57 GB real; 78% is hardlinks into the uv cache)** · fork / pm (upstream code: seam or config for extra worktree roots) · installs investigation 2026-10-18, `X:/Eternia/worktrees/installs-scratch/plan.md` · the one-off delete waits on the owner · READY
- [ ] **The test venv `~/.venvs/hermes-test` has no pytest-xdist, so `-n 4` in a lane brief errors (`unrecognized arguments: -n`) and every 2026-10-16 r-* lane ran its targeted set serially** · fork / suite · r-turnrec, r-chatsend, r-deadcode, r-sync, r-isolation reports 2026-10-16 · install xdist at a landing on a quiet box (never while tests run), or keep briefs to the runner scripts' `-j` · READY
- [ ] **Owner, after a reboot: delete `nemo_relay/_native.pyd.old-0.8.4` from the shared test venv** · fork / box · the 2026-10-16 nemo-relay 0.8.4→0.10.0 swap renamed the held `.pyd` (uv could not replace a loaded file); the old dist-info is parked in the session scratchpad · delete once no process holds it · BLOCKED 2026-10-16: owner sitting — after a reboot of the workstation, delete the file from the shared test venv
- [ ] **`integration/upstream-daily` has no updater: the GPT/Codex daily job is down; the branch was rebuilt by hand on 2026-10-16 (`04c26f21a27`, upstream `e6899c8090d`)** · fork / sync · owner 2026-10-16 "the updater gpt is dead" · until a job is back, a Claude lane rebuilds it per `Merging upstream.md` at each upstream release (with `--merge-base=<last merged tag>`, row above) · BLOCKED 2026-10-16: owner decision — bring a daily updater job back, or keep a Claude lane rebuilding the branch at each upstream release? · Recommend: a Claude lane per upstream release, with `--merge-base=<last merged tag>`
- [ ] **24 upstream PR branches are prepared and idle (16 splits, 7 doors, the phone fix `fix/connectors-files-lazy-wire`); the account cannot open PRs upstream** · fork / upstream · bodies kept beside the clone in `worktrees/pr-bodies/`; owner 2026-10-16 "pr branches should remain idle" · owner opens them when upstream accepts PRs again; re-check each against the next release first · DEFERRED 2026-10-16: owner "pr branches should remain idle" — until upstream accepts the owner's PRs again
- [ ] **18 carried-PR pairs stopped matching after the 2026-10-15 sync (8 hunk/line DRIFT: #119069 gateway.py, #121226 ×2, #121642 auth_nous.py, #123892 shell_hooks.py, #128652 hermes_state_messages.py, #129414 resolution_allowlist.json, #125261 environments/local.py; 9 fragments the PR branches rewrote: #125259, #125263 ×2, #125264, #128648 ×2, #128651, #128654, #128843): per PR re-cut the branch to the fork's text or adopt the PR's text in the fork, then re-pin** · fork / upstream PR tooling · q/carried `5692a35290f` check run · DEFERRED 2026-10-16: owner "pr branches should remain idle" — until upstream accepts the owner's PRs again
- [ ] **#128648's PR branch now lives in `hermes_cli/main_plugin_cli.py` / `plugins_declared_cli.py` while the fork carries an older shape in `plugins_manifest_cli_commands.py`; converge one onto the other, then re-map the carried-PR manifest** · fork / upstream PR tooling · q/carried `5692a35290f` · BLOCKED 2026-10-16: owner decision — converge the fork onto #128648's PR-branch shape, or the PR branch onto the fork's? · Recommend: the fork adopts the PR's shape, so the idle PR branch needs no push
- [ ] **Flake: `tests/tui_gateway/test_hosted_room_driver_runtime.py::test_peer_terminal_status_acknowledges_durable_stop_on_retry` printed FAILED then passed on retry (q-hosted run)** · fork / suite · q/hosted report · with q-suite-reds · READY 2026-10-16 **BLOCKED quiet box** (r-reds-a 2026-10-16: flake) **TAKEN 2026-10-18 r-quiet**
- [ ] **Test files still red on main `e829d753e12` (rel-0222-reds; r-reds-a closed the other 8 on 2026-10-16): channel_build_publication (host Node 20.17 is below the `engines` ^22.22: `require()` of `scripts/msix-shared.mjs` throws ERR_REQUIRE_ESM — upgrade the box, no code fix); timeouts desktop_bundle_smoke, kanban_boards, nous_recommendation_disk_cache, plugin_uninstall_windows_live, child_notice_profile_admission, gitspawn_config_injection, kanban_descendant_scope** · fork / suite · release gate log `worktrees/rel-0222-scratch/gate-1.log`, rel-0222-reds report · **BLOCKED quiet box** (timeouts; r-reds-a 2026-10-16) · READY 2026-10-16 **TAKEN 2026-10-18 r-quiet**



- [ ] **The full re-audit found nine fork fixes that have no upstream PR yet (`_codex_pool_row_refused`, the system_prompt anchor repair, the `_sanitize_client_source` NameError, `terminal_tool_result.timed_out`, the tts piper download switch, the live-guard console-event refusal, the relay optional binding, the runtime_provider `auto` re-check, the pyproject F821): give each a prepared branch and a PR body in `pr-bodies`** · fork / upstream PRs · same doc §4 · DEFERRED 2026-10-16: owner "prepared PR branches stay idle while upstream is not taking the owner's PRs"



## Filed on arrival — 2026-10-15 (lane w1015j-hermes)

- [ ] **The shared hermes clone's pack directory holds about 40 `.idx` files with no `.pack` and 8 `tmp_pack_*` leftovers from interrupted fetches (`git count-objects -v` warns on each); the likely source of the 2026-10-15 "fetch-pack: invalid index-pack output"** · fork / clone health · measured 2026-10-15 18:45 · lane: an owner/landing step with no lane open — `git -C <clone> fsck --connectivity-only`, then delete the orphan `.idx`/`tmp_pack_*` files (or `git gc --prune=now`); never a lane's repair of a shared object store · BLOCKED 2026-10-16: owner sitting — the shared clone on the workstation with no lane open: `git fsck --connectivity-only`, then remove the orphan `.idx` / `tmp_pack_*` files

## Filed on arrival — 2026-10-16 (h2-redact)

- [ ] **A claim commit rebased onto a moved `origin/main` came out of `git rebase` "Successfully rebased" with a PEER lane's four fresh `TAKEN 2026-10-16 h4-seeds` marks reverted in `runtime-queue.md` (rerere is on, 424 entries in the shared `rr-cache`); caught only by reading `git diff origin/main HEAD` before the retried push. Queue files are one-line-per-row and every lane edits them, so a recorded resolution replays onto unrelated rows** · fork / clone health · measured 2026-10-16 by h2-redact (never pushed; the claim was rebuilt on a fresh `origin/main` with a temporary index instead of a rebase) · fix shape: claim and file-on-arrival commits are built on the fetched tip (read-tree + update-index + commit-tree), never rebased; or `rerere.enabled=false` for queue paths · filed 2026-10-16 by h2-redact · BLOCKED 2026-10-16: owner decision — turn rerere off on the shared hermes clone, or build every claim and file-on-arrival commit on the fetched tip? · Recommend: `rerere.enabled=false` on the shared clone
- [ ] **`tests/agent_runtime/test_goal_workspace_realm_stage42.py` times out on `origin/main` run alone: every test's `_run_harness("realm", "use", …)` subprocess hits its timeout inside `communicate` (7 tests, 45-50 s, file red)** · fork / suite · proven pre-existing 2026-10-16 by h2-redact: red at merge-base `fb5f3d9dff0` via `scripts/run_tests.sh` alone, same node set as the branch · filed 2026-10-16 by h2-redact · READY 2026-10-16 **BLOCKED quiet box** (r-reds-a 2026-10-16: subprocess timeouts) **TAKEN 2026-10-18 r-quiet**
- [ ] **`tests/agent_runtime/test_stream_relay.py::test_a_new_process_pays_the_boot_sections_inside_their_cold_budget` reds on `origin/main`: `agents_readiness` 3778-6895 ms against its 3500 ms cold budget (`parses_by_caller: skills_tool.py 60`)** · fork / snapshot boot cost · proven pre-existing 2026-10-16 by h2-redact at merge-base `fb5f3d9dff0` (6895 ms alone) · filed 2026-10-16 by h2-redact · READY 2026-10-16 **BLOCKED quiet box** (r-reds-a 2026-10-16: wall-clock budget) **TAKEN 2026-10-18 r-quiet**
- [ ] **`tests/agent_runtime/test_discussion_group_compute.py::test_compute_question_lost_answer_ack_and_confirmed_stop` reds on `origin/main` run alone (80 s, no gate load): the `until(...)` poll in `tests/agent_runtime/native_recovery_provider.py` hits its 30 s deadline with the member task still `status: running` / `attempt_stage: running` and only the `message.user` event in the room log — the compute child never answers the question. The 2026-10-10 sweep (L6.24) had it passing; find what moved.** · fork / discussion compute · evidence: lane land-h1 2026-10-16, red on the landing branch AND alone on `origin/main` `21beb9ad132` · READY 2026-10-16 **BLOCKED quiet box** (r-reds-a 2026-10-16: GREEN alone on `ec6c87365b9` (47 s): load, nothing fixed) **TAKEN 2026-10-18 r-quiet**
- [ ] **Two more discussion tests red intermittently, with no change of theirs: `tests/agent_runtime/test_discussion_group_native.py::test_real_group_compare_discuss_target_and_reopen` fails in the same `until(...)` deadline in `tests/agent_runtime/native_recovery_provider.py` as the compute row above (`AssertionError: None`, 234 s), red ALONE on `origin/main` `ec2e339b694` and green alone on the land-hpk tree; `tests/agent_runtime/test_discussion_definition_store.py::test_two_processes_with_same_revision_have_exactly_one_winner` reds only under the -j 8 gate (`_queue.Empty` from its child-process result queue) and is green alone on both trees. Fix the shared poll with the compute row (one cause, one fix); give the two-process test a deadline measured under gate load, not raised blind.** · fork / discussion compute · evidence: lane land-hpk 2026-10-16, bundled gate on the land-hpk tree plus `run_tests.sh` re-runs on both trees · READY 2026-10-16 **BLOCKED quiet box** (r-reds-a 2026-10-16: intermittent; the compute row it shares a cause with is green alone) **TAKEN 2026-10-18 r-quiet**

## Filed on arrival — 2026-10-16 (land-h234)


- [ ] **hermes test entry points claim no machine-wide heavy-run slot (the launcher's `tool/heavy_run/slot_lock.dart`), so a hermes suite oversubscribes the 16 processors beside launcher lanes — decide whether `scripts/run_tests.sh` claims a slot** · launcher core-packages-queue row "Only run_tier.dart and verify_stagec_qa_tooling.dart claim a heavy-run slot automatically" · filed 2026-10-16 from the launcher queue relabel · BLOCKED 2026-10-16: owner decision — should hermes test entry points claim the launcher's heavy-run slot? · Recommend: yes, in the fork-owned `scripts/run_tests_bundled.py` (Phase B has landed, so `scripts/run_tests.sh` is unfenced too)

## Filed on arrival — 2026-10-16 (lane h5-deadcode)


## Filed on arrival — 2026-10-17 (footprint audit)

- [ ] **Footprint owner-ruling check accepts a new unapproved grandfathered reason after an old exemption leaves.** On main `0bea7e062b`, `scripts/upstream_footprint.py::grandfathered_count` reads 120 while `GRANDFATHERED_REASONS` remains 121; appending an in-memory reason with `grandfathered: true`, no `owner_ruling`, and raising the fixture by one gives count 121 and `unruled_reasons == []`, so both assertions in `tests/scripts/test_upstream_footprint.py::test_every_raise_cites_an_owner_ruling` accept it. The current footprint tests pass (18 tests in the footprint and add-row files, 2026-10-17). Pin the identities of grandfathered rows to the original approved set, allowing only removal; a count alone also permits swapping an old exemption for a new one. Add controls for reuse of the vacant slot and same-count substitution; retain the owner-ruling requirement for every new row. · fork / upstream footprint · audit 2026-10-17, in-memory control only; no fixture changed · READY

## Filed on arrival — 2026-10-17 (lane r-plugins)

- [ ] **`tests/hermes_cli/test_update_completion_process.py` 9 red alone on origin/main `8c5e95d7e9` (first: `test_old_process_new_git_tree_completes_in_fresh_python[None]`: `completion-pending` still exists after the fresh-python completion); not in the features-run rows** · fork / suite · lane r-plugins: same 9 nodes alone on the branch and on origin/main · READY

## Filed on arrival — 2026-10-18 land/q6

- [ ] **--affected misses a file that reaches a changed module only through an intermediate an earlier bundle member loaded** · fork / suite · r-recorder 1bf2272916 · READY
- [ ] **--affected is tail-bound on 70–177 s files (test_operator_redo 140–177 s); the runner's path-ordered bundles put them in series** · fork / suite · r-recorder locks run: 32 files, 364 s · shard for --affected · READY
- [ ] **test_bundled_plugin_discovery_is_kept_between_tests red in its first bundle on a fresh worktree, green alone** · fork / suite · r-recorder run1 log · READY
- [ ] **`scripts/run_tests.sh tests/pm/test_build_operations.py` reports `0 tests passed, 0 failed` for a file whose direct pytest run is 24 passed (2026-10-18, uv 0.12.3): the bundled summary loses tests/pm counts, so a red there would read as green** · fork / suite · q7 run, named alongside one tui node · READY
- [ ] **pm install deletion: a hardlinked `.pyd` (730 links into the uv cache) cannot be unlinked while any live Python maps the same file, so `shutil.rmtree` of an orphan install state leaves those links; the pruner (080735728c row) must skip-and-continue, not abort** · fork / box · installs cleanup 2026-10-18, 335/335 aborted on the first locked `.pyd` · READY
- [ ] **Fork gate: every hermes child the e2e/native tests spawn repeats provider discovery (~1.6 s) and the git version lookup; a test-only shortcut (the session chain hands children a cached provider snapshot + version info through the environment) cuts it fork-side without an upstream PR. The top of the last cold `--scope fork` gate is these files (native_conversation_roundtrip 243 s, gateway_peer_two_roots_e2e 194 s, subagent_native_roundtrip 107 s, embedded_phone_session 106 s, serve_socket_child_e2e 85 s)** · fork / suite · gate store runs.jsonl 2026-10-18T02:26 (1,248 s, work 8,574 s, util 0.98 at -j 8); r-perf-2026-10-17 note · measure child boot before and after · READY
- [ ] **Fork gate runs at -j 8 on a 16-logical-CPU box with utilization 0.98 (work-bound); measure -j 10/12 on a quiet box (the X: HDD may cap it) and set the default from the result** · fork / suite · same run · READY

- [ ] **The whole-tree gates each re-read and re-parse the tree on their own: ~360 s of a cold landing gate's work, seven walkers three quarters of it (test_upstream_skip_list 76 s, s55 emitters 39, fork_import_layers 37, no_ladder_routing 34, coverage_claims 33, no_frozen_hermes_home 24, no_silent_package_patches 20); one session-scoped source/AST cache (read + `ast.parse` once per path, keyed on mtime) shared by every walker** · fork / suite · `docs/agent-runtime-harness/11-gate-directory.md` § Cost (gate store durations 2026-10-18) · measure the seven before/after · READY
- [ ] **The gate directory's currency test enumerates only `tests/tooling/`, `scripts/check*`, `scripts/*_gate.py` and the contract dumps; a gate written elsewhere (most of § One authority per value live in `tests/agent_runtime/`, `tests/hermes_cli/`) joins the page by discipline alone. A `pytest.mark.gate` on every gate file, read by `test_gate_directory_current.py`, makes the enumeration positive** · fork / suite · same page · READY

