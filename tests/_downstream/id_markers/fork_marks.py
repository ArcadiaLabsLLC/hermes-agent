"""Rows that hold on EVERY host because of FORK behaviour -- retired by a fork change or a fork PR.

Fixture opt-ins (the credentials file, the real Windows pause, config reads through
load_config, the scoped monkeypatch undo, the claude home), the rule-4 strict xfails
that name the fork symbol and its ``*_downstream.py`` sibling, and the timeouts the
fork's ``--timeout=30`` cannot hold. A row whose premise happens to be win32 but whose
cause is the fork (``_WIN_REEXEC_BRANCH``, ``_FORK_SYSTEM_PATH``, the
``_escape_shell_arg`` xfail) is here, under ``if _WIN:``.

One ``ROWS`` table, already host-filtered; ``hooks._merge`` concatenates the four.
The map is ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import (  # noqa: F401
    _CLAUDE_HOME_TMP,
    _CONFIG_READ_THROUGH,
    _CREDENTIALS_FILE,
    _FORK_LIVE_SYSTEM_GUARD,
    _FORK_MANAGED_PYTHON,
    _FORK_PERSONA_CONFIG_SYNC,
    _fork_replaces,
    _FORK_SPAWN_DETACHED,
    _FORK_SYSTEM_PATH,
    _LOOKALIKE,
    _REAL_PAUSE,
    _SCOPED_UNDO,
    TELEGRAM_PARITY_DEFECT_REASON,
    _WIN,
    _WIN_REEXEC_BRANCH,
)

__layer__ = "models"

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = {
    # MCF-66: these classes exercise the real ~/.claude/.credentials.json
    # reader/writer; each redirects Path.home() at its tmp_path (enforced by
    # tests/test_claude_code_credentials_file_gate.py, which reads this table).
    **{
        f"tests/agent/test_anthropic_adapter.py::{cls}": (_CREDENTIALS_FILE,)
        for cls in (
            "TestReadClaudeCodeCredentials",
            "TestResolveAnthropicToken",
            "TestRefreshOauthToken",
            "TestWriteClaudeCodeCredentials",
            "TestResolveWithRefresh",
            "TestRunOauthSetupToken",
        )
    },
    # ML-16 / B20(iv): a known, owner-owned defect, fenced strict.
    "tests/hermes_cli/test_commands.py::TestSlackNativeSlashes::test_telegram_parity": (
        pytest.mark.xfail(strict=True, reason=TELEGRAM_PARITY_DEFECT_REASON),
    ),
    # Tests ABOUT _pause_windows_gateways_for_update opt out of the fork
    # conftest default that returns None; their service/process transports
    # are mocked and the gateway fence still stands behind them.
    **{
        f"tests/hermes_cli/test_update_concurrent_quarantine.py::{test}": (_REAL_PAUSE,)
        for test in (
            "test_pause_windows_gateways_for_update_stops_profile_and_unmapped_pids",
            "test_pause_and_resume_windows_gateway_service",
            "test_pause_windows_gateway_service_failure_restores_every_attempted_service",
            "test_pause_windows_gateway_service_surfaces_rollback_start_failure",
            "test_pause_windows_gateways_aborts_when_service_discovery_is_indeterminate",
            "test_pause_windows_gateways_aborts_when_gateway_pid_discovery_is_indeterminate",
            "test_pause_kill_set_covers_venv_guard_abort_set",
        )
    },
    # The fork's hermes_cli.tirith_config lets TIRITH_* env win over config.yaml;
    # this upstream test pins the config value (fixture: tools_conftest).
    "tests/tools/test_approval.py::TestTirithImportErrorFailOpenPolicy::"
    "test_fail_open_false_escalates_to_approval_on_import_error": (
        pytest.mark.tirith_config_value_under_test,
    ),
    # The fork runner's 30s default is below the child PowerShell's own 30s
    # budget; this upstream test needs the headroom.
    "tests/scripts/desktop_update/test_desktop_update_windows_retry_policy.py::"
    "test_retry_policy_distinguishes_self_lock_deferral": (pytest.mark.timeout(45),),
    # MCF-66: reads the real ~/.claude/.credentials.json via the fixture's
    # redirected Path.home() (gate: tests/test_claude_code_credentials_file_gate.py).
    "tests/hermes_cli/test_codex_cli_model_picker.py::"
    "test_claude_code_file_detected_by_model_picker": (_CREDENTIALS_FILE,),
    # Identity-only inspection of the frozen updater surface; never invokes it.
    "tests/hermes_cli/test_lazy_command_exports.py::"
    "test_frozen_updater_surface_resolves_to_real_objects": (_REAL_PAUSE,),
    # The real negative liveness poll takes 30 s plus process startup; the
    # fork's repo-wide --timeout=30 cannot observe the expected refusal.
    "tests/hermes_cli/test_gateway_job_teardown_live.py::TestResumeVerificationLive::"
    "test_dead_relaunch_is_not_reported_as_success": (
        pytest.mark.timeout(90),
        # A live gateway anywhere on the machine answers the fleet-wide poll.
        pytest.mark.requires_no_live_gateway,
    ),
    "tests/test_tests_tree_layout.py::"
    "test_every_test_directory_mirrors_a_source_directory_or_is_declared": (
        pytest.mark.xfail(strict=True, reason=(
            "the fork's tests/_downstream/ (id marks, conftest plugin) and "
            "tests/tooling/ (fork gates) mirror no source package and upstream's "
            "_NON_MIRROR_DIRS cannot name them; fork half: "
            "tests/test_tests_tree_layout_downstream.py"
        )),
    ),
    "tests/hermes_cli/test_config_read_guard.py::"
    "test_no_raw_config_yaml_reads_outside_owner_modules": (
        pytest.mark.xfail(reason=_FORK_PERSONA_CONFIG_SYNC, strict=True),
    ),
    "tests/hermes_cli/test_dashboard_tui_backcompat.py::"
    "test_dashboard_tui_flag_is_accepted_not_rejected": (
        pytest.mark.xfail(reason=_FORK_LIVE_SYSTEM_GUARD, strict=True),
    ),
    "tests/hermes_cli/test_gateway_windows.py::"
    "test_build_gateway_argv_keeps_venv_console_python_for_uv_venv": (
        pytest.mark.xfail(reason=_FORK_MANAGED_PYTHON, strict=True),
    ),
    **{
        f"tests/hermes_cli/test_gateway_windows.py::{test}": (
            pytest.mark.xfail(reason=_FORK_SPAWN_DETACHED, strict=True),
        )
        for test in (
            "test_spawn_detached_marks_primary_breakaway_success",
            "test_spawn_detached_warns_and_marks_no_breakaway_fallback",
        )
    },
    # The fork resolves tirith's flags through hermes_cli.tirith_config (env wins).
    "tests/tools/test_cron_approval_mode.py::TestCronDenyModeAllGuards::"
    "test_tirith_import_error_fail_closed_blocks_in_cron_deny": (
        pytest.mark.tirith_config_value_under_test,
    ),
    # Readers the fork moved to load_config_readonly; upstream patches load_config.
    **{
        node: (_CONFIG_READ_THROUGH,)
        for node in (
            "tests/tools/test_browser_console.py::TestBrowserVisionConfig",
            "tests/tools/test_image_generation.py::TestModelResolution",
            "tests/tools/test_vision_native_fast_path.py::TestHandleVisionAnalyzeFastPath::"
            "test_supports_vision_override_bypasses_provider_allowlist",
            "tests/tools/test_vision_native_fast_path.py::TestHandleVisionAnalyzeFastPath::"
            "test_text_mode_wins_over_supports_vision_override",
            "tests/tools/test_vision_tools.py::TestHandleVisionAnalyze",
            "tests/tools/test_vision_tools.py::TestVisionConfig",
            "tests/tools/test_vision_tools.py::TestVisionCpuBurstCap",
        )
    },
    # Fork behaviour replaces upstream's; the fork assertion is the _downstream sibling.
    "tests/tools/test_async_delegation.py::"
    "test_real_process_restart_restores_owned_completion_once": (
        pytest.mark.xfail(strict=True, reason=(
            "the fork's tools.process_registry.ProcessRegistry."
            "restore_durable_completions is an explicit startup step, not an "
            "import side effect; fork half: "
            "tests/tools/test_async_delegation_downstream.py"
        )),
    ),
    "tests/gateway/test_api_server_active_work_drain.py::TestShutdownSettleWindow::"
    "test_api_work_still_live_at_settle_exit_is_reinterrupted": (_SCOPED_UNDO,),
    "tests/gateway/test_mirror.py::TestSessionsIndexProfileScoping::"
    "test_fallback_follows_active_profile_home": (_SCOPED_UNDO,),
    # MCF-66: these files drive the real ~/.claude/.credentials.json
    # reader/writer; the fork opts them in AND points Path.home() at tmp_path.
    **{
        f"tests/agent/{name}.py": (_CREDENTIALS_FILE, _CLAUDE_HOME_TMP)
        for name in (
            "test_anthropic_borrowed_row_authority",
            "test_anthropic_credential_persist_failure",
            "test_anthropic_spent_rotation_verdict",
        )
    },
    # macOS-only classes; each _setup redirects Path.home() itself.
    **{
        f"tests/agent/test_anthropic_keychain.py::{cls}": (_CREDENTIALS_FILE,)
        for cls in ("TestReadClaudeCodeCredentialsPriority", "TestReadClaudeCodeCredentialsDesync")
    },
    **{
        node: (_SCOPED_UNDO,)
        for node in (
            "tests/agent/test_anthropic_credential_persist_failure.py::"
            "test_reauthentication_clears_the_persist_failure_quarantine",
            "tests/agent/test_canon_args_memo_parity.py::TestComplexityProof::"
            "test_json_loads_linear_not_quadratic",
            "tests/cron/test_cron_profile_isolation.py::test_cron_storage_anchors_at_profile_home",
            "tests/hermes_state/test_append_messages_batch.py::TestAppendMessagesBatch::"
            "test_atomicity_all_or_nothing",
            "tests/hermes_state/test_retired_wal_generation_capture.py::"
            "test_close_refuses_to_settle_without_a_capture",
            "tests/hermes_state/test_retired_wal_generation_capture.py::"
            "test_failed_capture_still_pins_the_handle_and_surfaces_through_the_registry",
            "tests/hermes_state/test_session_db_read_conn_pool.py::"
            "test_permits_are_not_stranded_by_a_failed_open",
            "tests/plugins/memory/test_holographic_store.py::TestConcurrency::"
            "test_failed_write_does_not_pin_write_lock",
            "tests/plugins/platforms/photon/test_sidecar_paths.py::"
            "test_adapter_import_does_not_resolve_sidecar_dir",
        )
    },
    "tests/agent/test_external_skills.py::TestGetAllSkillsDirs::test_local_always_first": (
        _fork_replaces(
            "agent.skill_utils.get_all_skills_dirs (shared skills root second)",
            "tests/agent/test_external_skills_downstream.py",
        ),
    ),
    "tests/agent/test_prompt_builder.py::TestBuildContextFilesPrompt::"
    "test_hermes_md_still_wins_over_agents_override": (
        _fork_replaces(
            "agent.prompt_builder.build_context_files_prompt (context sources load additively)",
            "tests/agent/test_prompt_builder_downstream.py",
        ),
    ),
    **{
        f"tests/providers/test_entry_point_discovery.py::{test}": (
            _fork_replaces(
                "hermes_cli.plugins_discovery split (the enable lists are read there, "
                "not on hermes_cli.plugins)",
                "tests/providers/test_entry_point_discovery_downstream.py",
            ),
        )
        for test in (
            "test_entry_point_callable_and_module_targets",
            "test_entry_point_failure_is_isolated",
        )
    },
    **{
        node: (_CONFIG_READ_THROUGH,)
        for node in (
            "tests/plugins/dashboard_auth/test_nous_provider.py::TestConfigYamlSource",
            "tests/plugins/dashboard_auth/test_nous_provider_downstream.py::TestConfigYamlSource",
            "tests/plugins/dashboard_auth/test_self_hosted_provider.py::TestPluginRegister",
        )
    },
    **{
        f"tests/test_live_system_guard.py::{test}": (
            _fork_replaces(
                "_live_system_guard backend-spawn arm (tests/conftest.py)",
                "tests/test_live_system_guard_downstream.py",
            ),
        )
        for test in (
            "test_gateway_start_inside_a_container_exec_is_not_blocked",
            "test_gateway_start_on_the_host_is_still_blocked",
        )
    },
    "tests/test_live_system_guard_self_test.py::"
    "test_subprocess_run_gateway_status_passes_through": (_LOOKALIKE,),
    # The fork runs the whole tree under --timeout=30; these PowerShell
    # harnesses carry their own child budgets above that.
    "tests/scripts/desktop_update/test_desktop_update_windows_cwd.py": (pytest.mark.timeout(75),),
    "tests/scripts/desktop_update/test_desktop_update_windows_progress.py": (pytest.mark.timeout(120),),
    "tests/scripts/desktop_update/test_desktop_update_windows_ui_delivery.py": (pytest.mark.timeout(75),),
    "tests/scripts/desktop_update/test_desktop_update_windows_pipe_drain.py::"
    "test_update_step_survives_pipe_leak_flood_and_live_child_stall": (pytest.mark.timeout(330),),
    "tests/scripts/install/test_install_ps1_managed_python_provenance.py::"
    "test_python_find_timeout_kills_uv_and_fails_stage": (pytest.mark.timeout(60),),
    "tests/tools/test_tool_search_multiquery.py::TestBatchedDescribe::"
    "test_registered_direct_surface_name_keeps_exact_error": (
        _fork_replaces(
            "tools.tool_search.dispatch_tool_describe (details for an in-session direct tool)",
            "tests/tools/test_tool_search_multiquery_downstream.py",
        ),
    ),
    # The fork's doctor_config reads config.yaml from get_hermes_home() at call
    # time, so upstream's patch of doctor.HERMES_HOME no longer selects the file.
    "tests/hermes_cli/test_doctor.py::test_run_doctor_vendor_slug_policy_for_openai_api_endpoint"
    "[https://api.openai.com/v1-True]": (
        _fork_replaces(
            "hermes_cli.doctor_config._check_config_file (home resolved at call time)",
            "tests/hermes_cli/test_doctor_downstream.py",
        ),
    ),
    # Lane REDS3: the bundled eternia-harness plugin (kind backend, auto-loaded)
    # registers post_api_request for the usage ledger (f5c9838487), and upstream's
    # test does not take the bundled tree out of its sweep.
    "tests/hermes_cli/test_plugins.py::TestPluginHooks::test_request_hooks_are_invokeable": (
        _fork_replaces(
            "eternia-harness post_api_request hook (plugins/eternia-harness, usage ledger)",
            "tests/hermes_cli/test_plugins_downstream.py",
        ),
    ),
    # Lane REDS3 (wave-close gate): the pool's round-robin position is a sidecar
    # cursor (agent_runtime.pool_rotation, MCF-44), so select() leaves auth.json.
    "tests/hermes_cli/test_oauth_status_pool_observation.py::"
    "test_status_snapshot_leaves_round_robin_order_and_counts_untouched": (
        _fork_replaces(
            "agent_runtime.pool_rotation sidecar cursor (credential_rotation.json)",
            "tests/hermes_cli/test_oauth_status_pool_observation_downstream.py",
        ),
    ),
    # A local-path origin reads as a fork, and the fork never resets a diverged
    # fork checkout (update_history.guard_fork_history exits 2; 1487c101ee).
    "tests/hermes_cli/test_update_diverged_rescue_ref.py::"
    "test_hermes_update_keeps_local_commit_behind_a_rescue_ref": (
        _fork_replaces(
            "hermes_cli.update_cmd._reconcile_diverged_checkout fork-history guard",
            "tests/hermes_cli/test_update_diverged_rescue_ref_downstream.py",
        ),
    ),
}

if _WIN:
    ROWS.update({
        "tests/hermes_cli/test_dashboard_unified_launch.py::TestUnifiedDashboardRouting::"
        "test_profile_launch_reexecs_machine_dashboard": (
            pytest.mark.xfail(reason=_WIN_REEXEC_BRANCH, strict=True),
        ),
        "tests/tools/test_local_env_blocklist.py::TestSanePathIncludesHomebrew::"
        "test_make_run_env_preserves_windows_mixed_case_path_key": (
            pytest.mark.xfail(reason=_FORK_SYSTEM_PATH, strict=True),
        ),
        "tests/tools/test_file_operations.py::TestShellFileOpsHelpers::"
        "test_escape_shell_arg_rewrites_forward_slash_native_paths": (
            _fork_replaces(
                "ShellFileOperations._escape_shell_arg (native Windows paths, no /c/ rewrite)",
                "tests/tools/test_file_operations_downstream.py",
            ),
        ),
    })

# An upstream custom-endpoint flow whose context probe resolves a fixture host
# over real DNS (fixture: conftest_plugin._no_ollama_show_probe).
ROWS["tests/hermes_cli/test_custom_provider_model_switch.py::TestCustomProviderModelSwitch::"
         "test_custom_endpoint_switch_prunes_stale_model_config_pool_entry"] = (
    pytest.mark.no_ollama_show_probe,
)

# Upstream web-server tests whose restart / desktop-startup path runs the REAL
# gateway orphan reap and its 30 s exit wait (fixture: conftest_plugin).
ROWS.update({
    node: (pytest.mark.no_real_orphan_reap,)
    for node in (
        "tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::"
        "test_telegram_onboarding_apply_reports_restart_failure_after_save",
        "tests/hermes_cli/test_web_server.py::TestDesktopCronTicker::test_ticker_runs_when_desktop",
    )
})

ROWS.update({
    node: (_SCOPED_UNDO,)
    for node in (
        "tests/hermes_cli/test_kanban_worker_pid_fingerprint.py::"
        "test_unverified_fingerprint_capture_never_authorizes_a_signal",
        "tests/hermes_cli/test_macos_tcc_anchor.py::TestEnsureTccAnchor::"
        "test_alias_failure_leaves_anchor_unmarked",
        "tests/hermes_cli/test_plugins.py::TestPluginDiscovery::test_failed_discovery_is_not_cached",
        "tests/hermes_cli/test_update_zip_two_phase.py::test_failed_swap_rolls_back_every_earlier_swap",
        "tests/hermes_cli/test_update_zip_two_phase.py::test_file_swap_failure_restores_the_original_file",
        "tests/hermes_cli/test_update_zip_two_phase.py::test_failed_staging_leaves_no_orphaned_copies",
        "tests/hermes_cli/test_update_zip_two_phase.py::test_staging_restores_backup_when_dst_is_missing",
        "tests/hermes_cli/test_update_zip_two_phase.py::"
        "test_commit_failure_plus_discard_leaves_no_staging_litter",
    )
})
