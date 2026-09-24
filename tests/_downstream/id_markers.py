"""Markers the fork applies BY TEST ID to upstream test files it no longer edits.

Lane CARRY (2026-09-24): an upstream test file the fork used to edit in place
(a platform skip, an xfail, a timeout, a fork marker) is restored to upstream's
bytes, and the mark moves here. The file then leaves the ``[up-fp]`` ratchet and
the weekly merge stops conflicting on it.

``ID_MARKS`` maps a node id WITHOUT its parametrize suffix — or one WITH it,
which covers that parameter only, or a class id, which covers every test in the
class, or a bare file path, which covers every test in the file — to the marks
the fork applies. ``_WIN`` / ``_NOT_WIN`` rows are platform treatments; each names what
retires it. A row whose file is collected but whose id no longer exists is a
UsageError, not a silent no-op: an unmatched row would read as coverage it no
longer gives.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_WIN = sys.platform == "win32"

_PATH_SPELLING = (
    "upstream interpolates a Windows tmp_path into a JSON string literal "
    "(backslash-U and backslash-b are invalid escapes); fixed by the open PR "
    "up/win-path-spelling"
)
_WSL_FAKE = (
    "patches is_wsl but not platform.system/shutil.which, so a native-Windows "
    "host takes the Windows branch; the premise is a Linux (WSL) host"
)
_SEPARATOR_SPELLING = (
    "the tool under test (git worktree --porcelain, find via the POSIX shell) "
    "echoes forward slashes, upstream compares against str(Path) backslashes; "
    "a test-side spelling fix, PR candidate class win-path-spelling"
)
_CONTAINER_SPELLING = (
    "upstream spells a container path as str(tmp_path) and a warning's path via "
    "{!r}; on Windows tmp_path is drive-anchored (not POSIX-absolute) and repr "
    "doubles backslashes. Test-side spelling, PR candidate class win-path-spelling"
)
_TMP_LITERAL = (
    "upstream mocks gettempdir() as the literal \"/tmp\" and spells the operand "
    "unquoted; on Windows realpath(\"/tmp\") lands on the current drive and "
    "shlex eats the separators. Test-side spelling, PR candidate class "
    "win-path-spelling"
)
_FORK_SYSTEM_PATH = (
    "the fork's tools/environments/local.py _augment_windows_system_path appends "
    "the System32 dirs, so upstream's verbatim equality cannot hold on Windows; "
    "the fork's assertion is tests/tools/test_local_env_blocklist_downstream.py; "
    "retires with the G2 Windows-paths PR"
)

_POSIX_ONLY_LINUX = "POSIX-only; upstream fix = @pytest.mark.linux_only"
_FORK_LIVE_SYSTEM_GUARD = (
    "the fork's live-system guard (tests/conftest.py) refuses the spawn of a real "
    "`hermes dashboard` backend; the fork's in-process twin is the test's "
    "*_downstream.py sibling"
)
_FORK_PERSONA_CONFIG_SYNC = (
    "the fork's agent_runtime/persona_config_sync.py reads a pulled realm "
    "subtree's config.yaml raw (not this machine's user config); the fork-scope "
    "guard is tests/hermes_cli/test_config_read_guard_downstream.py"
)
_FORK_MANAGED_PYTHON = (
    "the fork's hermes_cli.gateway.resolve_managed_python replaces get_python_path "
    "in _build_gateway_argv, so upstream's patch no longer steers it; the fork twin "
    "is tests/hermes_cli/test_gateway_windows_downstream.py"
)
_FORK_SPAWN_DETACHED = (
    "the fork's hermes_cli.gateway_windows._spawn_detached(script_path) replaces "
    "upstream's breakaway retry; covered by tests/gateway/test_windows_gateway_spawn.py"
)
_WIN_REEXEC_BRANCH = (
    "cmd_dashboard re-execs via subprocess.Popen on win32 and upstream stubs only "
    "os.execvpe, so a real dashboard child is spawned (the fork's live-system guard "
    "refuses it); the twin stubbing both branches is "
    "tests/hermes_cli/test_dashboard_unified_launch_downstream.py"
)
_SQLITE_HANDLE_LEFT_OPEN = (
    "upstream's `with kbc.connect()` does not close the sqlite handle, and Windows "
    "refuses to rename a board directory with an open file (WinError 32/5); "
    "test-side fix = kbc.connect_closing, PR candidate class win-path-spelling"
)

#: Single source: the banner in ``hermes_cli_conftest._KNOWN_DEFECTS`` and the
#: strict xfail below carry this one string (ML-16).
TELEGRAM_PARITY_DEFECT_REASON = (
    "KNOWN DEFECT (owner call, not an environment gap): Slack's 50-slash app "
    "cap drops '/platform', a canonical gateway command with no native Slack "
    "slot, so Telegram/Slack parity cannot hold until an owner either pins it "
    "a slot (something else loses one) or declares it _SLACK_VIA_HERMES_ONLY. "
    "strict=True: the day parity holds, this XPASSes and reds — delete the "
    "mark and this row. Full account: _KNOWN_DEFECTS in "
    "tests/hermes_cli/conftest.py."
)

_CREDENTIALS_FILE = pytest.mark.allow_claude_code_credentials_file
_REAL_PAUSE = pytest.mark.real_windows_gateway_pause

ID_MARKS: dict[str, tuple[pytest.MarkDecorator, ...]] = {
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
    # The fork makes the background follow-up agent turn opt-in
    # (HERMES_BACKGROUND_AGENT_TURNS); these upstream witnesses pin that turn
    # (fixture: tests/_downstream/hermes_cli_conftest.py).
    "tests/hermes_cli/test_process_notification_display.py::"
    "test_process_completion_display_keeps_payload_separate_across_surfaces": (
        pytest.mark.background_agent_turns,
    ),
    "tests/hermes_cli/test_subagent_notification_display.py::"
    "test_completion_display_keeps_payload_separate_across_surfaces": (
        pytest.mark.background_agent_turns,
    ),
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
}

if _WIN:
    ID_MARKS.update({
        "tests/hermes_cli/test_dashboard_unified_launch.py::TestUnifiedDashboardRouting::"
        "test_profile_launch_reexecs_machine_dashboard": (
            pytest.mark.xfail(reason=_WIN_REEXEC_BRANCH, strict=True),
        ),
        "tests/hermes_cli/test_kanban_boards.py::TestBoardCRUD::"
        "test_remove_clears_init_cache_for_recreated_db": (
            pytest.mark.xfail(reason=_SQLITE_HANDLE_LEFT_OPEN, strict=True),
        ),
        "tests/hermes_cli/test_relaunch.py::TestRelaunch::test_calls_execvp": (
            pytest.mark.skip(reason=_POSIX_ONLY_LINUX),
        ),
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
        "tests/tools/test_local_env_blocklist.py::TestSanePathIncludesHomebrew::"
        "test_make_run_env_preserves_windows_mixed_case_path_key": (
            pytest.mark.xfail(reason=_FORK_SYSTEM_PATH, strict=True),
        ),
        "tests/hermes_cli/test_kanban_db.py::"
        "test_worktree_workspace_explicit_target_materializes_linked_worktree": (
            pytest.mark.xfail(reason=_SEPARATOR_SPELLING, strict=True),
        ),
        "tests/tools/test_file_operations.py::TestSearchFilesFallbackHiddenPaths::"
        "test_hidden_root_with_hidden_ancestor_includes_files": (
            pytest.mark.xfail(reason=_SEPARATOR_SPELLING, strict=True),
        ),
        "tests/tools/test_file_operations.py::TestSearchFilesFallbackHiddenPaths::"
        "test_normal_root_still_excludes_hidden_descendants": (
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
        "tests/tools/test_voice_mode.py::TestDetectAudioEnvironment::"
        "test_wsl_without_pulse_blocks_voice": (pytest.mark.skip(reason=_WSL_FAKE),),
        "tests/tools/test_voice_mode.py::TestWSL2PowerShellFallback::"
        "test_powershell_pipeline_preserves_real_exit_status": (
            pytest.mark.skip(reason=_WSL_FAKE),
        ),
        "tests/tools/test_voice_mode.py::TestWSL2PowerShellFallback::"
        "test_wsl2_unique_temp_filename": (pytest.mark.skip(reason=_WSL_FAKE),),
    })


# ── Lane CARRY2B: upstream test files outside tests/hermes_cli ─────────────
#
#: Prefix of every row that skips an upstream test because it is POSIX-only
#: (not because of fork behaviour); the tests-PR lane turns these rows into
#: upstream platform marks.
_POSIX_ONLY = "POSIX-only; upstream fix = @pytest.mark.linux_only"


def _posix_only(detail: str) -> pytest.MarkDecorator:
    return pytest.mark.skip(reason=f"{_POSIX_ONLY} ({detail})")


_CONFIG_READ_THROUGH = pytest.mark.config_reads_through_load_config
_LOOKALIKE = pytest.mark.spawns_gateway_lookalike
_TIRITH_NO_BUILD = _posix_only(
    "tirith ships no Windows build: _detect_target() is None and every entry "
    "point short-circuits to allow before the behaviour under test"
)

ID_MARKS.update({
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
    # sh runs the extracted stage2 keygen text in a tmp HERMES_HOME; the fork's
    # _live_system_guard argv classifier reads "gateway" in its comments.
    **{
        f"tests/tools/test_stage2_hook_api_server_keygen.py::{test}": (_LOOKALIKE,)
        for test in (
            "test_keygen_appends_to_existing_env_without_key",
            "test_keygen_never_overwrites_operator_key",
            "test_keygen_refuses_symlinked_env",
            "test_keygen_skips_when_container_env_provides_key",
            "test_keygen_env_key_with_existing_env_file_key_warns_not_clobbers",
            "test_keygen_env_key_drops_stale_empty_assignment",
            "test_keygen_warns_on_weak_container_env_key",
            "test_keygen_weak_env_key_warning_suppressed_when_env_file_key_wins",
        )
    },
})

if _WIN:
    ID_MARKS.update({
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
                "TestFailedDownloadCaching",
                "TestExplicitPathNoAutoDownload",
                "TestBackgroundInstall",
                "TestSpawnWarningDedup",
                "TestAppTldSuppression",
                "TestMkdtempOSErrorNoSpace",
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
    })


# ── CARRY2B: tests/gateway (+ tui_gateway's agent-turn lane) ───────────────
_AGENT_TURNS = pytest.mark.background_agent_turns
_MIDTEST_UNDO = pytest.mark.skip(reason=(
    "calls monkeypatch.undo(), which unwinds the shared per-test MonkeyPatch "
    "(the root conftest's hermetic pins included) and is red under the fork's "
    "_shared_monkeypatch_pin_tripwire; the scoped-context version is the "
    "_downstream sibling"
))

ID_MARKS.update({
    **{
        node: (_AGENT_TURNS,)
        for node in (
            "tests/gateway/test_completion_session_boundary.py::"
            "test_watcher_stamps_parent_session_id_on_completion_event",
            "tests/gateway/test_completion_session_boundary.py::"
            "test_watcher_falls_back_to_process_session_stamp",
            "tests/gateway/test_completion_session_boundary.py::"
            "test_completion_after_idle_end_still_delivers",
            "tests/gateway/test_completion_session_boundary.py::"
            "test_completion_from_live_session_delivers",
            "tests/gateway/test_completion_session_boundary.py::"
            "test_unstamped_legacy_completion_delivers",
            "tests/gateway/test_completion_delivery.py::"
            "test_autonomous_completion_redacts_real_command_and_output_secrets",
            "tests/gateway/test_completion_delivery.py::"
            "test_concurrent_process_watchers_coalesce_one_session_completion_turn",
            "tests/gateway/test_internal_event_bypass_pairing.py::"
            "test_notify_on_complete_uses_session_store_origin_for_group_topic",
            "tests/tui_gateway/test_kanban_notify_poller.py::"
            "TestNotificationPollerLoopKanbanWiring",
        )
    },
    "tests/gateway/test_api_server_active_work_drain.py::TestShutdownSettleWindow::"
    "test_api_work_still_live_at_settle_exit_is_reinterrupted": (_MIDTEST_UNDO,),
    "tests/gateway/test_mirror.py::TestSessionsIndexProfileScoping::"
    "test_fallback_follows_active_profile_home": (_MIDTEST_UNDO,),
    "tests/gateway/test_background_process_notifications.py::"
    "TestLoadBackgroundNotificationsMode::test_unknown_mode_falls_back_to_concise": (
        pytest.mark.xfail(strict=True, reason=(
            "the fork's gateway.run_config_loaders._load_background_notifications_mode "
            "falls back to 'result'; fork half: "
            "tests/gateway/test_background_process_notifications_downstream.py"
        )),
    ),
    # DEPENDENCY-bound: plugins/platforms/wecom/callback_adapter.py falls back
    # to ET=None without defusedxml; installing it retires these.
    **{
        f"tests/gateway/test_wecom_callback.py::{node}": (
            pytest.mark.skipif(
                importlib.util.find_spec("defusedxml") is None,
                reason="optional dependency 'defusedxml' is not installed",
            ),
        )
        for node in (
            "TestWecomCallbackEventConstruction::test_build_event_extracts_text_message",
            "TestWecomCallbackPollLoop::test_poll_loop_dispatches_handle_message",
        )
    },
})

if _WIN:
    ID_MARKS.update({
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
    })


# ── CARRY2B: agent, hermes_state, plugins, providers, cron, scripts, tui_gateway, tests/*.py
_CLAUDE_HOME_TMP = pytest.mark.claude_home_is_tmp_path


def _fork_replaces(symbol: str, sibling: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=(
        f"the fork's {symbol} makes this upstream assertion false; fork half: {sibling}"
    ))


ID_MARKS.update({
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
        node: (_MIDTEST_UNDO,)
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
    # The module cannot collect on Windows (os.geteuid at import; fork-hygiene
    # row filed), so this row is checked on POSIX only.
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
    **{
        f"tests/tui_gateway/test_tui_gateway_server.py::{test}": (_AGENT_TURNS,)
        for test in (
            "test_notification_poller_live_loop_requeues_foreign_completion_for_owner",
            "test_notification_poller_delivers_owned_events",
            "test_run_prompt_submit_delivers_completion_observed_by_poll",
            "test_run_prompt_submit_requeues_all_unstarted_notifications_with_real_threading",
            "test_run_prompt_submit_delivers_completion_owned_through_compression_lineage",
            "test_run_prompt_submit_prefers_origin_ui_session_id",
            "test_notification_poller_delivers_completion",
            "test_notification_poller_requeues_when_busy",
            "test_notification_poller_emits_distinct_watch_matches_once",
        )
    },
    # The fork runs the whole tree under --timeout=30; these PowerShell
    # harnesses carry their own child budgets above that.
    "tests/scripts/desktop_update/test_desktop_update_windows_cwd.py": (pytest.mark.timeout(75),),
    "tests/scripts/desktop_update/test_desktop_update_windows_progress.py": (pytest.mark.timeout(120),),
    "tests/scripts/desktop_update/test_desktop_update_windows_ui_delivery.py": (pytest.mark.timeout(75),),
    "tests/scripts/desktop_update/test_desktop_update_windows_pipe_drain.py::"
    "test_update_step_survives_pipe_leak_flood_and_live_child_stall": (pytest.mark.timeout(330),),
    "tests/scripts/install/test_install_ps1_managed_python_provenance.py::"
    "test_python_find_timeout_kills_uv_and_fails_stage": (pytest.mark.timeout(60),),
})


ID_MARKS.update({
    "tests/tools/test_tool_search_multiquery.py::TestBatchedDescribe::"
    "test_registered_direct_surface_name_keeps_exact_error": (
        _fork_replaces(
            "tools.tool_search.dispatch_tool_describe (details for an in-session direct tool)",
            "tests/tools/test_tool_search_multiquery_downstream.py",
        ),
    ),
})

if _WIN:
    ID_MARKS.update({
        "tests/tools/test_file_operations.py::TestShellFileOpsHelpers::"
        "test_escape_shell_arg_rewrites_forward_slash_native_paths": (
            _fork_replaces(
                "ShellFileOperations._escape_shell_arg (native Windows paths, no /c/ rewrite)",
                "tests/tools/test_file_operations_downstream.py",
            ),
        ),
    })


# ── Lane REDS2: the fork-scope gate over the 2026-09-24 wave ───────────────
#
#: A live-machine premise, not a platform one: the test reads the REAL fleet
#: process table and needs it to hold no hermes gateway (``pytest_runtest_setup``).
NO_LIVE_GATEWAY_MARK = "requires_no_live_gateway"

ID_MARKS.update({
    # The fork's doctor_config reads config.yaml from get_hermes_home() at call
    # time, so upstream's patch of doctor.HERMES_HOME no longer selects the file.
    "tests/hermes_cli/test_doctor.py::test_run_doctor_vendor_slug_policy_for_openai_api_endpoint"
    "[https://api.openai.com/v1-True]": (
        _fork_replaces(
            "hermes_cli.doctor_config._check_config_file (home resolved at call time)",
            "tests/hermes_cli/test_doctor_downstream.py",
        ),
    ),
})

if _WIN:
    ID_MARKS.update({
        # Upstream's own contract lets a `spawns_gateway_lookalike` test spawn a
        # `gateway run` stand-in (tests/conftest.py honours it); the fork's
        # tests/hermes_cli/_gateway_fence.py arming fixture does not.
        "tests/hermes_cli/test_plan_reconciliation_windows_live.py::"
        "test_plan_reconciliation_live_windows": (
            pytest.mark.xfail(strict=True, reason=(
                "the fork's tests/hermes_cli gateway fence refuses the "
                "`hermes gateway run` stand-in that the module's "
                "spawns_gateway_lookalike mark permits under upstream's guard"
            )),
        ),
    })


def _base_id(nodeid: str) -> str:
    return nodeid.split("[", 1)[0]


def _keys_for(base: str) -> list[str]:
    """``a::B::c`` -> ``["a::B::c", "a::B", "a"]``: the test id, each enclosing class, the file."""
    parts = base.split("::")
    return ["::".join(parts[:n]) for n in range(len(parts), 0, -1)]


def ids_marked(mark_name: str) -> set[str]:
    """Table ids carrying *mark_name* on this host (read by the fork's gates)."""
    return {
        node for node, marks in ID_MARKS.items()
        if any(mark.name == mark_name for mark in marks)
    }


def _narrowed_files(config) -> set[str]:
    """Files the command line narrowed to single ids (``file::test``)."""
    out: set[str] = set()
    for arg in config.args:
        if "::" not in arg:
            continue
        path = Path(arg.split("::", 1)[0])
        try:
            path = path.resolve().relative_to(config.rootpath.resolve())
        except (OSError, ValueError):
            pass
        out.add(path.as_posix())
    return out


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):  # noqa: D401 — pytest hook
    """Apply ``ID_MARKS`` before upstream's own modifyitems reads the marks."""
    matched: set[str] = set()
    collected_files: set[str] = set()
    for item in items:
        base = _base_id(item.nodeid)
        collected_files.add(base.split("::", 1)[0])
        exact = [item.nodeid] if item.nodeid != base else []
        for key in exact + _keys_for(base):
            marks = ID_MARKS.get(key)
            if marks is None:
                continue
            matched.add(key)
            for mark in marks:
                item.add_marker(mark)
    checkable = collected_files - _narrowed_files(config)
    stale = sorted(
        node for node in ID_MARKS
        if node not in matched and node.split("::", 1)[0] in checkable
    )
    if stale:
        raise pytest.UsageError(
            "tests/_downstream/id_markers.py names test ids that no longer exist "
            "in their (collected) file; delete or re-point the rows:\n  "
            + "\n  ".join(stale)
        )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):  # noqa: D401 — pytest hook
    """Skip a ``requires_no_live_gateway`` test on a machine running a gateway.

    Runs before any fixture, so it reads the real process table the test will
    read. A live gateway there (the operator's, or a sibling lane's) is found by
    the fleet-wide liveness poll and vouches for whatever the test relaunched.
    """
    if item.get_closest_marker(NO_LIVE_GATEWAY_MARK) is None:
        return
    from hermes_cli.gateway import find_gateway_pids

    live = sorted(find_gateway_pids(all_profiles=True))
    if live:
        pytest.skip(
            f"a hermes gateway runs on this machine (pid {live}); the test needs "
            "a fleet with none, because the liveness poll it asserts on is fleet-wide"
        )
