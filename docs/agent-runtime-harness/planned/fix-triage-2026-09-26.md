# Fix triage — one verdict per upstream-footprint row (2026-09-26)

Lane FIX-TRIAGE, design sitting, no code in the fork tree. Owner's ask (runtime-queue row, RULED 2026-09-26):
every ledger row gets DROP / PLUGIN / KEEP, every KEEP without a PR becomes a HELD branch or an issue DRAFT,
nothing is published ("we have too many today").

Population: `scripts/upstream_footprint.py --json` at fork `main` **b0580d4a162** — 169 rows, base `067fa1a257`,
`[up-fp] files=169 deleted_lines=906 heavy=4`. Upstream tip of record: `upstream/main` **77a799e2f9c**
(495 commits past the base). Every fork hunk was replayed onto that tip's tree (`git apply --cached --check`
against a `read-tree upstream/main` index): **164 of 167 non-empty diffs apply unchanged**; the three that
conflict are named in their rows (`hermes_cli/web_server_oauth.py`, `tools/file_tools_write_guards.py`,
`tools/mcp_tool_transport.py`). Only 18 of the 169 files were touched upstream since the base at all, so
"upstream already fixed it" was checked commit-by-commit on those 18 and is TRUE for none — the DROP verdicts
below are all surface verdicts (a surface the fork does not run), never "fixed upstream".

