# Planned - upstream-ready test-fix classes (2026-09-23)

Disposition pass over the 177 in-place-edit files of [`seam-s4-s5-s6-inventory-2026-09-23.md`](seam-s4-s5-s6-inventory-2026-09-23.md) 1.3. Base for fork hunks: the merge base `d337b736aa`, diffed to `origin/main` @ `a78027236d`. Branches cut from `upstream/main` @ `35b14ad5e2`; each is one commit, pushed to `origin`, no PR opened, and each `git cherry-pick --no-commit` onto `upstream/main` @ `c22b0a240f` exited 0. Every touched file was run with pytest on Windows (Python 3.12.5) on the `upstream/main` tree before and after; no test that passed before fails after.

## Classes lifted

| Class | Branch | Commit | Files | What |
|---|---|---|---|---|
| A | ~~`up/win-text-encoding`~~ dropped 2026-09-24 | `48a7527049` | 9 | encoding — hunks stay in the fork as `carry` |
| B | `up/win-line-endings` | `92bb0b99bd` | 7 | line endings |
| C | `up/win-tilde-home` | `d8dcb0664b` | 5 | ~ / USERPROFILE |
| D | `up/win-path-spelling` | `4af8c623ff` | 13 | path spelling |
| E | `up/win-shell-invocation` | `dc3b38ab36` | 10 | shell / executable resolution |
| F | `up/win-posix-only-apis` | `7032d7bd5d` | 4 | POSIX-only os APIs / mode bits |
| G | `up/win-env-var-case` | `610feaef09` | 2 | env-var name case |
| H | ~~`up/monkeypatch-undo-scoped`~~ dropped 2026-09-24 | `abbe273ab9` | 13 | mid-test monkeypatch.undo() — hunks stay in the fork as `carry` |
| K | `up/import-guard-relative-imports` | `b26e8ecfd2` | 1 | import-guard relative imports |
| L | `up/win-conpty-line-wrap` | `98233cbb75` | 1 | ConPTY line wrap |

**Dropped 2026-09-24 (lane UPREV, never opened):** classes A and H will not go upstream — upstream's `run_tests.sh` sets `PYTHONUTF8=1` (A) and neither class reproduces a red there (H). The branches are deleted from `origin`; their files' fork hunks are dispositioned `carry` with reason "PR dropped 2026-09-24: …" in the Upstream Sync ledger (`Harness_Brain/10 — Programs/Upstream Sync.md`), which is the authority for each file from here. The per-file rows below keep their class letter as provenance. The two other dropped branches, `up/profile-home-generic` (P7) and `up/profiles-delete-guard` (P6), were never classes of this doc.

Files with at least one lifted hunk: **62**. Files with nothing lifted: **115**.

## Not upstreamable - reasons

| Code | Files (nothing lifted) | Reason |
|---|---|---|
| R1 | 37 | tracks fork-only production code (the hunk only makes sense against a fork change) |
| R2 | 18 | fork test infrastructure: fork conftest fixtures, fork markers or fork live-system guards |
| R3 | 6 | fakes the host OS (sys.platform / _IS_WINDOWS / platform.system patch) - upstream AGENTS.md 'Don't fake the host OS' forbids it |
| R4 | 6 | marker-only: adds @pytest.mark.linux_only to skip rather than fix; needs per-test proof the behaviour is Linux-specific |
| R5 | 10 | fork doc/comment repoint or fork-gate-driven rewrite (MCF ids, fork notes, spell-gate obfuscation, source-reading gate rewrite) |
| R6 | 7 | file gone upstream, or deleted by the fork |
| R7 | 8 | pytest-timeout marker that only matters under the fork's repo-wide --timeout=30 |
| R8 | 5 | already fixed upstream since the merge base |
| R9 | 16 | no Windows failure reproduced on upstream/main, or covered by upstream's per-file subprocess isolation + `env -i` runner |
| R10 | 2 | correct change but the test stays red on Windows for another reason; not claimable yet |

