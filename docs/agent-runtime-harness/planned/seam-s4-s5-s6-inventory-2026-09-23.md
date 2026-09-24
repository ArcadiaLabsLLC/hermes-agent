# Planned — seam inventory for Stages 4, 5 and 6 (2026-09-23, read-only)

Inventory for [`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md) §2 Stages 4, 5, 6. Nothing was moved and no production code was touched. Base for every diff: the merge base `d337b736aa` (`seam/s4-s5-inventory` @ `bcf8012e6a`, `upstream/main` @ `5f47c35d37`). "Upstream file" = a path in `git ls-tree -r --name-only upstream/main`. Instruments: `git diff -U0 --no-renames d337b736aa HEAD` per file; Python `ast` over `git show <rev>:<path>` for the conftests and the two Stage 4 files; `git grep -l -F <basename> -- tests scripts` for the source-pin census (refactor plan §1 rule 6).

## Summary

1. **Stage 5 is a third of the size the plan assumes.** 252 upstream test files carry a fork diff; only **75** contain fork-added test functions (**317** `def test_`, 25 fork-added fixtures). The plan's "242 other files with fork test cases → `[up-fp] files` −242" does not hold.
2. **177 of the 252 are in-place edits to upstream tests** (portability, hermeticity, timing, fork-production drift), not fork tests. A MOVE lane cannot retire them. They need a disposition pass (upstream as a batched portability PR, or carry). The listing below is a sorting aid, not the disposition.
3. **Of the 75, 47 also replace upstream lines**, so they stay in the footprint after their tests move out. The most a MOVE-only Stage 5 can remove from `[up-fp] files` is **28**. Plus the four conftests shrink to one line each; that lowers lines, not files.
4. **26 of the 75 files are named by a string in `tests/` or `scripts/`**, mostly the env-gap registries' node ids. Moving a test into `test_<name>_downstream.py` changes those node ids, so each one has to be retargeted in the MOVE commit.
5. **"One `pytest_plugins` line per upstream conftest" does not work for three of the four.** pytest 9.0.3 `PytestPluginManager._check_non_top_pytest_plugins` fails any non-root conftest that defines `pytest_plugins` once the config is configured, and `pytest tests` configures the config before it loads a subdirectory conftest. Only `tests/conftest.py` can carry `pytest_plugins`. The three subdirectory conftests need a one-line star import instead, and it keeps their autouse fixtures scoped to their own directory. One plugin module is also not enough: three conftests define the same hook and private names, so the downstream side is four modules.
6. **Stage 4, `hermes_constants.py`:** 21 names changed (15 functions, 6 constants). Upstream already covers 4: the fork replaced upstream's `_default_hermes_root_memo` with its own `_DEFAULT_HERMES_ROOT_CACHE` and left upstream's global dead. 3 are generic: the `agent_browser_runnable` probe memo. 14 are ours, but only 4 upstream files call any of them. **The profile-aware `get_hermes_home` / `display_hermes_home` work that §0.4 describes is all upstream already.**
7. **Stage 4, `hermes_cli/profiles.py`:** 14 names changed. Upstream covers 1: `available_profile_templates` ≈ `list_profile_names()`. 10 are generic: delete refuses when no process inspector exists, plus the process-table seam. That is PR P6. 3 are ours: the Mission Control roster summaries and the orphan-marking side effect, which is a hook candidate.
8. **The `test_no_frozen_hermes_home.py` ledger holds no entry for either file.** Both files resolve at call time. Two entries in other files consume their values: `gateway/platforms/base.py` `_HERMES_ROOT` and `tools/process_registry.py` `CHECKPOINT_PATH`. Relocating or deleting the Stage 4 names moves no ledger entry.
9. **Stage 6 is 2 files, not 32.** Since the merge, the fork edits only `apps/desktop/src/app/settings/uninstall-section.tsx` (+6) and the generated `apps/desktop/src/lib/desktop-slash-registry.json` (+2). The desktop plugin SDK can host neither: 0 yes, 0 partly, 2 no. The first should go upstream; the second is generated from `hermes_cli/commands.py` and retires with that row.
10. **Order this implies:** Stage 4 becomes "delete 4, PR 13, relocate 17 into a fork module" rather than a function-level carry. Stage 5 splits into a MOVE lane (75 files) and a disposition lane (177 files). Stage 6 is one upstream PR.

---

## 1. Stage 5 — fork tests in upstream test files

### 1.1 Per top-level `tests/` directory

"Additive-only" = the fork diff deletes no upstream line. "Fork test fns" = `def test_` on an added line whose name is not on a removed line. Another 21 test `def` lines were edited in place, so their signatures were changed. Those count as replacements, not fork tests. "Fork fixtures" = an `@pytest.fixture` decorator on an added line.

| top-level dir | files edited | with fork tests | fork test fns | fork fixtures | additive-only | replace upstream lines | in-place only (no fork test) | +lines | −lines |
|---|---|---|---|---|---|---|---|---|---|
| `tests/hermes_cli` | 97 | 28 | 84 | 12 | 29 | 68 | 69 | 4909 | 1004 |
| `tests/tools` | 69 | 18 | 81 | 5 | 12 | 57 | 51 | 2924 | 256 |
| `tests/agent` | 33 | 14 | 84 | 3 | 11 | 22 | 19 | 2184 | 119 |
| `tests/gateway` | 24 | 5 | 25 | 0 | 6 | 18 | 19 | 1022 | 91 |
| `tests/scripts` | 8 | 2 | 14 | 0 | 2 | 6 | 6 | 411 | 12 |
| `tests (root)` | 4 | 3 | 19 | 5 | 0 | 4 | 1 | 877 | 22 |
| `tests/plugins` | 4 | 1 | 1 | 0 | 0 | 4 | 3 | 83 | 31 |
| `tests/hermes_state` | 3 | 0 | 0 | 0 | 0 | 3 | 3 | 19 | 22 |
| `tests/e2e` | 3 | 1 | 2 | 0 | 2 | 1 | 2 | 54 | 2 |
| `tests/tui_gateway` | 3 | 3 | 7 | 0 | 2 | 1 | 0 | 227 | 13 |
| `tests/cron` | 2 | 0 | 0 | 0 | 0 | 2 | 2 | 38 | 26 |
| `tests/docker` | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 3 | 1 |
| `tests/providers` | 1 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 1 |
| **total** | **252** | **75** | **317** | **25** | **64** | **188** | **177** | **12752** | **1600** |

The table includes two upstream files the fork **deleted** (`tests/hermes_cli/test_cross_profile_kill_refusal.py`, `tests/hermes_cli/test_stderr_timestamp.py`; −480 upstream lines, and upstream still ships both). It also includes one **path collision**: `tests/hermes_cli/test_gpt6_tiers_registration.py` is absent from the merge base, and both the fork and upstream added it afterwards.

### 1.2 The 75 files with fork test functions (the MOVE list)

"Source pins" = other files under `tests/` or `scripts/` that name this file's basename as a string (refactor rule 1.6). The first three are shown.

| file | fork test fns | fork fixtures | +/− | shape | source pins (tests/, scripts/) |
|---|---|---|---|---|---|
| `tests/test_hermes_constants.py` | 7 | 0 | +214/−1 | replaces | 1 — `scripts/ci/check_os_marker_fakes.py` |
| `tests/test_live_system_guard.py` | 1 | 0 | +14/−11 | replaces | 0 |
| `tests/test_live_system_guard_self_test.py` | 11 | 0 | +80/−1 | replaces | 0 |
| `tests/agent/test_bedrock_integration.py` | 1 | 0 | +18/−0 | additive | 0 |
| `tests/agent/test_compression_feasibility.py` | 1 | 0 | +21/−1 | replaces | 0 |
| `tests/agent/test_credential_pool.py` | 1 | 0 | +47/−0 | additive | 1 — `tests/test_claude_code_credentials_file_gate.py` |
| `tests/agent/test_external_skills.py` | 3 | 0 | +40/−2 | replaces | 2 — `tests/conftest.py`, `tests/test_hermetic_env_blanking.py` |
| `tests/agent/test_pet_generate.py` | 15 | 0 | +346/−0 | additive | 1 — `tests/agent/test_charsheet_pipeline.py` |
| `tests/agent/test_prompt_builder.py` | 9 | 0 | +118/−5 | replaces | 0 |
| `tests/agent/test_shell_hooks.py` | 5 | 0 | +89/−31 | replaces | 1 — `tests/agent/conftest.py` |
| `tests/agent/test_skill_utils.py` | 19 | 0 | +546/−4 | replaces | 0 |
| `tests/agent/test_skills_auto_load.py` | 1 | 0 | +17/−0 | additive | 0 |
| `tests/agent/test_subagent_progress.py` | 6 | 0 | +119/−0 | additive | 0 |
| `tests/agent/test_system_prompt.py` | 6 | 0 | +86/−4 | replaces | 0 |
| `tests/agent/test_turn_finalizer_final_response_persistence.py` | 2 | 0 | +56/−0 | additive | 0 |
| `tests/agent/test_usage_pricing.py` | 2 | 0 | +55/−5 | replaces | 0 |
| `tests/agent/transports/test_codex_transport.py` | 13 | 0 | +282/−0 | additive | 0 |
| `tests/e2e/test_platform_commands.py` | 2 | 0 | +51/−0 | additive | 0 |
| `tests/gateway/relay/test_contract_doc_conformance.py` | 4 | 0 | +192/−20 | replaces | 0 |
| `tests/gateway/test_background_process_notifications.py` | 10 | 0 | +196/−5 | replaces | 0 |
| `tests/gateway/test_feishu.py` | 1 | 0 | +50/−6 | replaces | 1 — `tests/gateway/conftest.py` |
| `tests/gateway/test_hosted_rooms.py` | 5 | 0 | +176/−0 | additive | 0 |
| `tests/gateway/test_platform_base.py` | 5 | 0 | +45/−1 | replaces | 3 — `tests/gateway/conftest.py`, `tests/gateway/test_tts_media_routing.py`, `tests/tools/test_send_message_tool.py` |
| `tests/hermes_cli/test_apply_profile_override.py` | 4 | 0 | +124/−2 | replaces | 1 — `tests/hermes_cli/conftest.py` |
| `tests/hermes_cli/test_bytecode_sweep.py` | 3 | `_clean_sweep_anchor` | +97/−1 | replaces | 0 |
| `tests/hermes_cli/test_codex_models.py` | 2 | 0 | +54/−27 | replaces | 0 |
| `tests/hermes_cli/test_commands.py` | 5 | 0 | +153/−0 | additive | 1 — `tests/hermes_cli/conftest.py` |
| `tests/hermes_cli/test_config.py` | 1 | 0 | +21/−3 | replaces | 0 |
| `tests/hermes_cli/test_config_read_guard.py` | 1 | 0 | +102/−21 | replaces | 0 |
| `tests/hermes_cli/test_curses_ui_search.py` | 1 | 0 | +6/−0 | additive | 0 |
| `tests/hermes_cli/test_dashboard_tui_backcompat.py` | 3 | 0 | +108/−31 | replaces | 0 |
| `tests/hermes_cli/test_dashboard_unified_launch.py` | 2 | 0 | +85/−11 | replaces | 0 |
| `tests/hermes_cli/test_dep_ensure.py` | 4 | 0 | +53/−0 | additive | 0 |
| `tests/hermes_cli/test_doctor.py` | 2 | 0 | +213/−49 | replaces | 3 — `scripts/ci/check_os_marker_fakes.py`, `tests/hermes_cli/_module_identity.py`, `tests/mutation_claims.json` |
| `tests/hermes_cli/test_gateway.py` | 4 | 0 | +116/−0 | additive | 3 — `scripts/ci/check_os_marker_fakes.py`, `tests/_fork_scope.py`, `tests/conftest.py` |
| `tests/hermes_cli/test_gateway_windows.py` | 1 | 0 | +18/−97 | replaces | 0 |
| `tests/hermes_cli/test_gpt6_tiers_registration.py` | 3 | 0 | +60/−0 | additive | 0 |
| `tests/hermes_cli/test_gui_command.py` | 3 | `_no_live_process_iter` | +136/−2 | replaces | 1 — `tests/hermes_cli/conftest.py` |
| `tests/hermes_cli/test_kanban_db.py` | 4 | 0 | +275/−2 | replaces | 5 — `tests/hermes_cli/conftest.py`, `tests/hermes_cli/test_kanban_blocked_sticky.py`, `tests/hermes_cli/test_kanban_core_functionality.py` |
| `tests/hermes_cli/test_managed_uv.py` | 1 | 0 | +50/−1 | replaces | 0 |
| `tests/hermes_cli/test_mcp_config.py` | 7 | 0 | +134/−0 | additive | 0 |
| `tests/hermes_cli/test_pending_supervisor_recovery.py` | 1 | 0 | +13/−0 | additive | 0 |
| `tests/hermes_cli/test_pip_install_detection.py` | 1 | 0 | +11/−0 | additive | 0 |
| `tests/hermes_cli/test_plugins.py` | 1 | 0 | +47/−6 | replaces | 2 — `tests/agent/test_verify_hooks.py`, `tests/agent_runtime/test_no_midtest_monkeypatch_undo.py` |
| `tests/hermes_cli/test_profiles.py` | 14 | 0 | +475/−1 | replaces | 6 — `tests/gateway/test_replace_ownership_guard.py`, `tests/hermes_cli/conftest.py`, `tests/hermes_cli/test_agent_import.py` |
| `tests/hermes_cli/test_restart_plan_reconciliation.py` | 1 | 0 | +25/−0 | additive | 0 |
| `tests/hermes_cli/test_slack_cli.py` | 2 | 0 | +36/−1 | replaces | 0 |
| `tests/hermes_cli/test_subcommands_batch.py` | 1 | 0 | +16/−1 | replaces | 0 |
| `tests/hermes_cli/test_update_gateway_launcher_refresh.py` | 9 | 0 | +116/−0 | additive | 0 |
| `tests/hermes_cli/test_web_ui_build.py` | 2 | 0 | +62/−2 | replaces | 3 — `scripts/run_tests.sh`, `tests/hermes_cli/conftest.py`, `tests/hermes_cli/test_run_with_idle_timeout.py` |
| `tests/hermes_cli/test_worktree_selfheal.py` | 1 | 0 | +92/−5 | replaces | 0 |
| `tests/plugins/dashboard_auth/test_nous_provider.py` | 1 | 0 | +30/−5 | replaces | 1 — `tests/plugins/dashboard_auth/test_self_hosted_provider.py` |
| `tests/scripts/test_contributor_map.py` | 1 | 0 | +20/−1 | replaces | 0 |
| `tests/scripts/test_run_tests_parallel.py` | 13 | 0 | +379/−7 | replaces | 1 — `tests/mutation_claims.json` |
| `tests/tools/test_approval.py` | 6 | 0 | +244/−12 | replaces | 0 |
| `tests/tools/test_browser_content_none_guard.py` | 1 | 0 | +65/−13 | replaces | 0 |
| `tests/tools/test_browser_orphan_reaper.py` | 3 | 0 | +61/−0 | additive | 0 |
| `tests/tools/test_code_execution.py` | 9 | 0 | +121/−10 | replaces | 3 — `scripts/run_tests_parallel.py`, `tests/tools/test_code_execution_modes.py`, `tests/tools/test_code_kernel.py` |
| `tests/tools/test_code_execution_modes.py` | 2 | 0 | +20/−10 | replaces | 0 |
| `tests/tools/test_execute_code_approval_cluster.py` | 1 | 0 | +84/−10 | replaces | 1 — `tests/tools/test_denial_circuit_breaker.py` |
| `tests/tools/test_file_operations.py` | 2 | 0 | +65/−15 | replaces | 1 — `tests/tools/conftest.py` |
| `tests/tools/test_file_staleness.py` | 4 | 0 | +8/−5 | replaces | 0 |
| `tests/tools/test_file_tools.py` | 2 | 0 | +93/−2 | replaces | 1 — `tests/upstream_source_assertions.json` |
| `tests/tools/test_local_env_windows_msys.py` | 5 | 0 | +60/−3 | replaces | 1 — `tests/hermes_cli/test_in_dir_msys_paths.py` |
| `tests/tools/test_oneshot_completion_linger.py` | 1 | 0 | +30/−0 | additive | 0 |
| `tests/tools/test_session_search.py` | 2 | 0 | +31/−0 | additive | 0 |
| `tests/tools/test_skills_tool.py` | 9 | 0 | +172/−0 | additive | 2 — `scripts/ci/check_os_marker_fakes.py`, `tests/tools/test_toolsets.py` |
| `tests/tools/test_terminal_tool_requirements.py` | 4 | 0 | +155/−0 | additive | 0 |
| `tests/tools/test_tirith_security.py` | 3 | `supported_platform` | +121/−2 | replaces | 1 — `tests/tools/conftest.py` |
| `tests/tools/test_tool_search.py` | 15 | 0 | +290/−0 | additive | 0 |
| `tests/tools/test_tool_search_multiquery.py` | 1 | 0 | +7/−2 | replaces | 0 |
| `tests/tools/test_toolsets.py` | 11 | 0 | +134/−0 | additive | 0 |
| `tests/tui_gateway/test_hosted_room_driver_runtime.py` | 2 | 0 | +114/−0 | additive | 0 |
| `tests/tui_gateway/test_kanban_notify_poller.py` | 1 | 0 | +16/−0 | additive | 0 |
| `tests/tui_gateway/test_tui_gateway_server.py` | 4 | 0 | +97/−13 | replaces | 4 — `tests/agent/test_notice_spine.py`, `tests/conftest.py`, `tests/hermes_cli/test_audio_playback_guard.py` |

### 1.3 The 177 files with in-place edits only (not movable; a disposition pass)

The labels come from a keyword heuristic over the diff lines, so treat them as a sorting aid rather than a disposition. The four conftests appear here because they have no fork `def test_`. §1.4 covers them.

- **other (isolation, doc-path fixes, fork-production drift)** (55): `agent/test_canon_args_memo_parity.py`, `agent/test_compression_adoption_preserves_live_tail.py`, `agent/test_nous_oauth_401_guidance.py`, `agent/test_provider_fallback.py`, `agent/test_save_url_image.py`, `cron/test_cron_memory_contract.py`, `e2e/conftest.py`, `e2e/matrix_xsign_bootstrap/test_bootstrap.py`, `gateway/test_api_server_active_work_drain.py`, `gateway/test_completion_session_boundary.py`, `gateway/test_compression_deferred_soft_result.py`, `gateway/test_config_env_bridge_authority.py`, `gateway/test_matrix.py`, `gateway/test_matrix_approval_reaction_fail_closed.py`, `gateway/test_post_stream_media_delivery.py`, `hermes_cli/test_auth_ssl_macos.py`, `hermes_cli/test_curator_recent_run_notice.py`, `hermes_cli/test_dashboard_auth_gate.py`, `hermes_cli/test_early_recovery.py`, `hermes_cli/test_gateway_migrate_multiplex.py`, `hermes_cli/test_kanban_boards.py`, `hermes_cli/test_kanban_per_profile_cap.py`, `hermes_cli/test_kanban_review_lifecycle.py`, `hermes_cli/test_kanban_worktree_teardown.py`, `hermes_cli/test_linux_desktop_entry.py`, `hermes_cli/test_macos_tcc_anchor.py`, `hermes_cli/test_node_runtime_npm_resolution.py`, `hermes_cli/test_nous_inference_url_validation.py`, `hermes_cli/test_orphan_desktop_serve_reap.py`, `hermes_cli/test_profile_delete_log_handlers.py`, `hermes_cli/test_setup_blank_slate.py`, `hermes_cli/test_setup_matrix_e2ee.py`, `hermes_cli/test_subprocess_timeouts.py`, `hermes_cli/test_update_serve_generation_recovery.py`, `hermes_cli/test_update_zip_two_phase.py`, `hermes_cli/test_voice_wrapper.py`, `hermes_cli/test_worktree_sync_base.py`, `hermes_state/test_append_messages_batch.py`, `hermes_state/test_retired_wal_generation_capture.py`, `hermes_state/test_session_db_read_conn_pool.py`, `plugins/platforms/photon/test_sidecar_paths.py`, `providers/test_entry_point_discovery.py`, `tools/test_browser_console.py`, `tools/test_checkpoint_manager.py`, `tools/test_completed_process_results.py`, `tools/test_delegate.py`, `tools/test_execute_helper_contract.py`, `tools/test_interrupt.py`, `tools/test_llm_content_none_guard.py`, `tools/test_skills_sync.py`, `tools/test_stage2_hook_symlink_chown.py`, `tools/test_startup_latency_regressions.py`, `tools/test_vision_native_fast_path.py`, `tools/test_vision_tools.py`, `tools/test_watch_patterns.py`
- **portability (Windows / encoding / shell) + hermeticity (home / env / tmp)** (33): `agent/lsp/test_workspace.py`, `agent/test_coding_context.py`, `agent/test_file_safety_sandbox_mirror.py`, `agent/test_proxy_and_url_validation.py`, `conftest.py`, `gateway/conftest.py`, `gateway/test_media_spaced_paths_and_history_dedupe.py`, `gateway/test_runtime_footer.py`, `gateway/test_status_command.py`, `hermes_cli/test_debug.py`, `hermes_cli/test_doctor_journal_modes.py`, `hermes_cli/test_kanban_worker_pid_fingerprint.py`, `hermes_cli/test_projects_db.py`, `hermes_cli/test_win_pty_bridge.py`, `hermes_cli/test_xai_provider_labels.py`, `plugins/dashboard_auth/test_self_hosted_provider.py`, `tools/test_browser_homebrew_paths.py`, `tools/test_computer_use.py`, `tools/test_file_ops_cwd_tracking.py`, `tools/test_file_tools_cwd_resolution.py`, `tools/test_file_tools_live.py`, `tools/test_file_tools_tilde_profile.py`, `tools/test_find_shell.py`, `tools/test_local_env_blocklist.py`, `tools/test_local_env_relative_cwd.py`, `tools/test_local_shell_init.py`, `tools/test_local_tempdir.py`, `tools/test_mcp_tool.py`, `tools/test_modal_sandbox_fixes.py`, `tools/test_skills_hub.py`, `tools/test_subprocess_home_isolation.py`, `tools/test_voice_mode.py`, `tools/test_working_diff.py`
- **portability (Windows / encoding / shell)** (32): `agent/test_curator_classification.py`, `agent/test_skill_commands.py`, `gateway/test_media_resend_dedup.py`, `gateway/test_session_state_cleanup.py`, `gateway/test_update_command.py`, `hermes_cli/test_auth_nous_provider.py`, `hermes_cli/test_backup.py`, `hermes_cli/test_cmd_update.py`, `hermes_cli/test_codex_runtime_plugin_migration.py`, `hermes_cli/test_completion.py`, `hermes_cli/test_deleted_profile_tombstone.py`, `hermes_cli/test_diff_command.py`, `hermes_cli/test_kanban_core_functionality.py`, `hermes_cli/test_lazy_command_exports.py`, `hermes_cli/test_prompt_compose_command.py`, `hermes_cli/test_relaunch.py`, `hermes_cli/test_setup_hermes_script.py`, `hermes_cli/test_tui_resume_flow.py`, `hermes_cli/test_update_autostash.py`, `hermes_cli/test_update_concurrent_quarantine.py`, `hermes_cli/test_update_stale_dashboard.py`, `tools/test_async_delegation.py`, `tools/test_base_environment.py`, `tools/test_docker_config_migrate.py`, `tools/test_local_background_child_hang.py`, `tools/test_local_env_cwd_recovery.py`, `tools/test_memory_tool.py`, `tools/test_process_registry.py`, `tools/test_skills_guard.py`, `tools/test_subprocess_stdin_guard.py`, `tools/test_terminal_output_transform_hook.py`, `tools/test_voice_wsl_pipewire.py`
- **hermeticity (home / env / tmp)** (31): `agent/test_anthropic_adapter.py`, `agent/test_anthropic_borrowed_row_authority.py`, `agent/test_anthropic_credential_persist_failure.py`, `agent/test_anthropic_keychain.py`, `agent/test_anthropic_spent_rotation_verdict.py`, `agent/test_image_routing.py`, `agent/test_shell_hooks_consent.py`, `cron/test_cron_profile_isolation.py`, `docker/test_dashboard.py`, `gateway/test_internal_event_bypass_pairing.py`, `gateway/test_mirror.py`, `hermes_cli/test_codex_cli_model_picker.py`, `hermes_cli/test_doctor_command_install.py`, `hermes_cli/test_doctor_live.py`, `hermes_cli/test_env_export_prefix.py`, `hermes_cli/test_fireworks_provider.py`, `hermes_cli/test_gmi_provider.py`, `hermes_cli/test_kanban_cli_dispatch_passthrough.py`, `hermes_cli/test_kanban_default_assignee.py`, `hermes_cli/test_local_quickstart.py`, `hermes_cli/test_noninteractive_git.py`, `hermes_cli/test_process_notification_display.py`, `hermes_cli/test_resolve_provider_openrouter_pool.py`, `hermes_cli/test_skin_cmd.py`, `hermes_cli/test_subagent_notification_display.py`, `plugins/memory/test_holographic_store.py`, `tools/test_cron_approval_mode.py`, `tools/test_image_generation.py`, `tools/test_notify_on_complete.py`, `tools/test_stage2_hook_api_server_keygen.py`, `tools/test_terminal_tool.py`
- **timing (timeouts / waits)** (9): `gateway/test_cron_interrupt_notification.py`, `gateway/test_platform_reconnect.py`, `hermes_cli/test_local_runtime.py`, `hermes_cli/test_mcp_startup.py`, `hermes_cli/test_relay_shared_metrics.py`, `hermes_cli/test_update_fleet_restart_pending.py`, `scripts/desktop_update/test_desktop_update_windows_pipe_drain.py`, `scripts/desktop_update/test_desktop_update_windows_retry_policy.py`, `scripts/install/test_install_ps1_managed_python_provenance.py`
- **portability (Windows / encoding / shell) + timing (timeouts / waits)** (9): `hermes_cli/test_gateway_job_teardown_live.py`, `hermes_cli/test_gateway_service.py`, `hermes_cli/test_kanban_reclaim_claim_lock_guard.py`, `scripts/desktop_update/test_desktop_update_windows_cwd.py`, `scripts/desktop_update/test_desktop_update_windows_progress.py`, `scripts/desktop_update/test_desktop_update_windows_ui_delivery.py`, `tools/test_approved_command_clean_slate.py`, `tools/test_local_interrupt_cleanup.py`, `tools/test_zombie_process_cleanup.py`
- **portability (Windows / encoding / shell) + hermeticity (home / env / tmp) + timing (timeouts / waits)** (5): `agent/conftest.py`, `hermes_cli/conftest.py`, `hermes_cli/test_active_sessions.py`, `tools/conftest.py`, `tools/test_execution_flag_detection.py`
- **deleted by the fork (upstream still ships it)** (2): `hermes_cli/test_cross_profile_kill_refusal.py`, `hermes_cli/test_stderr_timestamp.py`
- **hermeticity (home / env / tmp) + timing (timeouts / waits)** (1): `gateway/test_completion_delivery.py`

### 1.4 The four conftests: fork fixtures and hooks

`fork status` compares against the merge base: `added` means the name is absent there, and `modified` means an upstream name has a different body. Constants and helpers are listed below the table.

| conftest | name | kind | autouse | fork status | test files that name it (word match, conftest's own dir) |
|---|---|---|---|---|---|
| `tests/conftest.py` | `_shared_monkeypatch_pin_tripwire` | fixture | yes | added | `tests/agent_runtime/conftest.py`, `tests/agent_runtime/test_no_midtest_monkeypatch_undo.py`, `tests/hermes_cli/test_gateway_spawn_fence.py`, `tests/test_conftest_pin_tripwire.py` |
| `tests/conftest.py` | `_reset_snapshot_catalog_memos` | fixture | yes | added | — (autouse only) |
| `tests/conftest.py` | `_isolate_hermes_shim_dir` | fixture | yes | added | `tests/hermes_cli/test_path_setup.py`, `tests/hermes_cli/test_postinstall_noninteractive.py` |
| `tests/conftest.py` | `_neutralize_claude_code_credentials_file` | fixture | yes | added | `tests/agent/test_credential_pool_rotation_cursor.py`, `tests/test_claude_code_credentials_file_gate.py` |
| `tests/conftest.py` | `tmp_path` | fixture | no | added | every `tmp_path` user — it overrides the builtin (2,698 files) |
| `tests/conftest.py` | `pytest_configure` | hook | no | modified | — (hook) |
| `tests/conftest.py` | `_live_system_guard` | fixture | yes | modified | `tests/agent_runtime/test_no_midtest_monkeypatch_undo.py`, `tests/hermes_cli/_gateway_fence.py`, `tests/hermes_cli/test_gateway_spawn_fence.py`, `tests/test_live_system_guard_self_test.py` |
| `tests/hermes_cli/conftest.py` | `_gateway_fence_is_armed_for_this_test` | fixture | yes | added | — (autouse only) |
| `tests/hermes_cli/conftest.py` | `_agent_browser_probe_never_spawns` | fixture | yes | added | — (autouse only) |
| `tests/hermes_cli/conftest.py` | `_web_server_app_is_pristine` | fixture | yes | added | — (autouse only) |
| `tests/hermes_cli/conftest.py` | `_pairing_dir_follows_the_test_home` | fixture | yes | added | — (autouse only) |
| `tests/hermes_cli/conftest.py` | `_sys_modules_identity_is_restored` | fixture | yes | added | — (autouse only) |
| `tests/hermes_cli/conftest.py` | `_no_windows_gateway_pause_token` | fixture | yes | added | `tests/hermes_cli/_gateway_fence.py`, `tests/hermes_cli/test_gateway_spawn_fence.py` |
| `tests/hermes_cli/conftest.py` | `_no_live_process_table` | fixture | yes | added | — (autouse only) |
| `tests/hermes_cli/conftest.py` | `pytest_configure` | hook | no | added | — (hook) |
| `tests/hermes_cli/conftest.py` | `pytest_collection_modifyitems` | hook | no | added | — (hook) |
| `tests/hermes_cli/conftest.py` | `pytest_runtest_logreport` | hook | no | added | — (hook) |
| `tests/hermes_cli/conftest.py` | `pytest_sessionfinish` | hook | no | added | — (hook) |
| `tests/hermes_cli/conftest.py` | `pytest_terminal_summary` | hook | no | added | — (hook) |
| `tests/tools/conftest.py` | `pytest_configure` | hook | no | added | — (hook) |
| `tests/tools/conftest.py` | `pytest_collection_modifyitems` | hook | no | added | — (hook) |
| `tests/tools/conftest.py` | `pytest_runtest_logreport` | hook | no | added | — (hook) |
| `tests/tools/conftest.py` | `pytest_terminal_summary` | hook | no | added | — (hook) |
| `tests/agent/conftest.py` | `pytest_configure` | hook | no | added | — (hook) |
| `tests/agent/conftest.py` | `pytest_collection_modifyitems` | hook | no | added | — (hook) |
| `tests/agent/conftest.py` | `pytest_runtest_logreport` | hook | no | added | — (hook) |
| `tests/agent/conftest.py` | `pytest_terminal_summary` | hook | no | added | — (hook) |

- `tests/conftest.py` — support names that move with them (9 added): `_maybe_redirect_test_tmp`, `_TEST_TMP_RUN_DIR`, `_CREDENTIAL_SUFFIX_RE`, `_SharedMonkeypatchWitness`, `_SHARED_MONKEYPATCH_WITNESS`, `SHARED_MONKEYPATCH_UNWOUND_MESSAGE`, `_TMP_COUNTER`, `_TMP_NAME_RE`, `_ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK`; **modified upstream names** (cannot move — carry or upstream): `_looks_like_credential`, `_HERMES_BEHAVIORAL_VARS`
- `tests/hermes_cli/conftest.py` — support names that move with them (32 added): `_OWNER_DIR`, `_OWNER_NODEID_PREFIX`, `_AGENT_BROWSER_PROBE_BINDINGS`, `_APP_BASELINE`, `_EmptyProcessTable`, `_WINDOWS`, `_HOST`, `_WEB_BUILD_PREREQ_FILES`, `_VITE8_NODE_FLOOR`, `_node_version`, `_web_build_prereq_failure`, `_WEB_BUILD_PREREQ_REASON`, `_LOCAL_MODEL_PROBE_NODE_IDS`, `_local_model_probe_failure`, `_LOCAL_MODEL_PROBE_REASON`, `_ENV_GAPS`, `_POSIX_MODE_BITS_PROBE`, `_GIT_EOL_PROBE`, `_no_module`, `_no_posix_mode_bits`, `_no_os_chown`, `_no_posix_wait_status`, `_no_posix_privilege_api`, `_posix_only_branch`, `_git_name_only_ignores_cr_at_eol`, `_SHEBANG_EXEC_PROBE`, `_no_shebang_script_execution`, `_ENV_GAP_SKIPS`, `_STALE_ENV_GAP_ENTRIES`, `TELEGRAM_PARITY_DEFECT_REASON`, `_KNOWN_DEFECTS`, `_KNOWN_DEFECT_FAILURES`
- `tests/tools/conftest.py` — support names that move with them (13 added): `_cached`, `_no_posix_file_modes`, `_no_posix_exec_bit`, `_no_unwritable_dir_via_chmod`, `_no_shebang_exec`, `_no_af_unix`, `_no_process_groups`, `_ENV_GAPS`, `_ENV_GAP_SKIPS`, `_OWNER_DIR`, `_STALE`, `_KNOWN_DEFECTS`, `_KNOWN_DEFECT_FAILURES`
- `tests/agent/conftest.py` — support names that move with them (7 added): `_SLOW_LOOPBACK_TIMEOUT_SECONDS`, `_SLOW_LOOPBACK_TIMEOUT_NODE_IDS`, `_ENV_GAPS`, `_shell_hook_scripts_are_not_directly_executable`, `_ENV_GAP_SKIPS`, `_OWNER_DIR`, `_STALE`


What the modified upstream names are, and what that means for moving them:

- `tests/conftest.py::pytest_configure`: the fork adds registration lines for the `_ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK` marker. **Movable**: the plugin's own `pytest_configure` registers it, and both hooks run.
- `tests/conftest.py::_live_system_guard`: a performance rewrite that snapshots children lazily at the first guarded kill instead of walking the process table at every test's setup. **Generic**: a runner PR, alongside P5.
- `tests/conftest.py::_looks_like_credential` / `_CREDENTIAL_SUFFIX_RE`: suffix tuple → regex. **Generic**.
- `tests/conftest.py::_HERMES_BEHAVIORAL_VARS`: the fork adds its own env vars (`HERMES_HEAD_HOME`, the detached-service marker, …) to upstream's scrub tuple. **Movable as behaviour**: a plugin autouse fixture can `delenv` the fork's names, and the tuple goes back to upstream's. Its comment cites `hermes_constants.py` by line number, and that number is already stale.

### 1.5 The downstream side: skeleton (names only) and the one line per conftest

Four modules, not one. Merging them into one module would collide on four hook names (`pytest_configure`, `pytest_collection_modifyitems`, `pytest_runtest_logreport`, `pytest_terminal_summary`) and on the private names `_ENV_GAPS`, `_ENV_GAP_SKIPS`, `_OWNER_DIR`, `_STALE`, `_KNOWN_DEFECTS`, `_KNOWN_DEFECT_FAILURES`. Each of those carries a different value per directory. `_OWNER_DIR` is `Path(__file__).parent` today, so after the move it must name the owning test directory explicitly. The existing `tests/_env_gap_fence.py` (fork-only) stays the shared engine the three per-directory modules call.

```python
# tests/_downstream/conftest_plugin.py  — root; loaded by pytest_plugins
_TEST_TMP_RUN_DIR; _TMP_COUNTER; _TMP_NAME_RE; _CREDENTIAL_SUFFIX_RE
_ALLOW_CLAUDE_CODE_CREDENTIALS_FILE_MARK; SHARED_MONKEYPATCH_UNWOUND_MESSAGE
class _SharedMonkeypatchWitness: ...
_SHARED_MONKEYPATCH_WITNESS
def _maybe_redirect_test_tmp(...): ...
def pytest_configure(config): ...                              # the marker registration only
@pytest.fixture(autouse=True) def _shared_monkeypatch_pin_tripwire(...): ...
@pytest.fixture(autouse=True) def _reset_snapshot_catalog_memos(...): ...
@pytest.fixture(autouse=True) def _isolate_hermes_shim_dir(...): ...
@pytest.fixture(autouse=True) def _neutralize_claude_code_credentials_file(...): ...
@pytest.fixture def tmp_path(...): ...                         # overrides the builtin
@pytest.fixture(autouse=True) def _downstream_behavioral_vars_scrubbed(...): ...  # replaces the _HERMES_BEHAVIORAL_VARS edit

# tests/_downstream/hermes_cli_conftest.py  — star-imported; __all__ lists every name below
_OWNER_DIR; _OWNER_NODEID_PREFIX; _AGENT_BROWSER_PROBE_BINDINGS; _APP_BASELINE; _WINDOWS; _HOST
_WEB_BUILD_PREREQ_FILES; _VITE8_NODE_FLOOR; _WEB_BUILD_PREREQ_REASON; _LOCAL_MODEL_PROBE_NODE_IDS
_LOCAL_MODEL_PROBE_REASON; _ENV_GAPS; _POSIX_MODE_BITS_PROBE; _GIT_EOL_PROBE; _SHEBANG_EXEC_PROBE
_ENV_GAP_SKIPS; _STALE_ENV_GAP_ENTRIES; TELEGRAM_PARITY_DEFECT_REASON; _KNOWN_DEFECTS; _KNOWN_DEFECT_FAILURES
class _EmptyProcessTable: ...
def _node_version / _web_build_prereq_failure / _local_model_probe_failure / _no_module / _no_posix_mode_bits
    / _no_os_chown / _no_posix_wait_status / _no_posix_privilege_api / _posix_only_branch
    / _git_name_only_ignores_cr_at_eol / _no_shebang_script_execution: ...
@pytest.fixture(autouse=True) def _gateway_fence_is_armed_for_this_test / _agent_browser_probe_never_spawns
    / _web_server_app_is_pristine / _pairing_dir_follows_the_test_home / _sys_modules_identity_is_restored
    / _no_windows_gateway_pause_token / _no_live_process_table: ...
def pytest_configure / pytest_collection_modifyitems / pytest_runtest_logreport / pytest_sessionfinish
    / pytest_terminal_summary: ...

# tests/_downstream/tools_conftest.py  — star-imported
_ENV_GAPS; _ENV_GAP_SKIPS; _OWNER_DIR; _STALE; _KNOWN_DEFECTS; _KNOWN_DEFECT_FAILURES
def _cached / _no_posix_file_modes / _no_posix_exec_bit / _no_unwritable_dir_via_chmod / _no_shebang_exec
    / _no_af_unix / _no_process_groups: ...
def pytest_configure / pytest_collection_modifyitems / pytest_runtest_logreport / pytest_terminal_summary: ...

# tests/_downstream/agent_conftest.py  — star-imported
_SLOW_LOOPBACK_TIMEOUT_SECONDS; _SLOW_LOOPBACK_TIMEOUT_NODE_IDS; _ENV_GAPS; _ENV_GAP_SKIPS; _OWNER_DIR; _STALE
def _shell_hook_scripts_are_not_directly_executable: ...
def pytest_configure / pytest_collection_modifyitems / pytest_runtest_logreport / pytest_terminal_summary: ...
```

The one line each upstream conftest carries:

| conftest | the line |
|---|---|
| `tests/conftest.py` | `pytest_plugins = ["tests._downstream.conftest_plugin"]` |
| `tests/hermes_cli/conftest.py` | `from tests._downstream.hermes_cli_conftest import *  # noqa: F401,F403` |
| `tests/tools/conftest.py` | `from tests._downstream.tools_conftest import *  # noqa: F401,F403` |
| `tests/agent/conftest.py` | `from tests._downstream.agent_conftest import *  # noqa: F401,F403` |

Why the three subdirectory conftests get a star import: pytest 9.0.3 rejects `pytest_plugins` in any conftest it loads after configure ("Defining 'pytest_plugins' in a non-top-level conftest is no longer supported"). The fork's per-file runner loads every conftest up front, so it would pass there, while a bare `pytest tests` loads the subdirectory conftests later and fails. Listing the three modules in the root line instead would turn the seven `tests/hermes_cli/` autouse fixtures into suite-wide fixtures. The four hooks already filter by owner (`is_owned`, `_OWNER_NODEID_PREFIX`), but those fixtures do not. A star import keeps today's scoping exactly. `import *` skips `_`-prefixed names unless `__all__` lists them, so each module lists them. `tests/__init__.py` exists, so `tests/_downstream/` (with its own `__init__.py`) imports as `tests._downstream`. The modified upstream names in `tests/conftest.py` (§1.4) cannot move this way. The plan's Stage 3 PR series has to absorb them.

---

## 2. Stage 4 — the profile-home delta, name by name against `upstream/main`

Each name the fork adds or changes relative to the merge base is compared with `upstream/main`. Upstream changed none of the fork-modified bodies after the base, so every "differs" below is the fork's edit alone. "Upstream callers" = upstream-manifest production files that reference the name. "Sites" = every reference outside the defining file, tests included: the source-pin census a relocation pays.

### 2.1 `hermes_constants.py` (+288 / −16 against the base; 21 names)

| name | kind | fork | bucket | upstream equivalent / why | upstream callers | sites |
|---|---|---|---|---|---|---|
| `get_default_hermes_root` | fn | modified | **already-upstream** | upstream memoises the same computation in `_default_hermes_root_memo`. The fork replaced it with a dict and left upstream's global dead: `hermes_cli/gateway_migrate.py` still resets it and nothing reads it | many (unchanged) | — |
| `_resolve_default_hermes_root` | fn | added | **already-upstream** | the body of upstream `get_default_hermes_root`, extracted | 0 | — |
| `_DEFAULT_HERMES_ROOT_CACHE` | const | added | **already-upstream** | `_default_hermes_root_memo` | 0 | 1 |
| `reset_default_hermes_root_cache` | fn | added | **already-upstream** | `hermes_constants._default_hermes_root_memo = None`, which is the reset `gateway_migrate` already does | 0 | 5 |
| `agent_browser_runnable` | fn | modified | **generic** | caches the `--version` subprocess verdict per path. Upstream runs the probe on every call, and it helps any upstream user | many (unchanged) | — |
| `_AGENT_BROWSER_PROBE_CACHE` | const | added | **generic** | the memo above | 0 | — |
| `reset_agent_browser_probe_cache` | fn | added | **generic** | the invalidation hook for install/heal paths. Its one caller is an upstream file (`hermes_cli/dep_ensure.py`) | 1 | 9 |
| `CANONICAL_SHARED_SKILL_IDS` | const | added | **ours** | harness skill ids | 0 | 35 |
| `CONVERSATION_REQUEST_ASSEMBLED_STEP` | const | added | **ours** | Mission Control chat-phase name (`agent_runtime/mission_chat_phases.py`, `agent_runtime/conversation_observability.py`) | 0 | 14 |
| `_HERMES_HEAD_HOME` | const | added | **ours** | ContextVar holding the operator (head) home across relay hops | 0 | 1 |
| `record_hermes_head_home_if_unset` | fn | added | **ours** | records the outermost home once per context (persona relay) | 0 | 6 |
| `reset_hermes_head_home` | fn | added | **ours** | its reset | 0 | — |
| `get_hermes_head_home` | fn | added | **ours** | the home the Mission Control projection reads, ignoring persona overrides | 0 | 46 |
| `hermes_head_home_is_authoritative` | fn | added | **ours** | makes operator stores fail closed when the head is unknown | 0 | 13 |
| `get_hermes_background_work_home` | fn | added | **ours** | a name for the head-home decision, used for `processes.json` / `async_delegations`. It exists because the writers and the Mission Control HUD reader disagreed | 1 (`tools/async_delegation.py`) | 27 |
| `_HERMES_AUTH_HOME_OVERRIDE` | const | added | **ours** | ContextVar for the shared-auth home | 0 | — |
| `set_hermes_auth_home_override` | fn | added | **ours** | persona profiles share one operator auth. Upstream scopes auth per profile (`hermes_home_key()`), so this is harness policy, not a gap | 0 | — |
| `reset_hermes_auth_home_override` | fn | added | **ours** | its reset | 0 | — |
| `get_hermes_auth_home` | fn | added | **ours** | the single reader of `HERMES_AUTH_HOME` | 1 (`hermes_cli/auth.py`) | 15 |
| `get_shared_skills_dir` | fn | added | **ours** | the realm shared-skills root (`<root>/shared/skills`) | 1 (`agent/skill_utils.py`, already a §0.4 carry row) | 129 |
| `get_shared_characters_dir` | fn | added | **ours** | the install-wide character library | 0 | 16 |

Functions per bucket: **already-upstream 3 (+1 const), generic 2 (+1 const), ours 10 (+4 const).** Only four upstream files call any "ours" name (`hermes_cli/auth.py`, `tools/async_delegation.py`, `agent/skill_utils.py`, and for the generic reset `hermes_cli/dep_ensure.py`). So "carry" here does not have to mean lines in `hermes_constants.py`. The 14 "ours" names can move to a fork module such as `agent_runtime/home_authorities.py`, leaving one import edit in each of the three upstream callers. The cost is the source-pin census: the "sites" column, which is mostly `monkeypatch.setattr(hermes_constants, …)` in tests. With the 4 already-upstream names deleted, the 3 generic ones proposed as P7 (or carried additively if it is declined), and the 14 relocated, the file's fork delta falls to the P7 lines.

### 2.2 `hermes_cli/profiles.py` (+304 / −30 against the base; 14 names)

| name | kind | fork | bucket | upstream equivalent / why | upstream callers |
|---|---|---|---|---|---|
| `available_profile_templates` | fn | added | **already-upstream** | `list_profile_names()` (it also returns `default`, which the caller has to drop). Its one caller (`agent_runtime/persona_instance_identity.py::_profile_template_names`) reads names only. Upstream's version filters identity and tombstones, and this raw `iterdir` walk does not (§4 row 3) | 0 |
| `_profile_bound_backend_pids` | fn | modified | **generic** | raises `ProcessTableUnreadable` instead of returning `[]` when nothing can inspect processes, so "unknowable" is no longer read as "none bound". It also reads one injected table | internal |
| `_stop_profile_backends` | fn | modified | **generic** | passes the one reading through | internal |
| `delete_profile` | fn | modified | **generic** + ours | generic: it refuses before its first irreversible step when no process inspector exists (`force_unverified_writers` override, and the `--force-unverified-writers` flag in upstream `hermes_cli/subcommands/profile.py`, the `profile_cmd.py` catch, and the `web_routers/profiles.py` 409). Ours: the trailing `_mark_profile_personas_orphaned(canon)` call | CLI, web |
| `ProcessTableUnreadable` | class | added | **generic** | typed "cannot inspect" | 0 |
| `ProfileDeleteBlocked` | class | added | **generic** | typed refusal (`code`, `safe_details`) | 2 (`profile_cmd.py`, `web_routers/profiles.py`) |
| `_ProcessFacts` | class | added | **generic** | the per-process row. Its `exe` / `inspector_handle` fields exist for the fork's `hermes_cli/_desktop_processes.py`, which shadows upstream `hermes_cli/main_desktop.py::_stop_desktop_processes_locking_build` | 0 |
| `_ProcessTable` | class | added | **generic** | one reading with its identity facts | 0 |
| `_ProcessLister` | class | added | **generic** | the lister protocol (the test seam) | 0 |
| `_PsutilProcessLister` | class | added | **generic** | the production lister. Its comment "the caller answers 'no bound backends' — unchanged" is stale because the caller now refuses | 0 |
| `_PROCESS_LISTER` | const | added | **generic** | the module seam | 0 |
| `ProfileTemplateInfo` | class | added | **ours** | the Mission Control roster row | 0 |
| `available_profile_template_summaries` | fn | added | **ours** | the Mission Control placeable roster (servable-identity filtered, no config parse). Callers: `agent_runtime/snapshot.py`, `agent_runtime/profile_persona_discovery.py` | 0 |
| `_mark_profile_personas_orphaned` | fn | added | **ours → hook** | marks harness personas orphaned on profile delete. Upstream `VALID_HOOKS` has no profile-lifecycle hook, so the fix is a surface-widening PR (`on_profile_deleted(profile_name)`) with the harness plugin as the consumer. The fallback is carrying the one call line | 0 |

Functions/classes per bucket: **already-upstream 1, generic 9 (+1 const), ours 3.** The generic set is one PR: "P6 — profile delete refuses when it cannot see who is writing". It carries the `hermes_cli/subcommands/profile.py` / `profile_cmd.py` / `web_routers/profiles.py` edits with it, and the fork commit that introduced it records six killing mutations (`docs/agent-runtime-harness/planned/upstream-sync-20260914/commits.json`, ML-16 / B20). The two "ours" roster names relocate to `agent_runtime/` next to their only callers. They use upstream-private helpers (`_iter_named_profile_dirs`, `read_profile_meta`, `_PROFILE_ID_RE`), which is allowed for fork code but not for the plugin (§1 rule 3).

### 2.3 `tests/test_no_frozen_hermes_home.py` ledger entries these functions own

**None.** `FROZEN_LEDGER` has no key for `hermes_constants.py` or `hermes_cli/profiles.py`, because both resolve at call time. Two entries in other files freeze values these functions produce:

- `gateway/platforms/base.py` → `_HERMES_ROOT` = `get_default_hermes_root()` at import. Upstream-owned, and unaffected by deleting the fork's cache, since upstream's memo returns the same value.
- `tools/process_registry.py` → `CHECKPOINT_PATH`, `_CHECKPOINT_PATH_AT_IMPORT`: the import-time sentinel. The call-time answer is `agent_runtime.process_notifications.checkpoint_path` → `get_hermes_background_work_home`. Relocating that function moves no entry.

So Stage 4's gate ("ledger unchanged or shorter") holds trivially for every row above.

---

## 3. Stage 6 — desktop reach

Fork edits to upstream `apps/desktop/` files against `d337b736aa`: **2**. The plan's "32" was measured against the older base `c62bd9f207`, and the merge absorbed the rest. The fork also adds two fork-only test files there: `apps/desktop/src/app/settings/uninstall-section.test.tsx` and `apps/desktop/src/store/session-dot-state-downstream.test.ts`. These are not upstream files, so they do not count toward `[up-fp]`.

| upstream file | fork delta | what it is | SDK can host it? | API it would need / disposition |
|---|---|---|---|---|
| `apps/desktop/src/app/settings/uninstall-section.tsx` | +6 / −0 | the uninstall confirm step warns that removing the agent deletes the code checkout's git history (`pendingOption.needsAgent`) | **no** | `PluginContext.register` reaches `<Slot>` areas only (`titleBar.*`, the workspace page header, docks). No area exists inside the settings uninstall confirm, and the SDK forbids reaching into app stores. It would need a `settings.uninstall.confirm` contribution area. **Better: upstream**, because the warning holds for every upstream user who uninstalls the agent. |
| `apps/desktop/src/lib/desktop-slash-registry.json` | +2 / −0 | `/queue-status`, `/qstatus` rows | **no** | generated by `scripts/dump_desktop_slash_registry.py` from `hermes_cli/commands.py::desktop_surface_registry` (pinned by `tests/hermes_cli/test_desktop_slash_registry.py`). It follows the fork's `CommandDef("queue-status", …)` in the upstream `hermes_cli/commands.py`, and `gateway/run_busy.py` names it too. It retires when that command leaves core (upstream it, or register it through the Python plugin's `register_command`, provided the dump reads plugin commands, which it does not today) |

