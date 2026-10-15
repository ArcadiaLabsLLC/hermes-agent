# FOOTPRINT-DROP — bucket table (2026-09-27)

Lane FOOTPRINT-DROP (row in `Harness_Brain/10 — Programs/Upstream Sync.md`). Baseline at
`becaa5d8c0`: **151 files / 834 deleted / 4 heavy** (`scripts/upstream_footprint.py --json`,
base `2f14d5e6e4`). Every footprint file sorted once:

- **a** — upstream test file whose fork edit is a marker, a skip, a Windows-only guard or a
  behaviour-free comment/import: the mark moves to `tests/_downstream/id_markers/` by test
  id, the file goes back to upstream's bytes.
- **a/step3** — upstream test file carrying a Windows respelling of upstream's own test(s):
  the fork version moves to a sibling under `tests/_downstream/`, upstream's id is marked
  `_up_red` on win32 (strict xfail), the file goes back to upstream's bytes.
- **b** — a 1–3-line hook the harness plugin wraps at load. **None qualified**: every 1–3-line
  candidate is a signature, an inline expression, a SQL string, or (the one wrappable
  function, `agent/system_prompt.py::_plugin_session_info`) is called before lazy plugin
  discovery runs, so a load-time wrap would change the first render.
- **c** — the edit rides an OPEN upstream PR by `nekwo` whose file list names this path
  (`gh pr list -R NousResearch/hermes-agent --author nekwo --state open`, read 2026-09-27).
  A branch that is held and not opened is not (c). A test file the ledger calls "lifted"
  whose PR does not list it is not (c) either.
- **d** — must stay, with the reason.
- **e** — a (d) file carrying 20+ fork lines: the body moves into a fork-owned module and the
  upstream file keeps the import/call line.

Counts: a 14, a/step3 19, b 0, c 67, d 35, e 16.

