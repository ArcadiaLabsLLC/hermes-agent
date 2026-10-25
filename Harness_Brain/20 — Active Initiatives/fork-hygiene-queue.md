---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue




- **`FORK-MACOS-CI-TRIAGE` — Triage upstream/macOS jobs exposed by the subagent-history PR's broader CI matrix.** Run `38832830663`, macOS shards `116755299378` / `116755299386`, fails in update/PM/source-stamp/MCP subprocess fixtures: copied update trees lack `agent_runtime`, import probes hit the live-system guard, and PM/tool fixtures touch the setup environment. These files are outside Step 5's changed paths; Windows fork-scope qualification does not establish a macOS baseline. Reproduce on the same native CI host against the base before attributing or exempting them. Preserve the run logs; do not weaken live-system guards or grow the skip list from this report. · fork / CI · read 2026-10-16 (r-sync, `gh run view --log`): shard 1 = 17 reds in 6 files (update_missing_configured_deps, sessions_held_store_gate, update_import_guard, update_posix_pause, source_build_env, mcp_death_supervisor), shard 2 = 8 errors + ~20 failed (doctor_pm_store_probe, doctor_command_install, update_finish "No module named 'agent_runtime'" from the copied tree, update_pause_step_interruptions, update_post_commit_safety, update_recovery_closure, pm runtime_bootstrap_tls / update_dependency_legs); no `main` push runs the macOS matrix (runs 38884451206, 38976202285 carry no macOS job), so no base exists to compare · BLOCKED 2026-10-16: owner sitting — a macOS CI run on the base (`workflow_dispatch` of CI on `main`, or a Mac host) — triggering one needs the owner's GitHub account


- **`FORK-SECOND-WORKSTATION-ENV` — Qualify the canonical shared test environment on the second Windows workstation before treating the PM slow-exit check as covered there.** Baseline re-audit on `5fc3c617df` (2026-10-15): with no explicit `HERMES_PYTHON`, `scripts/run_tests.sh tests/pm/test_worker_slow_exit_downstream.py` refuses before collection because this Windows account has no shared environment with pytest at `~/.venvs/hermes-test`. Explicitly selecting this clone's Python 3.13.15 reproduces the PM fixture's Python 3.14 requirement error; no worker assertion runs. Commit `646acfb921` established a genuine 1/1 pass on another account's shared Python 3.14.5 environment, not this workstation. Use the existing shared-environment setup and runner, then rerun the single file; do not change upstream's fixture, relax the Python requirement, or add another runner. Evidence: `scripts/run_tests.sh`, `tests/pm/_fixtures.py::isolated_python`, `pm/pyproject.toml`; local re-audit receipts retained. Environment setup, not a demonstrated PM or Eternia runtime defect. · BLOCKED 2026-10-16: owner sitting — set up the shared `~/.venvs/hermes-test` (Python 3.14) on the second Windows workstation's account, then rerun the one file














## Filed on arrival — 2026-10-22 (release merge rel-v0224)


## Filed on arrival — 2026-10-22 (land w1022d)


## Filed on arrival — 2026-10-22 (land w1022a)