Hostable **0**, partly **0**, not **2**.

---

## 4. Queue rows this inventory hands over (for `Harness_Brain/20 — Active Initiatives/runtime-queue.md`, § Seams)

1. - [ ] **Stage 5's "one `pytest_plugins` line per upstream conftest" is rejected by pytest for three of the four conftests** · `seams / tests` · pytest 9.0.3 `_check_non_top_pytest_plugins` fails a non-root conftest that defines `pytest_plugins` once config is configured (a bare `pytest tests`), and moving the three into the root line would make the seven `tests/hermes_cli/` autouse fixtures suite-wide. The shape that works is four `tests/_downstream/` modules: root by `pytest_plugins`, the other three by a star import with `__all__`. Evidence: `docs/agent-runtime-harness/planned/seam-s4-s5-s6-inventory-2026-09-23.md` §1.5 · filed by lane S45 2026-09-23 **UNCLAIMED**
2. - [ ] **177 of the 252 upstream test files the fork edits hold in-place edits, not fork tests. Stage 5's MOVE lanes cannot retire them, and its `[up-fp] files −242` target is not reachable (MOVE ceiling 28)** · `seams / tests` · these need a disposition pass (a batched portability/hermeticity PR upstream, or carry with a reason) before Stage 5's gate means anything. Evidence: the same note §1.1–§1.3 · filed by lane S45 2026-09-23 **UNCLAIMED**
3. - [ ] **Two profile rosters answer "which profiles exist" differently: the orphan prune reads the raw `iterdir` one** · `fork / runtime` · `hermes_cli/profiles.py::available_profile_templates` walks `profiles/` raw, so tombstoned and ghost-shell dirs count as live. `available_profile_template_summaries` (fixed at `bcf8012e6a`) and upstream `list_profile_names()` filter identity and tombstones. `agent_runtime/persona_instance_identity.py::_profile_template_names` feeds the prune from the raw walk, so a persona bound to a deleted profile whose dir a stale writer re-created is not prunable. One authority, `list_profile_names()`. Evidence: the same note §2.2 · filed by lane S45 2026-09-23 **UNCLAIMED**
