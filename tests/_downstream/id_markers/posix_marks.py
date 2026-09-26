"""Rows (win32 only) whose PREMISE is POSIX -- retired by upstream ``linux_only`` marks.

``_posix_only`` skips and ``_posix_xfail`` strict xfails, the WSL-premise skips, the
tirith no-build skips, the TCC POSIX-venv rows, and ``IMPORT_TIME_POSIX_SHIMS``. Every
row retires with the open branch ``up/win-posix-only-apis``.

One ``ROWS`` table, already host-filtered; ``hooks._merge`` concatenates the four.
The map is ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import (
    __layer__,
    _POSIX_ONLY,
    _posix_only,
    _posix_xfail,
    _TCC_POSIX_VENV,
    _TIRITH_NO_BUILD,
    _WIN,
    _WSL_FAKE,
)

__layer__ = "models"

ROWS: dict[str, tuple[pytest.MarkDecorator, ...]] = {
}

if _WIN:
    ROWS.update({
        "tests/hermes_cli/test_relaunch.py::TestRelaunch::test_calls_execvp": (
            pytest.mark.skip(reason=_POSIX_ONLY),
        ),
        "tests/tools/test_voice_mode.py::TestDetectAudioEnvironment::"
        "test_wsl_without_pulse_blocks_voice": (pytest.mark.skip(reason=_WSL_FAKE),),
        "tests/tools/test_voice_mode.py::TestWSL2PowerShellFallback::"
        "test_powershell_pipeline_preserves_real_exit_status": (
            pytest.mark.skip(reason=_WSL_FAKE),
        ),
        "tests/tools/test_voice_mode.py::TestWSL2PowerShellFallback::"
        "test_wsl2_unique_temp_filename": (pytest.mark.skip(reason=_WSL_FAKE),),
        "tests/tools/test_browser_homebrew_paths.py::TestRunBrowserCommandPathConstruction::"
        "test_subprocess_path_includes_termux_fallback_dirs": (
            _posix_only("clears the env to HOME only; Windows Path.home() needs USERPROFILE"),
        ),
        **{
            f"tests/tools/test_find_shell.py::TestFindShellPrefersUserShell::{test}": (
                _posix_only("$SHELL is read only on _find_shell's non-Windows arm"),
            )
            for test in (
                "test_returns_shell_env_when_set_and_exists",
                "test_honours_allowlisted_bash_and_dash",
            )
        },
        "tests/tools/test_code_execution.py::TestRpcTokenAuthorization::"
        "test_missing_token_rejected": (_posix_only("socket.AF_UNIX socketpair"),),
        **{
            f"tests/tools/test_local_interrupt_cleanup.py::{test}": (_posix_only("os.getpgid"),)
            for test in (
                "test_kill_process_uses_cached_pgid_if_wrapper_already_exited",
                "test_exit_cleanup_kills_foreground_command_still_running",
            )
        },
        **{
            f"tests/tools/test_local_shell_init.py::TestResolveShellInitFiles::{test}": (
                _posix_only(
                    "auto-sourcing is gated on not _IS_WINDOWS, and HOME does not move ~ there"
                ),
            )
            for test in (
                "test_auto_sources_bashrc_when_present",
                "test_auto_sources_profile_when_present",
                "test_auto_sources_profile_before_bashrc",
            )
        },
        # Windows argv quoting mangles the multi-line `sh -c` script (sh:
        # "unexpected end of file"); two of them also need POSIX modes/euid.
        **{
            f"tests/tools/test_stage2_hook_api_server_keygen.py::{test}": (
                _posix_only("a multi-line `sh -c` argv does not survive Windows quoting"),
            )
            for test in (
                "test_keygen_creates_env_when_missing",
                "test_keygen_appends_to_existing_env_without_key",
                "test_keygen_never_overwrites_operator_key",
                "test_keygen_refuses_symlinked_env",
                "test_keygen_skips_when_container_env_provides_key",
                "test_keygen_env_key_with_existing_env_file_key_warns_not_clobbers",
                "test_keygen_env_key_drops_stale_empty_assignment",
                "test_keygen_readonly_env_degrades_to_warning_not_boot_abort",
                "test_keygen_warns_on_weak_container_env_key",
                "test_keygen_weak_env_key_warning_suppressed_when_env_file_key_wins",
            )
        },
        **{
            f"tests/tools/test_tirith_security.py::{cls}": (_TIRITH_NO_BUILD,)
            for cls in (
                "TestExitCodeMapping",
                "TestJsonParseFailure",
                "TestOSErrorFailOpen",
                "TestTimeoutFailOpen",
                "TestUnknownExitCode",
                "TestCaps",
                "TestProgrammingErrors",
                "TestEnsureInstalled",
                "TestBackgroundInstall",
                "TestSpawnWarningDedup",
                "TestAppTldSuppression",
                "TestCircuitBreakerHalfOpen",
                "TestEmojiVariationSelectorSuppression",
            )
        },
        "tests/tools/test_voice_wsl_pipewire.py::test_wsl_without_forwarding_still_blocks": (
            _posix_only("WSL premise; a Windows host finds powershell.exe and degrades to a notice"),
        ),
        "tests/tools/test_process_registry.py::TestPopenLeakOnSetupFailure::"
        "test_popen_killed_when_thread_creation_fails": (_posix_only("os.getpgid"),),
        "tests/tools/test_process_registry.py::TestKillProcess::"
        "test_kill_detached_session_uses_host_pid": (
            _posix_only("pins the psutil terminate seam; Windows kills the tree via taskkill"),
        ),
        **{
            f"tests/gateway/test_systemd_notify.py::{test}": (
                _posix_only("no socket.AF_UNIX, so no systemd notify socket"),
            )
            for test in (
                "test_notify_uses_nonblocking_datagram_send",
                "test_watchdog_sends_ready_heartbeat_and_stopping",
            )
        },
        "tests/gateway/test_update_command.py::TestHandleUpdateCommand::"
        "test_fallback_when_no_setsid": (
            _posix_only("pins the bash -c / setsid spawn; win32 spawns the interpreter"),
        ),
        "tests/gateway/test_update_streaming.py::TestUpdateCommandGatewayFlag::"
        "test_spawns_with_gateway_flag": (
            _posix_only("reads the bash -c command string; win32 spawns an argv list"),
        ),
        "tests/gateway/test_complete_path_at_filter.py::"
        "test_leading_slash_prefers_a_real_absolute_path": (
            _posix_only('"/etc" is drive-relative on Windows'),
        ),
        **{
            f"tests/hermes_cli/test_active_sessions.py::{test}": (
                _posix_xfail("pid 1 is init on POSIX; Windows has no pid 1, so it reads dead"),
            )
            for test in (
                "test_unknown_sibling_liveness_only_fences_its_own_session",
                "test_unknown_sibling_does_not_block_guarded_release_or_orphan_sweep",
            )
        },
        **{
            f"tests/hermes_cli/test_config.py::TestEnvWriteDenylist::"
            f"test_non_exec_near_misses_still_writable[{name}]": (
                _posix_xfail("env names are case-insensitive on Windows, so the "
                             "lowercase near-miss IS the denied variable"),
            )
            for name in ("git_config_parameters", "ld_preload")
        },
        "tests/hermes_cli/test_gateway_restart_loop.py::TestTerminalToolGatewayLifecycleGuard::"
        "test_non_regular_referenced_script_fails_closed": (_posix_xfail("os.mkfifo"),),
        "tests/hermes_cli/test_profiles.py::TestWrapperScript::test_creates_sh_on_posix": (
            _posix_xfail("the wrapper is mybot.bat on Windows; issue #83938"),
        ),
        "tests/hermes_cli/test_terminal_breadcrumbs.py": (_posix_xfail("os.ttyname"),),
        **{node: (_posix_xfail('termios'),) for node in (
            'tests/hermes_cli/test_cli_light_mode.py::TestOsc11DrainGuard::test_late_reply_is_consumed_not_leaked',
            'tests/hermes_cli/test_cli_light_mode.py::TestOsc11DrainGuard::test_post_deadline_straggler_is_drained',
        )},
        **{node: (_posix_xfail('os.chown (s6 supervision)'),) for node in (
            'tests/hermes_cli/test_container_boot.py::test_a_named_profile_slot_is_registered_but_never_autostarted',
            'tests/hermes_cli/test_container_boot.py::test_the_retired_opt_out_cannot_boot_a_second_gateway_in_the_container[config-false]',
            'tests/hermes_cli/test_container_boot.py::test_the_retired_opt_out_cannot_boot_a_second_gateway_in_the_container[env-false-overrides-config]',
        )},
        **{node: (_posix_xfail('os.geteuid / sudo (monkeypatched in setup)'),) for node in (
            'tests/hermes_cli/test_dashboard_system_gateway_elevation.py::test_only_system_scope_lifecycle_verbs_are_spawned_under_sudo[subcommand0-False-True]',
            'tests/hermes_cli/test_dashboard_system_gateway_elevation.py::test_only_system_scope_lifecycle_verbs_are_spawned_under_sudo[subcommand1-False-True]',
            'tests/hermes_cli/test_dashboard_system_gateway_elevation.py::test_only_system_scope_lifecycle_verbs_are_spawned_under_sudo[subcommand2-False-False]',
            'tests/hermes_cli/test_dashboard_system_gateway_elevation.py::test_only_system_scope_lifecycle_verbs_are_spawned_under_sudo[subcommand3-True-False]',
            'tests/hermes_cli/test_dashboard_system_gateway_elevation.py::test_restart_without_passwordless_sudo_fails_the_request',
            'tests/hermes_cli/test_dashboard_system_gateway_elevation.py::test_targeted_nopasswd_sudoers_still_elevates',
        )},
        **{node: (_posix_xfail('asyncio.start_unix_server'),) for node in (
            'tests/hermes_cli/test_display_ws_drop_keeps_lease.py::test_only_a_clean_viewer_close_hands_the_screen_back[1006-True]',
            'tests/hermes_cli/test_display_ws_drop_keeps_lease.py::test_only_a_clean_viewer_close_hands_the_screen_back[1005-True]',
            'tests/hermes_cli/test_display_ws_drop_keeps_lease.py::test_only_a_clean_viewer_close_hands_the_screen_back[1000-False]',
            'tests/hermes_cli/test_display_ws_drop_keeps_lease.py::test_a_takeover_made_by_another_process_stops_input_within_the_refresh_interval',
            'tests/hermes_cli/test_display_ws_drop_keeps_lease.py::test_no_bridge_task_or_socket_outlives_the_bridge',
        )},
        **{node: (_posix_xfail('os.getuid (XDG runtime ownership)'),) for node in (
            'tests/hermes_cli/test_gateway_foreign_xdg_runtime.py::TestRuntimeDirIsOurs::test_true_when_owned_by_current_uid',
            'tests/hermes_cli/test_gateway_foreign_xdg_runtime.py::TestRuntimeDirIsOurs::test_false_when_owned_by_other_uid',
            'tests/hermes_cli/test_gateway_foreign_xdg_runtime.py::TestRuntimeDirIsOurs::test_false_when_missing',
            'tests/hermes_cli/test_gateway_foreign_xdg_runtime.py::TestEnsureUserSystemdEnvForeignRuntime::test_replaces_foreign_leaked_xdg_runtime_dir',
            'tests/hermes_cli/test_gateway_foreign_xdg_runtime.py::TestEnsureUserSystemdEnvForeignRuntime::test_keeps_own_xdg_runtime_dir',
            'tests/hermes_cli/test_gateway_foreign_xdg_runtime.py::TestEnsureUserSystemdEnvForeignRuntime::test_does_not_crash_when_foreign_bus_is_unreadable',
        )},
        **{node: (_posix_xfail('os.geteuid / pwd (systemd linger)'),) for node in (
            'tests/hermes_cli/test_gateway_linger.py::TestEnsureLingerEnabled::test_loginctl_failure_shows_manual_guidance',
            'tests/hermes_cli/test_gateway_linger.py::TestEnsureLingerEnabled::test_system_scope_warning_uses_system_restart',
            'tests/hermes_cli/test_gateway_linger.py::TestEnsureSystemServiceLinger::test_fresh_enable_waits_on_target_uid_and_hints_restart_only_when_running[True]',
            'tests/hermes_cli/test_gateway_linger.py::TestEnsureSystemServiceLinger::test_fresh_enable_waits_on_target_uid_and_hints_restart_only_when_running[False]',
        )},
        **{node: (_posix_xfail('os.geteuid (systemd linger)'),) for node in (
            'tests/hermes_cli/test_multiplex_host_topology_reporting.py::test_doctor_checks_host_unit_linger_under_a_served_profile[False]',
            'tests/hermes_cli/test_multiplex_host_topology_reporting.py::test_doctor_checks_host_unit_linger_under_a_served_profile[True]',
        )},
        **{node: (_posix_xfail('POSIX argv carries raw non-UTF-8 bytes; Windows argv is UTF-16'),) for node in (
            'tests/hermes_cli/test_process_identity.py::test_register_self_survives_non_utf8_argv',
        )},
        **{node: (_posix_xfail('os.geteuid'),) for node in (
            'tests/hermes_cli/test_ssh_ownership_endpoint.py::test_ssh_runtime_readonly_purelib_falls_back_to_stat',
        )},
        **{node: (_posix_xfail('chmod cannot make an NTFS directory unwritable'),) for node in (
            'tests/hermes_cli/test_update_host_obligation.py::test_unwritable_host_state_dir_still_arms_the_obligation',
        )},
        **{node: (_posix_xfail('st_uid ownership; NTFS reports uid 0 for every file'),) for node in (
            'tests/hermes_cli/test_update_venv_ownership_preflight.py::test_foreign_owned_dist_info_child_detected',
            'tests/hermes_cli/test_update_venv_ownership_preflight.py::test_foreign_owned_refuses_with_chown_hint',
        )},
        **{
        f"tests/agent/test_prompt_builder.py::{test}": (
            _posix_only("chmod(0) does not make a directory unreadable on Windows"),
        )
        for test in (
            "TestFindHermesMd::test_unreadable_cwd_is_treated_as_not_found",
            "TestCursorrulesCandidates::test_unreadable_cwd_is_treated_as_absent",
        )
        },
        # The fixture builds a POSIX venv; the one id the fork also scoped-undoes
        # (fork_marks) carries both marks -- hooks._merge concatenates.
        **{node: (_TCC_POSIX_VENV,) for node in (
            *(f"tests/hermes_cli/test_macos_tcc_anchor.py::TestEnsureTccAnchor::{test}" for test in (
                "test_noop_on_non_macos",
                "test_install_signs_the_anchor_copy",
                "test_anchors_repair_generation_interpreter",
                "test_anchors_uv_managed_interpreter",
                "test_idempotent",
                "test_repairs_alias_symlinks_left_by_predecessor",
                "test_reanchors_after_patch_bump",
                "test_skips_homebrew_interpreter",
                "test_provisions_libpython_as_hardlink_when_present",
                "test_boot_gate_refusal_leaves_venv_untouched",
                "test_alias_failure_leaves_anchor_unmarked",
            )),
            *(f"tests/hermes_cli/test_macos_tcc_anchor.py::TestTccAnchorState::{test}" for test in (
                "test_state_active_through_unpatched_home_symlink",
                "test_state_missing_then_active",
                "test_state_skip_for_homebrew",
                "test_state_stale_after_patch_bump",
            )),
        )},
        # Lane TRIAGE (2026-09-26): the Windows-main reds of fork-hygiene-queue's
        # "25 failed in 18 files" row whose premise is POSIX.
        "tests/hermes_state/test_auto_vacuum_in_process_holder_gate.py::"
        "test_auto_vacuum_is_not_starved_by_a_retired_write_fenced_generation": (
            _posix_only("replaces state.db while a SessionDB still holds it open; Windows "
                        "refuses the rename over an open file (WinError 5)"),
        ),
        **{
            f"tests/hermes_state/test_cross_vm_fs_wal_refusal.py::TestDetectCrossVmFs::"
            f"test_only_virtiofs_and_9p_mounts_are_flagged[{param}]": (
                _posix_only("virtiofs/9p detection reads Linux /proc/self/mountinfo; "
                            "_detect_cross_vm_fs returns False off Linux by design"),
            )
            for param in ("/data/agent-True", "/mnt/host/db-True", "/mnt/my share/db-True")
        },
        **{
            f"tests/hermes_state/test_shared_session_db_registry.py::"
            f"TestMultiGenerationTeardownBarrier::{test}": (
                _posix_only("unlinks state.db under a live connection to mint a new inode; "
                            "Windows refuses to delete an open file (WinError 32)"),
            )
            for test in (
                "test_retired_drain_does_not_lift_a_pending_current_teardown",
                "test_replacement_is_not_published_before_the_last_close_settles",
            )
        },
        "tests/hermes_state/test_state_db_second_process_maintenance.py::"
        "test_holder_scan_sees_through_a_symlinked_home": (
            _posix_only("compares the holder to Popen(sys.executable).pid; a Windows venv "
                        "python.exe is a redirector, so the SQLite holder Restart Manager "
                        "names is its child (the scan itself resolves the alias)"),
        ),
        "tests/hermes_state/test_write_lock_owner_attribution.py::"
        "test_parse_proc_locks_keeps_only_write_locks_on_our_inodes_and_decodes_the_wal_write_byte": (
            _posix_only("Linux /proc/locks parsing keyed by os.makedev, which Windows lacks"),
        ),
        # Lane DROP-EXEC (2026-09-26): the Feishu adapter reverted to upstream bytes.
        **{
            f"tests/gateway/test_feishu.py::{test}": (
                _posix_only("FeishuAdapter.__init__ resolves get_hermes_home(); "
                            "patch.dict(os.environ, {}, clear=True) leaves no home on Windows"),
            )
            for test in (
                "TestAdapterBehavior::test_bot_origin_reactions_are_dropped_to_avoid_feedback_loops",
                "TestAdapterBehavior::test_build_event_handler_registers_reaction_and_card_processors",
                "TestAdapterBehavior::test_extract_audio_message_downloads_and_caches",
                "TestAdapterBehavior::test_extract_post_message_downloads_embedded_resources",
                "TestAdapterBehavior::test_extract_text_file_injects_content",
                "TestAdapterBehavior::test_extract_text_message_starting_with_slash_becomes_command",
                "TestAdapterBehavior::test_group_message_matches_bot_name_when_only_name_available",
                "TestAdapterBehavior::test_media_batch_merges_rapid_photo_messages",
                "TestAdapterBehavior::test_message_event_submits_to_adapter_loop",
                "TestAdapterBehavior::test_process_inbound_message_uses_event_sender_identity_only",
                "TestAdapterBehavior::test_reaction_on_peer_bot_message_is_not_routed",
                "TestAdapterBehavior::test_send_document_reply_uses_thread_flag",
                "TestAdapterBehavior::test_send_splits_fenced_code_blocks_into_separate_post_rows",
                "TestAdapterBehavior::test_send_uses_post_for_every_chunk_of_multi_chunk_markdown",
                "TestAdapterBehavior::test_text_batch_flushes_when_message_count_limit_is_hit",
                "TestAdapterBehavior::test_url_verification_requires_configured_verification_token",
                "TestAdapterBehavior::test_user_reaction_with_managed_emoji_is_still_routed",
                "TestAdapterBehavior::test_webhook_request_uses_same_message_dispatch_path",
                "TestDedupTTL::test_duplicate_within_ttl_is_rejected",
                "TestDedupTTL::test_persist_on_new_message_runs_off_event_loop_thread",
                "TestDeleteMessage::test_delete_message_calls_im_message_delete",
                "TestFeishuAdapterMessaging::test_connect_websocket_sets_channel_ua_tag_and_uses_owned_executor",
                "TestFeishuAdapterMessaging::test_edit_message_falls_back_to_text_when_post_update_is_rejected",
                "TestGroupMentionAtAll::test_at_all_still_requires_policy_gate",
                "TestPendingInboundQueue::test_drainer_replays_queued_events_when_loop_becomes_ready",
                "TestPendingInboundQueue::test_event_queued_when_loop_not_ready",
                "TestWebhookSecurity::test_rate_limit_resets_after_window_expires",
                "TestWebhookSecurity::test_signature_valid_passes",
                "TestWebhookSecurity::test_webhook_connect_requires_inbound_auth_secret",
                "TestWebhookSecurity::test_webhook_loads_auth_secrets_from_platform_extra",
            )
        },
    })

#: Upstream test modules that call a POSIX-only ``os`` attribute at IMPORT (a
#: ``skipif`` argument), so they cannot even collect on Windows. The fork lends
#: the attribute for that one module's import and takes it back; the tests the
#: condition guarded carry a ``_posix_only`` row. Retires with the open PR
#: branch ``up/win-posix-only-apis`` (the ``os.name != "nt" and`` form).
IMPORT_TIME_POSIX_SHIMS: dict[str, dict[str, object]] = {
    "tests/agent/test_prompt_builder.py": {"geteuid": lambda: -1},
} if _WIN else {}