- **`FH-DEFER-PR-128649-SHARED-TLS` — upstream PR #128649 (shared TLS platform context) is deferred; its code rides our `main` as a carry in `agent/ssl_verify.py::resolve_httpx_verify` (under truststore one shared context, certifi bundle on the platform store, certifi re-resolved first) + `tests/agent/test_ssl_verify.py`; retire both ledger rows when the PR lands upstream** · fork / upstream PR branches · evidence: lane w1024t-hermes2 · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens the PR (branch `up/tls-shared-platform-context` still needs the same rework before it can go)
- **`FH-DEFER-PR-J2A-HOSTED-ROOM-LIMITS` — upstream PR J2a (Group Chat limits, active members, conclusion, checkpoint budget) is deferred; the code already rides our `main` as the carry `gateway/hosted_room_limits.py` + the A3 hunk in `gateway/hosted_room_policy_checkpoint.py`; retire both (and their S3 ledger rows) when J2a lands upstream** · fork / upstream PR branches · plan `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` § Half B · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens it
- **`FH-DEFER-PR-J2B-HOSTED-ROOM-PINS` — upstream PR J2b (Group Chat history pin/unpin) is deferred; the code already rides our `main` as `gateway/hosted_room_history_pins.py` + the pinned-set prune hunk in `gateway/hosted_rooms.py`; retire both when J2b lands upstream** · fork / upstream PR branches · plan `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` § Half B · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens it
- **`FH-DEFER-PR-J2-B0-OMISSION-RESERVE` — upstream PR B0 (reserve the omission notice inside the Discussion prompt budget) is deferred; the fix already rides our `main` in `gateway/hosted_room_discussion.py::_build_prompt` (`reserved = len(omission…) + 2`); retire that hunk's ledger row when B0 lands upstream** · fork / upstream PR branches · plan `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` § Half B · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens it
- **`FH-DEFER-PR-SELF-REPO-GUARD-VARS` — the upstream PR for the self-repo guard's `$VAR` / `${VAR}` targets is deferred; the code rides our `main` as the fork seam `tools/self_repo_guard_vars.py` (scoped shell variables, expansion, the UNRESOLVED refusal) + its hook lines in upstream `tools/self_repo_guard.py` (import, `_find_mutation` bind, the cd / `-C` / `--work-tree` `expand_target` calls) + `tests/tools/test_self_repo_guard_vars.py`; retire the seam and that ledger row's VAR clause when the PR lands upstream** · fork / upstream PR branches · evidence: `tools/self_repo_guard_vars.py::ShellVars` · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens the PR (no `up/` branch cut yet: inline the seam into `tools/self_repo_guard.py` when it is)

## Filed on arrival — 2026-10-21 (lane w1021h-tooling, branch `w1021h/tooling`)

- **`FH-CI-MAIN-LARGE-RUNNER-QUEUE` — hermes CI on `main` never finishes: upstream's jobs ask for runner labels ArcadiaLabsLLC lacks; run 39494050964 (`79d3fa5754`) queued since 2026-10-20 holds `ci-refs/heads/main`, every later push pending → cancelled; 0 green in the last 200 runs** · fork CI · evidence `306a622a64` (branch `w1021h/tooling`) · RULED 2026-10-22: owner — no larger runners; a fork seam maps upstream's large-runner labels to standard runners through a repository variable whose default is upstream's label · RULED 2026-10-25: owner — zero upstream footprint: one fork-owned workflow on `ubuntu-latest` / `windows-latest` running `scripts/run_tests.sh` over the validated lanes on `main` pushes, then the owner disables upstream's `ci.yaml` for the fork in the repository's Actions settings (one click, after the fork workflow lands); supersedes the 2026-10-22 per-label seam · BUILT 2026-10-25 lane w1025a-hermes: `.github/workflows/fork-gates.yml` job `validated-suite` (ubuntu-latest + windows-latest, the validated scope then `tests/tooling tests/scripts`, push to `main`), pinned by `tests/ci/test_fork_suite_on_standard_runners.py` · BLOCKED 2026-10-25: owner sitting — in GitHub, ArcadiaLabsLLC/hermes-agent → Actions → "CI" (`ci.yaml`) → Disable workflow, and cancel queued run 39494050964 if it still holds `ci-refs/heads/main`; then read the first `Fork gates` run on `main` for the two `Validated suite` jobs

## Filed on arrival — 2026-10-20 (launcher orchestrator w1020r)

