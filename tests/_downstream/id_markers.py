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
import os
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


# ── CARRY2B: tests/gateway ──────────────────────────────────────────────────
# Upstream tests that call monkeypatch.undo() mid-body run upstream's bytes with
# undo narrowed to their own patches (conftest_plugin.pytest_pyfunc_call, lane
# CARRY3); no sibling copy.
_SCOPED_UNDO = pytest.mark.scoped_monkeypatch_undo

ID_MARKS.update({
    "tests/gateway/test_api_server_active_work_drain.py::TestShutdownSettleWindow::"
    "test_api_work_still_live_at_settle_exit_is_reinterrupted": (_SCOPED_UNDO,),
    "tests/gateway/test_mirror.py::TestSessionsIndexProfileScoping::"
    "test_fallback_follows_active_profile_home": (_SCOPED_UNDO,),
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
})

# Upstream test files back at upstream's bytes: upstream's own Windows reds at
# the tag (X:/wt/_holds/upstream-reds-v2026.9.24.md). No open fork PR covers any.
_UP_RED = "upstream-red on Windows at v2026.9.24; no fix yet"


def _up_red(detail: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{_UP_RED} ({detail})")


def _up_red_skip(detail: str) -> pytest.MarkDecorator:
    """For a red that kills the process (a thread-method timeout), not an assertion."""
    return pytest.mark.skip(reason=f"{_UP_RED} ({detail})")


def _posix_xfail(detail: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, reason=f"{_POSIX_ONLY} ({detail})")


_LIFECYCLE_SCAN = _up_red(
    "the lifecycle guard reads a referenced script through a POSIX command "
    "string; a Windows path in it loses its separators (class c-E)"
)

if _WIN:
    ID_MARKS.update({
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
        "tests/hermes_cli/test_gateway_restart_loop.py::TestTerminalToolGatewayLifecycleGuard::"
        "test_non_regular_referenced_script_fails_closed": (_posix_xfail("os.mkfifo"),),
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
        "tests/hermes_cli/test_profiles.py::TestWrapperScript::test_creates_sh_on_posix": (
            _posix_xfail("the wrapper is mybot.bat on Windows; issue #83938"),
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
        "tests/hermes_cli/test_terminal_breadcrumbs.py": (_posix_xfail("os.ttyname"),),
        "tests/hermes_cli/test_update_autostash.py::"
        "test_cmd_update_ordinary_divergence_also_leaves_a_rescue_ref": (
            _up_red("reads the ref at argv[2], but Windows git argv carries "
                    "-c windows.appendAtomically=false"),
        ),
        "tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::"
        "test_activating_an_endpoint_carries_its_credential_either_way": (
            _up_red_skip("activation probes llm.modern.com live; the lookup outlives the "
                         "30 s thread timeout, which kills the process"),
        ),
    })


# An upstream custom-endpoint flow whose context probe resolves a fixture host
# over real DNS (fixture: conftest_plugin._no_ollama_show_probe).
ID_MARKS["tests/hermes_cli/test_custom_provider_model_switch.py::TestCustomProviderModelSwitch::"
         "test_custom_endpoint_switch_prunes_stale_model_config_pool_entry"] = (
    pytest.mark.no_ollama_show_probe,
)

# Upstream web-server tests whose restart / desktop-startup path runs the REAL
# gateway orphan reap and its 30 s exit wait (fixture: conftest_plugin).
ID_MARKS.update({
    node: (pytest.mark.no_real_orphan_reap,)
    for node in (
        "tests/hermes_cli/test_web_server.py::TestWebServerEndpoints::"
        "test_telegram_onboarding_apply_reports_restart_failure_after_save",
        "tests/hermes_cli/test_web_server.py::TestDesktopCronTicker::test_ticker_runs_when_desktop",
    )
})

# ── CARRY3: upstream tests that call monkeypatch.undo() mid-body (see _SCOPED_UNDO).
ID_MARKS.update({
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



# ── Lane REDS3: upstream's own Windows reds in byte-identical files, no fork PR
# covers any (X:/wt/_holds/upstream-reds-v2026.9.24.md, classes e-BR and e-ID).
# After the CARRY3 block: a row that already carries a mark keeps it.
_TCC_POSIX_VENV = _posix_xfail(
    "the fixture builds a POSIX venv (bin/, symlinked interpreters) and patches only "
    "platform.system; venv_python_path follows sys.platform to Scripts/python.exe"
)
if _WIN:
    for _node in (
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
    ):
        ID_MARKS[_node] = (*ID_MARKS.get(_node, ()), _TCC_POSIX_VENV)
    ID_MARKS.update({
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
    })

# ── Lane REDS3 (wave-close gate on 6251144d09): upstream's own Windows reds that the
# conftest reach now selects. Every id below is red at the tag on this box
# (X:/wt/_holds/upstream-reds-v2026.9.24.md, class in each reason) unless named.
if _WIN:
    ID_MARKS.update({
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
            'tests/hermes_cli/test_worktree_command.py::test_list_shows_worktrees',
            'tests/hermes_cli/test_worktree_pushed_tier.py::TestCronWorktreeMaintenance::test_repo_discovery_requires_worktrees_dir',
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
            'tests/hermes_cli/test_backup.py::TestImport::test_import_auto_installs_gateway_service',
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
            'tests/hermes_cli/test_tui_resume_flow.py::test_make_tui_argv_dev_prebuilds_hermes_ink',
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
            'tests/hermes_cli/test_restore_own_holder_guard.py::test_safe_restore_fallback_still_works_without_holder',
            'tests/hermes_cli/test_update_import_guard.py::test_import_probe_sees_a_stale_editable_finder_instead_of_the_checkout_cwd',
        )},
        "tests/hermes_cli/test_completion.py::TestGenerateBash::test_valid_bash_syntax": (
            pytest.mark.xfail(strict=True, reason=(
                "bash resolves a native temp path by POSIX rules and eats its backslashes; "
                "fixed by the open fork PR #121226 (shell invocation)")),
        ),
    })

#: Upstream test modules that call a POSIX-only ``os`` attribute at IMPORT (a
#: ``skipif`` argument), so they cannot even collect on Windows. The fork lends
#: the attribute for that one module's import and takes it back; the tests the
#: condition guarded carry a ``_posix_only`` row. Retires with the open PR
#: branch ``up/win-posix-only-apis`` (the ``os.name != "nt" and`` form).
IMPORT_TIME_POSIX_SHIMS: dict[str, dict[str, object]] = {
    "tests/agent/test_prompt_builder.py": {"geteuid": lambda: -1},
} if _WIN else {}

_NEEDS_ACP = pytest.mark.skipif(
    importlib.util.find_spec("acp") is None,
    reason="imports `acp` inside the test (agent-client-protocol, extra [acp]), "
    "which the canonical test venv does not carry; runs once it is installed",
)
ID_MARKS.update({
    "tests/acp_adapter/test_acp_dashboard_model_switch_validation.py": (_NEEDS_ACP,),
    "tests/acp_adapter/test_edit_approval.py::"
    "test_acp_permission_tool_call_uses_edit_kind_and_diff_content": (_NEEDS_ACP,),
    "tests/acp_adapter/test_failed_turn_closure.py::"
    "test_acp_refusal_closes_the_turn_and_is_not_replayed_into_the_next_prompt": (_NEEDS_ACP,),
})

if _WIN and not sys.flags.utf8_mode:
    # Probe, not platform: the red is the cp1252 locale, so it does not occur under
    # scripts/run_tests.sh / run_tests_bundled.sh, which export PYTHONUTF8=1 — there
    # an unconditional strict xfail XPASSes.
    ID_MARKS.update({
        f"tests/hermes_cli/test_kanban_core_functionality.py::{test}": (
            _up_red("write_text() of a non-ASCII worker log with no encoding= under the cp1252 locale: UnicodeEncodeError (class e-ENC)"),
        )
        for test in (
            "test_dead_worker_reap_surfaces_the_workers_own_last_output",
            "test_dead_worker_reap_reads_the_log_of_the_dispatching_board",
        )
    })

if _WIN:
    ID_MARKS.update({
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
        **{
        f"tests/agent/test_prompt_builder.py::{test}": (
            _posix_only("chmod(0) does not make a directory unreadable on Windows"),
        )
        for test in (
            "TestFindHermesMd::test_unreadable_cwd_is_treated_as_not_found",
            "TestCursorrulesCandidates::test_unreadable_cwd_is_treated_as_absent",
        )
        },
    })


#: Test directories whose modules import an OPTIONAL distribution at import. The
#: canonical test venv is the live install plus a test runner, and the live
#: install does not carry these extras, so the modules cannot collect there.
#: The probe is the import spec: the day the distribution is installed, the
#: modules collect and run again, with nothing here to delete. Only a module
#: whose collection FAILED on exactly that missing import is skipped; the rest
#: of the directory runs.
REQUIRES_DISTRIBUTION: dict[str, tuple[str, str]] = {
    "tests/acp_adapter/": ("acp", "agent-client-protocol, extra [acp]"),
}


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):  # noqa: D401 — pytest hook
    """Lend ``IMPORT_TIME_POSIX_SHIMS`` to one module's import, then take them back;
    turn a collection that failed on a ``REQUIRES_DISTRIBUTION`` import into a skip."""
    shims = IMPORT_TIME_POSIX_SHIMS.get(collector.nodeid)
    lent = [name for name in (shims or {}) if not hasattr(os, name)]
    for name in lent:
        setattr(os, name, shims[name])
    try:
        report = yield
    finally:
        for name in lent:
            delattr(os, name)
    return _skip_if_distribution_missing(collector, report)


def _skip_if_distribution_missing(collector, report):
    if not report.failed:
        return report
    for prefix, (module, distribution) in REQUIRES_DISTRIBUTION.items():
        if (
            collector.nodeid.startswith(prefix)
            and importlib.util.find_spec(module) is None
            and f"No module named '{module}'" in str(report.longrepr)
        ):
            from _pytest.reports import CollectReport

            reason = f"Skipped: optional distribution {distribution} is not installed (no `{module}`)"
            return CollectReport(report.nodeid, "skipped", (str(collector.path), 0, reason), [])
    return report


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
