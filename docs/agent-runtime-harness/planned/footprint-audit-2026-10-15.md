# Footprint audit 2026-10-15 — the 48 upstream files the fork began editing after 2026-10-06

Design lane `fp-audit` (owner claim `037232c56ab`). Design only: no code moved here. Every
file the footprint ledger (`upstream-footprint-ledger.md`) lists on `origin/main` that was not
in it at the 2026-10-06 state (`711dbe7c029`, the fixture's `files=175` row) gets one of the
merge page's verdicts (`Harness_Brain/50 — Agent Handoffs/Merging upstream.md`, Step 3), asked
in that order: **drop** (upstream now does it; the fork test proving it is named) / **extract**
(the logic can live in a fork-owned module behind one call line; the module is named) /
**upstream** (generic; the PR it would be is named) / **kept** (no seam possible; why).

Measured against `v0.21.7` (`00f69310e29`, the last merged release; `git diff v0.21.7
origin/main -- <path>` is the fork hunk) and `v0.22.2` (`git fetch upstream --tags`,
2026-10-15) for the drop test. Rows that LEFT the ledger in the window: `cli.py`,
`tools/tirith_security.py`. Ratchet on `origin/main`: `[up-fp] files=222 deleted_lines=1050
heavy=4` (heavy = added+deleted > 200, `scripts/upstream_footprint.py`).

## 1. The table

`+a/-d` is the ledger's own count. "lane" names a MOVE lane in §2 or the drop lane in §3.

| path | +a/-d | ledger disp. | verdict | proof / module / PR | lane |
|---|---|---|---|---|---|
| `agent/auxiliary_local_runtime.py` | 6/1 | upstream | upstream | optional-module door (ledger plan item 3 "Minimal distribution"); `tests/hermes_cli/test_local_provider_alias_parity.py` | — |
| `agent/interrupt_control.py` | 6/3 | hook | upstream | HELD PR typed steer admission (`agent/steering.py` is fork-owned; the hunk is already the call line); `tests/agent_runtime/test_steer_provenance_downstream.py`, `test_leftover_steer_next_turn.py` | — |
| `agent/reasoning_effort.py` | 4/1 | carry | extract | profile-then-static lookup → `agent_runtime/reasoning_capabilities.py::codex_declared_or_static_efforts(model)`; 4 → 2 lines | R |
| `agent/transports/codex.py` | 22/3 | carry | extract | the `read()` closure (inspect-signature kwarg threading) and `declared_reasoning_efforts` → `agent_runtime/reasoning_capabilities.py::read_declared_efforts(profile, model, base_url, allow_warm)`; keeps the `allow_warm` kwarg and two call lines; 22 → ~6 | R |
| `agent/turn_iteration_prep.py` | 8/2 | hook | extract | the past-existing-steer-rows walk → `agent/steering.py::insert_pending_steer_rows(messages, index, text)`; 8 → 3 | M |
| `gateway/platforms/api_server.py` | 22/22 | upstream | upstream | PR #137460 (open); drop at the merge that carries it (`v0.22.2` does not); `tests/gateway/test_session_chat_approval.py` + the event-ordering test of `ce3609b4a8c` | — |
| `hermes_cli/_launchers.py` | 5/0 | upstream | upstream | PR candidate (unnamed in the row): the Windows twin of upstream's POSIX launcher-ownership guard; already one call line; `tests/hermes_cli/test_launcher_root_owner_downstream.py` | — |
| `hermes_cli/backup.py` | 3/0 | upstream | upstream | PR #128853 (`*.lock` excluded); `v0.22.2` still lacks any `.lock` rule; `tests/hermes_cli/test_backup_runtime_lock_downstream.py` | — |
| `hermes_cli/codex_models.py` | 2/0 | carry | kept | one call line recording the catalog; lane R re-points the import, count unchanged | — |
| `hermes_cli/local_runtime/devices.py` | 2/1 | upstream | upstream | PR candidate with `sqlite_runtime.py`: `-I` children inherit the pycache prefix (fork door `hermes_cli/child_interpreter.py`); already one line; `tests/hermes_cli/test_child_interpreter.py` | — |
| `hermes_cli/models.py` | 4/13 | carry | extract | restore upstream's `_github_reasoning_efforts_for_model_id` (still in `v0.22.2`); the fork module WIDENS its answer (GPT-6 tiers) instead of replacing it; deleted 13 → 1, added 4 | R |
| `hermes_cli/models_reasoning_caps.py` | 128/0 | carry | extract | an UPSTREAM file carrying the whole control-catalog cache (`_control_catalog_key`, `record_control_catalog`, `cached_control_*`, `github_default_reasoning_efforts`, `_endpoint_scope`, `_save_control_capabilities`) → `agent_runtime/reasoning_capabilities.py` (or a sibling `reasoning_control_catalog.py` if it passes 300 lines); keeps the 2-line `_seed_reasoning_caps` hook; 128 → 2 | R |
| `hermes_cli/sqlite_runtime.py` | 3/1 | upstream | upstream | same PR as `devices.py` | — |
| `hermes_cli/terminal_notify.py` | 9/0 | upstream | extract | the Windows stdout branch → `hermes_cli/windows_console.py::write_tty_windows(seq)`; `if os.name == "nt": return write_tty_windows(seq)`; 9 → 2; draft PR D5 stays the retirement; `tests/hermes_cli/test_terminal_notify_downstream.py` | M |
| `hermes_state_repair.py` | 2/0 | carry | upstream | PR candidate D3.02 (vanished-WAL TOCTOU); `tests/hermes_state/test_preflight_vanished_wal_downstream.py` | — |
| `hermes_state_rewind.py` | 4/1 | upstream | upstream | HELD reviewed-restore PR (with lane C's residue); `tests/agent_runtime/test_operator_history_controls.py` | — |
| `plugins/model-providers/copilot/__init__.py` | 7/1 | carry | upstream | PR candidate "provider-declared reasoning efforts" (one PR for the three profiles + `reasoning_effort.py`); lane R re-points its import | — |
| `plugins/model-providers/openai-codex/__init__.py` | 7/1 | carry | upstream | same PR | — |
| `plugins/model-providers/router/__init__.py` | 7/5 | carry | upstream | TWO PRs: `_DISK_TTL_SECONDS = 24 * 3600` is a one-line upstream NameError fix (`v0.21.7` AND `v0.22.2` use the name in `_efforts_cache_only` and the disk-mirror read and never define it) — its own PR; the `allow_warm` threading rides the efforts PR | — |
| `plugins/plugin_loader.py` | 3/0 | upstream | upstream | PR #128651 (open); `carried_prs.json` defers the path | — |
| `pm/client.py` | 10/0 | upstream | extract | grace wait → `pm/_fork_worker_exit.py::wait_for_slow_exit(process)`; one call line before the 5 s wait; 10 → 3; the PR candidate in the row stays | P |
| `pm/environment.py` | 25/0 | upstream | extract | `_retry_sync_on_sharing_violation` + markers → `pm/_fork_uv_retry.py`; one call line after `self._run`; 25 → 2; `tests/pm/test_uv_sync_sharing_violation.py` | P |
| `pm/environments.py` | 26/0 | carry | extract (split) | `_utf8_stdout` → `pm/_fork_console.py` (13 → 2); the `<parent>/.hermes` sibling candidate in `owning_home_root` (6 lines, `a1bc725068e`, NOT in the reason row) stays as **upstream** (PR candidate: owner lookup honours a data root beside the checkout); the 4-line tail rebind stays (kept) and gains the §3 import guard | P |
| `pm/install.py` | 8/0 | carry | kept | two tail rebinds through `pm/_fork_default_extras.py` / `pm/_fork_dependency_borrow.py`; already the seam form | — |
| `pm/plugins_state.py` | 5/0 | carry | kept | tail rebind through `pm/_fork_selection_memo.py` | — |
| `pm/testenv.py` | 5/0 | carry | kept | tail rebind to `pm/_fork_default_extras.DEFAULT_EXTRAS`; PR candidate with `pm/install.py` | — |
| `scripts/check` | 4/0 | upstream | upstream | generic cp1252 receipt fix; `tests/scripts/test_check_console_encoding_downstream.py` | — |
| `scripts/ci/classify_changes.py` | 1/0 | carry | kept | one route line; retires with the `venv_sync.py` hunk (pre-window row) | — |
| `scripts/install.ps1` | 2/0 | carry | upstream | PR candidate `-SkipUserPath` + env honour (D3.15); `tests/scripts/test_install_ps1_path_fence_downstream.py` | — |
| `tests/agent/test_run_agent_codex_responses.py` | 6/7 | upstream | upstream | held native branch `upstream/codex-retry-isolation`; `v0.22.2` keeps the autouse fixture | — |
| `tests/gateway/test_api_server_active_work_drain.py` | 2/0 | upstream | upstream | cron-budget settle (#132989 follow-up) | — |
| `tests/hermes_cli/test_auth_commands.py` | 3/3 | upstream | upstream | PR #121642 (`carried_prs.json` hunks); `v0.22.2` still spells `inference.example.com` | — |
| `tests/hermes_cli/test_launcher_runtime_selection.py` | 1/0 | carry | **drop** | a guarded tail import in `pm/environments.py` (`try: from pm._fork_dependency_borrow import … except ModuleNotFoundError: pass`) lets the minted tree omit the module; this fixture line goes; proof: the test passes without it | D |
| `tests/hermes_cli/test_source_launcher_publication.py` | 1/0 | carry | **drop** | same guard; the `BOOT_FILES` entry goes; proof: this test + `tests/pm/test_source_launcher_stages.py` + `test_source_update_launch.py` pass without it | D |
| `tests/hermes_cli/test_uninstall_dry_run.py` | 1/0 | upstream | upstream | PR #121640 (`carried_prs.json`) | — |
| `tests/tools/test_windows_agent_loop_papercuts.py` | 23/0 | upstream | upstream | PR #123892 (`carried_prs.json`) | — |
| `tests/tui_gateway/test_bot_relay_methods.py` | 6/3 | upstream | upstream | PR #137478 | — |
| `tests/tui_gateway/test_serve_exit_flush.py` | 68/37 | upstream | upstream | held native branch `upstream/shutdown-test-isolation` | — |
| `tools/approval.py` | 5/0 | hook | **drop** | upstream's `is_approval_bypass_active_for_session(session_key)` (in `v0.21.7`, beside `is_approval_bypass_active`) is the same reader plus `approvals.mode: off`; `agent_runtime/session_controls.py` switches to it; proof: `tests/agent_runtime/test_operator_session_controls.py::test_host_policy_and_bypass_are_reported_honestly`. If that test needs the flag-only distinction for `approval_source`, the fork builds it from public `is_session_yolo_enabled` + `HERMES_YOLO_MODE` in `session_controls.py` — still no upstream edit | D |
| `tools/checkpoint_maintenance.py` | 2/0 | upstream | upstream | one import + one call into lane C's module after the move; part of the held reviewed-restore PR | — |
| `tools/checkpoint_manager.py` | 493/34 | upstream | extract | the reviewed-restore family (module helpers `_history_safe_path`…`release_expired_restore_checkpoints`; methods `checkpoint_tree`, `recorded_file_diff`, `preview_restore`…`_delete_restore_file`, 27 defs) → `agent_runtime/checkpoint_reviewed_restore.py` as `ReviewedRestoreMixin` + helpers; `CheckpointManager` gains ONE base-class line; the three `_checkout_restore_paths` call sites and `_tool_lock_wait_seconds` stay as the upstream-logic-changed residue of the held PR; 493 → ~30 added, heavy 4 → 3 | C |
| `tools/checkpoint_pruning.py` | 14/3 | upstream | upstream | held PR (typed `CheckpointStoreBusy`, bounded wait); `tests/tools/test_checkpoint_store_wait_downstream.py` | — |
| `tools/delegate_tool_registry.py` | 6/2 | hook | upstream | held hook candidate (`authorize_record`), `docs/downstream/agent-console-subagents-controls-2026-10-15.md` | — |
| `tools/file_tools_paths.py` | 6/0 | upstream | upstream | PR #121645 (`carried_prs.json` lines) | — |
| `tools/file_tools_read_tracking.py` | 11/0 | carry | upstream | issue #128639 (PR #128647 closed unmerged); `tests/tools/test_file_snapshot_consistency.py` | — |
| `tui_gateway/methods_complete.py` | 3/0 | upstream | upstream | optional-module door (with `auxiliary_local_runtime.py`); `tests/agent_runtime/test_bundle_profile_switches.py` | — |
| `tui_gateway/methods_session_branch.py` | 2/0 | upstream | upstream | public session-construction hook | — |
| `tui_gateway/methods_session_interrupt.py` | 7/0 | upstream | extract | the `expected_execution_id` branch → `tui_gateway/session_execution.py::exact_interrupt_reply(params, rid)`; `if (reply := exact_interrupt_reply(params, rid)) is not None: return reply`; 7 → 2; the PR candidate stays; `tests/tui_gateway/test_native_execution_fence.py` | M |

**Counts:** drop 3 · extract 11 (one split with an upstream residue) · upstream 29 · kept 5 = 48.

## 2. The MOVE lanes, by footprint fall

One MOVE commit per lane, behaviour identical, the ledger rows re-derived in the same commit
(`scripts/upstream_footprint.py --ledger`), fixture lowered in a CHANGE commit after the gate.
Every fork module a lane creates is a new fork-only file (never an upstream path). Private
upstream names a moved body imports (`_run_git`, `_store_path`, `_index_path`, `_GIT_TIMEOUT`
in lane C; `_origin()` in lane R) are declared in the import-layers exception list with the
door they wait for, as `b273f4a005a` did for the Codex claims.

| lane | files | target module | tests that must stay green | fall |
|---|---|---|---|---|
| **C — reviewed restore** | `tools/checkpoint_manager.py` | `agent_runtime/checkpoint_reviewed_restore.py` (`ReviewedRestoreMixin` + module helpers; callers `agent_runtime/operator_{checkpoints,history_recovery,redo,turn_changes,undo}.py`, `turn_checkpoints.py` import unchanged names from the fork module) | `tests/tools/test_checkpoint_reviewed_restore_downstream.py`, `test_checkpoint_restore_lifecycle_downstream.py`, `test_checkpoint_history_compatibility_downstream.py`, `test_checkpoint_store_wait_downstream.py`, `tests/agent_runtime/test_turn_checkpoint_provenance.py`, `test_operator_history_controls.py`, upstream `tests/tools/test_checkpoint*` | added 493 → ~30; **heavy 4 → 3**; deleted unchanged (34, the held PR's residue) |
| **R — reasoning control catalog** | `hermes_cli/models_reasoning_caps.py`, `agent/transports/codex.py`, `hermes_cli/models.py`, `agent/reasoning_effort.py` (+ import re-points in `codex_models.py`, the three plugin profiles) | `agent_runtime/reasoning_capabilities.py` (143 lines today; split a `reasoning_control_catalog.py` beside it if the result passes 300) | `tests/agent_runtime/test_reasoning_capabilities.py`, `tests/agent/test_auxiliary_reasoning_catalog_floor.py`, `test_reasoning_disable_recovery.py`, `tests/hermes_cli/test_deleted_profile_tombstone.py`, upstream `tests/hermes_cli/test_models*.py`, `tests/agent/test_reasoning_effort*.py` | added ~158 → ~14; **deleted 1050 → 1038** |
| **P — pm seams** | `pm/environment.py`, `pm/client.py`, `pm/environments.py` (the `_utf8_stdout` body only) | `pm/_fork_uv_retry.py`, `pm/_fork_worker_exit.py`, `pm/_fork_console.py` (the `pm/_fork_*` convention `5d93d4f0064` set) | `tests/pm/test_uv_sync_sharing_violation.py`, `tests/pm/test_dependency_borrow_downstream.py`, `tests/pm/test_default_extras_downstream.py`, upstream `tests/pm/test_client*.py`, `test_environment*.py`, `tests/hermes_cli/test_launcher_runtime_selection.py` | added 61 → ~7 |
| **M — one-call seams** | `hermes_cli/terminal_notify.py`, `agent/turn_iteration_prep.py`, `tui_gateway/methods_session_interrupt.py` | `hermes_cli/windows_console.py` (new), `agent/steering.py`, `tui_gateway/session_execution.py` | `tests/hermes_cli/test_terminal_notify_downstream.py` + `test_terminal_notify.py`, `tests/agent_runtime/test_steer_provenance_downstream.py`, `test_leftover_steer_next_turn.py`, `tests/tui_gateway/test_native_execution_fence.py`, `test_native_compute_dispatch.py` | added 24 → ~7 |

Order: C, R, P, M. C and R touch disjoint files and may run concurrently; P and M after R
lands (R re-points imports that M's steering move must not race). One gate per batch
(`Running the tests.md`), never one per lane.

## 3. The drop lane (CHANGE, not MOVE)

| file | change | proof |
|---|---|---|
| `tools/approval.py` | delete `approval_bypass_active`; `agent_runtime/session_controls.py` reads `is_approval_bypass_active_for_session` | `tests/agent_runtime/test_operator_session_controls.py` green on the upstream reader (see the table row for the fallback) |
| `tests/hermes_cli/test_launcher_runtime_selection.py`, `tests/hermes_cli/test_source_launcher_publication.py` | guard the `pm/environments.py` tail import (`except ModuleNotFoundError: pass`, 2 lines, inside the row the ledger already carries) and delete the two fixture lines | both tests + `tests/pm/test_source_launcher_stages.py`, `test_source_update_launch.py`, `tests/pm/test_dependency_borrow_downstream.py` green |

Fall: **files 222 → 219**, added −7 (+2 in `pm/environments.py`).

After all four lanes and the drop lane: `[up-fp] files=219 deleted_lines≈1038 heavy=3`;
added lines across the 48 files ≈ 1,030 → ≈ 300.

## 4. Reason rows that read wrong (file them from the lane that lands the fix)

- `tools/approval.py` — "candidate public effective-bypass reader … candidate documented, not
  submitted": upstream has had the reader since before `v0.21.7`; the row describes a duplicate as a
  candidate. Retire with §3.
- `pm/environments.py` — the row names the UTF-8 reconfigure and the tail rebinds; the six-line
  `<parent>/.hermes` sibling candidate (`a1bc725068e`, runtime R623, inside `owning_home_root`)
  is unnamed. Lane P's re-derive names it and its PR.
- `tests/hermes_cli/test_launcher_runtime_selection.py`, `test_source_launcher_publication.py` —
  "Retire when the borrow leaves environments.py's tail": a two-line import guard retires both
  rows now (§3).
- `hermes_cli/models_reasoning_caps.py` — "Generic; PR candidate once the plugin provider
  profiles consume only the public hook": the row does not say the 128 lines sit in an upstream
  file with no fork module named; lane R's row names `agent_runtime/reasoning_capabilities.py`.
- `plugins/model-providers/router/__init__.py` — the row folds a one-line upstream NameError
  fix (`_DISK_TTL_SECONDS` undefined in `v0.21.7` and `v0.22.2`) into the efforts carry; it is
  its own PR and should be the first one opened when `nekwo` can open PRs again.
- `hermes_cli/_launchers.py` — disposition `upstream` with no PR named; the PR is the Windows twin
  of the POSIX launcher-ownership guard.
- `agent/interrupt_control.py` — the row cites `test_steer_provenance_downstream.py` without a
  directory; it is `tests/agent_runtime/test_steer_provenance_downstream.py`.