Inputs taken as given: `plugin-fit-2026-09-26.md` (a hook/carry row with a PLUGIN-NOW / PLUGIN-AFTER verdict
copies it; only its NO rows are triaged here); `Harness_Brain/10 — Programs/Upstream Sync.md` § Open upstream
PRs (26 rows) joined with `gh pr list --author @me` (33 open PRs at sitting time — the seven `up/*` fix PRs
#121640–#121646 are open and are NOT in the brain's table; filed as a queue row below); each PR's file set from
`gh pr view --json files`.

Verdict vocabulary. **DROP** — revert to upstream bytes: the file serves a surface the fork does not run.
**PLUGIN** — a seam exists on upstream/main today; the hook is named. **KEEP-PR #N** — one of our open PRs carries
it (the row leaves when it merges). **KEEP-HELD `up/<class>`** — a branch cut from `upstream/main`, pushed to
ORIGIN only, body in `X:/wt/_holds/fix-triage-0926/pr-<class>.md`. **KEEP-ISSUE** — a PR is the wrong shape
(behaviour question or design ask); draft in `X:/wt/_holds/fix-triage-0926/issue-<slug>.md`. **CARRY** — ruled
permanent, or a recorded parallel with no upstream shape yet. A mixed file gets the verdict of its largest hunk
and names the rest in `why`.

## 1. The table

| path | disposition | verdict | class | why |
|---|---|---|---|---|
| `.gitattributes` | carry-permanent | KEEP-PR #123874 | eol-lf | the root `eol=lf` rule is the PR (PLUGIN-FIT: AFTER #123874) |
| `.github/workflows/contributor-check.yml` | upstream | DROP | contributors-case-variants | upstream/main has no case-colliding contributor file (one `agent@agents-Mac-mini.local`) and `case-collision-check.yml` refuses a pair at CI, so a `case-variants/` lookup serves nothing there; revert, and delete the fork's own `contributors/emails/case-variants/` with it |
| `AGENTS.md` | carry-permanent | CARRY | fork-pointer | ruled 2026-09-24 (lane META) |
| `README.md` | carry-permanent | CARRY | licence-notice | ruled 2026-09-24 (lane META) |
| `agent/agent_init.py` | hook | PLUGIN | blocked-tools (PF-1) | (a) `llm_request` tool filter + `pre_tool_call` refusal; (b) init-phase receipts → KEEP-ISSUE `turn-phase-observer`; (c) `local-llama-hermes` floor exemption → KEEP-ISSUE `configurable-context-floor` |
| `agent/codex_runtime.py` | hook | KEEP-PR #123978 | per-call-usage | (a) the usage-ledger row rides #123978; (b) phase stamps are PLUGIN via `llm_execution` + `on_stream_start/delta/end` (PF-3) |
| `agent/conversation_compression.py` | hook | KEEP-ISSUE | configurable-context-floor | (a) the aux floor exemption is spelled on the `local-llama-hermes` provider name in the tree and must be re-authored as a config key → issue; (b) `child_model_config` on the compression child → the same issue's second ask (a `transform_compression_child` hook beside #124210) |
| `agent/conversation_loop.py` | hook | KEEP-PR #124210 | persisted-row-hooks | (a) `reuse_current_user_message` rides #124210; (b) prompt/turn timing marks → KEEP-ISSUE `turn-phase-observer` |
| `agent/credential_pool.py` | upstream | KEEP-PR #124193 | credential-pool | recorded parallel 8 |
| `agent/pet/generate/atlas.py` | upstream | KEEP-HELD `up/pet-atlas-extraction` | pet-atlas | strip-scale line erase, vertical box merge, lenient-row validation; `frame_x_bounds` / `_slot_bounds` are the charsheet's QA crop and stay OUT of the branch (move to `agent/charsheet/`) |
| `agent/process_bootstrap.py` | upstream | KEEP-HELD `up/copilot-direct-http-client` | copilot-client | the copilot direct-client branch; no upstream touch since base, applies clean |
| `agent/prompt_builder.py` | hook | PLUGIN | prompt-guidance (PF-2) | (a) the Safety sentence via `llm_request`, (b) the Windows hint via `register_system_prompt_section`; (c) the skill runtime-compat filter → KEEP-ISSUE `skill-visibility-hook`; (d) all-context-files load → KEEP-ISSUE `context-files-load-all`; the shared-root import rides #124191 |
| `agent/session_persistence.py` | hook | KEEP-PR #124210 | persisted-row-hooks | upstream rewrote the session-row heal 8× since base (6e4e0638e83…ff05a54ecd5); the fork hunk still applies |
| `agent/shell_hooks.py` | upstream | KEEP-PR #123892 | shell-hook-os-sep | — |
| `agent/skill_utils.py` | hook | KEEP-PR #124191 | skills-extra-dirs | — |
| `agent/system_prompt.py` | hook | KEEP-HELD `up/plugin-session-info-tool-names` | session-info | one additive line; the plugin already reads it defensively |
| `agent/turn_api_request.py` | hook | KEEP-ISSUE | turn-phase-observer | no request-phase hook exists; the three stamps are the ask |
| `agent/turn_context.py` | hook | KEEP-PR #124210 | persisted-row-hooks | — |
| `agent/turn_facade.py` | hook | KEEP-PR #124210 | persisted-row-hooks | — |
| `agent/turn_response_check.py` | hook | KEEP-ISSUE | turn-phase-observer | `post_api_request` → `post_llm_call` spans validation AND tool execution, so it cannot be derived |
| `agent/turn_response_intake.py` | upstream | KEEP-HELD `up/reasoning-relay-native` | reasoning-relay | relay native `_extract_reasoning` as `reasoning.available`; #123978 touches this file upstream-side for usage, not this hunk |
| `apps/desktop/src/app/settings/uninstall-section.test.tsx` | upstream | DROP | desktop-app | the fork neither builds nor ships the desktop app; the git-history warning is a desktop confirm-step affordance |
| `apps/desktop/src/app/settings/uninstall-section.tsx` | upstream | DROP | desktop-app | same |
| `cli.py` | upstream | KEEP-PR #121646 | tirith-config | — |
| `contributors/emails/uperLu@users.noreply.github.com` | upstream | KEEP-PR #123874 | eol-lf | in that PR's file set (the CRLF normalisation) |
| `evals/postmortem/live_ab/cache_concurrency_probe.py` | upstream | KEEP-PR #123890 | evals-nameerror | — |
| `gateway/hosted_room_discussion.py` | hook | KEEP-ISSUE | group-chat-host-surface | host-declared `DiscussionLimits` + `active_member_ids`: a widening whose shape upstream should choose |
| `gateway/hosted_room_policy_checkpoint.py` | hook | KEEP-ISSUE | group-chat-host-surface | same issue (`max_active_events`) |
| `gateway/hosted_rooms.py` | hook | KEEP-ISSUE | group-chat-host-surface | same issue (`pin_room_history` / `unpin_room_history`) |
| `gateway/lifecycle_ledger.py` | upstream | KEEP-PR #123891 | process-home | — |
| `gateway/platforms/base.py` | upstream | KEEP-HELD `up/media-path-hardening` | media-hardening | `$HOME` for the denylist, backslash as a MEDIA terminator, NUL paths dropped in `_add`; upstream's one touch (2ed91ca39d8) is elsewhere in the file |
| `gateway/run.py` | upstream | KEEP-PR #121646 | tirith-config | the approvals heads-up hunk; `restore_durable_completions` at `start_gateway` → KEEP-ISSUE `durable-completion-restore`; four upstream touches since base (venv overlay, replay stamp), hunk applies |
| `gateway/run_notifications.py` | upstream | KEEP-HELD `up/watcher-reply-to` | watcher-reply-to | `reply_to=watcher message_id`; upstream 34343e79ab6 changes the synthetic-event anchor, not the watcher send |
| `gateway/shutdown_watchdog.py` | upstream | KEEP-PR #123891 | process-home | — |
| `hermes_cli/auth.py` | hook | KEEP-PR #124190 | store-home-override | `_auth_file_path` honours `HERMES_AUTH_HOME` (PLUGIN-FIT: AFTER #124190); `persist_provider_login` already moved to the fork-only transport |
| `hermes_cli/auth_codex.py` | carry | KEEP-HELD `up/auth-on-verification` | auth-on-verification | the `on_verification` kwarg + fire only; the branch ALREADY EXISTS on origin (da0369aee6, cut 2026-09-26 from 467902fdb3c, body `X:/wt/_holds/pr-bodies/auth-on-verification.md`) — reused, not re-cut; 8 upstream commits behind, rebase before opening |
| `hermes_cli/auth_codex_browser.py` | carry | KEEP-HELD `up/auth-on-verification` | auth-on-verification | same |
| `hermes_cli/auth_commands.py` | hook | PLUGIN | harness-cli (LAUNCHER-MOVE) | `register_cli_command("harness")` sub-verbs (PLUGIN-FIT §4 Q5); deletes once the launcher spells `hermes harness auth …` — launcher row filed 793a0c2fe; fallback if the launcher move is refused: the existing held `up/plugin-cli-commands` adds `parent="auth"` |
| `hermes_cli/auth_minimax.py` | carry | KEEP-HELD `up/auth-on-verification` | auth-on-verification | kwarg + fire + `persist=False` |
| `hermes_cli/auth_nous.py` | upstream | KEEP-PR #121642 | nous-login-url | — |
| `hermes_cli/auth_xai.py` | carry | KEEP-HELD `up/auth-on-verification` | auth-on-verification | kwarg + fire |
| `hermes_cli/commands_platforms.py` | upstream | DROP | slack-adapter | the fork never runs the Slack adapter; the 50-command clamp report serves a manifest nobody here generates — revert |
| `hermes_cli/config.py` | hook | KEEP-HELD `up/readonly-config-reads` | readonly-config | the `ensure_home=False` hunk ("reading config must not scaffold the home") is the PR; the `project_readonly_config` ContextVar → KEEP-ISSUE `config-readonly-projection` |
| `hermes_cli/doctor.py` | upstream | KEEP-HELD `up/doctor-call-time-home` | doctor-home | call-time `HERMES_HOME` / `_DHH` via PEP 562, dotenv per run; the `check_gateway_launcher` import (agent_runtime) stays OUT of the branch — CARRY until a doctor-check registration hook |
| `hermes_cli/doctor_config.py` | upstream | KEEP-HELD `up/doctor-call-time-home` | doctor-home | — |
| `hermes_cli/doctor_platform.py` | upstream | KEEP-HELD `up/doctor-call-time-home` | doctor-home | — |
| `hermes_cli/doctor_state.py` | upstream | KEEP-HELD `up/doctor-call-time-home` | doctor-home | — |
| `hermes_cli/gateway.py` | upstream | KEEP-PR #119069 | launchd-pwd-guard | the `pwd` guard rides #119069 and the two `getuid` guards belong beside it at its rebase; `resolve_managed_python` / `_detect_venv_dir` are a RECORDED PARALLEL (CARRY until the launcher install moves onto pm bundles); the home receipt is fork observability (CARRY); `_command_matches_profile` is a no-behaviour extraction (REVERT candidate) |
| `hermes_cli/gateway_windows.py` | upstream | KEEP-HELD `up/win-gateway-task-console` | win-gateway-task | console-less task detection + `status` warning + the named-profile wrapper pin refusal; the `resolve_managed_python` call stays with the CARRY above |
| `hermes_cli/kanban_db_dispatch.py` | upstream | KEEP-HELD `up/kanban-crash-evidence` | kanban-crash-evidence | with `hermes_cli/kanban_crash_evidence.py` (485 lines); upstream 63e44332f5d touched the reclaim path, the hunk still applies |
| `hermes_cli/main.py` | hook | KEEP-HELD `up/profile-bootstrap-extraction` | profile-bootstrap (P1) | (a) the −187 extraction into `_profile_bootstrap.py`; (b) the boot-clock marks CARRY (no fire site); (c) manifest CLI commands → `up/plugin-cli-commands` (existing branch); (d) `restore_durable_completions` and (e) the dead `cmd_postinstall` import are PLUGIN (PF-2) |
| `hermes_cli/main_web_build.py` | upstream | KEEP-HELD `up/bytecode-sweep-lock` | bytecode-sweep | with `hermes_cli/_bytecode_sweep.py` |
| `hermes_cli/mcp_config.py` | upstream | KEEP-HELD `up/mcp-test-env` | mcp-test-env | the `--env` hunk, re-authored without the fork's `flag_binding`; needs #124210's `runtime_env` to be honoured by `_build_safe_env`; the machine-root tokens are CARRY (fork), the `_ENV_VAR_NAME_RE` re-home is a parallel → REVERT to upstream's constant |
| `hermes_cli/plugin_compat.py` | upstream | KEEP-PR #121023 | plugin-compat | — |
| `hermes_cli/plugins.py` | hook | KEEP-HELD `up/plugin-cli-commands` | cli-commands-manifest | the Stage-1 seam (`discover_declared_cli_commands` / `_materialize_declared_cli_command`); the branch ALREADY EXISTS on origin (df624d82cc, body `X:/wt/_holds/pr-bodies/plugin-cli-commands.md`, also carries `parent=` sub-verbs under a built-in) — reused; the discovery `elapsed_ms` log rides along |
| `hermes_cli/plugins_discovery.py` | upstream | KEEP-HELD `up/readonly-config-reads` | readonly-config | enable/disable lists through `load_config_readonly`, one shared read |
| `hermes_cli/plugins_manifest.py` | hook | KEEP-HELD `up/plugin-cli-commands` | cli-commands-manifest | the manifest `cli_commands` field (existing branch, above) |
| `hermes_cli/provider_catalog.py` | upstream | KEEP-HELD `up/oauth-flow-catalog` | oauth-catalog | `OAUTH_FLOW_OVERRIDES` + `disconnect_command_for` only; `provider_login_catalog` / `MODELS_DEV_LANE_IDS` / `models_dev_id_for` / `_default_flow_for` are the launcher roster → MOVE to a fork module beside `model_picker_policy.py`, never a PR |
| `hermes_cli/service_manager.py` | upstream | KEEP-PR #121640 | doc-accuracy | — |
| `hermes_cli/slack_cli.py` | upstream | DROP | slack-adapter | same as `commands_platforms.py` |
| `hermes_cli/subcommands/auth.py` | hook | PLUGIN | harness-cli (LAUNCHER-MOVE) | the two parsers; same move |
| `hermes_cli/subcommands/mcp.py` | upstream | KEEP-HELD `up/mcp-test-env` | mcp-test-env | the `--env KEY=VALUE` argument |
| `hermes_cli/uninstall.py` | upstream | KEEP-PR #121640 | doc-accuracy | upstream a9756158697 touched the file (launchd sweep); hunk applies |
| `hermes_cli/update_cmd.py` | upstream | KEEP-HELD `up/updater-fork-history` | updater-fork-history | the fork-history guard with `hermes_cli/update_history.py`; the dead `_warn_legacy_console_gateway_task` tail import is a REVERT |
| `hermes_cli/update_cmd_git.py` | upstream | KEEP-ISSUE | updater-fork-sync-no-force | dropping `--force-with-lease` from the fork sync and the diverged-fork message change upstream's updater behaviour for every fork — a question, not a fix |
| `hermes_cli/update_cmd_windows.py` | upstream | KEEP-HELD `up/win-gateway-task-console` | win-gateway-task | `_warn_legacy_console_gateway_task`; the `ManagedPythonUnavailable` tolerance stays with the gateway CARRY |
| `hermes_cli/update_inventory.py` | upstream | KEEP-HELD `up/updater-fork-history` | updater-fork-history | cached history assessment in the plan |
| `hermes_cli/web_routers/oauth.py` | upstream | KEEP-HELD `up/oauth-flow-catalog` | oauth-catalog | disconnect command from the one authority |
| `hermes_cli/web_server_oauth.py` | upstream | KEEP-HELD `up/oauth-flow-catalog` | oauth-catalog | CONFLICTS on 77a799e2f9c (6d70abc8713 relabelled the Anthropic card 'Anthropic Account') — re-authored on upstream's current table |
| `hermes_cli/worktree_ops.py` | upstream | KEEP-PR #121640 | doc-accuracy | — |
| `hermes_state_messages.py` | upstream | KEEP-HELD `up/state-db-small-fixes` | state-db | `finish_reason` on every role; two upstream touches since base, hunk applies |
| `hermes_state_sessions.py` | upstream | KEEP-HELD `up/state-db-small-fixes` | state-db | `ORDER BY started_at DESC, id DESC` tie-break |
| `model_tools.py` | hook | PLUGIN | blocked-tools (PF-1) | (a) the filter; (b) memo hit/miss counters → KEEP-ISSUE `turn-phase-observer`; (c) `ensure_tool_describe_present` CARRY (PAR-DESIGN 7b: bridge dispatch precedes every hook) |
| `nix/checks.nix` | upstream | DROP | nix | the fork does not build the nix flake |
| `plugins/dashboard_auth/_shared.py` | upstream | KEEP-HELD `up/readonly-config-reads` | readonly-config | read-only load + deepcopy of the section |
| `plugins/memory/__init__.py` | upstream | KEEP-HELD `up/memory-plugin-publish-module` | memory-publish | `_publish_module` binds the child on its parent package; `_unpublish_module` has NO caller in the tree — the branch wires it on `exec_module` failure, which is what the row claims |
| `plugins/platforms/feishu/adapter.py` | upstream | DROP | feishu-adapter | the Feishu adapter is never enabled here (its toolsets are stripped from every persona) |
| `providers/__init__.py` | upstream | KEEP-HELD `up/providers-discovery-import` | boot-import | one line; the revert re-reds `tests/agent_runtime/test_tool_visibility_import_deferral.py` |
| `pyproject.toml` | carry-permanent | CARRY | packaging | the `agent_runtime` include retires at Stage 7; the ruff `F821` select + per-file ignores → KEEP-HELD `up/ruff-f821` |
| `run_agent.py` | hook | PLUGIN | blocked-tools (PF-1) | leaves the footprint with PF-1 |
| `scripts/audit_pr_attribution.py` | upstream | DROP | contributors-case-variants | see `contributor-check.yml` |
| `scripts/check_subprocess_stdin.py` | upstream | KEEP-HELD `up/win-path-identity` | win-path-identity | `as_posix()` compares |
| `scripts/releases/authors.py` | upstream | DROP | contributors-case-variants | see `contributor-check.yml` |
| `scripts/run_tests.sh` | upstream | KEEP-HELD `up/test-runner` | test-runner (P5) | runner improvements; the hermetic-env rows are the fork's and are split out at the branch |
| `scripts/run_tests_parallel.py` | upstream | KEEP-HELD `up/test-runner` | test-runner (P5) | node-id selectors, adaptive jobs, timeout retry, pathsep split |
| `tests/_fixtures/env_filter.py` | upstream | KEEP-HELD `up/test-runner` | test-runner (P5) | one compiled credential-suffix alternation |
| `tests/_fixtures/live_system_guard.py` | upstream | KEEP-HELD `up/live-system-guard` | live-system-guard | the backend-spawn arm and the other guard hardenings (159/8) |
| `tests/agent/test_coding_context.py` | upstream | KEEP-HELD `up/win-test-fixes-2` | win-tests-2 | LEDGER DRIFT: the row says "lifted: up/win-line-endings", but #121221's file set (5 files) does not carry it |
| `tests/agent/test_compression_adoption_preserves_live_tail.py` | upstream | KEEP-HELD `up/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/agent/test_image_routing.py` | upstream | KEEP-PR #121222 | win-tilde-home | also in #121641's file set |
| `tests/agent/test_provider_fallback.py` | upstream | KEEP-HELD `up/test-hygiene` | test-hygiene | names `test_fallback_model.py`, deleted upstream in e2fd462ebe |
| `tests/agent/test_shell_hooks_consent.py` | upstream | KEEP-PR #121222 | win-tilde-home | — |
| `tests/agent/test_skill_commands.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/agent/test_skill_utils.py` | upstream | KEEP-HELD `up/win-test-fixes-2` | win-tests-2 | `Path()` compare; REVERT the orphan S5 banner; one hunk already upstream (b2ecd3518f) |
| `tests/cron/test_cron_memory_contract.py` | upstream | KEEP-HELD `up/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/docker/test_dashboard.py` | upstream | DROP | docker-tests | the fork runs no docker tier; a comment repoint in a test it never runs — revert |
| `tests/gateway/test_feishu.py` | upstream | DROP | feishu-adapter | see the adapter |
| `tests/gateway/test_media_spaced_paths_and_history_dedupe.py` | upstream | KEEP-PR #121222 | win-tilde-home | — |
| `tests/hermes_cli/test_apply_profile_override.py` | upstream | KEEP-HELD `up/win-test-fixes-2` | win-tests-2 | pin `_get_platform_default_hermes_home` + encoding |
| `tests/hermes_cli/test_auth_nous_provider.py` | upstream | KEEP-PR #121225 | win-posix-only-apis | also in #121642's file set |
| `tests/hermes_cli/test_backup.py` | upstream | KEEP-PR #121224 | win-path-spelling | also #121225; the `.bat` wrapper hunk is R10 (still red) — DROP that hunk |
| `tests/hermes_cli/test_deleted_profile_tombstone.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/hermes_cli/test_doctor.py` | upstream | KEEP-HELD `up/doctor-call-time-home` | doctor-home | the three `setenv` sites, test half of the class |
| `tests/hermes_cli/test_doctor_journal_modes.py` | upstream | KEEP-PR #121225 | win-posix-only-apis | the linux-marker rest → `up/platform-markers-linux` |
| `tests/hermes_cli/test_early_recovery.py` | upstream | KEEP-PR #121218 | import-guard | — |
| `tests/hermes_cli/test_gateway_migrate_multiplex.py` | upstream | KEEP-HELD `up/platform-markers-linux` | platform-markers | `@pytest.mark.platforms("linux")` is upstream's own marker (`tests/test_hermes_constants.py` uses it at base) |
| `tests/hermes_cli/test_kanban_worktree_teardown.py` | upstream | KEEP-HELD `up/platform-markers-linux` | platform-markers | — |
| `tests/hermes_cli/test_linux_desktop_entry.py` | upstream | KEEP-HELD `up/platform-markers-linux` | platform-markers | 20 markers on `.desktop`-entry tests |
| `tests/hermes_cli/test_local_runtime.py` | upstream | KEEP-HELD `up/test-hygiene` | test-hygiene | the stub's `/models/unload` marks the model unloaded |
| `tests/hermes_cli/test_node_runtime_npm_resolution.py` | upstream | KEEP-HELD `up/platform-markers-linux` | platform-markers | — |
| `tests/hermes_cli/test_orphan_desktop_serve_reap.py` | upstream | KEEP-HELD `up/platform-markers-linux` | platform-markers | — |
| `tests/hermes_cli/test_projects_db.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/hermes_cli/test_prompt_compose_command.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/hermes_cli/test_setup_hermes_script.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/hermes_cli/test_win_pty_bridge.py` | upstream | KEEP-PR #121219 | win-conpty | — |
| `tests/scripts/test_run_tests_parallel.py` | upstream | KEEP-HELD `up/test-runner` | test-runner (P5) | REVERT the orphan S5 banners; one hunk already upstream (524c38a98a) |
| `tests/test_hermes_constants.py` | upstream | KEEP-HELD `up/win-test-fixes-2` | win-tests-2 | `sys.platform` pin, mirrors upstream's own win32 sibling |
| `tests/tools/test_approved_command_clean_slate.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/tools/test_base_environment.py` | upstream | DROP | R10 | the hunk does not turn the test green on Windows (bash resolution, then NTFS mode bits) and its concurrency half targets tests upstream deleted (524c38a98a) — revert |
| `tests/tools/test_delegate.py` | upstream | KEEP-HELD `up/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/tools/test_execution_flag_detection.py` | upstream | KEEP-PR #121226 | win-shell-invocation | the second hunk annotates a test upstream deleted (5f6b1d251f) — DROP that hunk |
| `tests/tools/test_file_ops_cwd_tracking.py` | upstream | DROP | R10 | still red at a later line after the hunk — revert |
| `tests/tools/test_file_tools.py` | upstream | DROP | dead-hunk | the tree carries only an unused `import os` (the `normpath` extension the ledger names is not in the diff, and upstream's file has no `os.` use) — revert |
| `tests/tools/test_file_tools_live.py` | upstream | KEEP-PR #121226 | win-shell-invocation | the whole diff, LF pin included, is in #121226's branch (the ledger's `up/win-line-endings` attribution is stale) |
| `tests/tools/test_file_tools_tilde_profile.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/tools/test_interrupt.py` | upstream | KEEP-HELD `up/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/tools/test_local_background_child_hang.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/tools/test_local_env_cwd_recovery.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/tools/test_local_env_relative_cwd.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/tools/test_local_env_windows_msys.py` | upstream | KEEP-HELD `up/win-test-fixes-2` | win-tests-2 | `os.path.join`; REVERT the duplicated S5 banner |
| `tests/tools/test_modal_sandbox_fixes.py` | hook | KEEP-HELD `up/win-test-fixes-2` | win-tests-2 | the `_native_host_cwd` fixture spelling; the `tool_describe`-injected expectation is CARRY (7b) |
| `tests/tools/test_skills_hub.py` | upstream | KEEP-PR #121221 | win-line-endings | the `jo.txt` R10 hunk — DROP that hunk |
| `tests/tools/test_subprocess_home_isolation.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/tools/test_terminal_output_transform_hook.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tools/approval_context.py` | upstream | KEEP-PR #121646 | tirith-config | — |
| `tools/approval_detection.py` | upstream | KEEP-HELD `up/win-path-identity` | win-path-identity | the verification-artifact exemption accepts the MSYS spelling and asks identity through `tools/path_identity` (new file in the branch) |
| `tools/async_delegation.py` | hook | KEEP-PR #124190 | store-home-override | — |
| `tools/browser_tool_lifecycle.py` | upstream | KEEP-HELD `up/win-path-identity` | win-path-identity | socket-dir binding by identity |
| `tools/code_execution_env.py` | upstream | KEEP-HELD `up/win-path-identity` | win-path-identity | interpreter / prefix identity |
| `tools/credential_files.py` | upstream | KEEP-PR #121643 | win-remote-posix-paths | — |
| `tools/environments/local.py` | upstream | KEEP-HELD `up/win-runtime-fixes` | win-runtime | `_augment_windows_system_path` (called from `_make_run_env`); `_shell_arg_safe_path` is defined with no caller left in the tree — DROP that def |
| `tools/file_tools.py` | upstream | KEEP-PR #121645 | win-posix-guard-forms | upstream 666681cbf3d touched the file; hunk applies |
| `tools/file_tools_write_guards.py` | upstream | KEEP-PR #121645 | win-posix-guard-forms | CONFLICTS on 77a799e2f9c (four upstream commits on the guards, 641c49f8412…42841ece0f0) — the PR needs a rebase |
| `tools/image_generation_tool.py` | carry | KEEP-HELD `up/readonly-config-reads` | readonly-config | the FAL key read |
| `tools/mcp_tool_config.py` | hook | KEEP-PR #124210 | persisted-row-hooks | upstream 678a4762b88 / 40347fd40d7 (uv/uvx resolver) touched the file; hunk applies |
| `tools/mcp_tool_transport.py` | hook | KEEP-PR #124210 | persisted-row-hooks | CONFLICTS on 77a799e2f9c (75b64fb8ff5 rebuilt the identity inputs) — the PR needs a rebase |
| `tools/process_registry.py` | upstream | KEEP-PR #124190 | store-home-override | `checkpoint_path` via the background-work home; `ProcessNotificationMixin` + `wait_ceiling_seconds` → KEEP-ISSUE `durable-completion-restore`; the PTY `0x1A` EOF → `up/win-runtime-fixes` |
| `tools/process_registry_notifications.py` | upstream | KEEP-HELD `up/process-notification-redaction` | notification-redaction | redact, ANSI-strip and bound every field; `agent.redact` and `tools.ansi_strip` exist upstream |
| `tools/registry.py` | upstream | KEEP-HELD `up/tool-registry-probe-cache` | registry-probe-cache | TTL/grace re-probe bound, `registry_epoch`, probe accounting; `scan_registered_tools` needs the fork's `tools/toolset_scan.py` → OUT of the branch (CARRY with its reader); toolset registration hunks ride #123979 |
| `tools/skills_hub_official.py` | upstream | KEEP-PR #121643 | win-remote-posix-paths | — |
| `tools/skills_tool.py` | hook | PLUGIN | skill-results (PF-3) | (c) runtime-compat refusal and (e) the inspection reader are PLUGIN / MOVE; (a) shared roots ride #124191; (b) `resolve_skill` is ADOPT upstream's walk (Q6); (d) `skills_list` filter → KEEP-ISSUE `skill-visibility-hook`; (f) G2 |
| `tools/skills_tool_plugin.py` | hook | PLUGIN | skill-results (PF-3) | leaves the footprint with PF-3 |
| `tools/terminal_tool.py` | hook | KEEP-PR #123977 | command-guard | (a) the envelope gate rides #123977; (b) task_id scope and (c) the brief schema are PLUGIN (PF-1); upstream 666681cbf3d touched the file, hunk applies |
| `tools/terminal_tool_result.py` | upstream | KEEP-HELD `up/win-path-identity` | win-path-identity | cwd change by identity |
| `tools/tirith_security.py` | upstream | KEEP-PR #121646 | tirith-config | — |
| `tools/tool_search.py` | hook | KEEP-PR #124192 | tool-search-never-defer | (a) rides #124192; (b) describe-over-all + legacy args CARRY (PAR-DESIGN 7b) |
| `tools/tts_tool.py` | carry | KEEP-HELD `up/readonly-config-reads` | readonly-config | the deep-copied config read; the `denotes_same_file` hunk → `up/win-path-identity` |
| `tools/tts_tool_delivery.py` | upstream | KEEP-HELD `up/win-path-identity` | win-path-identity | audio paths by identity |
| `tools/vision_tools.py` | carry | KEEP-HELD `up/readonly-config-reads` | readonly-config | the two config reads; the `_lookup_supports_vision` import serves the fork's `_accepts_tool_result_images` and stays |
| `toolsets.py` | hook | KEEP-PR #123979 | register-toolset | (a) rides #123979; (b) `expand_toolset_names` is a MOVE to `agent_runtime/toolset_names.py` (PF-3) |
| `tui_gateway/entry.py` | upstream | KEEP-ISSUE | durable-completion-restore | an explicit startup restore vs upstream's ctor-time restore is a behaviour question |
| `tui_gateway/hosted_room_driver.py` | hook | KEEP-ISSUE | group-chat-host-surface | `request_reconciliation`; its three settlement fixes can be lifted as plain fixes once the issue says which surface |
| `tui_gateway/server.py` | upstream | KEEP-HELD `up/test-hygiene` | test-hygiene | ten upstream touches since base and the docstring still names the deleted `test_every_method_has_a_contract` |
| `utils.py` | upstream | KEEP-HELD `up/atomic-write-newline` | atomic-write | `newline=` passthrough; three fork callers, none upstream — the body says so |
| `website/docs/developer-guide/billing-lifecycle.md` | upstream | DROP | website-docs | the fork does not publish the website; a stale-page fix belongs to whoever renders it |
| `website/docs/developer-guide/chronos-managed-cron-contract.md` | upstream | DROP | website-docs | same |
| `website/docs/developer-guide/gateway-session-lifecycle.md` | upstream | DROP | website-docs | same |
| `website/docs/developer-guide/relay-connector-contract.md` | upstream | DROP | website-docs | same |
| `website/docs/user-guide/egress/network-isolation.md` | upstream | DROP | website-docs | same |
