---
type: initiative
program: upstream-sync
status: ready-to-land
blocking: "operator: push main, then fast-forward the candidate onto main"
docs: "docs/agent-runtime-harness/planned/"
tags: [initiative, program/upstream-sync]
---

# upstream-merge-2026-09-21

Bring `main` (56 ahead, 3,002 behind `NousResearch/hermes-agent:main` at `ea0c2b820b`) up to date with one history-preserving merge. Dispatched 2026-09-21 to an Opus lane after the per-file Codex reconciliation branches were deleted ([[0006 — Upstream sync is a real merge, per-file reconciliation retired]]).

> [!warning] Blocking
> The lane's report. Then `scripts/run_tests.sh` on the validated four-directory scope against the exact candidate SHA. The operator lands it fast-forward; nobody else pushes `main`.

## Files

**Worktree:** `X:/Eternia/worktrees/merge-upstream-20260921`, branch `merge/upstream-2026-09-21`, cut from `main` @ `042f58edf8`.
**Measured before dispatch** (`git merge-tree --write-tree main upstream/main`): 40 conflicted files, 51 hunks — 29 production (`agent/` 7, `gateway/` 3, `hermes_cli/` 9, `tools/` 8, `hermes_constants.py`, `scripts/run_tests_parallel.py`) and 11 tests/docs. Worst file: `tests/hermes_cli/test_doctor.py` (3 hunks). Nothing in `agent_runtime/` or `harness_parts/` conflicts.
**Resolution rules given to the lane:** keep both when additive; upstream's version of upstream logic with the fork's addition re-applied; the seams survive (`_downstream_cli`, `_profile_bootstrap`, `_boot_clock`, harness registration, `process_registry.restore_durable_completions`, profile scoping); never drop a fork test; `pyproject`/`uv.lock` = fork pair + new upstream rows.

## Landing state (2026-09-21 evening)

Candidate tip carries: the merge, the lane's two fixes, `c86bd3efed` (terminal_tool), `cae43faa67` (slash registry + dashboard test), lane B `1ca2a7e779` (gates judge per line), lane A `0db5e8e353` (doctor serves `HERMES_HOME`/`_DHH` live via PEP 562), and `main` merged in. Landing checks on the landed tip: touched tests + tooling gates + docs gate = 1,325 passed, 3 failed, all three named and rowed (the residual doctor vendor-slug test; `test_no_frozen_hermes_home` on two upstream names; the docket gate, pre-existing). Contract dumps fresh (CLI 196 paths, payload 152 keys). The mutation inventory cannot run on `main` (stale desk-litter entry, rowed). Branch pushed.

**Operator lands it:** `git -C X:/Eternia/hermes-agent push origin main` then `git -C X:/Eternia/hermes-agent push origin merge/upstream-2026-09-21:main` (fast-forward verified at push time).

## Resume

1. Read the lane's report (≤ 30 lines: tip SHA, per-file rule, test counts, reds marked merge-caused vs pre-existing, ≤ 3 open rows).
2. In a landing worktree: `git fetch origin && git checkout merge/upstream-2026-09-21`; run `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/cli tests/state` in the background with a log (≥ 25 min); `scripts/dump_cli_contract.py --check`; `scripts/dump_payload_contract.py --check`.
3. Land: `git push origin merge/upstream-2026-09-21:main` only if fast-forward from `main`; otherwise re-merge `main` into the branch first (never rebase a merge).
4. Update [[Upstream Sync]]'s cursor, delete this note's row in [[fork-hygiene-queue]], remove the worktree, delete the branch.
5. Do not touch the primary checkout's index while landing ([[Known Pitfalls]]).

## Suite verdict on the candidate (2026-09-21, `e3ac4726ca`, validated scope, 109 min)

`21,587 passed / 269 failed / 432 skipped` across 1,806 files; 102 red files. Every red file that exists on `main` was re-run on `main` (`bd3c22215d`, 96 files, 16 min) and the two runs were diffed per test id. Logs: `X:/Eternia/worktrees/merge-suite-20260921.log`, `main-reds-full-20260921.log`.