- **`FORK-PARALLEL-MESSAGING-GATEWAY` — recorded parallel: the fork's persona messaging gateway (`agent_runtime/messaging/`, own Telegram transport over httpx) shadows upstream's `plugins/platforms/telegram/` + `gateway/platforms/base.py::BasePlatformAdapter` + `gateway/run.py::GatewayRunner`/`gateway/session.py::SessionStore`; not adopted because wrapping brings upstream's second session store and runner-private coupling, and re-admits 71 upstream test files (plan §2.2); retires if upstream exposes a session-store-free transport hook a persona turn can sit behind** · `docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md` §2.2 · `Harness_Brain/30 — Decisions/0015 — Upstream features the fork does not ship leave the suite and the boot path.md` · DEFERRED 2026-10-20: owner "sounds good persona system for our custom gateway is the way" — kept until upstream ships a transport-only hook; re-check at each upstream merge's supersession pass

## Filed on arrival — 2026-10-18 (land w4)


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


## Filed on arrival — 2026-10-09 (final gates)


## Filed on arrival — 2026-10-08 (lane opus-w1-hermes)


## Filed on arrival — 2026-10-08 GenUI qualification

- **`FORK-RUNNING-TURN-STREAM` — Diagnose the running-turn stream intermittent remaining after the HTTPS-scanning control.** After the operator disabled scanning, the ten H01 files pass across controls (96 distinct passes / one existing skip), with certificate and permission assertions unchanged. On `f6c27f4d0b`, `tests/agent_runtime/test_serve_gateway_chat_reply_lanes.py::test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane` fails its six-second start-frame wait under eight-worker load, then both file tests pass serially. The two-roots file also passes all nine when allowed its declared duration; its earlier 120-second cap was a command choice. Trace the start-event publication/fixture boundary before changing behavior or deadlines. The former certificate blocker is qualified; the parallel failure remains evidence. Separate from H03 commentary. · fork / suite · [H01 control and log digests](../../docs/downstream/history-red-triage-2026-10-12.md#https-scanning-control-after-the-operators-setting-change), [H01 diagnosis](../../docs/downstream/stream-delivery-diagnosis-2026-10-12.md#h01-still-open-no-speculative-runtime-change) · no reproduction since `f6c27f4d0b`: the ten-file control passed 96 / one skip three times, the presence repair `911275e641` landed, and the test recorder keeps its reader exception + last 32 frame summaries on a failed wait; keep it as a watch and do not touch deadlines · DEFERRED 2026-10-18: a watch, not lane work — reopen when a landing gate's log reds this node, with the recorder's frame timeline

## Filed on arrival — 2026-10-06 (lane console-generated-content)



The repository AS A FORK: upstream sync and the boundary, CI, the suite and its gates, the god-file refactor, this vault. Runtime and Mission Control rows do NOT go here — the hermes half is [[runtime-queue]], the launcher half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. Rows: one line + a pointer, never a restatement; claim with `**TAKEN <date> <who>**` before starting; a landing deletes its row.

## Filed on arrival — 2026-10-06 (lane h-prereq-window)


## Filed on arrival — 2026-10-05 (owner ask: a usable suite)

- **`FORK-BARE-PYTEST-FILES-SEVERAL` — A bare pytest over files from several test directories hangs `test_gateway_spawn_fence::test_subprocess_run_refuses_the_measured_argv` (the fence is not armed; a real `gateway run` starts) and reddens `test_conftest_isolation_downstream` test_2/test_4; red on main `71079deb70`** · `fork / suite` · evidence: lane h-suite-hermetic report · reproducing it starts a real gateway on the operator's machine · BLOCKED 2026-10-16: owner sitting — a VM or watchdog box off the operator's desktop for the reproduction
- **`FORK-FAST-PARTIAL-FULL-SUITES` — Owner ask: make the partial (fork-scope) and full test suites fast enough to use — the fork gate ran 872 files / ~13k tests in ~18 min wall at 8 workers (per-file seconds summed 5,977; slowest file 233 s), ~13 tests/s, against the launcher's Flutter suite at ~40,000 tests in 8 min (~83 tests/s); the full scope is 6,066 files and on hold for the P0 freeze. Measure where the time goes (interpreter + import cost per process, conftest/fixtures, hermetic env setup, the slow tail, timeouts, Defender, worker count) and write a staged plan** · `fork / suite` · evidence: landing h-turn1 wave 2 gate log (2026-10-05 20:22–20:40 local) · **PLAN `plan/h-suite-speed` `6d2db880cf`; owner took O1–O5 as recommended 2026-10-06; exec lanes h-suite-runner (stages 0–3), h-suite-tail-a / h-suite-tail-b (stage 4); stage 5 after three identical failure sets, 6–7 after** · **Stages 0–4 LANDED `15d4e37d0d` (2026-10-06; full-tree gate 1059 s → 813 s, 99% utilization); stage 5 LANDED `7e9e0489f1` (2026-10-18: landing gate defaults to -j 12, 0 failed at -j 8/10/12/16); stage 6 LANDED as `--affected` (`a65a22deff`); open: stage 7, the full scope under its watchdog** · BLOCKED 2026-10-18: another lane — `FORK-P0-VALIDATED-SUITE-FROZE` stage 7 runs the full scope, which waits on the freeze bisect

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

- **`FORK-CI-MAIN-REMAINING-SLICES` — hermes CI on `main`: the runner crash and the 43 lint errors and the mutation job are fixed; what is left is hb's slices 5–8 and the Issues switch** · `hermes` · **NARROWED 2026-09-06 (w18/ha `57b6964b01` (pre-rewrite), w18/hc `2b1f6e849c` (pre-rewrite))** — run 34046863701 (hc's push) is the first with `ruff enforcement (blocking)` and `Changed-line mutation claims` GREEN. **ha, slices 1–4, CLOSED:** all 16 tests across 11 files, one commit per file (`48a690da4c` doc-cite report needs a 4-commit repo under a depth-1 checkout; `188c511bae` + `9765564afa` stale `patch()` targets from `96cfc09a34` (pre-rewrite); `9463780a78` tool-inventory mutations wrote CRLF; `caffc04c1c` a hand-typed Windows byte count; `43cbb598ef` a real duplicate helper (`realm_sync._ledger_time` == `store._stamp`); `30f1ec6635` a BOM on `install.ps1` from the 2026-07-31 upstream merge; `23a90c6063` `test_env_gap_registry` was a DESIGN fault — a green host was read as "every row rotted"; `cee66b50fd` a witness that had not followed its reader; `d2137867b7` a directory-only git exclude that misses POSIX's symlink, which is also why the worktree GC never reaped on Linux; `ce3dc7f465` `os.path.normcase` on Windows-registry PATH data). Six of the eleven reproduced on Windows and were never platform facts — they live outside the four validated test directories and had simply never been run. **hc, CLOSED except Playwright:** ruff's 43 were all genuine `F821` (38 undeclared names in exec-assembled part-file import headers, 5 a missing `typing.Any`), 0 noqa (`fa0fb62788` (pre-rewrite), `f29ad6ca6c` (pre-rewrite), `3af990fca7` (pre-rewrite)); `test_harness_parts_namespace.py` never checked header PRESENCE, ruff is the real gate, said so in `6c629b9122` (pre-rewrite); the mutation job's exit was right and four registered needles had stopped anchoring — re-derived, each proven KILLED, plus `tests/scripts/test_mutation_claims_still_anchor.py` (`abaace6a87` (pre-rewrite), `bbc1caafb0`), and a fifth needle went ambiguous on landing over hd and was fixed forward (`2b1f6e849c` (pre-rewrite)). The notifier `notify-main-red` LANDED (`028aceb9c6` (pre-rewrite)) and FIRED on run 34046863701 — and failed on its own step, because **Issues are disabled on `nekwo/hermes-agent`** (register row). **hb, slices 5–8, CLOSED (hermes `962a10d0fb` (pre-rewrite), 13 commits):** all nine reds and the uncollected `test_tombstone_registry.py` (1,155 tests lost at collection to a `check=True` diff under `fetch-depth: 1`); two were the CI checkout, not the code — `ci.yml` now fetches full history with `filter: blob:none`, and the docket gate had been FALSELY accusing seven backed stages; three were product defects (`_ABS_PATH_RE`'s POSIX branch truncated at the first space, `entrypoint_name` used the host separator, `note_peer_seen` read the clock twice); the eight `stream_frames` goldens were regenerated for a path-tail redaction (`262a165b47`), which the launcher re-vendored 2026-09-06 (w18/lf). **What remains here:** (1) the next main-push run after hb lands must show the eight slices green; (3) the Issues switch, then one red push to prove the notifier end to end; then delete this row. · RULED 2026-10-21: owner — turn Issues on for the fork's GitHub repository, then one red push proves `notify-main-red` end to end · BLOCKED 2026-10-21: another lane — `FH-CI-MAIN-LARGE-RUNNER-QUEUE` (CI on main never finishes; slices 5–8 and the notify-main-red proof wait on it)
- **`FORK-HERMES-PACK-MAINTENANCE` — hermes pack maintenance is a SILENT no-op on git < 2.32** · `hermes` · `_run_bounded_repack` issues `git repack -d --geometric=2 --write-midx`, which exits 129 on older git; the runner sends both streams to DEVNULL and never reads the return code, then `_claim_repack_slot` suppresses retries for 6 hours. Measured on git 2.31.1.windows.1 — this box. Upstream-owned; decide: warn, fall back to `repack -a -d`, or require 2.32. Ruling 1. · `hermes_cli/worktree_ops.py`, upstream-owned · BLOCKED 2026-10-16: upstream — an upstream issue on `hermes_cli/worktree_ops.py::_run_bounded_repack` (warn, fall back to `repack -a -d`, or require git 2.32); none filed
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


## Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast-gate design, guard fix, build batch 2 C1–C4, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


## Filed on arrival — 2026-10-11 (fast-gate landing, whole-tree gate, filed by the orchestrator)



## Filed on arrival — 2026-10-11 (Console history final qualification)

- **`FORK-REQUALIFY-HOST-XFAILS` — Requalify the last two host-sensitive strict xfails from hosted Windows run 38426498916: `tests/scripts/desktop_update/test_desktop_update_windows_marker.py::test_owner_creation_time_is_read_for_system_processes[False|True]` XPASS on the elevated hosted runner and red here with "no process here grants only limited query rights" (unelevated, by the look of it; not demonstrated).** · fork / inherited-test expectations · the other 15 of the 17 nodes are qualified: 5 retired on main earlier (`455ea739f72`, `9effac5d6a2`), `test_source_build` retired and 9 moved to probe-backed env-gap rows (unelevated `sc.exe`, user-vs-system `core.autocrlf`, delivery CLI through PATH) by lane r-isolation 2026-10-16 · move the two ids to the `_unelevated_windows_shell` owner only after one elevated run shows them green; do not make them non-strict · BLOCKED 2026-10-16: owner sitting — one run of the two ids in an elevated shell






## Filed on arrival — 2026-10-13 shutdown-test repair

