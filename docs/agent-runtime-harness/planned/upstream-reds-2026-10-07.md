# Upstream reds in inherited test files — 2026-10-07

Lane h-red-inherited. Main's landing gate on 2026-10-07 (`4b598dc048`) read 69 red nodes in
18 test files that also exist in `upstream/main`. Each node was run on the fork branch and on
the merge-base of `origin/main` and `upstream/main` (`ee5f49b943`, a detached worktree, same
venv). The 23 nodes below are red on that upstream code too, with the same assertion, so the
fork does not cause them. They are recorded here, not fixed, not skipped, and not
allowlisted. The other 46 nodes are the fork's: 4 fixed in this lane (`_fallback_session_info`),
and 42 still open. Those 42 are 40 gateway-fence refusals: under the bundled runner the
suite's own interpreter lives under the store root (`<root>/installs/*/test-environment`).
The fence half is the same cause lane h-red-cli holds; its fence fix clears these 40 with no
second change. The other 2 are a plugin discovery that an auth read triggers
(`agent.provider_access.current_access`). That row goes to `runtime-queue.md` § Seams.

Proof command, run once per file from the merge-base worktree:

```
git -C X:/Eternia/hermes-agent worktree add --detach X:/Eternia/worktrees/hermes-upstream-probe ee5f49b943
cd X:/Eternia/worktrees/hermes-upstream-probe
C:/Users/beast/.venvs/hermes-test/Scripts/python.exe -m pytest <file> -q --tb=short -p no:cacheprovider
```

| node | cause (as observed on the merge-base) | proof |
|---|---|---|
| `tests/gateway/test_complete_path_at_filter.py::test_remote_backend_completion_lists_the_backend_not_the_host` | The fake backend runs the gateway's POSIX listing script through `subprocess.run(shell=True)`. On Windows that is `cmd.exe`, so the listing comes back empty (`[]`). Windows-only. | file run, 3 failed |
| `…::test_remote_backend_completion_expands_tilde_on_the_backend` | same | same |
| `…::test_remote_backend_completion_speaks_posix_from_a_windows_host` | same | same |
| `tests/tools/test_bot_retry_policy.py::test_deliver_retries_same_argv_on_transient_failure` | The fake delivery transport never answers, so the reply is `''`. The CLI argv resolves to `hermes.EXE` on Windows. Same family as the bot-relay node below. | file run, 4 failed |
| `…::test_deliver_retries_once_on_context_overflow` | same | same |
| `…::test_deliver_never_retries_auth_failure` | same (`'error' not in {'result': {'reply': ''}}`) | same |
| `…::test_deliver_retry_reads_the_stream_the_cli_writes_and_resumes_the_persisted_row` | same | same |
| `tests/tui_gateway/test_bot_relay_methods.py::test_deliver_validates_profile_and_runs_transport` | `assert 'hermes.EXE' in ('hermes', 'hermes.exe')`. The basename match is case-sensitive, but Windows PATHEXT casing gives `hermes.EXE`. | file run, 2 failed |
| `…::test_reported_turn_still_lingering_at_the_cap_is_booked_from_its_latest_report_not_killed` | `subprocess.TimeoutExpired` at the test's 2 s cap. A Windows interpreter cold start is slower than that. | same |
| `tests/tui_gateway/test_display_methods.py::test_install_worker_keeps_the_requested_profile_scope` | `ModuleNotFoundError: fcntl`. POSIX-only. | file run, 2 failed |
| `…::test_install_sudo_card_ignores_a_client_supplied_session_id` | same | same |
| `tests/tui_gateway/test_display_watch.py::test_screen_started_or_stopped_by_another_process_is_broadcast_as_status` | Path compared case-sensitively (`c:\users\…` vs `C:\Users\…`). Windows-only. | file run, 1 failed |
| `tests/tui_gateway/test_show_reasoning_display_gate.py::test_gateway_lifecycle_set_covers_desktop_card_tools` | The test parses `const CARD_TOOL_NAMES = new Set([...])`, but `apps/desktop/src/lib/tool-render-class.ts` now declares an array `as const`. The test and the desktop source drifted apart upstream. | file run, 1 failed |
| `tests/tui_gateway/test_ephemeral_profile_override.py::TestBackgroundProfileOverride::test_background_binds_and_restores_profile_home` | Expects `/home/user/.hermes/profiles/work`, gets `\home\user\…`, because `Path` renders backslashes on Windows. | file run, 3 failed |
| `…::TestBackgroundProfileOverride::test_background_restores_override_on_error` | same | same |
| `…::TestPreviewRestartProfileOverride::test_preview_binds_and_restores_profile_home` | same | same |
| `tests/hermes_cli/test_plugin_provider_picker_residue.py::test_hermes_model_routes_registered_plugin_profiles_to_the_generic_flow` | `_fake_binary` writes an extensionless `#!/bin/sh` file. `shutil.which` cannot resolve it on Windows, so the external-process plugin never admits and `config.model` stays a string. | file run, 2 failed |
| `…::test_any_external_process_plugin_counts_as_signed_in_when_its_binary_resolves` | same (`auth_verified` False) | same |
| `tests/hermes_cli/test_plugin_provider_picker_admission.py::test_external_process_plugin_authenticated_flag_tracks_binary_and_catalog_uses_fallback` | same fake-binary shape | file run, 1 failed |
| `tests/tui_gateway/test_tui_gateway_server.py::test_session_create_uses_bound_profile_backend_not_launch` | A remote POSIX cwd (`/home/felix/…`) is treated as a host path on Windows and falls back to `~`. | `-k "bound_profile_backend or ssh_named_profile_cwd or workspace_move_accepts_remote"`, 4 failed |
| `…::test_ssh_named_profile_cwd_beats_launch_terminal_cwd[ssh]` | same (`'~' == '/home/kali'`) | same |
| `…::test_ssh_named_profile_cwd_beats_launch_terminal_cwd[local]` | same | same |
| `…::test_workspace_move_accepts_remote_dir_for_bound_ssh_profile` | same (`4017 working directory does not exist`) | same |

These are candidates for `tests/fixtures/upstream_skip_list.txt` rows (`env` or `upstream`).
That list is the landing's call, made under its own rule. This lane does not add rows to it.