| class | tests | files | disposition |
|---|---|---|---|
| pre-existing on `main` (red in both runs) | 194 | 72 | rowed in [[fork-hygiene-queue]]; not this merge's to fix |
| new upstream test files absent from `main` | 6 | 6 | Windows-shaped reds in upstream code and tests; rowed |
| red on the candidate, green on `main` | 45 | 22 | split below |

Owner ruling 2026-09-21: **only merge-caused defects on the fork's side are fixed.** Upstream code and upstream tests are not touched; the fork's structural gates are fork-side.

### The 45 "green on main, red on the candidate", by cause

- **Fork seam broke** (fixed, `c86bd3efed`): `tools/terminal_tool.py` wrapper did not forward upstream's new `_completion_output_chars`, so every background spawn raised NameError. 2 tests.
- **Fork data lost in the merge** (sheet F2): the desktop slash-registry dump took upstream's copy and dropped the fork's `/queue-status` + `/qstatus` rows. 2 tests.
- **Fork-retained test whose premise upstream moved** (sheet F3): `test_profile_launch_attaches_to_running_dashboard`. Upstream rewrote `cmd_dashboard` (175 lines) and pruned this test; the module is byte-identical to upstream. 1 test.
- **Fork seam vs new upstream tests** (sheet F4, lane A): the fork deleted `hermes_cli/doctor.py`'s module-level `HERMES_HOME` (call-time rule); three new upstream tests patch `doctor.HERMES_HOME` and die on AttributeError. 3 tests.
- **Fork structural gates now scan upstream-authored code** (sheet F5, lane B): the no-`undo()` gate flags three upstream test sites; the flag-binding gate flags `hermes_cli/send_cmd.py` (`mentions or []`, upstream code). 2 tests.
- **Not the merge: worktree path artifact** (row): 9 serve boot tests read a `stderr` frame before `ready`. `agent_runtime/serve_registry.py` judges a process "serve-like" only when its command line contains `hermes` AND `serve`; under the runner that comes from the checkout path, and `X:/Eternia/worktrees/merge-upstream-20260921` lacks `hermes`. Proven on `main`: relative path fails, absolute `X:/Eternia/hermes-agent/...` passes. Lanes on this program cut worktrees under `X:/Eternia/worktrees/hermes-*`.
- **Not ours: upstream tests or code red on this Windows box** (row, 26 tests): `pwd` imported unguarded in `hermes_cli/gateway.py::_restart_macos_launchd_gateways` (10 tests across `test_pending_supervisor_recovery` / `test_update_launchd_restart_verification`); the kanban zombie reaper calls `proc.poll()` on upstream's own fake (3 tests, `test_kanban_core_functionality` / `test_kanban_db`); POSIX-only assumptions (`test_config` denylist near-miss x2, `test_startup_fast_guards` path separator x2, `test_gui_command`, `test_stale_pid_guard`, `test_install_cua_driver` x2, `test_active_sessions` x2); the fork's gateway fence blocking a live schtasks test (`test_gateway_windows`); this box's bash (`test_gateway_restart_loop`); a 12 s network-timed picker (`test_inventory_pricing`).

### Fix sheets (implementation-ready; one CHANGE commit each; touched tests only; report <= 30 lines)

**F2: re-dump the slash registry** (landing, mechanical). In the candidate: `python scripts/dump_desktop_slash_registry.py`; the diff is exactly `+"/qstatus": null` and `+"/queue-status": null`. Touched test: `tests/hermes_cli/test_desktop_slash_registry.py`.

**F3: retire the fork-retained dashboard attach test** (landing, mechanical). Delete `TestUnifiedDashboardRouting::test_profile_launch_attaches_to_running_dashboard` in `tests/hermes_cli/test_dashboard_unified_launch.py` (the `_capture_reexec` helper stays; four other tests use it). Commit body: upstream pruned the test and rewrote `cmd_dashboard`; the module carries no fork edit. Touched test: that file.