- **`FORK-QUALIFY-NATIVE-WINDOWS-MSYS` — Qualify native Windows MSYS foreground-child ownership and cleanup.** Three `sleep.exe 3518` children survived the failing inherited shutdown-test setup; adding the executable suffix did not make the ancestry scan find them. They were explicitly reaped. The repaired test owns its Python child by a ready PID receipt, which does not prove MSYS tree cleanup. Reproduce through the existing local-environment process owner before attributing a production defect or proposing a fix; no broad process-name kill or new process registry. · fork / native process qualification · [evidence](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · reproduced 2026-10-16 (r-isolation) through the owner: after `kill_live_foreground_processes(now=True)` (signalled 1, rc 1) the MSYS `usr\bin\sleep.exe` survived with a dead Windows parent, because `_kill_process_windows` -> `terminate_pid` -> `taskkill /T` walks parent links the MSYS spawn already broke; the graceful path signalled 0 (evidence appended to the doc above); both files are upstream-owned · BLOCKED 2026-10-16: upstream — an issue naming the reproduction, filed by the owner, before any fork-side kill change

- **`FORK-QUALIFY-POSIX-EXIT-FLUSH` — Qualify POSIX exit-flush test signal-state restoration.** The unchanged SIGTERM test saves only SIGTERM, while `install_exit_flush_signal_handlers` also replaces SIGINT; `_restore_signal_state` clears the handler map after restoring the supplied entries. Baseline and candidate Linux tests pass but do not inspect the next test's handler state. Use a bounded native before/after probe and repair the existing fixture if confirmed; no runtime redesign or shared fixture duplication. · fork / native test isolation · [source finding](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · confirmed 2026-10-16 (r-isolation) by a before/after probe: SIGTERM restored, SIGINT left as `_handle_exit_flush_signal` with an empty chain map; the test file is upstream-owned, fix drafted in `docs/agent-runtime-harness/upstream-prs/serve-exit-flush-signal-restore-body.md` · BLOCKED 2026-10-16: upstream — that PR, posted in the owner's next posting sitting


## Filed on arrival — 2026-10-15 (land-w1015b)


## Filed on arrival — 2026-10-15 (owner: "testing commands should be optimised")


## Filed on arrival — 2026-10-15 (lane w1015h-fh-h)


## Filed on arrival — 2026-10-15 (upstream PR sync lanes up-sync-1015-*)


## Filed on arrival — 2026-10-15 (owner: the footprint ratchet only goes up)

### Filed on arrival — 2026-10-16 (Phase B lanes pb-*, release gate triage rel-0222-reds)

- **`FORK-CHECKPOINT-MANAGER-TIMEOUT` — `tests/tools/test_checkpoint_manager.py` times out in the 2026-10-17 `--scope features` run (first: `no result before the cap`); fix whether or not it was red before (owner)** · fork / suite · features run 2026-10-17 (gate store runs.jsonl, `features-1`) · BLOCKED 2026-10-18: upstream — issue text: "`tools/checkpoint_manager._init_store` spawns `git init --bare` plus five `git config` per store (222 of `tests/tools/test_checkpoint_manager.py`'s 1,177 git spawns); fold them into `git init -c` or one config write. Every spawn also pays `pm.client.ensure('git')` (see the store_root row in runtime-queue § Upstream-owned)." q-pm 2026-10-18 alone: 93.4 s / 56 passed idle, 140.1 s under load, 1,180 ensure calls = 19.6 s · r-state 2026-10-18: green alone twice on an idle box (run_tests.sh 68.7 s on origin/main, 62.5 s on `q/r-state`; bare 56.9 s, slowest test 4.1 s); the cost is 1,190 git spawns (~47 ms each: `git init --bare` + five `git config` per store, 44 stores) inside upstream `tools/checkpoint_manager.py`, so a loaded box reaches the cap; no fork-only fix (the store init is the subject) — next: an upstream PR folding the five configs into `git init -c`/one `config` call, or a skip-list call by the owner
- **`FORK-NEMO-PYD-OLD-DELETE` — Owner, after a reboot: delete the retired shared test venv `~/.venvs/hermes-test-3145-retired` (Python 3.14.5 / SQLite 3.50.4; it still holds the held `nemo_relay/_native.pyd.old-0.8.4`)** · fork / box · the shared venv was rebuilt on Python 3.14.7 / SQLite 3.53.1 on 2026-10-19 (same 146 pins, WAL on; `FORK-SHARED-TEST-VENV-SQLITE` closed); the retired folder is the rollback until one landing gate has run on the new venv · BLOCKED 2026-10-19: owner sitting — after a reboot of the workstation and one green landing gate on the new venv, delete the retired folder
- **`FORK-24-UPSTREAM-PR-BRANCHES` — 24 upstream PR branches are prepared and idle (16 splits, 7 doors, the phone fix `fix/connectors-files-lazy-wire`); the account cannot open PRs upstream** · fork / upstream · bodies kept beside the clone in `worktrees/pr-bodies/`; owner 2026-10-16 "pr branches should remain idle" · owner opens them when upstream accepts PRs again; re-check each against the next release first · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: when upstream takes the owner's PRs again, re-check each against the newest release tag and re-run `check_carried_prs.py` before opening — `worktrees/pr-bodies/`
- **`FORK-18-CARRIED-PR-PAIRS` — 18 carried-PR pairs stopped matching after the 2026-10-15 sync (8 hunk/line DRIFT: #119069 gateway.py, #121226 ×2, #121642 auth_nous.py, #123892 shell_hooks.py, #128652 hermes_state_messages.py, #129414 resolution_allowlist.json, #125261 environments/local.py; 9 fragments the PR branches rewrote: #125259, #125263 ×2, #125264, #128648 ×2, #128651, #128654, #128843): per PR re-cut the branch to the fork's text or adopt the PR's text in the fork, then re-pin** · fork / upstream PR tooling · q/carried `5692a35290f` check run · re-anchored 2026-10-18 on q/q-sync (fork adopts the PR's spelling where only spelling differed; #129414 deferred as a fork relocation): 17 → 9 pairs, `check_carried_prs.py` 4 drift + 5 errors; the nine left differ in logic, not spelling (#119069 gateway.py, #121642 auth_nous.py, #125259 config.py, #125261 local.py, #125263 run_tests_parallel.py, #125264 base.py, #128648 main.py + plugins.py, #128652 hermes_state_messages.py) · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: re-cut those eight PR branches to the fork's text when upstream takes the owner's PRs again; adopting the PR's logic in the fork needs a per-PR review lane



- **`FORK-FULL-RE-AUDIT-FOUND` — The full re-audit found nine fork fixes that have no upstream PR yet (`_codex_pool_row_refused`, the system_prompt anchor repair, the `_sanitize_client_source` NameError, `terminal_tool_result.timed_out`, the tts piper download switch, the live-guard console-event refusal, the relay optional binding, the runtime_provider `auto` re-check, the pyproject F821): give each a prepared branch and a PR body in `pr-bodies`** · fork / upstream PRs · same doc §4 · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: cut the nine branches from the then-current release tag only when upstream takes the owner's PRs again (a branch cut now drifts before it can open) — owner 2026-10-16 deferral



## Filed on arrival — 2026-10-15 (lane w1015j-hermes)


## Filed on arrival — 2026-10-16 (h2-redact)


## Filed on arrival — 2026-10-16 (land-h234)



## Filed on arrival — 2026-10-16 (lane h5-deadcode)


## Filed on arrival — 2026-10-17 (footprint audit)


## Filed on arrival — 2026-10-17 (lane r-plugins)


## Filed on arrival — 2026-10-18 land/q6




## Filed on arrival — 2026-10-18 (lane r-quiet)

## Filed on arrival — 2026-10-18 (lane q-gates)

## Filed on arrival — 2026-10-18 (lane q-stale)

## Filed on arrival — 2026-10-18 (lane r-turn)

## Filed on arrival — 2026-10-18 (lane h1-setup)
- **`FORK-STATE-SCHEMA-AUTOCOMMIT` — a fresh `state.db` build autocommits ~100 DDL statements (`hermes_state_schema._init_schema` on the `isolation_level=None` writer): in `journal_mode=DELETE` each is a rollback-journal create+delete+fsync, 87-110 ms CPU per store even at `synchronous=OFF` (100 statements: 105 ms autocommitted vs 6 ms in one transaction); the fork's tests now dodge it with a stripped template, production first-runs and every DELETE-mode install still pay it** · upstream-owned / hermes_state · lane h1-setup measurement (`tests/_downstream/session_db_template.py` docstring) · BLOCKED 2026-10-18: upstream — issue text: "wrap the fresh-store DDL in `_init_schema` in one `BEGIN`/`COMMIT` (SQLite DDL is transactional); a fresh store becomes one journal cycle instead of ~100"

## Filed on arrival — 2026-10-18 (lane h2-sleep)
- **`FORK-TEST-UPSTREAM-FIXED-WAITS` — The largest suite sleeps left are upstream constants a test cannot shorten: `tools/terminal_tool.py::_run_foreground` retries any backend exception at 2+4+8 s (the five `_LIFECYCLE_SCAN` strict-xfail rows in `test_gateway_restart_loop.py` reach the test double's `execute` on Windows, so each pays 14 s: 70 s per run), `hermes_cli/local_runtime/supervisor.py::unload_model`'s 15 s / 0.3 s poll (44 s in `test_local_runtime.py`), `cron/scheduler.py::_launch_external_cron_worker` (18 s in `test_restart_safe_worker_death_evidence.py`) and `hermes_state._sleep_before_write_retry` (15 s in `test_compression_watermark_commit.py`)** · fork / suite (upstream code) · probe 2026-10-18 lane h2-sleep (main-thread sleep per call site, top 44 files) · BLOCKED 2026-10-18: upstream — issue text: "retry backoffs and poll deadlines in `terminal_tool._run_foreground`, `LocalRuntimeSupervisor.unload_model`, `_launch_external_cron_worker` and `SessionDB` write retry are module literals; make each an injectable interval (constructor or module attribute) so tests set it once, and do not retry an `AssertionError` from a test double as a transient backend error"

## Filed on arrival — 2026-10-18 (lane h3-plugins)

## Filed on arrival — 2026-10-18 (lane h6-collect)

## Filed on arrival — 2026-10-18 (land h1018)

## Filed on arrival — 2026-10-18 (lane w2-reds)

## Filed on arrival — 2026-10-18 (lane w2-speed-b)

## Filed on arrival — 2026-10-18 (landing land-w2)

## Filed on arrival — 2026-10-18 (landing land-ww2)

## Filed on arrival — 2026-10-18 (landing land-w3)

## Filed on arrival — 2026-10-18 (land w6)

## Filed on arrival — 2026-10-18 (session r-perf close-out)

- **`FORK-ORPHAN-INSTALL-LEFTOVERS` — the 335 owner-approved orphan pm install states under `X:\Eternia\.hermes\installs` each keep ~82 locked files (~36 MB, hardlinked native modules such as aiohttp `.pyd` held by live Pythons; the whole folder is 5.1 GB), and `uv cache prune` failed on a held temp dir (os error 32); rerun `delete_orphans.py` (skip-and-continue) and `uv cache prune` after a reboot** · fork / workstation · deleter run 2026-10-18 `deleted=0 skipped=0 failed=335` (all PARTIAL) · BLOCKED 2026-10-18: owner sitting — a workstation reboot
- **`FORK-STALE-PR-BRANCH-LAZY-HTTPS` — remote branch `upstream-pr/lazy-https-opener` (`95b3221fbec`) is dead: its SSLKEYLOGFILE cause is fixed by the launcher strip (`1616c349cc`) and FORK-DIAGNOSE-LOCAL-CLI-STARTUP is closed; delete it (`git push origin --delete upstream-pr/lazy-https-opener`), a remote-ref delete the owner runs** · fork / git · w4-misc `317dc4779c` · BLOCKED 2026-10-18: owner sitting — the owner deletes the remote branch

## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)


## Filed on arrival — 2026-10-19 (ns + rt-model landing ab8578f8f5: reds on main after land w10)

- **`FORK-LENS-PULL-DOOR-BUNDLE-DEATH` — `tests/agent_runtime/lens/test_lens_pull_door.py` killed its bundle once in the lint landing gate (passed alone, 12 later members re-bundled)** · fork / suite · gate log of land/lint 2026-10-19 · DEFERRED 2026-10-19: a watch — reopen with the hang stack when a second gate sees it

## Filed on arrival — 2026-10-19 (lane rt-ns-seed)


## Filed on arrival — 2026-10-20 (parent session)

## Filed on arrival — 2026-10-25 (lane w1024t-hermes2)


