"""Rows (win32 only) that are upstream's OWN Windows reds at v2026.9.24 -- retired by an upstream fix.

``_up_red`` / ``_up_red_skip`` rows with their class letters, the lifecycle-scan rows, the
path-spelling strict xfails (PR class win-path-spelling), and the cp1252 e-ENC rows (a
locale PROBE, not a platform guard). The evidence is
``X:/wt/_holds/upstream-reds-v2026.9.24.md``.

One ``ROWS`` table, already host-filtered; ``hooks._merge`` concatenates the four.
The map is ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import sys

import pytest

from tests._downstream.id_markers.reasons import (
    _CONTAINER_SPELLING,
    __layer__,
    _LIFECYCLE_SCAN,
    _PATH_SPELLING,
    _SEPARATOR_SPELLING,
    _TMP_LITERAL,
    _up_red,
    _up_red_skip,
    _WIN,
)

__layer__ = "models"

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = {
}

if _WIN:
    ROWS.update({
        "tests/tools/test_approval.py::TestDetectDangerousRm::test_nonrecursive_verification_artifact_cleanup_is_not_dangerous": (
            pytest.mark.xfail(reason=_TMP_LITERAL, strict=True),
        ),
        "tests/tools/test_approval.py::TestDetectDangerousRm::test_symlinked_temp_dir_only_exempts_canonical_target": (
            pytest.mark.xfail(reason=_TMP_LITERAL, strict=True),
        ),
        "tests/tools/test_computer_use.py::TestCuaDriverSessionReconnect::"
        "test_cli_fallback_reads_screenshot_from_file": (
            pytest.mark.xfail(reason=_PATH_SPELLING, strict=True),
        ),
        "tests/hermes_cli/test_kanban_db.py::"
        "test_worktree_workspace_explicit_target_materializes_linked_worktree": (
            pytest.mark.xfail(reason=_SEPARATOR_SPELLING, strict=True),
        ),
        "tests/tools/test_file_tools_cwd_resolution.py::test_container_absolute_input_path_does_not_follow_host_symlink": (
            pytest.mark.xfail(reason=_CONTAINER_SPELLING, strict=True),
        ),
        "tests/tools/test_file_tools_cwd_resolution.py::test_container_relative_path_keeps_container_cwd_symlink": (
            pytest.mark.xfail(reason=_CONTAINER_SPELLING, strict=True),
        ),
        "tests/tools/test_file_tools_cwd_resolution.py::test_warning_fires_when_relative_path_escapes_workspace": (
            pytest.mark.xfail(reason=_CONTAINER_SPELLING, strict=True),
        ),
        "tests/tools/test_file_tools_cwd_resolution.py::test_warning_fires_from_terminal_cwd_when_registry_empty": (
            pytest.mark.xfail(reason=_CONTAINER_SPELLING, strict=True),
        ),
        "tests/hermes_cli/test_doctor_structural_corruption.py::"
        "test_doctor_routes_structural_damage_to_recover_not_fts_rebuild": (
            _up_red("an FTS-only stomp reads as structural damage; no Windows marker in the text"),
        ),
        **{
            f"tests/hermes_cli/test_gateway.py::{test}": (
                _up_red_skip("the stop test outlives the 30 s thread timeout, which kills "
                             "the process; the port test asserts the POSIX branch"),
            )
            for test in (
                "TestRestartWaitsForApiServerPort::"
                "test_port_is_reported_free_once_the_old_listener_closes",
                "TestStopProfileGateway::"
                "test_stop_profile_gateway_keeps_pid_file_when_process_still_running",
            )
        },
        **{
            f"tests/hermes_cli/test_gateway_restart_loop.py::{cls}::{test}": (_LIFECYCLE_SCAN,)
            for cls, tests in (
                ("TestTerminalToolGatewayLifecycleGuard", (
                    "test_blocks_lifecycle_command_hidden_in_referenced_script",
                    "test_blocks_launchctl_submit_hidden_in_referenced_script",
                    "test_blocks_executable_shebang_script",
                    "test_shell_option_with_value_still_scans_script",
                    "test_nested_wrapper_script_is_scanned",
                    "test_safe_referenced_script_passes_through",
                )),
                ("TestLifecycleGuardModule", (
                    "test_nul_padded_script_is_still_scanned",
                    "test_nul_padded_script_without_shebang_is_scanned",
                    "test_oversized_nul_bearing_text_still_fails_closed",
                    "test_cloud_backed_symlink_fails_closed_without_opening_target",
                    "test_third_party_cloudstorage_path_fails_closed_without_opening",
                )),
                ("TestDotSourceIsScannedLikeSource", (
                    "test_both_spellings_block_a_referenced_script",
                    "test_env_assignment_prefix_does_not_hide_dot_source",
                    "test_dot_source_nested_in_shell_c_is_blocked",
                )),
                ("TestTransparentWrapperPrefixes", (
                    "test_wrapped_script_reference_is_scanned",
                    "test_wrapped_dot_source_is_scanned",
                    "test_wrapped_shell_c_payload_is_scanned",
                    "test_privilege_and_namespace_wrappers_are_scanned",
                    "test_command_string_options_are_rescanned",
                    "test_local_script_named_like_a_wrapper_is_still_scanned",
                )),
                ("TestTerminalToolGatewayLifecycleGuardRemote", (
                    "test_remote_backend_script_read_uses_env_execute",
                    "test_unscannable_executed_script_names_the_reason",
                )),
            )
            for test in tests
        },
        "tests/hermes_cli/test_gateway_windows.py::"
        "test_exec_schtasks_round_trips_non_ascii_task_argument_live": (
            _up_red("schtasks /Create is refused unelevated (Access is denied); the "
                    "fork's gateway fence refuses the spawn first"),
        ),
        "tests/hermes_cli/test_gui_command.py::"
        "test_stop_desktop_processes_locking_build_posix_swap_bypasses_early_return": (
            _up_red("asserts the POSIX branch of code that has a Windows branch"),
        ),
        "tests/hermes_cli/test_kanban_db.py::"
        "test_infrastructure_spawn_refusal_never_charges_the_card": (
            _up_red("the refused spawn auto-blocks the card; no Windows marker in the text"),
        ),
        "tests/hermes_cli/test_mcp_config.py::TestMcpRemoveEvictsManager::"
        "test_remove_evicts_in_memory_provider": (
            _up_red("fakes a console with isatty(); _stdin_is_console() also asks "
                    "GetConsoleMode of the real handle (class e-TTY)"),
        ),
        "tests/hermes_cli/test_profiles.py::TestFindAliasForProfile::"
        "test_list_profiles_surfaces_custom_alias": (
            _up_red("the alias is read back with its .bat suffix; issue #83938"),
        ),
        "tests/hermes_cli/test_resource_limits.py::"
        "test_named_profile_reroute_defers_limit_to_final_process": (
            _up_red("spawns a real `hermes serve` (SystemExit 1 upstream; the fork's "
                    "live-system guard refuses the spawn)"),
        ),
        "tests/hermes_cli/test_desktop_lifecycle_windows_live.py::"
        "test_holder_scan_fallback_respects_token_classifier": (
            _up_red("patches hermes_cli.main._detect_venv_python_processes, but upstream's "
                    "update_cmd_windows._desktop_owns_gateway_lifecycle calls its own module-level "
                    "binding since 27df3b8847 (upstream-owned function, byte-identical here)"),
        ),
        "tests/tools/test_approved_command_clean_slate.py::"
        "test_retry_backoff_does_not_clear_genuine_interrupt": (
            _up_red_skip("patches time.sleep module-wide, so terminal_tool's cleanup thread "
                         "busy-loops; under upstream's tests/home_io_guard.py (2026-09-25 merge) "
                         "the spin starves the test past the 30 s thread timeout, which kills "
                         "the process (upstream-owned test, loop and guard; green before the guard)"),
        ),
        # Arrived with the 2026-09-25 merge (067fa1a257): upstream tests of upstream code,
        # red on Windows with no fork line in the path.
        "tests/hermes_cli/test_gui_command.py::test_gui_successful_pack_swaps_new_app_into_release": (
            _up_red("the pack step asks pm for git and the hermetic harness disables lazy installs"),
        ),
        "tests/hermes_cli/test_update_wedged_gateway.py::TestLaunchdRestartWedgedIntegration": (
            _up_red("the launchd restart path imports the POSIX-only pwd module (class e-BR)"),
        ),
        "tests/test_live_system_guard.py::test_default_home_unmarked_tmpdir_is_relocated_before_pytest_uses_it": (
            _up_red("the relocated tmpdir is still reported under the operator home on Windows"),
        ),
        "tests/tools/test_code_execution_modes.py::test_selected_interpreter_environment_and_real_rpc": (
            _up_red("the child environment carries Windows-only keys the expected mapping omits"),
        ),
        "tests/scripts/test_run_tests_parallel.py::test_scratch_root_is_per_user": (
            _up_red("calls os.getuid, which Windows does not have"),
        ),
        "tests/tools/test_file_write_safety.py::TestBomHandling::test_a_dangling_symlink_destination_is_occupied": (
            _up_red("readlink hands back the extended-length \\?\ spelling (class c-D)"),
        ),
        # Red on pure upstream/main 067fa1a257 on this box too (coordinator's
        # pure_upstream_rerun.log): upstream Windows reds, byte-identical files.
        "tests/hermes_cli/test_home_init_soul_symlink.py::test_initialize_home_replaces_unwritable_soul_symlink[cyclic]": (
            _up_red("a cyclic symlink resolves to WinError 1921, not the POSIX loop error"),
        ),
        "tests/hermes_cli/test_shallow_boundary_repair.py::test_failed_shallow_maintenance_restores_original_bytes": (
            _up_red("read-only git object files refuse the restore on Windows (WinError 5)"),
        ),
        "tests/hermes_cli/test_update_no_gateway_restart.py::test_restart_deferral_crosses_real_completion_process": (
            _up_red("the real completion child exits 1 on Windows; no Windows marker in the text"),
        ),
        # Upstream-NEW test files (2026-09-25 merge) red on PURE upstream/main 067fa1a257
        # on this box too (lane log upnew_pure.log: 60 failed in 13 files).
        **{node: (_up_red('red on pure upstream/main 067fa1a257 on Windows (upstream-new file, 2026-09-25 merge)'),) for node in (
            'tests/hermes_cli/test_backup_preflight.py::test_preflight_captures_committed_wal_without_application_imports',
            'tests/hermes_cli/test_install_bucket_separation.py::TestProfileCopyExclusions::test_copies_profile_payload_without_install_artifacts[export]',
            'tests/hermes_cli/test_memory_dependency_admission.py::test_setup_requires_dependencies_and_keeps_the_existing_union[False]',
            'tests/hermes_cli/test_memory_dependency_admission.py::test_setup_requires_dependencies_and_keeps_the_existing_union[True]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_atexit_recovers_only_stopped_serves_after_cached_update[0-False]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_atexit_recovers_only_stopped_serves_after_cached_update[0-True]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_atexit_recovers_only_stopped_serves_after_cached_update[9-False]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_atexit_recovers_only_stopped_serves_after_cached_update[9-True]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_historical_payload_maps_to_takeover_request_schema[None-False]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_historical_payload_maps_to_takeover_request_schema[None-True]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_historical_payload_maps_to_takeover_request_schema[resume1-False]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_historical_payload_maps_to_takeover_request_schema[resume1-True]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_only_known_early_updater_restarts_with_original_arguments[unrelated-False]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_only_known_early_updater_restarts_with_original_arguments[unrelated-True]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_only_known_early_updater_restarts_with_original_arguments[update_cmd-False]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_only_known_early_updater_restarts_with_original_arguments[update_cmd-True]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[False-utf-8-0]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[False-utf-8-7]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[False-utf-8-sig-0]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[False-utf-8-sig-7]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[None-utf-8-0]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[None-utf-8-7]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[None-utf-8-sig-0]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[None-utf-8-sig-7]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[True-utf-8-0]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[True-utf-8-7]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[True-utf-8-sig-0]',
            'tests/hermes_cli/test_old_updater_takeover.py::test_takeover_waits_propagates_status_and_never_reenters_old_code[True-utf-8-sig-7]',
            'tests/hermes_cli/test_shared_profile_warning.py::test_cli_entrypoint_registers_and_warns_once_for_live_shared_home[cli]',
            'tests/hermes_cli/test_shared_profile_warning.py::test_cli_entrypoint_registers_and_warns_once_for_live_shared_home[serve]',
            'tests/hermes_cli/test_shared_profile_warning.py::test_cli_startup_quarantines_corrupt_ledger[\\xff]',
            'tests/hermes_cli/test_shared_profile_warning.py::test_cli_startup_quarantines_corrupt_ledger[{broken]',
            'tests/hermes_cli/test_shared_profile_warning.py::test_warning_tracks_live_other_install_in_same_home',
            'tests/hermes_cli/test_source_build.py::test_installed_npm_does_not_authorize_missing_workspace_dependencies',
            'tests/hermes_cli/test_source_channel_integration.py::test_retirement_refuses_to_downgrade_newer_source[shallow]',
            'tests/hermes_cli/test_source_launcher_publication.py::test_running_source_launcher_can_republish_itself[native-with-maker]',
            'tests/hermes_cli/test_source_launcher_publication.py::test_running_source_launcher_can_republish_itself[native]',
            'tests/hermes_cli/test_update_completion_process.py::test_bootstrap_does_not_initialize_old_site_packages',
            'tests/hermes_cli/test_update_completion_process.py::test_failed_build_preserves_exit_status_without_maintenance',
            'tests/hermes_cli/test_update_completion_process.py::test_old_process_new_git_tree_completes_in_fresh_python[None]',
            'tests/hermes_cli/test_update_completion_process.py::test_old_process_new_git_tree_completes_in_fresh_python[receipt]',
            'tests/hermes_cli/test_update_completion_process.py::test_old_process_new_git_tree_completes_in_fresh_python[request]',
            'tests/hermes_cli/test_update_completion_process.py::test_prepare_failure_preserves_correlated_pm_receipt',
            'tests/hermes_cli/test_update_completion_process.py::test_progress_is_forwarded_before_held_stage_is_released[prepare]',
            'tests/hermes_cli/test_update_completion_process.py::test_progress_is_forwarded_before_held_stage_is_released[selected]',
            'tests/hermes_cli/test_update_target_identity.py::test_branch_update_uses_real_refs_and_completion_request[fork-late-reverted]',
            'tests/hermes_cli/test_update_target_identity.py::test_branch_update_uses_real_refs_and_completion_request[fork-late-wrong-branch]',
            'tests/hermes_cli/test_update_target_identity.py::test_update_syntax_failure_restores_pre_update_head[True-early]',
            'tests/hermes_cli/test_update_target_identity.py::test_update_syntax_failure_restores_pre_update_head[True-late-other-branch]',
            'tests/hermes_cli/test_update_target_identity.py::test_update_syntax_failure_restores_pre_update_head[True-late]',
            'tests/hermes_cli/test_update_target_identity.py::test_update_syntax_failure_restores_pre_update_head[True-origin]',
            'tests/hermes_cli/test_venv_sync_currency.py::test_own_tree_sync_reuses_pm_without_writing_an_extra_stamp',
            'tests/hermes_cli/test_version_info.py::test_get_version_info_derives_identity_from_reachable_release_tag',
            'tests/hermes_cli/test_version_info.py::test_get_version_info_takes_the_version_a_calver_only_release_shipped',
            'tests/hermes_cli/test_web_memory_provider_setup_install.py::test_setup_admits_real_provider_union_and_keeps_selection_on_failure[pip_dependencies-cli]',
            'tests/hermes_cli/test_web_memory_provider_setup_install.py::test_setup_admits_real_provider_union_and_keeps_selection_on_failure[pip_dependencies-dashboard]',
            'tests/hermes_cli/test_web_memory_provider_setup_install.py::test_setup_admits_real_provider_union_and_keeps_selection_on_failure[pyproject-cli]',
            'tests/hermes_cli/test_web_memory_provider_setup_install.py::test_setup_admits_real_provider_union_and_keeps_selection_on_failure[pyproject-dashboard]',
            'tests/hermes_cli/test_web_memory_provider_setup_install.py::test_setup_admits_real_provider_union_and_keeps_selection_on_failure[python_dependencies-cli]',
            'tests/hermes_cli/test_web_memory_provider_setup_install.py::test_setup_admits_real_provider_union_and_keeps_selection_on_failure[python_dependencies-dashboard]',
        )},
        "tests/hermes_cli/test_isolated_serve_ledger_marker.py::"
        "test_isolated_serve_ledger_row_is_marked_and_ordinary_serve_is_not": (
            _up_red("spawns a real `hermes serve` against a tmp home (the fork's live-system "
                    "guard backend-spawn arm refuses it by design; green on pure upstream)"),
        ),
        "tests/hermes_cli/test_session_message_page_owner.py::"
        "test_message_pages_identify_the_serving_profile[None]": (
            _up_red("with no serving profile the default page is the serving page, 120 != 1"),
        ),
        "tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::"
        "test_activating_an_endpoint_carries_its_credential_either_way": (
            _up_red_skip("activation probes llm.modern.com live; the lookup outlives the "
                         "30 s thread timeout, which kills the process"),
        ),
        "tests/hermes_cli/test_plugins.py::TestPluginDiscovery::"
        "test_enabled_portable_plugin_registers_components": (
            _up_red("app.darwin.location is str(tmp_path), a drive-letter path the declaration "
                    "rejects as not absolute, so the plugin is disabled at load (class c-D)"),
        ),
        "tests/tui_gateway/test_tui_gateway_server.py::"
        "test_load_cfg_raw_sees_replacement_with_pinned_mtime_and_size": (
            _up_red("shutil.copy2 over an existing file keeps its NTFS file id and creation "
                    "ctime, so no field of the cache signature moves (class e-ID)"),
        ),
        # A SKIP: the red is a teardown error, which a strict xfail cannot cover (the
        # call phase passes and reads XPASS(strict)).
        **{node: (_up_red_skip("the Proactor loop close in tests/conftest.py _ensure_current_event_loop "
                               "teardown calls time.monotonic, which the test's three-tick clock has "
                               "exhausted"),) for node in (
            'tests/hermes_cli/test_backup.py::TestSafeCopyDb::test_aborts_when_source_remains_busy_past_deadline',
        )},
        **{node: (_up_red('CRLF written where LF is asserted (class c-B, issue class #121221)'),) for node in (
        )},
        **{node: (_up_red('HOME patched, USERPROFILE not, in a ~-expansion (class c-C, #121222)'),) for node in (
            'tests/hermes_cli/test_resume_latest_and_in_dir.py::test_in_dir_expands_user_home',
        )},
        **{node: (_up_red('path spelling: separators or drive-qualified POSIX literals (class c-D, PR class win-path-spelling #121224)'),) for node in (
            'tests/hermes_cli/test_plugin_manifest_v2.py::TestDirectoryPluginKeepsIdentityOverEntryPoint::test_loader_and_listing_prefer_the_installed_directory',
            'tests/hermes_cli/test_ssh_session_token_parser.py::test_token_file_rejects_parent_escape',
            'tests/hermes_cli/test_startup_fast_guards.py::test_literal_tilde_hermes_home_expands_before_any_reader',
            'tests/hermes_cli/test_startup_fast_guards.py::test_normalize_hermes_home_env_rewrites_tilde_and_leaves_absolute_alone',
            'tests/hermes_cli/test_update_host_obligation.py::test_recovery_host_state_dir_matches_the_gateway_resolver[env0]',
            'tests/hermes_cli/test_update_host_obligation.py::test_recovery_host_state_dir_matches_the_gateway_resolver[env1]',
        )},
        **{node: (_up_red('bash invocation with Windows paths inside a POSIX command string (class c-E, #121226)'),) for node in (
            'tests/hermes_cli/test_agent_env_advertisement.py::TestWrapCommandAdvertisesHarness::test_shell_sets_default_and_preserves_outer',
            'tests/hermes_cli/test_bang_shell_mode.py::TestBangExecution::test_output_is_streamed_to_writer',
            'tests/hermes_cli/test_bang_shell_mode.py::TestBangExecution::test_stderr_is_merged_into_output',
            'tests/hermes_cli/test_bang_shell_mode.py::TestBangExecution::test_runs_in_requested_cwd',
        )},
        **{node: (_up_red('an open handle or read-only file blocks the delete, WinError 5 (class c-H)'),) for node in (
            'tests/hermes_cli/test_plugin_install_ref.py::test_reinstall_after_manual_directory_removal_retains_pin',
            'tests/hermes_cli/test_shallow_boundary_repair.py::test_repair_does_not_mask_unrelated_object_loss',
        )},
        **{node: (_up_red('asserts the POSIX branch of code that has a Windows branch (class e-BR)'),) for node in (
            'tests/hermes_cli/test_agent_plugins.py::test_server_declaration_joins_mcp_and_preserves_liveness',
            'tests/hermes_cli/test_cli_clarify_batch.py::TestClarifyBellOnPrompt::test_bell_on_prompt_rings_and_off_is_silent',
            'tests/hermes_cli/test_cli_init.py::TestPromptToolkitTerminalCompatibility::test_lf_enter_binding_respects_multiline_shortcuts',
            'tests/hermes_cli/test_cli_init.py::TestPromptToolkitTerminalCompatibility::test_cpr_gating_posix_suppresses_without_ssh',
            'tests/hermes_cli/test_ctrl_enter_newline.py::test_ctrl_j_legacy_submit_when_multiline_shortcuts_disabled',
            'tests/hermes_cli/test_install_cua_driver.py::TestInstallCuaDriverUpgrade::test_upgrade_with_binary_present_runs_installer',
            'tests/hermes_cli/test_install_cua_driver.py::TestInstallCuaDriverUpgrade::test_non_upgrade_without_binary_runs_installer',
            'tests/hermes_cli/test_local_runtime_child_env.py::test_spawn_server_keeps_the_callers_environment',
            'tests/hermes_cli/test_orphan_desktop_serve_reap.py::test_reap_passes_child_pid_exclude_to_scan',
            'tests/hermes_cli/test_orphan_desktop_serve_reap.py::test_reap_kills_descendants_of_killed_roots_but_spares_a_failed_roots_subtree',
            'tests/hermes_cli/test_plugins_cmd_catalog.py::test_catalog_platform_mismatch_refuses_before_install',
            'tests/hermes_cli/test_stale_pid_guard.py::TestKillStaleDashboardProcesses::test_stop_only_targets_the_invoking_hermes_home',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_skips_build_only_on_termux_when_fresh',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_skips_install_on_termux_when_bundle_fresh',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_scopes_npm_install_on_termux_workspace',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_keeps_desktop_workspace_install_behaviour',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_npm_install_forces_include_dev',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_keeps_desktop_always_build_behaviour',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_decodes_dev_prebuild_with_utf8_replace',
            'tests/hermes_cli/test_tui_npm_install.py::test_make_tui_argv_exits_with_recovery_hint_when_workspace_unrecoverable',
        )},
        **{node: (_up_red('fake executable is an extensionless #! script, neither run nor found via PATHEXT (class e-EXE)'),) for node in (
            'tests/hermes_cli/test_goal_gates.py::test_run_gate_fail_captures_output',
            'tests/hermes_cli/test_web_server_git.py::test_gh_auth_refresh_waits_out_a_probe_started_before_it',
            'tests/hermes_cli/test_worktree.py::TestPrMergedEscapeHatch::test_merged_pr_tree_is_reaped',
            'tests/hermes_cli/test_worktree.py::TestPrMergedEscapeHatch::test_merged_verdict_memoized_by_branch_and_head',
        )},
        **{node: (_up_red('a same-size, pinned-mtime replacement keeps the NTFS file id and creation ctime (class e-ID)'),) for node in (
            'tests/hermes_cli/test_cli_mcp_config_watch.py::test_pinned_mtime_same_size_replacement_triggers_reload',
            'tests/hermes_cli/test_config_cache_signature.py::test_load_config_sees_replacement_with_pinned_mtime_and_size',
        )},
        **{node: (_up_red('the fixture path carries characters Windows rejects, WinError 123 (class e-NAME)'),) for node in (
            'tests/hermes_cli/test_doctor_wal_checkpoint_guard.py::test_session_count_reads_a_home_with_uri_reserved_characters',
        )},
        **{node: (_up_red('prompt_toolkit needs a real Windows console; none under pytest (class e-TTY)'),) for node in (
        )},
        **{node: (_up_red('no Windows marker in the failure text; red at the tag on this box (class f-?)'),) for node in (
            'tests/hermes_cli/test_anon_sign_in_flow.py::test_the_scope_is_entered_for_the_preconditions_and_the_persist_but_never_around_a_wait',
            'tests/hermes_cli/test_noninteractive_git.py::TestNoninteractiveGitEnv::test_safe_directory_reset_still_revokes_wildcard_for_real_git',
            'tests/hermes_cli/test_plugin_validate.py::test_portable_validation_fails_orphan_and_reports_availability',
        )},
        "tests/hermes_cli/test_completion.py::TestGenerateBash::test_valid_bash_syntax": (
            pytest.mark.xfail(strict=True, reason=(
                "bash resolves a native temp path by POSIX rules and eats its backslashes; "
                "fixed by the open fork PR #121226 (shell invocation)")),
        ),
        **{
            f"tests/acp_adapter/test_session.py::TestSymlinkAliasNormalization::{test}": (
                _up_red("realpath over a Windows drive: an alias does not resolve to its "
                        "target and a POSIX literal is drive-qualified (class c-D)"),
            )
            for test in (
                "test_symlink_alias_compares_equal",
                "test_missing_path_keeps_lexical_normalization",
                "test_list_sessions_matches_symlink_alias_cwd",
            )
        },
        **{
            f"tests/gateway/test_runtime_footer.py::{test}": (
                _up_red(f"{why}; twin: tests/gateway/test_runtime_footer_downstream.py"),
            )
            for test, why in (
                ("test_home_relative_cwd_collapses_home", "HOME patched, USERPROFILE not (class c-C, #121222)"),
                ("test_format_footer_all_fields", "HOME patched, USERPROFILE not (class c-C, #121222)"),
                ("test_format_footer_latency_in_field_order", "HOME patched, USERPROFILE not (class c-C, #121222)"),
                ("test_format_footer_skips_missing_context_length", "a POSIX cwd literal is drive-qualified (class c-D)"),
                ("test_default_build_footer_line_ignores_turn_seconds", "a POSIX cwd literal is drive-qualified (class c-D)"),
            )
        },
        # Lane TRIAGE (2026-09-26): upstream reds on Windows main whose cause is the
        # SQLite 3.45.3 bundled with Windows CPython 3.12.5 (CI runs 3.50.4), or a
        # Windows-only caller of a process-wide patch.
        **{
            f"tests/hermes_state/test_fts_runtime_rebuild.py::TestRuntimeFtsRebuild::{test}": (
                _up_red("SQLite 3.45.3 cannot DROP a corrupt FTS5 table from a fresh "
                        "connection ('vtable constructor failed: messages_fts'), so the "
                        "stale-FTS rebuild never recovers; product defect, runtime-queue "
                        "upstream-owned row"),
            )
            for test in (
                "test_corruption_fails_open_and_rebuilds_on_reopen",
                "test_repeated_deferrals_reap_inactive_orphan_then_rebuild",
                "test_retry_backoff_resets_when_the_blocking_holder_set_changes",
                "test_legacy_inline_fts_fails_open_and_recovers",
            )
        },
        "tests/hermes_state/test_state_db_malformed_repair.py::test_repair_rebuilds_stale_btree_indexes": (
            _up_red("pins SQLite >= 3.46 integrity_check wording 'wrong # of entries'; "
                    "3.45.3 reports 'row N missing from index', which the product also "
                    "parses and repairs via reindex_btree (probed)"),
        ),
        "tests/hermes_state/test_state_db_repair_non_destructive.py::"
        "test_interrupted_snapshot_rolls_back_destination": (
            _up_red_skip("patches time.monotonic process-wide with a 2-tick iterator; the "
                         "conftest's Proactor loop close (IocpProactor.close) calls it at "
                         "teardown and gets StopIteration. Test passes, teardown errors; "
                         "PR candidate: an unbounded tick source"),
        ),
    })

if _WIN and not sys.flags.utf8_mode:
    # Probe, not platform: the red is the cp1252 locale, so it does not occur under
    # scripts/run_tests.sh / run_tests_bundled.sh, which export PYTHONUTF8=1 — there
    # an unconditional strict xfail XPASSes.
    ROWS.update({
        f"tests/hermes_cli/test_kanban_core_functionality.py::{test}": (
            _up_red("write_text() of a non-ASCII worker log with no encoding= under the cp1252 locale: UnicodeEncodeError (class e-ENC)"),
        )
        for test in (
            "test_dead_worker_reap_surfaces_the_workers_own_last_output",
            "test_dead_worker_reap_reads_the_log_of_the_dispatching_board",
        )
    })