| path | added | deleted | bucket | reason |
|---|---|---|---|---|
| `.gitattributes` | 7 | 0 | d | root-only `* text=auto eol=lf`; no fork-owned file carries a root rule (ruling 2026-09-24) |
| `AGENTS.md` | 2 | 0 | d | pointer line for non-Claude agents, which read only AGENTS.md (ruling 2026-09-24) |
| `README.md` | 7 | 1 | d | licence notice; moving it leaves the fork README stating MIT only - legal, owner call |
| `agent/agent_init.py` | 25 | 1 | d | call sites inside `init_agent`; no init-phase hook |
| `agent/codex_runtime.py` | 2 | 0 | c | rides open upstream PR #123978 |
| `agent/conversation_compression.py` | 11 | 2 | d | inline floor condition + argument |
| `agent/conversation_loop.py` | 16 | 0 | c | rides open upstream PR #124210, #123978 |
| `agent/credential_pool.py` | 9 | 18 | c | rides open upstream PR #124193 |
| `agent/pet/generate/atlas.py` | 199 | 14 | e | fork-only `frame_x_bounds`/`_slot_bounds` movable to `agent/charsheet/`; rest is the G3 PR body |
| `agent/process_bootstrap.py` | 5 | 0 | d | branch inside `build_keepalive_http_client`; callers bind the name at import, a load-time wrap misses them |
| `agent/prompt_builder.py` | 39 | 7 | c | rides open upstream PR #124191 |
| `agent/session_persistence.py` | 5 | 2 | c | rides open upstream PR #124210 |
| `agent/shell_hooks.py` | 1 | 1 | c | rides open upstream PR #123892 |
| `agent/skill_utils.py` | 9 | 4 | c | rides open upstream PR #124191 |
| `agent/system_prompt.py` | 1 | 0 | d | 1 line; a plugin wrap of `_plugin_session_info` lands only at discovery, which `_frozen_plugin_prompt_sections` triggers AFTER building session_info - the first render would lose `tool_names` |
| `agent/turn_api_request.py` | 11 | 0 | d | in-function timing stamps; no per-phase hook |
| `agent/turn_context.py` | 18 | 8 | c | rides open upstream PR #124210 |
| `agent/turn_facade.py` | 2 | 0 | c | rides open upstream PR #124210 |
| `agent/turn_response_check.py` | 6 | 0 | d | in-function timing stamp; no response-validation hook |
| `agent/turn_response_intake.py` | 12 | 1 | c | rides open upstream PR #123978 |
| `apps/shared/src/gateway-contract.generated.ts` | 1 | 0 | d | generated from the contract; no plugin gateway-method seam |
| `apps/shared/src/gateway-contract.openrpc.json` | 12 | 0 | d | generated from the contract; no plugin gateway-method seam |
| `cli.py` | 2 | 1 | c | rides open upstream PR #121646 |
| `contributors/emails/uperLu@users.noreply.github.com` | 2 | 2 | a | CRLF->LF only: revert to upstream bytes, `-text` keeper in a fork-owned nested `.gitattributes`, declared in `tests/test_line_endings.py` |
| `evals/postmortem/live_ab/cache_concurrency_probe.py` | 12 | 0 | c | rides open upstream PR #123890 |
| `gateway/hosted_room_discussion.py` | 85 | 33 | e | Group Chat host-surface widening (85/33) |
| `gateway/hosted_room_policy_checkpoint.py` | 6 | 3 | d | same Group Chat widening, 6 lines |
| `gateway/hosted_rooms.py` | 72 | 4 | e | pin/unpin retention opt-in (72), generic surface widening |
| `gateway/lifecycle_ledger.py` | 12 | 4 | c | rides open upstream PR #123891 |
| `gateway/platforms/base.py` | 4 | 2 | c | rides open upstream PR #125264 |
| `gateway/run.py` | 4 | 6 | c | rides open upstream PR #121646 |
| `gateway/run_notifications.py` | 2 | 1 | d | `reply_to=` inside the watcher loop; no hook site |
| `gateway/shutdown_watchdog.py` | 12 | 3 | c | rides open upstream PR #123891 |
| `hermes_cli/auth.py` | 13 | 1 | c | rides open upstream PR #124190, #121642 |
| `hermes_cli/auth_codex.py` | 3 | 1 | d | PR-1 `on_verification` kwarg - a signature (branch held, not opened) |
| `hermes_cli/auth_codex_browser.py` | 4 | 1 | d | PR-1 `on_verification` kwarg - a signature (branch held, not opened) |
| `hermes_cli/auth_commands.py` | 7 | 0 | d | dispatch arms for `auth set-key`/`auth login` inside `auth_command` |
| `hermes_cli/auth_minimax.py` | 7 | 2 | d | PR-1 `on_verification` kwarg - a signature (branch held, not opened) |
| `hermes_cli/auth_nous.py` | 2 | 1 | c | rides open upstream PR #121642 |
| `hermes_cli/auth_xai.py` | 6 | 1 | d | PR-1 `on_verification` kwarg - a signature (branch held, not opened) |
| `hermes_cli/config.py` | 10 | 6 | c | rides open upstream PR #125259 |
| `hermes_cli/doctor.py` | 40 | 7 | c | rides open upstream PR #125260 |
| `hermes_cli/doctor_config.py` | 8 | 3 | c | rides open upstream PR #125260 |
| `hermes_cli/doctor_platform.py` | 5 | 1 | c | rides open upstream PR #125260 |
| `hermes_cli/doctor_state.py` | 13 | 5 | c | rides open upstream PR #125260 |
| `hermes_cli/gateway.py` | 169 | 19 | e | G11 guards + home receipt (169/19) |
| `hermes_cli/gateway_windows.py` | 123 | 2 | e | G11 launcher interpreter / console-less detection (123) |
| `hermes_cli/kanban_db_dispatch.py` | 13 | 0 | d | crash-evidence capture inside the reclaim path, 13 lines |
| `hermes_cli/main.py` | 62 | 195 | e | seam 0.3 hunk plan (62/195, heavy) |
| `hermes_cli/main_web_build.py` | 2 | 47 | d | already one call into `_bytecode_sweep.py`; the 47 are upstream lines it replaces |
| `hermes_cli/mcp_config.py` | 18 | 2 | d | 18 lines, under the (e) bar; `--env` G13 |
| `hermes_cli/plugin_compat.py` | 4 | 0 | c | rides open upstream PR #121023 |
| `hermes_cli/plugins.py` | 50 | 2 | c | rides open upstream PR #124210, #123979, #123977 |
| `hermes_cli/plugins_discovery.py` | 6 | 6 | c | rides open upstream PR #125259 |
| `hermes_cli/plugins_manifest.py` | 20 | 0 | e | `cli_commands` entry parser movable; the field lines stay |
| `hermes_cli/provider_catalog.py` | 196 | 0 | e | 196 added; launcher-roster half movable |
| `hermes_cli/service_manager.py` | 1 | 1 | c | rides open upstream PR #121640 |
| `hermes_cli/subcommands/auth.py` | 37 | 0 | e | `set-key`/`login` parser block (37) movable to a fork module, one call line |
| `hermes_cli/subcommands/mcp.py` | 10 | 0 | d | `--env` flag, 10 lines |
| `hermes_cli/uninstall.py` | 3 | 1 | c | rides open upstream PR #121640 |
| `hermes_cli/update_cmd.py` | 11 | 0 | c | rides open upstream PR #125265 |
| `hermes_cli/update_cmd_git.py` | 5 | 2 | d | never-force guard, owner keep 2026-09-27 |
| `hermes_cli/update_cmd_windows.py` | 30 | 1 | e | launcher refresh tolerance (30) |
| `hermes_cli/update_inventory.py` | 15 | 0 | c | rides open upstream PR #125265 |
| `hermes_cli/web_routers/oauth.py` | 4 | 26 | d | already a call into `provider_catalog.disconnect_command_for`; the 26 are the upstream helper it replaces |
| `hermes_cli/web_server_oauth.py` | 8 | 31 | d | already built from `provider_catalog`; the 31 are the upstream table it replaces |
| `hermes_cli/worktree_ops.py` | 1 | 1 | c | rides open upstream PR #121640 |
| `hermes_state_messages.py` | 3 | 1 | d | row-projection condition inline |
| `hermes_state_sessions.py` | 2 | 2 | d | ORDER BY tie-break inside SQL text |
| `model_tools.py` | 31 | 0 | e | memo counters + `ensure_tool_describe_present` (31) |
| `plugins/dashboard_auth/_shared.py` | 4 | 3 | c | rides open upstream PR #125259 |
| `plugins/memory/__init__.py` | 69 | 1 | e | `_publish_module`/`_unpublish_module` (69) movable to a fork module |
| `providers/__init__.py` | 1 | 1 | d | import path; the revert re-reds `test_tool_visibility_import_deferral.py` (lane MECH) |
| `pyproject.toml` | 64 | 1 | d | `agent_runtime` packages.find include, no override point (ruling 2026-09-24) |
| `scripts/check_subprocess_stdin.py` | 2 | 2 | c | rides open upstream PR #125262 |
| `scripts/run_tests.sh` | 116 | 1 | c | rides open upstream PR #125263 |
| `scripts/run_tests_parallel.py` | 185 | 44 | c | rides open upstream PR #125263 |
| `tests/_fixtures/env_filter.py` | 10 | 1 | c | rides open upstream PR #125263 |
| `tests/_fixtures/live_system_guard.py` | 169 | 9 | e | backend-spawn arm movable to `tests/_downstream/`; the Windows console refusal is the recorded 2026-09-27 carry |
| `tests/agent/test_coding_context.py` | 13 | 2 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-line-endings) |
| `tests/agent/test_compression_adoption_preserves_live_tail.py` | 1 | 1 | a | comment-only doc-pointer fix on an upstream-authored line; the coverage-claims gate scopes upstream lines out (`tests/_fork_scope.py`) - revert |
| `tests/agent/test_provider_fallback.py` | 5 | 3 | a | comment-only doc-pointer fix on an upstream-authored line; the coverage-claims gate scopes upstream lines out (`tests/_fork_scope.py`) - revert |
| `tests/agent/test_shell_hooks_consent.py` | 6 | 1 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-tilde-home) |
| `tests/agent/test_skill_commands.py` | 10 | 2 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-shell-invocation; file not in #121226) |
| `tests/agent/test_skill_utils.py` | 7 | 5 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (Path compare) + orphan import/banner revert |
| `tests/conftest.py` | 7 | 1 | d | import-time stale-lock sweep runs before any plugin; recorded Windows console carry 2026-09-27 |
| `tests/cron/test_cron_memory_contract.py` | 1 | 1 | a | comment-only doc-pointer fix on an upstream-authored line; the coverage-claims gate scopes upstream lines out (`tests/_fork_scope.py`) - revert |
| `tests/gateway/test_media_spaced_paths_and_history_dedupe.py` | 1 | 0 | a | unused `Path` import left after the tilde-home lift - revert |
| `tests/hermes_cli/test_apply_profile_override.py` | 24 | 2 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (platform root pin) |
| `tests/hermes_cli/test_auth_nous_provider.py` | 33 | 4 | c | rides open upstream PR #121642 |
| `tests/hermes_cli/test_backup.py` | 33 | 7 | c | rides open upstream PR #121225, #121224 |
| `tests/hermes_cli/test_deleted_profile_tombstone.py` | 6 | 1 | c | rides open upstream PR #121224 |
| `tests/hermes_cli/test_doctor.py` | 3 | 3 | c | rides open upstream PR #125260 |
| `tests/hermes_cli/test_doctor_journal_modes.py` | 4 | 3 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (OS error text; file not in #121225) |
| `tests/hermes_cli/test_gateway_migrate_multiplex.py` | 3 | 0 | a | `platforms("linux")` marks, moved to id_markers by test id |
| `tests/hermes_cli/test_kanban_worktree_teardown.py` | 1 | 0 | a | `platforms("linux")` marks, moved to id_markers by test id |
| `tests/hermes_cli/test_linux_desktop_entry.py` | 20 | 0 | a | `platforms("linux")` marks, moved to id_markers by test id |
| `tests/hermes_cli/test_local_runtime.py` | 5 | 0 | a/step3 | stub fix so the 15 s unload loop exits under the fork `--timeout=30`: fork stub -> sibling, upstream ids marked |
| `tests/hermes_cli/test_node_runtime_npm_resolution.py` | 3 | 0 | a | `platforms("linux")` marks, moved to id_markers by test id |
| `tests/hermes_cli/test_orphan_desktop_serve_reap.py` | 5 | 0 | a | `platforms("linux")` marks, moved to id_markers by test id |
| `tests/hermes_cli/test_projects_db.py` | 19 | 7 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-path-spelling; file not in #121224) |
| `tests/hermes_cli/test_prompt_compose_command.py` | 25 | 11 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-shell-invocation; file not in #121226) |
| `tests/hermes_cli/test_setup_hermes_script.py` | 19 | 1 | c | rides open upstream PR #121226 |
| `tests/hermes_cli/test_win_pty_bridge.py` | 41 | 3 | c | rides open upstream PR #121219 |
| `tests/scripts/test_run_tests_parallel.py` | 131 | 3 | c | rides open upstream PR #125263 |
| `tests/test_hermes_constants.py` | 9 | 1 | a | POSIX premise (`~/.hermes` native root): `_posix_only` by id |
| `tests/test_live_system_guard_self_test.py` | 4 | 0 | a | Windows guard (signal 0 = CTRL_C_EVENT): skip by id on win32 + the no-delivery bypass check as a sibling |
| `tests/tools/test_approved_command_clean_slate.py` | 20 | 2 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-shell-invocation; file not in #121226) |
| `tests/tools/test_delegate.py` | 2 | 2 | a | comment-only doc-pointer fix on an upstream-authored line; the coverage-claims gate scopes upstream lines out (`tests/_fork_scope.py`) - revert |
| `tests/tools/test_execution_flag_detection.py` | 11 | 2 | c | rides open upstream PR #121226 |
| `tests/tools/test_file_tools_live.py` | 35 | 4 | c | rides open upstream PR #121226 |
| `tests/tools/test_file_tools_tilde_profile.py` | 9 | 2 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-path-spelling; not in #121224) |
| `tests/tools/test_interrupt.py` | 1 | 1 | a | comment-only doc-pointer fix on an upstream-authored line; the coverage-claims gate scopes upstream lines out (`tests/_fork_scope.py`) - revert |
| `tests/tools/test_local_background_child_hang.py` | 10 | 3 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-shell-invocation; not in #121226) |
| `tests/tools/test_local_env_cwd_recovery.py` | 10 | 1 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-path-spelling; not in #121224) |
| `tests/tools/test_local_env_relative_cwd.py` | 25 | 2 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-shell-invocation; not in #121226) |
| `tests/tools/test_local_env_windows_msys.py` | 15 | 3 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (os.path.join layout) |
| `tests/tools/test_modal_sandbox_fixes.py` | 28 | 4 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (`_native_host_cwd`) |
| `tests/tools/test_skills_hub.py` | 4 | 3 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (POSIX bundle keys; test file not in #121643) |
| `tests/tools/test_subprocess_home_isolation.py` | 9 | 2 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-path-spelling; not in #121224) |
| `tests/tools/test_terminal_output_transform_hook.py` | 6 | 1 | a/step3 | Windows respelling of upstream test(s), no open PR carries the file: fork version -> sibling under `tests/_downstream/`, upstream id `_up_red` on win32 (win-shell-invocation; not in #121226) |
| `tools/approval_context.py` | 3 | 9 | c | rides open upstream PR #121646 |
| `tools/approval_detection.py` | 43 | 7 | c | rides open upstream PR #125262 |
| `tools/async_delegation.py` | 15 | 1 | c | rides open upstream PR #124190 |
| `tools/browser_tool_lifecycle.py` | 2 | 1 | c | rides open upstream PR #125262 |
| `tools/code_execution_env.py` | 3 | 2 | c | rides open upstream PR #125262 |
| `tools/credential_files.py` | 1 | 1 | c | rides open upstream PR #121643 |
| `tools/environments/local.py` | 67 | 1 | c | rides open upstream PR #125261 |
| `tools/file_tools.py` | 24 | 2 | c | rides open upstream PR #121645 |
| `tools/file_tools_write_guards.py` | 5 | 4 | c | rides open upstream PR #121645 |
| `tools/image_generation_tool.py` | 2 | 2 | c | rides open upstream PR #125259 |
| `tools/mcp_tool_config.py` | 41 | 1 | c | rides open upstream PR #124210 |
| `tools/mcp_tool_transport.py` | 3 | 3 | c | rides open upstream PR #124210 |
| `tools/process_registry.py` | 4 | 6 | c | rides open upstream PR #125261 |
| `tools/process_registry_notifications.py` | 29 | 1 | e | G6 sanitiser (29) movable to a fork module, one call line |
| `tools/registry.py` | 194 | 36 | c | rides open upstream PR #123979 |
| `tools/skills_hub_official.py` | 1 | 1 | c | rides open upstream PR #121643 |
| `tools/skills_tool.py` | 53 | 68 | c | rides open upstream PR #124191 |
| `tools/terminal_tool.py` | 86 | 0 | e | typed block envelope (86); S2 DESIGN: a safety envelope must not be bypassable - body movable, the call site stays |
| `tools/terminal_tool_result.py` | 2 | 1 | c | rides open upstream PR #125262 |
| `tools/tirith_security.py` | 61 | 11 | c | rides open upstream PR #121646 |
| `tools/tool_search.py` | 117 | 16 | e | recorded parallel (117/16) |
| `tools/tts_tool.py` | 5 | 4 | c | rides open upstream PR #125262, #125259 |
| `tools/tts_tool_delivery.py` | 3 | 2 | c | rides open upstream PR #125262 |
| `tools/vision_tools.py` | 5 | 5 | c | rides open upstream PR #125259 |
| `toolsets.py` | 25 | 2 | c | rides open upstream PR #123979 |
| `tui_gateway/contracts/prompt_voice.py` | 1 | 0 | d | `reject_if_busy` contract field; no plugin gateway-method seam |
| `tui_gateway/host_supervisor.py` | 5 | 1 | d | recorded Windows console carry 2026-09-27 |
| `tui_gateway/hosted_room_driver.py` | 15 | 2 | d | Group Chat host-surface widening, 15 lines |
| `tui_gateway/methods_prompt.py` | 2 | 0 | d | `reject_if_busy` branch in the busy path |
| `tui_gateway/server.py` | 2 | 1 | d | `skill_view` in a module frozenset; the docstring half is upstream rot the gate scopes out - revert that line |

## Outcome (lane tip)

**151 / 834 / 4 -> 117 / 766 / 3.** Each move's red is in its commit message.

- **a** (14): all executed. Linux marks by id (5); doc pointers + an unused import (6, plus
  the `tui_gateway/server.py` docstring line); `test_hermes_constants` was already gated by
  upstream's own `platforms("linux")` (pure revert); the bypass self-test is a win32 skip by
  id plus a sibling; the CRLF contributor file carries upstream's bytes under a `-text` keeper.
- **a/step3** (19): the tree differed from the sort. 16 were Windows respellings of tests
  upstream itself now marks `platforms("linux"/"posix")` — identical skip set before and
  after, pure reverts. 2 (`test_skill_utils`, `test_skills_hub`) moved to `*_downstream.py`
  siblings with win32 strict xfails. `test_local_runtime`'s stub fix became a
  `timeout(90)` mark by id (upstream's test passes in 30.2 s). Siblings follow the tree's
  `tests/<area>/*_downstream.py` convention, not `tests/_downstream/` (plumbing only).
- **b**: none (see above).
- **e** executed (12): `subcommands/auth.py`, `plugins/memory/__init__.py`,
  `process_registry_notifications.py`, `plugins_manifest.py`, `live_system_guard.py`,
  `model_tools.py`, `agent/pet/generate/atlas.py` (fork-only half), `provider_catalog.py`
  (full revert), `gateway_windows.py`, `gateway.py`, `update_cmd_windows.py`,
  `tool_search.py`, `terminal_tool.py`.
- **e not executed** (3), now (d): `gateway/hosted_room_discussion.py`,
  `gateway/hosted_rooms.py` — the bodies call six-plus upstream privates (`_transaction`,
  `_room_row`, `_require_authority`, ...), so a move needs a door per private for a seam
  that is a single widening PR; `hermes_cli/main.py` — its own staged plan (seam 0.3,
  S1 + P1), not lane-sized.