Also not lifted as classes: a state-leak class (sys.modules restore, AWS scrub, relaunch argv; R9 - upstream's `scripts/run_tests.sh` runs each file under `env -i` in its own subprocess) and a timing class (R7/R8 - upstream relaxed `test_mcp_startup` to 2.0 s itself, and the rest are sized for the fork's runner).

## Per file

`Lifted` names the class(es) above; `Rest` is the reason code for hunks that were not lifted.

| File | Lifted | Rest | Note |
|---|---|---|---|
| `tests/agent/conftest.py` | - | R2 | fork retry/backoff + isolation fixtures (seam inventory 1.4) |
| `tests/agent/lsp/test_workspace.py` | C | - |  |
| `tests/agent/test_anthropic_adapter.py` | - | R2 | allow_claude_code_credentials_file marker (MCF-66) |
| `tests/agent/test_anthropic_borrowed_row_authority.py` | - | R2 | same marker |
| `tests/agent/test_anthropic_credential_persist_failure.py` | H | R2 | undo hunk lifted; marker hunk is fork |
| `tests/agent/test_anthropic_keychain.py` | - | R2 | same marker |
| `tests/agent/test_anthropic_spent_rotation_verdict.py` | - | R2 | same marker |
| `tests/agent/test_canon_args_memo_parity.py` | H | - |  |
| `tests/agent/test_coding_context.py` | B | - |  |
| `tests/agent/test_compression_adoption_preserves_live_tail.py` | - | R5 | docstring points at a fork-renamed test file |
| `tests/agent/test_curator_classification.py` | - | R9 | passes on upstream/main (the em-dash assertions moved) |
| `tests/agent/test_file_safety_sandbox_mirror.py` | D | - |  |
| `tests/agent/test_image_routing.py` | C | - | test_finds_absolute_path stays red (not a fork hunk) |
| `tests/agent/test_nous_oauth_401_guidance.py` | - | R6 | gone upstream |
| `tests/agent/test_provider_fallback.py` | - | R5 | MCF-78 docstring |
| `tests/agent/test_proxy_and_url_validation.py` | G | - |  |
| `tests/agent/test_save_url_image.py` | D | - |  |
| `tests/agent/test_shell_hooks_consent.py` | C | - |  |
| `tests/agent/test_skill_commands.py` | E | R8 | pwd -W lifted; supporting-files hunk targets a test upstream deleted |
| `tests/conftest.py` | - | R2 | fork hermetic fixtures, live-system guard, temp-root redirect |
| `tests/cron/test_cron_memory_contract.py` | - | R5 | docstring node-id repoint |
| `tests/cron/test_cron_profile_isolation.py` | H | - |  |
| `tests/docker/test_dashboard.py` | - | R5 | MCF-78 comment repoint |
| `tests/e2e/conftest.py` | - | R1 | _queued_events runner attribute |
| `tests/e2e/matrix_xsign_bootstrap/test_bootstrap.py` | - | R6 | gone upstream; hunk is spell-gate obfuscation |
| `tests/gateway/conftest.py` | - | R2 | fork fixtures |
| `tests/gateway/test_api_server_active_work_drain.py` | H | - |  |
| `tests/gateway/test_completion_delivery.py` | - | R1 | checkpoint_path + background-agent-turns default |
| `tests/gateway/test_completion_session_boundary.py` | - | R1 | background-agent-turns default |
| `tests/gateway/test_compression_deferred_soft_result.py` | - | R6 | gone upstream |
| `tests/gateway/test_config_env_bridge_authority.py` | - | R9 | SystemRoot spelling; passes upstream |
| `tests/gateway/test_cron_interrupt_notification.py` | - | R1 | _cron_drain_timeout is fork |
| `tests/gateway/test_internal_event_bypass_pairing.py` | - | R1 | HERMES_BACKGROUND_AGENT_TURNS is fork |
| `tests/gateway/test_matrix.py` | - | R5 | TrustState spell-gate obfuscation |
| `tests/gateway/test_matrix_approval_reaction_fail_closed.py` | - | R5 | same |
| `tests/gateway/test_media_resend_dedup.py` | D | - |  |
| `tests/gateway/test_media_spaced_paths_and_history_dedupe.py` | C | - |  |
| `tests/gateway/test_mirror.py` | H | - |  |
| `tests/gateway/test_platform_reconnect.py` | - | R1 | bounded boot-send tasks are fork |
| `tests/gateway/test_post_stream_media_delivery.py` | D | - |  |
| `tests/gateway/test_runtime_footer.py` | C+D | - | tilde tests in C, POSIX cwd literals in D |
| `tests/gateway/test_session_state_cleanup.py` | - | R9 | passes upstream |
| `tests/gateway/test_status_command.py` | - | R9 | passes upstream |
| `tests/gateway/test_update_command.py` | A | R5 | known-command rewrite is a merge-drift overwrite of upstream's own fix |
| `tests/hermes_cli/conftest.py` | - | R2 | fork fixtures (1,266 lines) |
| `tests/hermes_cli/test_active_sessions.py` | - | R7 | bounds sized for the fork runner + timeout marker |
| `tests/hermes_cli/test_auth_nous_provider.py` | F | - |  |
| `tests/hermes_cli/test_auth_ssl_macos.py` | - | R2 | NOTE (fork) sys.path comment |
| `tests/hermes_cli/test_backup.py` | D+F | R10 | kanban path in D, chmod spy in F; .bat wrapper hunk not lifted (other tests in the class stay red) |
| `tests/hermes_cli/test_cmd_update.py` | - | R1 | history guard is fork |
| `tests/hermes_cli/test_codex_cli_model_picker.py` | - | R2 | credentials marker |
| `tests/hermes_cli/test_codex_runtime_plugin_migration.py` | A | - |  |
| `tests/hermes_cli/test_completion.py` | E | - |  |
| `tests/hermes_cli/test_cross_profile_kill_refusal.py` | - | R6 | deleted by the fork |
| `tests/hermes_cli/test_curator_recent_run_notice.py` | - | R9 | reload removal; no upstream failure |
| `tests/hermes_cli/test_dashboard_auth_gate.py` | - | R9 | app.state restore; no upstream failure |
| `tests/hermes_cli/test_debug.py` | B | - |  |
| `tests/hermes_cli/test_deleted_profile_tombstone.py` | D | - |  |
| `tests/hermes_cli/test_diff_command.py` | B | - |  |
| `tests/hermes_cli/test_doctor_command_install.py` | - | R1 | doctor HERMES_HOME resolution is fork |
| `tests/hermes_cli/test_doctor_journal_modes.py` | F | R4 | geteuid + strerror lifted; bare win32 skipif and kanban relative_to hunk not lifted |
| `tests/hermes_cli/test_doctor_live.py` | - | R1 | same |
| `tests/hermes_cli/test_early_recovery.py` | K | - |  |
| `tests/hermes_cli/test_env_export_prefix.py` | - | R9 | reload removal; per-file isolation upstream |
| `tests/hermes_cli/test_fireworks_provider.py` | - | R1 | doctor HERMES_HOME |
| `tests/hermes_cli/test_gateway_job_teardown_live.py` | - | R7 |  |
| `tests/hermes_cli/test_gateway_migrate_multiplex.py` | - | R4 |  |
| `tests/hermes_cli/test_gateway_service.py` | - | R2 | rewrite driven by the fork live-system guard (ML-14) |
| `tests/hermes_cli/test_gmi_provider.py` | - | R1 | doctor HERMES_HOME |
| `tests/hermes_cli/test_kanban_boards.py` | - | R1 | connect_closing is fork |
| `tests/hermes_cli/test_kanban_cli_dispatch_passthrough.py` | - | R9 | sys.modules restore; per-file isolation upstream |
| `tests/hermes_cli/test_kanban_core_functionality.py` | - | R1 | Windows reaper poll branch |
| `tests/hermes_cli/test_kanban_default_assignee.py` | - | R8 | upstream rewrote the fixture |
| `tests/hermes_cli/test_kanban_per_profile_cap.py` | - | R9 | sys.modules restore |
| `tests/hermes_cli/test_kanban_reclaim_claim_lock_guard.py` | - | R9 | true/sleep resolve via Git on PATH; passes |
| `tests/hermes_cli/test_kanban_review_lifecycle.py` | - | R9 | **_ fake signature; passes upstream |
| `tests/hermes_cli/test_kanban_worker_pid_fingerprint.py` | H | - |  |
| `tests/hermes_cli/test_kanban_worktree_teardown.py` | - | R4 |  |
| `tests/hermes_cli/test_lazy_command_exports.py` | - | R2 | real_windows_gateway_pause marker |
| `tests/hermes_cli/test_linux_desktop_entry.py` | - | R4 | 19 markers |
| `tests/hermes_cli/test_local_quickstart.py` | - | R1 | catalog refresh stub |
| `tests/hermes_cli/test_local_runtime.py` | - | R1 | unload confirmation is fork |
| `tests/hermes_cli/test_macos_tcc_anchor.py` | H | - |  |
| `tests/hermes_cli/test_mcp_startup.py` | - | R8 | upstream relaxed the stopwatch to 2.0 s |
| `tests/hermes_cli/test_node_runtime_npm_resolution.py` | - | R4 |  |
| `tests/hermes_cli/test_noninteractive_git.py` | - | R8 | upstream removed the vacuous `or True` |
| `tests/hermes_cli/test_nous_inference_url_validation.py` | - | R5 | source-reading gate rewrite (banned upstream) |
| `tests/hermes_cli/test_orphan_desktop_serve_reap.py` | - | R4 |  |
| `tests/hermes_cli/test_process_notification_display.py` | - | R1 | background agent turns |
| `tests/hermes_cli/test_profile_delete_log_handlers.py` | - | R9 | **__ stub signature; passes upstream |
| `tests/hermes_cli/test_projects_db.py` | D | - |  |
| `tests/hermes_cli/test_prompt_compose_command.py` | E | - |  |
| `tests/hermes_cli/test_relaunch.py` | - | R3 | platform hunk fakes linux; argv fixture showed no failure (R9) |
| `tests/hermes_cli/test_relay_shared_metrics.py` | - | R7 |  |
| `tests/hermes_cli/test_resolve_provider_openrouter_pool.py` | - | R9 | AWS scrub already in tests/conftest.py + env -i |
| `tests/hermes_cli/test_setup_blank_slate.py` | - | R1 | skill_search/tool_describe toolsets |
| `tests/hermes_cli/test_setup_hermes_script.py` | E | - |  |
| `tests/hermes_cli/test_setup_matrix_e2ee.py` | - | R6 | gone upstream |
| `tests/hermes_cli/test_skin_cmd.py` | A | - |  |
| `tests/hermes_cli/test_stderr_timestamp.py` | - | R6 | deleted by the fork |
| `tests/hermes_cli/test_subagent_notification_display.py` | - | R1 | background agent turns |
| `tests/hermes_cli/test_subprocess_timeouts.py` | A | - |  |
| `tests/hermes_cli/test_tui_resume_flow.py` | B | - |  |
| `tests/hermes_cli/test_update_autostash.py` | - | R2 | stubs the fork's venv-process walk cost |
| `tests/hermes_cli/test_update_concurrent_quarantine.py` | - | R2 | real_windows_gateway_pause marker |
| `tests/hermes_cli/test_update_fleet_restart_pending.py` | - | R1 | fleet settle clock |
| `tests/hermes_cli/test_update_serve_generation_recovery.py` | - | R4 |  |
| `tests/hermes_cli/test_update_stale_dashboard.py` | - | R3 |  |
| `tests/hermes_cli/test_update_zip_two_phase.py` | H | - |  |
| `tests/hermes_cli/test_voice_wrapper.py` | - | R2 | NOTE (fork) sys.path comment |
| `tests/hermes_cli/test_win_pty_bridge.py` | L | - |  |
| `tests/hermes_cli/test_worktree_sync_base.py` | - | R5 | comment cites fork archive note |
| `tests/hermes_cli/test_xai_provider_labels.py` | - | R8 | upstream made the assertion relative |
| `tests/hermes_state/test_append_messages_batch.py` | H | - |  |
| `tests/hermes_state/test_retired_wal_generation_capture.py` | H | - |  |
| `tests/hermes_state/test_session_db_read_conn_pool.py` | H | - |  |
| `tests/plugins/dashboard_auth/test_self_hosted_provider.py` | - | R1 | load_config_readonly caller is fork (96cfc09a34) |
| `tests/plugins/memory/test_holographic_store.py` | H | - |  |
| `tests/plugins/platforms/photon/test_sidecar_paths.py` | H | - |  |
| `tests/providers/test_entry_point_discovery.py` | - | R1 | plugins_discovery module is fork |
| `tests/scripts/desktop_update/test_desktop_update_windows_cwd.py` | - | R7 |  |
| `tests/scripts/desktop_update/test_desktop_update_windows_pipe_drain.py` | - | R7 |  |
| `tests/scripts/desktop_update/test_desktop_update_windows_progress.py` | - | R7 |  |
| `tests/scripts/desktop_update/test_desktop_update_windows_retry_policy.py` | - | R1 | history-refusal arm + R7 marker |
| `tests/scripts/desktop_update/test_desktop_update_windows_ui_delivery.py` | - | R7 |  |
| `tests/scripts/install/test_install_ps1_managed_python_provenance.py` | - | R7 |  |
| `tests/tools/conftest.py` | - | R2 | fork fixtures |
| `tests/tools/test_approved_command_clean_slate.py` | E | - |  |
| `tests/tools/test_async_delegation.py` | - | R1 | explicit restore_durable_completions (96cfc09a34) |
| `tests/tools/test_base_environment.py` | - | R10 | bash resolution correct; 0600 test then fails on NTFS mode bits; concurrency tests deleted upstream |
| `tests/tools/test_browser_console.py` | - | R1 | load_config_readonly |
| `tests/tools/test_browser_homebrew_paths.py` | - | R1 | dep_ensure stub |
| `tests/tools/test_checkpoint_manager.py` | D | - |  |
| `tests/tools/test_completed_process_results.py` | - | R1 | follow-up wording |
| `tests/tools/test_computer_use.py` | D | R3 | json.dumps lifted; gnome-shell hunk fakes linux |
| `tests/tools/test_cron_approval_mode.py` | - | R1 | tirith_config resolution is fork |
| `tests/tools/test_delegate.py` | - | R5 | docstring path |
| `tests/tools/test_docker_config_migrate.py` | A | - |  |
| `tests/tools/test_execute_helper_contract.py` | - | R1 | tool_describe (T6b) |
| `tests/tools/test_execution_flag_detection.py` | E | R8 | second hunk annotates a test upstream deleted |
| `tests/tools/test_file_ops_cwd_tracking.py` | - | R10 | _find_bash is right but the test still fails at a later line |
| `tests/tools/test_file_tools_cwd_resolution.py` | - | R9 | container-spelling rewrite; not in the baseline red set |
| `tests/tools/test_file_tools_live.py` | B+E | - | cat case needs both; tilde_exact in E |
| `tests/tools/test_file_tools_tilde_profile.py` | D | - |  |
| `tests/tools/test_find_shell.py` | - | R3 |  |
| `tests/tools/test_image_generation.py` | - | R1 | load_config_readonly |
| `tests/tools/test_interrupt.py` | - | R5 | docstring path |
| `tests/tools/test_llm_content_none_guard.py` | - | R8 | upstream rewrote the source read |
| `tests/tools/test_local_background_child_hang.py` | E | - |  |
| `tests/tools/test_local_env_blocklist.py` | - | R3 | posix_path_arm/windows_path_arm fake _IS_WINDOWS + os.pathsep |
| `tests/tools/test_local_env_cwd_recovery.py` | D | - |  |
| `tests/tools/test_local_env_relative_cwd.py` | E | - |  |
| `tests/tools/test_local_interrupt_cleanup.py` | - | R1 | Windows arm asserts the fork's _kill_process; red on upstream |
| `tests/tools/test_local_shell_init.py` | - | R3 | fakes _IS_WINDOWS; HOME part alone stays red |
| `tests/tools/test_local_tempdir.py` | - | R6 | gone upstream (and R3) |
| `tests/tools/test_mcp_tool.py` | G | - |  |
| `tests/tools/test_memory_tool.py` | A | - |  |
| `tests/tools/test_modal_sandbox_fixes.py` | - | R1 | tool_describe injection; host-cwd helper untested here |
| `tests/tools/test_notify_on_complete.py` | - | R1 | checkpoint_path |
| `tests/tools/test_process_registry.py` | F | R1 | getpgid + taskkill seam lifted; python3/PTY hunk R10; checkpoint_path R1 |
| `tests/tools/test_skills_guard.py` | A | - |  |
| `tests/tools/test_skills_hub.py` | B | R10 | hash test in B; jo.txt write_bytes does not fix the KeyError |
| `tests/tools/test_skills_sync.py` | - | R9 | passes upstream |
| `tests/tools/test_stage2_hook_api_server_keygen.py` | - | R2 | works around the fork argv classifier |
| `tests/tools/test_stage2_hook_symlink_chown.py` | A | - |  |
| `tests/tools/test_startup_latency_regressions.py` | - | R1 | probe-client stub is fork |
| `tests/tools/test_subprocess_home_isolation.py` | D | - |  |
| `tests/tools/test_subprocess_stdin_guard.py` | A | - | still red on a real checker finding |
| `tests/tools/test_terminal_output_transform_hook.py` | E | - |  |
| `tests/tools/test_terminal_tool.py` | - | R1 | T6b brief/full descriptions |
| `tests/tools/test_vision_native_fast_path.py` | - | R1 | load_config_readonly |
| `tests/tools/test_vision_tools.py` | - | R1 | load_config_readonly |
| `tests/tools/test_voice_mode.py` | - | R3 | platform.system patch; which stub R9 |
| `tests/tools/test_voice_wsl_pipewire.py` | - | R9 | which stub; not in baseline red set |
| `tests/tools/test_watch_patterns.py` | - | R1 | checkpoint_path |
| `tests/tools/test_working_diff.py` | B | - |  |
| `tests/tools/test_zombie_process_cleanup.py` | - | R2 | teardown rewrite cites the fork live-system guard; passes upstream |

## Commit-body corrections (fixed 2026-09-24)

- `up/win-path-spelling` said 17 tests turn green; its list is 18. Fixed in `4af8c623ff`.
- `up/win-shell-invocation` said 14; its list is 13, and a comment in `test_setup_hermes_script.py` used a machine path, now `C:\work\hermes-agent\...`. Fixed in `dc3b38ab36`.
- `up/monkeypatch-undo-scoped` said 13 files; it lists 14. Fixed in `abbe273ab9`.
- All three were amended and force-pushed with lease (unopened branches); each still cherry-picks clean onto `upstream/main` `c22b0a240f`. Test results are unchanged; the only tree change is that comment.