**F4: the doctor's `HERMES_HOME` patch seam** (lane A). Facts: the fork's only edits to `hermes_cli/doctor.py` are (1) deleting `HERMES_HOME = get_hermes_home()` and the import-time `load_hermes_dotenv(...)`, moving the dotenv load into `_run_doctor`; (2) the `run_doctor` browser-probe wrapper and the `check_gateway_launcher` row. Upstream's new tests (`tests/hermes_cli/test_doctor.py::test_run_doctor_vendor_slug_policy_for_openai_api_endpoint[*]`, `tests/hermes_cli/test_doctor_wal_holder_guard.py::test_doctor_names_retired_wal_holders_instead_of_healthy_state_db`) patch `doctor.HERMES_HOME` with `raising=True`. Steps: read the three tests and every read of `HERMES_HOME` upstream added to `doctor.py` since `c62bd9f207` (`git diff c62bd9f207 upstream/main -- hermes_cli/doctor.py`). Decision rule: restore the module-level name exactly as upstream spells it (`HERMES_HOME = get_hermes_home()`), keep the dotenv load in `_run_doctor`, and confirm `hermes_cli/main.py` imports `hermes_cli.doctor` lazily inside the doctor command handler (after `_apply_profile_override`) so the profile override still wins; if the import is eager, do NOT restore the constant: report it and stop. Positive control: the three tests red before, green after; `tests/hermes_cli/test_doctor*.py` run directly. Record the disposition as `carry` in `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams-field-notes-2026-09-21.md` section 2 (one line).

**F5: fork structural gates scope to fork-touched files** (lane B). Two fork-only gates now read upstream-authored code: `tests/agent_runtime/test_no_midtest_monkeypatch_undo.py::test_no_test_in_the_tree_unwinds_the_shared_monkeypatch` (sites: `tests/hermes_cli/test_gateway.py:37` and `:1349`, a locally constructed `pytest.MonkeyPatch()`, not the shared fixture; `tests/hermes_state/test_clean_close_residual_poison.py:132`, the shared fixture) and `tests/hermes_cli/test_flag_binding_boundary.py::test_no_handler_collapses_an_absent_flag_into_an_empty_collection` (site: `hermes_cli/send_cmd.py:210`). Ruling: upstream code is not edited, and neither gate grows an allowlist. Design: one shared helper (new fork-only module `tests/_fork_scope.py`) that answers "is this file fork-touched?" = absent from `upstream/main` OR its blob differs from `upstream/main`'s (`git ls-tree -r upstream/main` once per session, compare `git hash-object` of the working file to the listed blob; no per-file `git diff`). When the `upstream/main` ref is absent (CI, a clone without the remote), the helper returns True for every file, so the gates fail CLOSED to their current behaviour. Both gates filter their scan through it; their docstrings gain one paragraph stating the rule and its reason (upstream's tests are upstream's; the conftest tripwire `_shared_monkeypatch_pin_tripwire` remains the behavioural guard for every file). Positive control for each gate: plant one `monkeypatch.undo()` / one `or []` in a fork-only file on a throwaway copy, red; revert. Touched tests: the two gate files run directly.

**F5 as shipped (lane B, `1ca2a7e779`):** the file-level rule was not enough. `tests/hermes_cli/test_gateway.py` is fork-EXTENDED (116 appended lines), so it reads as fork-touched while its two `undo()` sites are upstream's lines. The helper therefore also answers per line: `is_fork_authored(path, lineno)` diffs the working file against the upstream blob and a finding is ours only on an inserted line. Both gates filter FINDINGS, not their walks, so the anti-vacuity floors still measure the whole tree and a green gate pays no git call. Fail-closed proofs and six new tests are in the commit.

**Lane geometry:** worktrees `X:/Eternia/worktrees/hermes-mfix-a` (branch `merge-fix/doctor-home`) and `hermes-mfix-b` (branch `merge-fix/gate-scope`), both cut from `merge/upstream-2026-09-21` @ `c86bd3efed`. Opus. Landing merges both into the candidate, then `main` into the candidate, re-runs the touched tests plus the tooling gates, pushes the branch, and hands the operator the fast-forward.
