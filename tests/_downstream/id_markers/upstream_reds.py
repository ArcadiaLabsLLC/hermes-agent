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
        **{
            f"tests/hermes_cli/test_kanban_worker_session_source.py::{test}": (
                _up_red("the retag matches worker cwd against a backslashed workspace root"),
            )
            for test in ("test_retag_reclaims_legacy_worker_rows", "test_retag_gate_is_per_board")
        },
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
            'tests/hermes_cli/test_backup_stability.py::test_quick_snapshot_is_published_with_manifest',
            'tests/hermes_cli/test_oneshot_surrogate.py::test_oneshot_replaces_lone_surrogate_and_exits_zero',
        )},
        **{node: (_up_red('HOME patched, USERPROFILE not, in a ~-expansion (class c-C, #121222)'),) for node in (
            'tests/hermes_cli/test_resume_latest_and_in_dir.py::test_in_dir_expands_user_home',
        )},
        **{node: (_up_red('path spelling: separators or drive-qualified POSIX literals (class c-D, PR class win-path-spelling #121224)'),) for node in (
            'tests/hermes_cli/test_agent_plugins.py::test_loads_manifest_skill_and_stdio_server',
            'tests/hermes_cli/test_browser_connect_default_chromium.py::TestLinuxProfileDir::test_native_path_when_nothing_exists',
            'tests/hermes_cli/test_browser_connect_default_chromium.py::TestLinuxProfileDir::test_snap_chromium_profile_is_found',
            'tests/hermes_cli/test_browser_connect_default_chromium.py::TestLinuxProfileDir::test_flatpak_chrome_profile_is_found',
            'tests/hermes_cli/test_browser_connect_default_chromium.py::TestLinuxProfileDir::test_native_profile_wins_when_present',
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
            'tests/hermes_cli/test_external_process_auth_status.py::test_auth_verified_from_on_disk_credential_store',
            'tests/hermes_cli/test_external_process_auth_status.py::test_auth_verified_from_copilot_cli_plaintext_store',
            'tests/hermes_cli/test_external_process_auth_status.py::test_explicit_filter_keeps_signed_in_external_process_row',
            'tests/hermes_cli/test_external_process_auth_status.py::test_catalog_key_resolves_from_copilot_cli_store',
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
            'tests/hermes_cli/test_modify_other_keys_aliases.py::test_buffer_level_shift_space_no_raw_csi',
            'tests/hermes_cli/test_modify_other_keys_aliases.py::test_buffer_level_shift_letter_no_raw_csi',
        )},
        **{node: (_up_red('no Windows marker in the failure text; red at the tag on this box (class f-?)'),) for node in (
            'tests/hermes_cli/test_anon_sign_in_flow.py::test_the_scope_is_entered_for_the_preconditions_and_the_persist_but_never_around_a_wait',
            'tests/hermes_cli/test_noninteractive_git.py::TestNoninteractiveGitEnv::test_safe_directory_reset_still_revokes_wildcard_for_real_git',
            'tests/hermes_cli/test_plugin_ownership_ledger.py::test_shared_entrypoint_module_uses_the_active_profile_scope',
            'tests/hermes_cli/test_plugin_ownership_ledger.py::test_provider_overlay_switches_profiles_and_reveals_fresh_global_fallback',
            'tests/hermes_cli/test_plugin_ownership_ledger.py::test_direct_plugin_platform_registration_infers_immutable_scope',
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
