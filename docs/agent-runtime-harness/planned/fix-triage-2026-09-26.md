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
| `agent/pet/generate/atlas.py` | upstream | KEEP-HELD `fix/pet-atlas-extraction` | pet-atlas | strip-scale line erase, vertical box merge, lenient-row validation; `frame_x_bounds` / `_slot_bounds` are the charsheet's QA crop and stay OUT of the branch (move to `agent/charsheet/`) |
| `agent/process_bootstrap.py` | upstream | KEEP-HELD `fix/copilot-direct-http-client` | copilot-client | the copilot direct-client branch; no upstream touch since base, applies clean |
| `agent/prompt_builder.py` | hook | PLUGIN | prompt-guidance (PF-2) | (a) the Safety sentence via `llm_request`, (b) the Windows hint via `register_system_prompt_section`; (c) the skill runtime-compat filter → KEEP-ISSUE `skill-visibility-hook`; (d) all-context-files load → KEEP-ISSUE `context-files-load-all`; the shared-root import rides #124191 |
| `agent/session_persistence.py` | hook | KEEP-PR #124210 | persisted-row-hooks | upstream rewrote the session-row heal 8× since base (6e4e0638e83…ff05a54ecd5); the fork hunk still applies |
| `agent/shell_hooks.py` | upstream | KEEP-PR #123892 | shell-hook-os-sep | — |
| `agent/skill_utils.py` | hook | KEEP-PR #124191 | skills-extra-dirs | — |
| `agent/system_prompt.py` | hook | KEEP-HELD `feat/plugin-session-info-tool-names` | session-info | one additive line; the plugin already reads it defensively |
| `agent/turn_api_request.py` | hook | KEEP-ISSUE | turn-phase-observer | no request-phase hook exists; the three stamps are the ask |
| `agent/turn_context.py` | hook | KEEP-PR #124210 | persisted-row-hooks | — |
| `agent/turn_facade.py` | hook | KEEP-PR #124210 | persisted-row-hooks | — |
| `agent/turn_response_check.py` | hook | KEEP-ISSUE | turn-phase-observer | `post_api_request` → `post_llm_call` spans validation AND tool execution, so it cannot be derived |
| `agent/turn_response_intake.py` | upstream | KEEP-HELD `fix/reasoning-relay-native` | reasoning-relay | relay native `_extract_reasoning` as `reasoning.available`; #123978 touches this file upstream-side for usage, not this hunk |
| `apps/desktop/src/app/settings/uninstall-section.test.tsx` | upstream | DROP | desktop-app | the fork neither builds nor ships the desktop app; the git-history warning is a desktop confirm-step affordance |
| `apps/desktop/src/app/settings/uninstall-section.tsx` | upstream | DROP | desktop-app | same |
| `cli.py` | upstream | KEEP-PR #121646 | tirith-config | — |
| `contributors/emails/uperLu@users.noreply.github.com` | upstream | KEEP-PR #123874 | eol-lf | in that PR's file set (the CRLF normalisation) |
| `evals/postmortem/live_ab/cache_concurrency_probe.py` | upstream | KEEP-PR #123890 | evals-nameerror | — |
| `gateway/hosted_room_discussion.py` | hook | KEEP-ISSUE | group-chat-host-surface | host-declared `DiscussionLimits` + `active_member_ids`: a widening whose shape upstream should choose |
| `gateway/hosted_room_policy_checkpoint.py` | hook | KEEP-ISSUE | group-chat-host-surface | same issue (`max_active_events`) |
| `gateway/hosted_rooms.py` | hook | KEEP-ISSUE | group-chat-host-surface | same issue (`pin_room_history` / `unpin_room_history`) |
| `gateway/lifecycle_ledger.py` | upstream | KEEP-PR #123891 | process-home | — |
| `gateway/platforms/base.py` | upstream | KEEP-PR #125264 (`fix/media-path-hardening`) | media-hardening | `$HOME` for the denylist, backslash as a MEDIA terminator, NUL paths dropped in `_add`; upstream's one touch (2ed91ca39d8) is elsewhere in the file |
| `gateway/run.py` | upstream | KEEP-PR #121646 | tirith-config | the approvals heads-up hunk; `restore_durable_completions` at `start_gateway` → KEEP-ISSUE `durable-completion-restore`; four upstream touches since base (venv overlay, replay stamp), hunk applies |
| `gateway/run_notifications.py` | upstream | CARRY (was KEEP-PR #125266, closed 2026-09-27: upstream 10938a7cf9 rules the arming message_id a stale anchor) | watcher-reply-to | `reply_to=watcher message_id`; upstream 34343e79ab6 changes the synthetic-event anchor, not the watcher send |
| `gateway/shutdown_watchdog.py` | upstream | KEEP-PR #123891 | process-home | — |
| `hermes_cli/auth.py` | hook | KEEP-PR #124190 | store-home-override | `_auth_file_path` honours `HERMES_AUTH_HOME` (PLUGIN-FIT: AFTER #124190); `persist_provider_login` already moved to the fork-only transport |
| `hermes_cli/auth_codex.py` | carry | KEEP-HELD `feat/auth-on-verification` | auth-on-verification | the `on_verification` kwarg + fire only; the branch ALREADY EXISTS on origin (da0369aee6, cut 2026-09-26 from 467902fdb3c, body `X:/wt/_holds/pr-bodies/auth-on-verification.md`) — reused, not re-cut; 8 upstream commits behind, rebase before opening |
| `hermes_cli/auth_codex_browser.py` | carry | KEEP-HELD `feat/auth-on-verification` | auth-on-verification | same |
| `hermes_cli/auth_commands.py` | hook | PLUGIN | harness-cli (LAUNCHER-MOVE) | `register_cli_command("harness")` sub-verbs (PLUGIN-FIT §4 Q5); deletes once the launcher spells `hermes harness auth …` — launcher row filed 793a0c2fe; fallback if the launcher move is refused: the existing held `feat/plugin-cli-commands` adds `parent="auth"` |
| `hermes_cli/auth_minimax.py` | carry | KEEP-HELD `feat/auth-on-verification` | auth-on-verification | kwarg + fire + `persist=False` |
| `hermes_cli/auth_nous.py` | upstream | KEEP-PR #121642 | nous-login-url | — |
| `hermes_cli/auth_xai.py` | carry | KEEP-HELD `feat/auth-on-verification` | auth-on-verification | kwarg + fire |
| `hermes_cli/commands_platforms.py` | upstream | DROP | slack-adapter | the fork never runs the Slack adapter; the 50-command clamp report serves a manifest nobody here generates — revert |
| `hermes_cli/config.py` | hook | KEEP-PR #125259 (`fix/readonly-config-reads`) | readonly-config | the `ensure_home=False` hunk ("reading config must not scaffold the home") is the PR; the `project_readonly_config` ContextVar → KEEP-ISSUE `config-readonly-projection` |
| `hermes_cli/doctor.py` | upstream | KEEP-PR #125260 (`fix/doctor-call-time-home`) | doctor-home | call-time `HERMES_HOME` / `_DHH` via PEP 562, dotenv per run; the `check_gateway_launcher` import (agent_runtime) stays OUT of the branch — CARRY until a doctor-check registration hook |
| `hermes_cli/doctor_config.py` | upstream | KEEP-PR #125260 (`fix/doctor-call-time-home`) | doctor-home | — |
| `hermes_cli/doctor_platform.py` | upstream | KEEP-PR #125260 (`fix/doctor-call-time-home`) | doctor-home | — |
| `hermes_cli/doctor_state.py` | upstream | KEEP-PR #125260 (`fix/doctor-call-time-home`) | doctor-home | — |
| `hermes_cli/gateway.py` | upstream | KEEP-PR #119069 | launchd-pwd-guard | the `pwd` guard rides #119069 and the two `getuid` guards belong beside it at its rebase; `resolve_managed_python` / `_detect_venv_dir` are a RECORDED PARALLEL (CARRY until the launcher install moves onto pm bundles); the home receipt is fork observability (CARRY); `_command_matches_profile` is a no-behaviour extraction (REVERT candidate) |
| `hermes_cli/gateway_windows.py` | upstream | KEEP-HELD `fix/win-gateway-task-console` | win-gateway-task | console-less task detection + `status` warning + the named-profile wrapper pin refusal; the `resolve_managed_python` call stays with the CARRY above |
| `hermes_cli/kanban_db_dispatch.py` | upstream | KEEP-HELD `feat/kanban-crash-evidence` | kanban-crash-evidence | with `hermes_cli/kanban_crash_evidence.py` (485 lines); upstream 63e44332f5d touched the reclaim path, the hunk still applies |
| `hermes_cli/main.py` | hook | KEEP-HELD `refactor/profile-bootstrap-extraction` | profile-bootstrap (P1) | (a) the −187 extraction into `_profile_bootstrap.py`; (b) the boot-clock marks CARRY (no fire site); (c) manifest CLI commands → `feat/plugin-cli-commands` (existing branch); (d) `restore_durable_completions` and (e) the dead `cmd_postinstall` import are PLUGIN (PF-2) |
| `hermes_cli/main_web_build.py` | upstream | KEEP-HELD `fix/bytecode-sweep-lock` | bytecode-sweep | with `hermes_cli/_bytecode_sweep.py` |
| `hermes_cli/mcp_config.py` | upstream | KEEP-HELD `feat/mcp-test-env` | mcp-test-env | the `--env` hunk, re-authored without the fork's `flag_binding`; needs #124210's `runtime_env` to be honoured by `_build_safe_env`; the machine-root tokens are CARRY (fork), the `_ENV_VAR_NAME_RE` re-home is a parallel → REVERT to upstream's constant |
| `hermes_cli/plugin_compat.py` | upstream | KEEP-PR #121023 | plugin-compat | — |
| `hermes_cli/plugins.py` | hook | KEEP-HELD `feat/plugin-cli-commands` | cli-commands-manifest | the Stage-1 seam (`discover_declared_cli_commands` / `_materialize_declared_cli_command`); the branch ALREADY EXISTS on origin (df624d82cc, body `X:/wt/_holds/pr-bodies/plugin-cli-commands.md`, also carries `parent=` sub-verbs under a built-in) — reused; the discovery `elapsed_ms` log rides along |
| `hermes_cli/plugins_discovery.py` | upstream | KEEP-PR #125259 (`fix/readonly-config-reads`) | readonly-config | enable/disable lists through `load_config_readonly`, one shared read |
| `hermes_cli/plugins_manifest.py` | hook | KEEP-HELD `feat/plugin-cli-commands` | cli-commands-manifest | the manifest `cli_commands` field (existing branch, above) |
| `hermes_cli/provider_catalog.py` | upstream | KEEP-HELD `refactor/oauth-flow-catalog` | oauth-catalog | `OAUTH_FLOW_OVERRIDES` + `disconnect_command_for` only; `provider_login_catalog` / `MODELS_DEV_LANE_IDS` / `models_dev_id_for` / `_default_flow_for` are the launcher roster → MOVE to a fork module beside `model_picker_policy.py`, never a PR |
| `hermes_cli/service_manager.py` | upstream | KEEP-PR #121640 | doc-accuracy | — |
| `hermes_cli/slack_cli.py` | upstream | DROP | slack-adapter | same as `commands_platforms.py` |
| `hermes_cli/subcommands/auth.py` | hook | PLUGIN | harness-cli (LAUNCHER-MOVE) | the two parsers; same move |
| `hermes_cli/subcommands/mcp.py` | upstream | KEEP-HELD `feat/mcp-test-env` | mcp-test-env | the `--env KEY=VALUE` argument |
| `hermes_cli/uninstall.py` | upstream | KEEP-PR #121640 | doc-accuracy | upstream a9756158697 touched the file (launchd sweep); hunk applies |
| `hermes_cli/update_cmd.py` | upstream | KEEP-PR #125265 (`fix/updater-fork-history`) | updater-fork-history | the fork-history guard with `hermes_cli/update_history.py`; the dead `_warn_legacy_console_gateway_task` tail import is a REVERT |
| `hermes_cli/update_cmd_git.py` | upstream | KEEP-ISSUE | updater-fork-sync-no-force | dropping `--force-with-lease` from the fork sync and the diverged-fork message change upstream's updater behaviour for every fork — a question, not a fix |
| `hermes_cli/update_cmd_windows.py` | upstream | KEEP-HELD `fix/win-gateway-task-console` | win-gateway-task | `_warn_legacy_console_gateway_task`; the `ManagedPythonUnavailable` tolerance stays with the gateway CARRY |
| `hermes_cli/update_inventory.py` | upstream | KEEP-PR #125265 (`fix/updater-fork-history`) | updater-fork-history | cached history assessment in the plan |
| `hermes_cli/web_routers/oauth.py` | upstream | KEEP-HELD `refactor/oauth-flow-catalog` | oauth-catalog | disconnect command from the one authority |
| `hermes_cli/web_server_oauth.py` | upstream | KEEP-HELD `refactor/oauth-flow-catalog` | oauth-catalog | CONFLICTS on 77a799e2f9c (6d70abc8713 relabelled the Anthropic card 'Anthropic Account') — re-authored on upstream's current table |
| `hermes_cli/worktree_ops.py` | upstream | KEEP-PR #121640 | doc-accuracy | — |
| `hermes_state_messages.py` | upstream | KEEP-HELD `fix/state-db-small-fixes` | state-db | `finish_reason` on every role; two upstream touches since base, hunk applies |
| `hermes_state_sessions.py` | upstream | KEEP-HELD `fix/state-db-small-fixes` | state-db | `ORDER BY started_at DESC, id DESC` tie-break |
| `model_tools.py` | hook | PLUGIN | blocked-tools (PF-1) | (a) the filter; (b) memo hit/miss counters → KEEP-ISSUE `turn-phase-observer`; (c) `ensure_tool_describe_present` CARRY (PAR-DESIGN 7b: bridge dispatch precedes every hook) |
| `nix/checks.nix` | upstream | DROP | nix | the fork does not build the nix flake |
| `plugins/dashboard_auth/_shared.py` | upstream | KEEP-PR #125259 (`fix/readonly-config-reads`) | readonly-config | read-only load + deepcopy of the section |
| `plugins/memory/__init__.py` | upstream | KEEP-HELD `fix/memory-plugin-publish-module` | memory-publish | `_publish_module` binds the child on its parent package; `_unpublish_module` has NO caller in the tree — the branch wires it on `exec_module` failure, which is what the row claims |
| `plugins/platforms/feishu/adapter.py` | upstream | DROP | feishu-adapter | the Feishu adapter is never enabled here (its toolsets are stripped from every persona) |
| `providers/__init__.py` | upstream | KEEP-HELD `fix/providers-discovery-import` | boot-import | one line; the revert re-reds `tests/agent_runtime/test_tool_visibility_import_deferral.py` |
| `pyproject.toml` | carry-permanent | CARRY | packaging | the `agent_runtime` include retires at Stage 7; the ruff `F821` select + per-file ignores → KEEP-HELD `chore/ruff-f821` |
| `run_agent.py` | hook | PLUGIN | blocked-tools (PF-1) | leaves the footprint with PF-1 |
| `scripts/audit_pr_attribution.py` | upstream | DROP | contributors-case-variants | see `contributor-check.yml` |
| `scripts/check_subprocess_stdin.py` | upstream | KEEP-PR #125262 (`fix/win-path-identity`) | win-path-identity | `as_posix()` compares |
| `scripts/releases/authors.py` | upstream | DROP | contributors-case-variants | see `contributor-check.yml` |
| `scripts/run_tests.sh` | upstream | KEEP-PR #125263 (`fix/test-runner`) | test-runner (P5) | runner improvements; the hermetic-env rows are the fork's and are split out at the branch |
| `scripts/run_tests_parallel.py` | upstream | KEEP-PR #125263 (`fix/test-runner`) | test-runner (P5) | node-id selectors, adaptive jobs, timeout retry, pathsep split |
| `tests/_fixtures/env_filter.py` | upstream | KEEP-PR #125263 (`fix/test-runner`) | test-runner (P5) | one compiled credential-suffix alternation |
| `tests/_fixtures/live_system_guard.py` | upstream | CARRY | live-system-guard | the backend-spawn arm imports `tests._downstream` and mirrors the fork's `_gateway_fence.py`; transplanted onto upstream/main it reddened 10 guard tests (`ModuleNotFoundError: tests._downstream`), so it is fork test infrastructure, not a PR — re-verdicted from KEEP-HELD after the branch was cut and deleted |
| `tests/agent/test_coding_context.py` | upstream | KEEP-HELD `test/win-test-fixes-2` | win-tests-2 | LEDGER DRIFT: the row says "lifted: up/win-line-endings", but #121221's file set (5 files) does not carry it |
| `tests/agent/test_compression_adoption_preserves_live_tail.py` | upstream | KEEP-HELD `test/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/agent/test_image_routing.py` | upstream | KEEP-PR #121222 | win-tilde-home | also in #121641's file set |
| `tests/agent/test_provider_fallback.py` | upstream | KEEP-HELD `test/test-hygiene` | test-hygiene | names `test_fallback_model.py`, deleted upstream in e2fd462ebe |
| `tests/agent/test_shell_hooks_consent.py` | upstream | KEEP-PR #121222 | win-tilde-home | — |
| `tests/agent/test_skill_commands.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/agent/test_skill_utils.py` | upstream | KEEP-HELD `test/win-test-fixes-2` | win-tests-2 | `Path()` compare; REVERT the orphan S5 banner; one hunk already upstream (b2ecd3518f) |
| `tests/cron/test_cron_memory_contract.py` | upstream | KEEP-HELD `test/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/docker/test_dashboard.py` | upstream | DROP | docker-tests | the fork runs no docker tier; a comment repoint in a test it never runs — revert |
| `tests/gateway/test_feishu.py` | upstream | DROP | feishu-adapter | see the adapter |
| `tests/gateway/test_media_spaced_paths_and_history_dedupe.py` | upstream | KEEP-PR #121222 | win-tilde-home | — |
| `tests/hermes_cli/test_apply_profile_override.py` | upstream | KEEP-HELD `test/win-test-fixes-2` | win-tests-2 | pin `_get_platform_default_hermes_home` + encoding |
| `tests/hermes_cli/test_auth_nous_provider.py` | upstream | KEEP-PR #121225 | win-posix-only-apis | also in #121642's file set |
| `tests/hermes_cli/test_backup.py` | upstream | KEEP-PR #121224 | win-path-spelling | also #121225; the `.bat` wrapper hunk is R10 (still red) — DROP that hunk |
| `tests/hermes_cli/test_deleted_profile_tombstone.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/hermes_cli/test_doctor.py` | upstream | KEEP-PR #125260 (`fix/doctor-call-time-home`) | doctor-home | the three `setenv` sites, test half of the class |
| `tests/hermes_cli/test_doctor_journal_modes.py` | upstream | KEEP-PR #121225 | win-posix-only-apis | the linux-marker rest → `test/platform-markers-linux` |
| `tests/hermes_cli/test_early_recovery.py` | upstream | DROP-AT-MERGE (was KEEP-PR #121218, closed 2026-09-27 as overtaken) | import-guard | — |
| `tests/hermes_cli/test_gateway_migrate_multiplex.py` | upstream | KEEP-HELD `test/platform-markers-linux` | platform-markers | `@pytest.mark.platforms("linux")` is upstream's own marker (`tests/test_hermes_constants.py` uses it at base) |
| `tests/hermes_cli/test_kanban_worktree_teardown.py` | upstream | KEEP-HELD `test/platform-markers-linux` | platform-markers | — |
| `tests/hermes_cli/test_linux_desktop_entry.py` | upstream | KEEP-HELD `test/platform-markers-linux` | platform-markers | 20 markers on `.desktop`-entry tests |
| `tests/hermes_cli/test_local_runtime.py` | upstream | KEEP-HELD `test/test-hygiene` | test-hygiene | the stub's `/models/unload` marks the model unloaded |
| `tests/hermes_cli/test_node_runtime_npm_resolution.py` | upstream | KEEP-HELD `test/platform-markers-linux` | platform-markers | — |
| `tests/hermes_cli/test_orphan_desktop_serve_reap.py` | upstream | KEEP-HELD `test/platform-markers-linux` | platform-markers | — |
| `tests/hermes_cli/test_projects_db.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/hermes_cli/test_prompt_compose_command.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/hermes_cli/test_setup_hermes_script.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/hermes_cli/test_win_pty_bridge.py` | upstream | KEEP-PR #121219 | win-conpty | — |
| `tests/scripts/test_run_tests_parallel.py` | upstream | KEEP-PR #125263 (`fix/test-runner`) | test-runner (P5) | REVERT the orphan S5 banners; one hunk already upstream (524c38a98a) |
| `tests/test_hermes_constants.py` | upstream | KEEP-HELD `test/win-test-fixes-2` | win-tests-2 | `sys.platform` pin, mirrors upstream's own win32 sibling |
| `tests/tools/test_approved_command_clean_slate.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/tools/test_base_environment.py` | upstream | DROP | R10 | the hunk does not turn the test green on Windows (bash resolution, then NTFS mode bits) and its concurrency half targets tests upstream deleted (524c38a98a) — revert |
| `tests/tools/test_delegate.py` | upstream | KEEP-HELD `test/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/tools/test_execution_flag_detection.py` | upstream | KEEP-PR #121226 | win-shell-invocation | the second hunk annotates a test upstream deleted (5f6b1d251f) — DROP that hunk |
| `tests/tools/test_file_ops_cwd_tracking.py` | upstream | DROP | R10 | still red at a later line after the hunk — revert |
| `tests/tools/test_file_tools.py` | upstream | DROP | dead-hunk | the tree carries only an unused `import os` (the `normpath` extension the ledger names is not in the diff, and upstream's file has no `os.` use) — revert |
| `tests/tools/test_file_tools_live.py` | upstream | KEEP-PR #121226 | win-shell-invocation | the whole diff, LF pin included, is in #121226's branch (the ledger's `up/win-line-endings` attribution is stale) |
| `tests/tools/test_file_tools_tilde_profile.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/tools/test_interrupt.py` | upstream | KEEP-HELD `test/test-hygiene` | test-hygiene | stale doc pointer |
| `tests/tools/test_local_background_child_hang.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/tools/test_local_env_cwd_recovery.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/tools/test_local_env_relative_cwd.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tests/tools/test_local_env_windows_msys.py` | upstream | KEEP-HELD `test/win-test-fixes-2` | win-tests-2 | `os.path.join`; REVERT the duplicated S5 banner |
| `tests/tools/test_modal_sandbox_fixes.py` | hook | KEEP-HELD `test/win-test-fixes-2` | win-tests-2 | the `_native_host_cwd` fixture spelling; the `tool_describe`-injected expectation is CARRY (7b) |
| `tests/tools/test_skills_hub.py` | upstream | DROP-AT-MERGE (was KEEP-PR #121221, closed 2026-09-27 as overtaken) | win-line-endings | the `jo.txt` R10 hunk — DROP that hunk |
| `tests/tools/test_subprocess_home_isolation.py` | upstream | KEEP-PR #121224 | win-path-spelling | — |
| `tests/tools/test_terminal_output_transform_hook.py` | upstream | KEEP-PR #121226 | win-shell-invocation | — |
| `tools/approval_context.py` | upstream | KEEP-PR #121646 | tirith-config | — |
| `tools/approval_detection.py` | upstream | KEEP-PR #125262 (`fix/win-path-identity`) | win-path-identity | the verification-artifact exemption accepts the MSYS spelling and asks identity through `tools/path_identity` (new file in the branch) |
| `tools/async_delegation.py` | hook | KEEP-PR #124190 | store-home-override | — |
| `tools/browser_tool_lifecycle.py` | upstream | KEEP-PR #125262 (`fix/win-path-identity`) | win-path-identity | socket-dir binding by identity |
| `tools/code_execution_env.py` | upstream | KEEP-PR #125262 (`fix/win-path-identity`) | win-path-identity | interpreter / prefix identity |
| `tools/credential_files.py` | upstream | KEEP-PR #121643 | win-remote-posix-paths | — |
| `tools/environments/local.py` | upstream | KEEP-PR #125261 (`fix/win-runtime-fixes`) | win-runtime | `_augment_windows_system_path` (called from `_make_run_env`); `_shell_arg_safe_path` is defined with no caller left in the tree — DROP that def |
| `tools/file_tools.py` | upstream | KEEP-PR #121645 | win-posix-guard-forms | upstream 666681cbf3d touched the file; hunk applies |
| `tools/file_tools_write_guards.py` | upstream | KEEP-PR #121645 | win-posix-guard-forms | CONFLICTS on 77a799e2f9c (four upstream commits on the guards, 641c49f8412…42841ece0f0) — the PR needs a rebase |
| `tools/image_generation_tool.py` | carry | KEEP-PR #125259 (`fix/readonly-config-reads`) | readonly-config | the FAL key read |
| `tools/mcp_tool_config.py` | hook | KEEP-PR #124210 | persisted-row-hooks | upstream 678a4762b88 / 40347fd40d7 (uv/uvx resolver) touched the file; hunk applies |
| `tools/mcp_tool_transport.py` | hook | KEEP-PR #124210 | persisted-row-hooks | CONFLICTS on 77a799e2f9c (75b64fb8ff5 rebuilt the identity inputs) — the PR needs a rebase |
| `tools/process_registry.py` | upstream | KEEP-PR #124190 | store-home-override | `checkpoint_path` via the background-work home; `ProcessNotificationMixin` + `wait_ceiling_seconds` → KEEP-ISSUE `durable-completion-restore`; the PTY `0x1A` EOF → `fix/win-runtime-fixes` |
| `tools/process_registry_notifications.py` | upstream | KEEP-HELD `fix/process-notification-redaction` | notification-redaction | redact, ANSI-strip and bound every field; `agent.redact` and `tools.ansi_strip` exist upstream |
| `tools/registry.py` | upstream | KEEP-HELD `fix/tool-registry-probe-cache` | registry-probe-cache | TTL/grace re-probe bound, `registry_epoch`, probe accounting; `scan_registered_tools` needs the fork's `tools/toolset_scan.py` → OUT of the branch (CARRY with its reader); toolset registration hunks ride #123979 |
| `tools/skills_hub_official.py` | upstream | KEEP-PR #121643 | win-remote-posix-paths | — |
| `tools/skills_tool.py` | hook | PLUGIN | skill-results (PF-3) | (c) runtime-compat refusal and (e) the inspection reader are PLUGIN / MOVE; (a) shared roots ride #124191; (b) `resolve_skill` is ADOPT upstream's walk (Q6); (d) `skills_list` filter → KEEP-ISSUE `skill-visibility-hook`; (f) G2 |
| `tools/skills_tool_plugin.py` | hook | PLUGIN | skill-results (PF-3) | leaves the footprint with PF-3 |
| `tools/terminal_tool.py` | hook | KEEP-PR #123977 | command-guard | (a) the envelope gate rides #123977; (b) task_id scope and (c) the brief schema are PLUGIN (PF-1); upstream 666681cbf3d touched the file, hunk applies |
| `tools/terminal_tool_result.py` | upstream | KEEP-PR #125262 (`fix/win-path-identity`) | win-path-identity | cwd change by identity |
| `tools/tirith_security.py` | upstream | KEEP-PR #121646 | tirith-config | — |
| `tools/tool_search.py` | hook | KEEP-PR #124192 | tool-search-never-defer | (a) rides #124192; (b) describe-over-all + legacy args CARRY (PAR-DESIGN 7b) |
| `tools/tts_tool.py` | carry | KEEP-PR #125259 (`fix/readonly-config-reads`) | readonly-config | the deep-copied config read; the `denotes_same_file` hunk → `fix/win-path-identity` |
| `tools/tts_tool_delivery.py` | upstream | KEEP-PR #125262 (`fix/win-path-identity`) | win-path-identity | audio paths by identity |
| `tools/vision_tools.py` | carry | KEEP-PR #125259 (`fix/readonly-config-reads`) | readonly-config | the two config reads; the `_lookup_supports_vision` import serves the fork's `_accepts_tool_result_images` and stays |
| `toolsets.py` | hook | KEEP-PR #123979 | register-toolset | (a) rides #123979; (b) `expand_toolset_names` is a MOVE to `agent_runtime/toolset_names.py` (PF-3) |
| `tui_gateway/entry.py` | upstream | KEEP-ISSUE | durable-completion-restore | an explicit startup restore vs upstream's ctor-time restore is a behaviour question |
| `tui_gateway/hosted_room_driver.py` | hook | KEEP-ISSUE | group-chat-host-surface | `request_reconciliation`; its three settlement fixes can be lifted as plain fixes once the issue says which surface |
| `tui_gateway/server.py` | upstream | KEEP-HELD `test/test-hygiene` | test-hygiene | ten upstream touches since base and the docstring still names the deleted `test_every_method_has_a_contract` |
| `utils.py` | upstream | KEEP-HELD `feat/atomic-write-newline` | atomic-write | `newline=` passthrough; three fork callers, none upstream — the body says so |
| `website/docs/developer-guide/billing-lifecycle.md` | upstream | DROP | website-docs | the fork does not publish the website; a stale-page fix belongs to whoever renders it |
| `website/docs/developer-guide/chronos-managed-cron-contract.md` | upstream | DROP | website-docs | same |
| `website/docs/developer-guide/gateway-session-lifecycle.md` | upstream | DROP | website-docs | same |
| `website/docs/developer-guide/relay-connector-contract.md` | upstream | DROP | website-docs | same |
| `website/docs/user-guide/egress/network-isolation.md` | upstream | DROP | website-docs | same |

## 2. Held branches (KEEP-HELD rows) — cut from `upstream/main` 77a799e2f9c, pushed to ORIGIN only, never to upstream

28 branches cut and pushed this sitting, plus two REUSED that were already on origin (`feat/auth-on-verification` da0369aee6, `feat/plugin-cli-commands` df624d82cc; bodies under `X:/wt/_holds/pr-bodies/`). Each branch carries one commit whose subject is the PR title and a body under `X:/wt/_holds/fix-triage-0926/pr-<class>.md` (upstream's PR template, filled). The tests column is the branch's own run of that class's upstream test files on this box; where a class was red, the SAME targets were run on a pristine `upstream/main` worktree and the failure sets diffed — `introduced: N` is the count of failures the branch adds, and it is 0 everywhere. A red that is the base tree's own (Windows-host reds upstream has not fixed, `schtasks` needing elevation, `tests._downstream`-free trees) is reported, not hidden. `up/live-system-guard` was cut, reddened 10 guard tests on `tests._downstream`, and was DELETED (row re-verdicted CARRY).

| branch | tip | diff vs upstream/main | body (`X:/wt/_holds/fix-triage-0926/`) | tests (this box, Windows 10 19045) |
|---|---|---|---|---|
| `feat/atomic-write-newline` | 114ad80297e (pushed: 114ad80297e) | 1 file changed, 4 insertions(+), 4 deletions(-) | `pr-atomic-write-newline.md` | 25 passed, 1 skipped |
| `fix/bytecode-sweep-lock` | 5a49ec39070 (pushed: 5a49ec39070) | 3 files changed, 791 insertions(+), 47 deletions(-) | `pr-bytecode-sweep-lock.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 385/20/49 (passed/failed/skipped), identical on unmodified `upstream/main`; one collection error on both sides (`truststore` not installed in this interpreter); failures introduced by this branch: 0 |
| `fix/copilot-direct-http-client` | b6b3b4ca236 (pushed: b6b3b4ca236) | 1 file changed, 5 insertions(+) | `pr-copilot-direct-http-client.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 64/0/2 (passed/failed/skipped), identical on unmodified `upstream/main`; one collection error on both sides (`truststore` not installed in this interpreter); failures introduced by this branch: 0; new test `tests/agent/test_copilot_direct_http_client.py` |
| `fix/doctor-call-time-home` | eb97d8821ff — OPENED as #125260 2026-09-27; (pushed: eb97d8821ff) | 5 files changed, 82 insertions(+), 35 deletions(-) | `pr-doctor-call-time-home.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 293/9/54 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0 |
| `feat/kanban-crash-evidence` | 8a8bbc6c813 (pushed: 8a8bbc6c813) | 2 files changed, 498 insertions(+) | `pr-kanban-crash-evidence.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 601/6/8 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0 |
| `feat/mcp-test-env` | 7545a31723f (pushed: 7545a31723f) | 2 files changed, 23 insertions(+) | `pr-mcp-test-env.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 201/8/0 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0 |
| `fix/media-path-hardening` | 917396caf06 — OPENED as #125264 2026-09-27; (pushed: 917396caf06) | 1 file changed, 4 insertions(+), 2 deletions(-) | `pr-media-path-hardening.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 436/1/16 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/gateway/test_media_path_hardening.py` |
| `fix/memory-plugin-publish-module` | 667d9c4fa80 (pushed: 667d9c4fa80) | 1 file changed, 76 insertions(+), 2 deletions(-) | `pr-memory-plugin-publish-module.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 249/1/0 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/plugins/memory/test_cli_module_publish.py` |
| `refactor/oauth-flow-catalog` | b7fd17717a7 (pushed: b7fd17717a7) | 3 files changed, 105 insertions(+), 58 deletions(-) | `pr-oauth-flow-catalog.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 287/1/1 (passed/failed/skipped), identical on unmodified `upstream/main`; one collection error on both sides (`truststore` not installed in this interpreter); failures introduced by this branch: 0 |
| `fix/pet-atlas-extraction` | 5c976b226f2 (pushed: 5c976b226f2) | 1 file changed, 109 insertions(+), 14 deletions(-) | `pr-pet-atlas-extraction.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 83/0/0 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/agent/test_pet_atlas_extraction.py` |
| `test/platform-markers-linux` | 022906ae592 (pushed: 022906ae592) | 5 files changed, 32 insertions(+) | `pr-platform-markers-linux.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 79/2/34 (passed/failed/skipped), unmodified `upstream/main`: 85/27/3 (passed/failed/skipped); failures introduced by this branch: 0 |
| `feat/plugin-session-info-tool-names` | a13c068b787 (pushed: a13c068b787) | 1 file changed, 1 insertion(+) | `pr-plugin-session-info-tool-names.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 255/17/6 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0 |
| `fix/process-notification-redaction` | dfb4e2aabd0 (pushed: dfb4e2aabd0) | 1 file changed, 29 insertions(+), 1 deletion(-) | `pr-process-notification-redaction.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 224/6/35 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/tools/test_process_notification_redaction.py` |
| `refactor/profile-bootstrap-extraction` | 4fdca58701c (pushed: 4fdca58701c) | 2 files changed, 375 insertions(+), 195 deletions(-) | `pr-profile-bootstrap-extraction.md` | 146 passed, 3 skipped, 1 warning |
| `fix/providers-discovery-import` | 5ce87836af0 (pushed: 5ce87836af0) | 2 files changed, 2 insertions(+), 2 deletions(-) | `pr-providers-discovery-import.md` | 19 failed, 46 passed; base tree same targets: 19 failed, 46 passed; introduced: 0 |
| `fix/readonly-config-reads` | 1f4541dd330 — OPENED as #125259 2026-09-27; (pushed: 1f4541dd330) | 12 files changed, 94 insertions(+), 30 deletions(-) | `pr-readonly-config-reads.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 2237/7/47 (passed/failed/skipped), unmodified `upstream/main`: 2234/10/47 (passed/failed/skipped); failures introduced by this branch: 0 |
| `fix/reasoning-relay-native` | 0b3ff4ec4de (pushed: 0b3ff4ec4de) | 1 file changed, 12 insertions(+), 1 deletion(-) | `pr-reasoning-relay-native.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 372/0/0 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/agent/test_reasoning_relay_native.py` |
| `chore/ruff-f821` | 28390921b6e (pushed: 28390921b6e) | 1 file changed, 68 insertions(+), 1 deletion(-) | `pr-ruff-f821.md` | `ruff check .`: All checks passed on this branch; on unmodified `upstream/main` F821 is not selected (forcing it reports 2808 findings); introduced: 0 |
| `fix/state-db-small-fixes` | 47f78f177cb (pushed: 47f78f177cb) | 2 files changed, 5 insertions(+), 3 deletions(-) | `pr-state-db-small-fixes.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 445/0/10 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/hermes_state/test_finish_reason_and_listing_order.py` |
| `test/test-hygiene` | 0e0e09f53df (pushed: 0e0e09f53df) | 7 files changed, 16 insertions(+), 9 deletions(-) | `pr-test-hygiene.md` | 23 failed, 122 passed, 1 skipped; base tree same targets: 23 failed, 68 passed; introduced: 0 |
| `fix/test-runner` | 33c7ed5dfeb — OPENED as #125263 2026-09-27; (pushed: 33c7ed5dfeb) | 4 files changed, 284 insertions(+), 46 deletions(-) | `pr-test-runner.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 284/3/21 (passed/failed/skipped), unmodified `upstream/main`: 281/3/21 (passed/failed/skipped); failures introduced by this branch: 0 |
| `fix/tool-registry-probe-cache` | b958a974edf (pushed: b958a974edf) | 1 file changed, 119 insertions(+), 35 deletions(-) | `pr-tool-registry-probe-cache.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 275/21/0 (passed/failed/skipped), identical on unmodified `upstream/main`; one collection error on both sides (`truststore` not installed in this interpreter); failures introduced by this branch: 0; new test `tests/tools/test_registry_grace_reprobe.py` |
| `fix/updater-fork-history` | 8dc246c5787 — OPENED as #125265 2026-09-27; (pushed: 8dc246c5787) | 4 files changed, 292 insertions(+) | `pr-updater-fork-history.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 299/14/33 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0 |
| `fix/watcher-reply-to` | 58a4608a49c — OPENED as #125266 2026-09-27; (pushed: 58a4608a49c) | 1 file changed, 2 insertions(+), 1 deletion(-) | `pr-watcher-reply-to.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 1055/3/9 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/gateway/test_watcher_reply_to.py` |
| `fix/win-gateway-task-console` | 8aa40dea437 (pushed: 8aa40dea437) | 2 files changed, 112 insertions(+) | `pr-win-gateway-task-console.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 357/24/16 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0; new test `tests/hermes_cli/test_gateway_windows_task_console.py` |
| `fix/win-path-identity` | f93b87d3fb9 — OPENED as #125262 2026-09-27; (pushed: f93b87d3fb9) | 9 files changed, 556 insertions(+), 17 deletions(-) | `pr-win-path-identity.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 1526/28/13 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0 |
| `fix/win-runtime-fixes` | 4140e5d5bb7 — OPENED as #125261 2026-09-27; (pushed: 4140e5d5bb7) | 3 files changed, 72 insertions(+), 4 deletions(-) | `pr-win-runtime-fixes.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 768/41/161 (passed/failed/skipped), identical on unmodified `upstream/main`; failures introduced by this branch: 0 |
| `test/win-test-fixes-2` | bfde9ce1a98 (pushed: bfde9ce1a98) | 6 files changed, 96 insertions(+), 17 deletions(-) | `pr-win-test-fixes-2.md` | `scripts/run_tests.sh` over the upstream test files for the touched paths: this branch 144/0/10 (passed/failed/skipped), unmodified `upstream/main`: 143/1/10 (passed/failed/skipped); failures introduced by this branch: 0 |


## 3. Issue drafts (KEEP-ISSUE rows) — `X:/wt/_holds/fix-triage-0926/issue-<slug>.md`; four filed 2026-09-27, four still drafts

| draft | rows it retires | the question |
|---|---|---|
| `issue-turn-phase-observer.md` → #125255 | `agent/turn_api_request.py`, `agent/turn_response_check.py`; the (b) halves of `agent/conversation_loop.py`, `agent/agent_init.py`, `model_tools.py` | the phase vocabulary of an `on_turn_phase` / `on_agent_init_phase` observer |
| `issue-group-chat-host-surface.md` → #125258 | `gateway/hosted_room_discussion.py`, `gateway/hosted_room_policy_checkpoint.py`, `gateway/hosted_rooms.py`, `tui_gateway/hosted_room_driver.py` | kwargs on the existing functions or a `RoomHost` protocol; the three settlement fixes split out after |
| `issue-configurable-context-floor.md` | `agent/conversation_compression.py`; `agent/agent_init.py` (c) | a `context.minimum_length` key (the fork's provider-name exemption is not a PR shape); `transform_compression_child` beside #124210 |
| `issue-skill-visibility-hook.md` → #125257 | `agent/prompt_builder.py` (c), `tools/skills_tool.py` (d) | `filter_skill_visible(skill_name, frontmatter, session_info)` in `hides()` / `_find_all_skills` |
| `issue-config-readonly-projection.md` | `hermes_cli/config.py` (the ContextVar half) | `set_readonly_projection(fn)` on the read-only door |
| `issue-durable-completion-restore.md` → #125256 | `tui_gateway/entry.py`; `gateway/run.py` (P2 hunk); `tools/process_registry.py` (mixin, `wait_ceiling_seconds`); `hermes_cli/main.py` (d) | an explicit, idempotent startup restore instead of the ctor-time import side effect; wait ceiling as config |
| `issue-updater-fork-sync-no-force.md` | `hermes_cli/update_cmd_git.py` | whether `--force-with-lease` on the fork sync push is intentional |
| `issue-context-files-load-all.md` | `agent/prompt_builder.py` (d) | a `context_files.load_all` key |

## 4. Close candidates

**None.** Every one of our 33 open PRs was checked against the table: no open PR's subject is a DROP row (the DROP set is website docs, the desktop app, nix, docker tests, the Feishu and Slack adapters, the contributors `case-variants/` lookup, two R10 test hunks and one dead hunk), and none of the 18 upstream-touched files carries our fix already. Two open PRs need a REBASE before review, not a close: #121645 (`tools/file_tools_write_guards.py` conflicts with 641c49f8412…42841ece0f0) and #124210 (`tools/mcp_tool_transport.py` conflicts with 75b64fb8ff5). #121220 was already closed 2026-09-26 as superseded and stays closed.

## 5. Counts and what this sitting did not do

Verdicts over 169 rows: **DROP 19 · PLUGIN 8 · KEEP-PR 58 · KEEP-HELD 71 (29 classes; 27 cut and pushed here + 2 reused from origin; `up/live-system-guard` cut, refuted, deleted) · KEEP-ISSUE 9 (8 drafts) · CARRY 4.**

- No fork tree file was changed; the ledger's `disposition` column is untouched — an exec lane applies the DROP reverts (19 files, all byte-revertible with `git checkout upstream/main -- <path>` except `tools/environments/local.py`'s dead `_shell_arg_safe_path` def, which is a partial) and re-takes `[up-fp]`.
- `scripts/upstream_footprint.py --check` (the brief's gate) does not exist; the script's flags are `--base`, `--json`, `--ledger`, `--refresh-manifest`. The line of record was re-taken with the bare invocation: `[up-fp] files=169 deleted_lines=906 heavy=4`, unchanged.
- Held branches carry each class's fork tests where one exists upstream-shaped (`test_path_identity.py`, `test_update_history.py`, `test_bytecode_sweep*.py`, `test_config_readonly_no_scaffold.py`); `feat/kanban-crash-evidence` carries a 485-line module with no test in either tree — its body says so.
- Every branch's test line was taken on this box (Windows 10 19045); where a class reddened, the SAME targets were run on a pristine `upstream/main` worktree and the failure sets diffed — the §2 column records "introduced: N", and N is 0 for every branch.
- The eight `up/*` fix PRs #121640–#121646 are open upstream and absent from `Harness_Brain/10 — Programs/Upstream Sync.md` § Open upstream PRs (queue row filed by the parent).

## 6. Drop re-triage 2026-09-27 (upstream/main ad4e4496c2)

Lane DROP-RETRIAGE, docs only. Question: since the held branches were cut from `upstream/main` **77a799e2f9c**,
upstream reached **ad4e4496c2** (800 commits). Of the fork's footprint (`scripts/upstream_footprint.py --json` at
fork `main` **1504b30f91**: 152 rows), `git diff --name-only 77a799e2f9c ad4e4496c2 -- <paths>` names **33** files.
Per file: the upstream commits in range and their diff; the fork's own delta (`git diff 067fa1a257 origin/main`)
replayed with `git apply --cached --check` onto a `read-tree ad4e4496c2` index; and every held branch / open PR that
§1 names for the path, merged with `git merge-tree --write-tree ad4e4496c2 <ref>` (PR heads fetched from
`pull/<n>/head`; #125259–#125266 are the held branches of §2, opened since, byte-identical tips). A CONFLICTS
verdict is a conflict NEW in the range — each was re-run against 77a799e2f9c and was clean there. The pin is the
brief's; `upstream/main` had moved 21 commits further (758ad514eb) at sitting time and those are not triaged here.

Vocabulary. **DROP-NOW** — upstream now carries the fork's lines (commit named). **SUPERSEDES** — one of our open
PRs / held branches is now redundant. **CONFLICTS** — our branch needs a rebase against this change (hunk named).
**KEEP** — upstream's change is unrelated; the fork lines are still needed.

| path | §1 verdict | upstream commits (n) | new verdict | why |
|---|---|---|---|---|
| `agent/agent_init.py` | PLUGIN (PF-1) | 1 | KEEP | 516535b542 names an exhausted (402) pool in `_routed_client_kwargs`; the init receipts and the `local-llama-hermes` floor exemption are elsewhere and apply clean |
| `agent/conversation_compression.py` | KEEP-ISSUE `configurable-context-floor` | 8 | KEEP | f807217ff1…e81be5b66a are compression-child prompt adoption and seeded-prompt retention; the aux-floor exemption and `child_model_config` hunks are untouched and apply clean |
| `agent/conversation_loop.py` | KEEP-PR #124210 | 2 | KEEP | a4db03cee9 (empty live Model/Provider is a stale route) and f762b96bfd (one return shape); `reuse_current_user_message` and the timing marks not carried; #124210 merges clean |
| `agent/prompt_builder.py` | PLUGIN (PF-2) | 3 | KEEP | c1685027af names the Skill Safety heading, d9ef15dd3c/0d9329bd95 add `ASYNC_HANDOFF_GUIDANCE`; upstream still loads ONE context file (first found wins) and has no runtime-compat skill filter; #124191 merges clean |
| `agent/system_prompt.py` | KEEP-HELD `feat/plugin-session-info-tool-names` | 1 | KEEP | 96a8cecd39 appends the async-handoff guidance keyed on `valid_tool_names`; `session_info["tool_names"]` still absent; branch merges clean |
| `agent/turn_context.py` | KEEP-PR #124210 | 1 | KEEP | b90b7ae7ed titles subagent sessions without a model call; unrelated to the reuse hunks; #124210 merges clean |
| `apps/shared/src/gateway-contract.generated.ts` | — (joined the footprint after §1) | 4 | KEEP | upstream regenerated for `FailedDelegation` / `continuation_kind` / `hermes_not_connected`; the fork's `reject_if_busy` on `PromptSubmitParams` is untouched and applies clean — regenerate at the merge |
| `apps/shared/src/gateway-contract.openrpc.json` | — (joined the footprint after §1) | 4 | KEEP | same four commits (0f15d80a02, 42d70d29ac, da4a1ffd08, a30bd337e5); the `reject_if_busy` property applies clean |
| `gateway/run.py` | KEEP-PR #121646 | 7 | KEEP | 24758cf4b8…d915436657 unbound the turn executor, 556b8427b7 retains the hygiene seeded prompt; the approvals heads-up and `restore_durable_completions` hunks apply clean; #121646's only conflict is `cli.py`, pre-existing at 77a |
| `gateway/run_notifications.py` | KEEP-HELD `fix/watcher-reply-to` (now PR #125266) | 1 | CONFLICTS #125266 (`fix/watcher-reply-to`) | semantic, not textual (merges clean): 10938a7cf9 (#52694) rules the watch-arming `message_id` a STALE reply anchor and strips it from the synthetic completion event; #125266 adds exactly that anchor (`reply_to=watcher.get("message_id")`) on `_send_watcher_message` — reconcile against upstream's stated direction, or close, before review |
| `hermes_cli/auth.py` | KEEP-PR #124190 | 2 | KEEP | b085de8e3c/c1edc9f1b5 stop routing a real OpenAI key to OpenRouter; `_auth_file_path` untouched; #124190 merges clean |
| `hermes_cli/doctor_platform.py` | KEEP-HELD `fix/doctor-call-time-home` (now PR #125260) | 1 | KEEP | 3ddf06867f adds the Windows autostart doctor check; the module-constant `HERMES_HOME` import is unchanged; branch merges clean |
| `hermes_cli/gateway.py` | KEEP-PR #119069 | 2 | KEEP | 029445545c/5a0225dfff make the restart watcher stdlib-only; the `pwd`/`getuid` guards and the `resolve_managed_python` parallel are untouched; #119069 merges clean |
| `hermes_cli/gateway_windows.py` | KEEP-HELD `fix/win-gateway-task-console` | 3 | KEEP | 33f45ca30b/a1d2a5bd57 reconcile Startup-folder entries, 46fba4c9a4 scopes the readiness poll to this install; upstream still never inspects the REGISTERED task's action, so the console-task warning is not carried; this file merges clean (the branch's conflict is `update_cmd_windows.py`) |
| `hermes_cli/main.py` | KEEP-HELD `refactor/profile-bootstrap-extraction` | 2 | CONFLICTS `refactor/profile-bootstrap-extraction` | 8684bf3ddc adds the `_explicit_cli_profile` global + `explicit_cli_profile()` and edits `_apply_profile_override` inside the block the branch moves to `_profile_bootstrap.py` (merge-tree conflict over main.py:464–677); the rebase must carry the global into the extracted module. The fork's own main.py delta no longer applies either. `feat/plugin-cli-commands` merges clean |
| `hermes_cli/mcp_config.py` | KEEP-HELD `feat/mcp-test-env` | 1 | KEEP | b148d97602 changes two hint strings to name `/reload-mcp`; branch merges clean |
| `hermes_cli/uninstall.py` | KEEP-PR #121640 | 6 | CONFLICTS #121640 | 0fec10a3ce…c437bab069 insert the desktop-userData lines at both print sites where #121640 adds its git-history line (`run_uninstall` summary and `_print_uninstall_dry_run`); textual — upstream still names no git history, so the content stays. The fork's own hunk conflicts at the same sites |
| `hermes_cli/update_cmd.py` | KEEP-HELD `fix/updater-fork-history` (now PR #125265) | 5 | KEEP | ff46826872 parks a detached HEAD behind a rescue ref — a different hazard from the fork-history guard; the rest are channel retries, PM git and Desktop rebuild; branch merges clean |
| `hermes_cli/update_cmd_git.py` | KEEP-ISSUE `updater-fork-sync-no-force` | 1 | KEEP | ff46826872 adds `_park_detached_head`; `_sync_fork_with_upstream` still pushes `--force-with-lease`, so the issue's question stands |
| `hermes_cli/update_cmd_windows.py` | KEEP-HELD `fix/win-gateway-task-console` | 4 | CONFLICTS `fix/win-gateway-task-console` | 3ddf06867f inserts `reconcile_autostart_launchers()` directly after "Refreshed Windows gateway launcher scripts" in `_refresh_windows_gateway_launchers` — the line the branch's `_warn_legacy_console_gateway_task()` call follows; the fork's `ManagedPythonUnavailable` carry hunk conflicts at the same site |
| `hermes_state_messages.py` | KEEP-HELD `fix/state-db-small-fixes` | 2 | KEEP | 3d7058fc83 re-folds display orders, e0bc2c1ce9 adds `get_latest_todo_result`; `finish_reason` is still assistant-only; branch merges clean |
| `hermes_state_sessions.py` | KEEP-HELD `fix/state-db-small-fixes` | 9 | KEEP | `created_source`, `show_subagents`, route writers stop nulling the prompt; the list `ORDER BY started_at DESC` still has no `id` tie-break; branch merges clean |
| `scripts/run_tests.sh` | KEEP-HELD `fix/test-runner` (now PR #125263) | 2 | KEEP | 22fe26db2a/16da7f1b38 forward the Windows e2e knobs; branch merges clean |
| `tests/hermes_cli/test_backup.py` | KEEP-PR #121224 | 5 | KEEP | a71ff10071…6125c0c707 append failed-zip-member tests; the fork's Windows-spelling hunks apply clean; #121224's conflicts are in other files and predate 77a |
| `tests/hermes_cli/test_linux_desktop_entry.py` | KEEP-HELD `test/platform-markers-linux` | 1 | CONFLICTS `test/platform-markers-linux` | a6686cc396 appends four install tests after :641 where the branch adds markers; rebase, and decide markers for the four new unmarked tests (they drive the same `install_desktop_entry`) |
| `tools/async_delegation.py` | KEEP-PR #124190 | 1 | KEEP | a30bd337e5's `failed_delegations_for_session` reads through `_db_path()`, so the background-work home still governs it; #124190 merges clean |
| `tools/credential_files.py` | KEEP-PR #121643 | 1 | KEEP | a164569429 adds the `composer-pastes` cache dir; the `as_posix()` hunk is untouched |
| `tools/file_tools.py` | KEEP-PR #121645 | 2 | CONFLICTS #121645 | b9d5e4d17f/0a99750128 add `_resolve_entry_for_task` to the `tools.file_tools_paths` import line (file_tools.py:31) that the PR edits to add `_posix_match_forms`; a second rebase point beside the known `file_tools_write_guards.py` one |
| `tools/mcp_tool_transport.py` | KEEP-PR #124210 (CONFLICTS on 77a) | 1 | KEEP | 0cd93f0268 attaches a Windows kill-on-close job before the stdio spawn; unrelated. §1's conflict is RETIRED: #124210 (re-cut, merge-base f077152871) merges clean on ad4e4496c2. The fork's own hunk still does not apply, as at 77a |
| `tools/process_registry.py` | KEEP-PR #124190 | 3 | KEEP | 8cb4fdc925 heartbeats only on new output, 7550800d8b/627bf49baa recovered-PID fate; `checkpoint_path` and the mixin hunks apply clean; #124190 and `fix/win-runtime-fixes` merge clean |
| `tools/process_registry_notifications.py` | KEEP-HELD `fix/process-notification-redaction` | 1 | KEEP | 8cb4fdc925 adds the hidden heartbeat display; upstream still interpolates raw command/output, so redaction is still needed; branch merges clean |
| `tools/terminal_tool.py` | KEEP-PR #123977 | 5 | KEEP | b9d5e4d17f…b686f1b40b docker mounted-cwd remap, 4317ed0e71/e6f0966b01 heartbeat schema; #123977 merges clean |
| `tui_gateway/server.py` | KEEP-HELD `test/test-hygiene` | 5 | KEEP | answer-only chrome gate and prefill; the docstring still names the deleted test and the branch merges clean. The fork's `skill_view` hunk no longer applies: c0f1ed114c/f41c6517ea turned the tuple into `_TOOL_LIFECYCLE_UI_TOOLS` — re-author as a set member at the merge |

Counts over the 33 upstream-touched footprint files: **DROP-NOW 0 · SUPERSEDES 0 · CONFLICTS 6 · KEEP 27.**
- No upstream commit in the range carries a fork line: nothing becomes droppable and no open PR or held branch is redundant.
- CONFLICTS: 4 held branches (`fix/watcher-reply-to` #125266 semantic; `refactor/profile-bootstrap-extraction`, `fix/win-gateway-task-console`, `test/platform-markers-linux` textual) and 2 PRs (#121640, #121645) — each clean against 77a799e2f9c.
- Retired: §1's #124210 conflict on `tools/mcp_tool_transport.py` (the re-cut PR merges clean).
- The fork's own delta no longer applies on 6 files (`hermes_cli/main.py`, `hermes_cli/uninstall.py`, `hermes_cli/update_cmd_windows.py`, `tests/hermes_cli/test_linux_desktop_entry.py`, `tools/mcp_tool_transport.py` as at 77a, `tui_gateway/server.py`) — merge-time work, not a verdict change.

## 7. Open-PR staleness 2026-09-27 (upstream/main 062dc1e7f0)

Lane PR-STALE, docs only. Question: has upstream made any of our 15 open upstream PRs stale? Per PR: merge-base
with `upstream/main` **062dc1e7f0**; the PR's files (`git diff --name-only <mb> origin/<branch>`); the upstream
commits on them (`git log <mb>..upstream/main -- <files>`, union count below) and their diffs at the PR's hunks
(`git log -L`); `git merge-tree --write-tree upstream/main origin/<branch>`; and each file's PR diff checked with
`git apply --cached --check` (and `-R`) against a `read-tree upstream/main` index. For the Windows test PRs each
touched test was also read on `upstream/main` for a `platforms(...)` gate. Nothing was published.

Vocabulary as brief. **FRESH** — no upstream change on the PR's lines, or unrelated. **REBASE** — textual conflict
only. **OVERTAKEN** — upstream fixed the same thing; close. **REVERSED** — upstream ruled the opposite way; owner
call. **PARTIAL** — some hunks are upstream; survivors named. One pattern dominates: upstream **bd258480d3**
("make the test suite pass on Windows", 2026-08-27; its `linux_only` marks renamed to `platforms("linux")` by
9b8ad35ee6) fixed some of the same tests and GATED others as Linux-only instead of fixing them. A gated test is
not a fixed one: our hunk would make it run on Windows, so un-gating it is an owner call (listed as "gated"
below), never a silent re-open.

| PR | branch | files | upstream commits on them | merge | verdict | why |
|---|---|---|---|---|---|---|
| #121646 | `up/tirith-env-overrides` | 8 | 96 | CONFLICT `cli.py` | REBASE | df1b647b42 rewrote the `_ensure_tirith_security` warning block (`missing_is_expected()`) the PR's `tirith_enabled(self.config)` hunk sits in; upstream still has no shared reader, `approval_context._tirith_fail_open` still ignores `TIRITH_*`, and quoted config flags still parse raw — the fix stands |
| #121645 | `up/win-posix-guard-forms` | 4 | 15 | CONFLICT `tools/file_tools.py`, `tools/file_tools_write_guards.py` | REBASE | 0a99750128 (file_tools.py import line :31) and 641c49f841 (write_guards import line) moved the lines the PR edits; `_is_blocked_device_path` and `_check_sensitive_path` still compare only the `os.path.normpath` form, so the POSIX-form guard is still needed |
| #121644 | `up/win-python-snippet-verbatim` | 2 | 25 | clean | OVERTAKEN | bd258480d3 added `_exec_python_snippet` (base64 through every quoting layer) and moved both `_run_python_snippet` callers — the UTF-16 reader included — onto it; `_run_python_snippet`, which the PR patches, has no caller on `upstream/main` |
| #121643 | `up/win-remote-posix-paths` | 7 | 30 | CONFLICT `tests/tools/test_credential_files.py`, `tools/environments/daytona.py` | PARTIAL | upstream: `iter_skills_files` `.as_posix()` (92686159d1), Daytona parent via `PurePosixPath` (bd258480d3). Survive: `iter_cache_files` as_posix, Modal + SSH `posixpath.dirname`, `OptionalSkillSource` bundle keys, both tests |
| #121642 | `up/nous-login-inference-url` | 4 | 46 | clean | FRESH | `_nous_device_code_login` still persists `token_data["inference_base_url"]` unvalidated (auth_nous.py:1401) and no store-load heal exists; the upstream commits on these files are unrelated |
| #121641 | `up/win-drive-image-paths` | 2 | 14 | CONFLICT `agent/image_routing.py` | OVERTAKEN | bd258480d3 carries the same `_LOCAL_IMAGE_PATH_RE` (`~/`, `/`, `[A-Za-z]:[\\/]`, either separator) plus a `normpath`; only our extra pattern test is not upstream |
| #121640 | `up/doc-accuracy` | 5 | 22 | CONFLICT `hermes_cli/uninstall.py` | REBASE | as §6: 0fec10a3ce…c437bab069 (desktop userData lines) at both print sites; the `test_puid_pgid_remap.py` cite (service_manager.py:310) and the "pre-push stale-base gate" docstring (worktree_ops.py:216) are still wrong upstream |
| #121226 | `up/win-shell-invocation` | 10 | 14 | CONFLICT `tests/tools/test_file_tools_live.py`, `tests/tools/test_local_env_relative_cwd.py` | PARTIAL | none fixed upstream. Survive (untouched, ungated): `test_completion`, `test_setup_hermes_script`, `test_execution_flag_detection`, `test_file_tools_live` (conflict = upstream blank-line removal). Gated `platforms("linux")` by bd258480d3: `test_skill_commands`, `test_prompt_compose_command`, `test_approved_command_clean_slate`, `test_local_background_child_hang`, `test_local_env_relative_cwd`, `test_terminal_output_transform_hook` |
| #121225 | `up/win-posix-only-apis` | 4 | 60 | CONFLICT `tests/hermes_cli/test_doctor_journal_modes.py` | PARTIAL | upstream: the `os.geteuid` collection-time guard (`hasattr(os, "geteuid")`, bd258480d3); the missing-file strerror test gated Linux-only. Survive: `test_auth_nous_provider` mode spy, `test_backup` chmod spy, `test_process_registry` getpgid + taskkill seam |
| #121224 | `up/win-path-spelling` | 13 | 53 | CONFLICT in 7 test files | PARTIAL | upstream fixed the same asserts in 7 (bd258480d3; 427d4936c2 for subprocess-home): `test_file_safety_sandbox_mirror`, `test_save_url_image`, `test_media_resend_dedup`, `test_post_stream_media_delivery`, `test_projects_db`, `test_checkpoint_manager`, `test_subprocess_home_isolation`. Gated: `test_file_tools_tilde_profile`, `test_local_env_cwd_recovery`. Survive: `test_runtime_footer`, `test_backup` (kanban `endswith`), `test_deleted_profile_tombstone` (`re.escape`), `test_computer_use` (`json.dumps`) |
| #121222 | `up/win-tilde-home` | 5 | 9 | CONFLICT `tests/agent/lsp/test_workspace.py`, `tests/agent/test_image_routing.py`, `tests/gateway/test_media_spaced_paths_and_history_dedupe.py` | PARTIAL | upstream: `USERPROFILE` in `test_image_routing` and `test_media_spaced_paths_and_history_dedupe` (bd258480d3). Gated: `lsp/test_workspace` (3d12e86ef1 also added a win32 branch, then gated it), `test_shell_hooks_consent`. Survive: `test_runtime_footer` only |
| #121221 | `up/win-line-endings` | 5 | 24 | CONFLICT in all 5 files | OVERTAKEN | `test_debug`, `test_tui_resume_flow`, `test_skills_hub` (bd258480d3), `test_diff_command` (3c08d16ba7) take the same byte-exact writes / CRLF-tolerant assert; `test_working_diff` has `core.autocrlf false` (92686159d1) — our remaining `write_bytes` there is redundant under it |
| #121218 | `up/import-guard-relative-imports` | 1 | 3 | CONFLICT `tests/hermes_cli/test_early_recovery.py` | OVERTAKEN | 8b7eae99ef deleted `test_early_recovery_module_is_stdlib_only`, the guard the PR edits; the file now proves stdlib-only startup with a `python -S` run instead |
| #124210 | `up/persisted-row-hooks` | 12 | 4 | clean | FRESH | a4db03cee9/f762b96bfd (conversation_loop), b90b7ae7ed (turn_context), 0cd93f0268 (mcp_tool_transport) are unrelated; no `transform_persisted_row` / `transform_mcp_*` / `reuse_current_user_message` upstream |
| #123978 | `widen/per-call-usage-record` | 9 | 10 | clean | FRESH | `post_api_request` still carries no per-call `cost` and nothing keeps `api_call_records`; the turn_finalizer / conversation_loop / test_run_agent commits are interrupt, compaction and todo work |

Counts over the 15 PRs: **FRESH 3 · REBASE 3 · OVERTAKEN 4 · REVERSED 0 · PARTIAL 5.**
- FRESH: #121642, #124210, #123978. REBASE: #121646, #121645, #121640.
- OVERTAKEN (close, citing the commit): #121644 and #121641 (bd258480d3), #121221 (bd258480d3 / 3c08d16ba7 / 92686159d1), #121218 (8b7eae99ef).
- PARTIAL (rebase down to the survivors named above): #121643, #121226, #121225, #121224, #121222.
- No REVERSED verdict; the nearest is the gated tests: upstream chose Linux-only gating where we fixed.

To close: **#121644, #121641, #121221, #121218.** For the owner: (1) the PARTIAL PRs' gated tests — 6 files in #121226,
2 in #121224, 2 in #121222 — cut them (accept upstream's Linux-only gate) or keep them and remove the gate in the
same PR (more Windows coverage, a harder review); (2) #121222 and #121224 now both reduce to hunks in
`tests/gateway/test_runtime_footer.py`, so one PR can carry both.

## 8. Dedupe 2026-09-27 (upstream/main 2f14d5e6e4, open upstream PRs as of 2026-09-27)

Lane DEDUPE, docs only. Question: is any PR or held branch of ours already covered by someone else's upstream work
(upstream `CONTRIBUTING.md` § "Before You Start: Search First")? Population: the 40 upstream PRs open under `nekwo` at
sitting start (#121218, #121221, #121641, #121644 were closed as overtaken by §7 during the sitting and are kept for the
record) and the 24 held branches named in the brief. Per item: its files and commit message (PR bodies for PRs); three
`gh search prs --repo NousResearch/hermes-agent --state open` keyword queries plus one `gh pr list --state open
--search <main file>`, results filtered to other authors; every candidate's diff read with `gh pr diff` before a
verdict; and the merged side, `git log <merge-base>..upstream/main -- <files>`, each item's patch checked with `git
apply --cached --check` (and `-R`, per hunk) against a `read-tree upstream/main` index, conflicting hunks read with
`git merge-file --diff3`. No hunk of any item is already present whole on `upstream/main`; the merged-side overlaps are
same-symptom fixes spelled differently. Nothing was published, closed or deleted.

Vocabulary as brief. **UNIQUE** — no open PR or merged commit fixes the same symptom (a candidate listed was read and
differs). **OVERLAPS** — same area and symptom, different fix; what differs and whether to reference or rebase is in
the row. **DUPLICATE-OF** — the same fix; close the PR or delete the held branch. A merged commit is named by hash
(`bd258480d3` reached `upstream/main` through the 27df3b8847 merge; it is "make the test suite pass on Windows").

| item | files (main file) | queries run | candidate | verdict | why |
|---|---|---|---|---|---|
| #125265 | 4 (`hermes_cli/update_cmd.py`) | "fork fast-forward update reset"; "update_history"; "updater fork history"; path `hermes_cli/update_cmd.py` | #114658 | OVERLAPS #114658 | same symptom (`hermes update` resetting a checkout that holds local commits), different fix: #114658 refuses any same-branch reset when `origin/<branch>..HEAD` is non-empty; ours is fork-only (`guard_fork_history`, `update_history.py`) and caches the history assessment in the plan. Reference it; if it lands first, the fork guard is what remains of ours |
| #125264 | 2 (`gateway/platforms/base.py`) | "media delivery denylist"; "backslash terminator media path"; "NUL path media"; path `gateway/platforms/base.py` | #78162 | OVERLAPS #78162 | same function (`_media_delivery_denied_paths`), same "denylist misses on Windows" family, different hunk: #78162 adds `%SystemRoot%` / `%ProgramData%` / AppData credential roots; ours makes the home root honour `$HOME`, adds a backslash to the terminator class and drops NUL paths. Adjacent lines (`home = ...`); reference, whichever lands second rebases |
| #125263 | 4 (`scripts/run_tests_parallel.py`) | "run_tests.sh Windows"; "run_tests_parallel"; "test runner timeout retry"; path `scripts/run_tests_parallel.py` | #122252, #66253, #81376, #39347 | OVERLAPS #122252 | both change the automatic `-j` default in `run_tests_parallel.py` (#122252 clamps to the cgroup `memory.max`, #66253 to the fd budget, ours `_adaptive_default_jobs` caps by CPU). Path splitting, bounded timeout retry and node-id selectors are ours alone; #81376 (Windows output to a file) and #39347 (venv probe) are other symptoms. Reference #122252 and fold the default into one rule |
| #125262 | 9 (`tools/approval_detection.py`) | "path identity Windows"; "samefile Windows path compare"; "path_identity"; path `tools/approval_detection.py` | none | UNIQUE | no open PR or merged commit compares paths by file identity; `tools/path_identity.py` is new |
| #125261 | 3 (`tools/environments/local.py`) | "PTY EOF Windows"; "terminal Windows PATH system tooling"; "Ctrl-Z EOF"; path `tools/environments/local.py` | none | UNIQUE | §6: the `process_registry.py` commits (8cb4fdc925, 7550800d8b, 627bf49baa) are heartbeat / recovered-PID work; no open PR on PTY EOF or the child PATH |
| #125260 | 5 (`hermes_cli/doctor.py`) | "doctor HERMES_HOME"; "doctor dotenv"; "_DHH"; path `hermes_cli/doctor.py` | #65096 | OVERLAPS #65096 | same symptom (doctor names the wrong home in its advice), different layer: #65096 replaces literal `~/.hermes` strings with `_DHH`; ours makes `HERMES_HOME` / `_DHH` resolve at call time. Complementary; if #65096 lands its new `{_DHH}` sites become `{_dhh()}` under ours. Reference it |
| #125259 | 12 (`hermes_cli/config.py`) | "load_config_readonly"; "read-only config scaffold"; "config scaffold home"; path `hermes_cli/config.py` | none | UNIQUE | no open PR on read-only config loads scaffolding the home; the `load_config_readonly` hits are unrelated callers |
| #124210 | 12 (`tools/mcp_tool_config.py`) | "persisted row hook"; "reuse_current_user_message"; "MCP HERMES_HOME stdio"; path `tools/mcp_tool_config.py` | none | UNIQUE | §7 FRESH; no open PR adds persisted-row / MCP transform hooks or `reuse_current_user_message` |
| #124195 | 2 (`tools/environments/base_output.py`) | "drain_fd"; "pipe drain"; "base_output"; path `tools/environments/base_output.py` | none | UNIQUE | no open PR exposes a public pipe drain; the "pipe drain" hits are qqbot / update-console fixes |
| #124194 | 4 (`hermes_cli/local_runtime/bootstrap.py`) | "local runtime executable_path"; "model_dirs"; "model_overrides"; path `hermes_cli/local_runtime/bootstrap.py` | none | UNIQUE | the `model_overrides` hits are models_dev / reasoning keys, a different config tree; no local-runtime executable / model-dir PR |
| #124193 | 2 (`agent/credential_pool.py`) | "_select_unlocked"; "credential pool rotate"; "_pick_and_rotate"; path `agent/credential_pool.py` | #121517, #115546 | UNIQUE | #121517 passes `model=` at the `mark_exhausted_and_rotate` call site, #115546 adds a `strategy` property after `_select_unlocked`; neither touches the strategy branch ours extracts into `_pick_and_rotate` (textual neighbours only) |
| #124192 | 4 (`tools/tool_search.py`) | "never_defer"; "tool_search eager"; "tool search defer"; path `tools/tool_search.py` | #114578 (salvage of #110714) | DUPLICATE-OF #114578 | same feature: a config list of tool names that never defer behind tool search, plugin/MCP tools included (`tools.tool_search.eager` there, `never_defer` here, the same `is_deferrable_tool_name` short-circuit). #114578 is teknium1's salvage of #110714 plus a per-server `defer: false`, and closes #86620. Close ours, pointing at #114578 |
| #124191 | 4 (`agent/skill_utils.py`) | "skills extra_dirs"; "excluded_dirs skills"; "skills external dirs"; path `agent/skill_utils.py` | #51412, #113491 | UNIQUE | the external-dirs PRs are a read-only guard (#51412) and flat-skill collapse (#113491); none adds writable `skills.extra_dirs` / `excluded_dirs` |
| #124190 | 4 (`hermes_constants.py`) | "auth store home override"; "background work ledger"; "HERMES_AUTH_HOME"; path `hermes_constants.py` | #74639 | OVERLAPS #74639 | same symptom (the auth store must outlive a disposable `HERMES_HOME`), different mechanism and size: #74639 is an absolute `HERMES_AUTH_HOME` env with auth-aware backup / restore / profile / uninstall flows; ours is a context-local `set_store_home_override("auth" / "background_work")`. Reference it; ours is the smaller seam and also covers the background-work ledger |
| #123979 | 5 (`tools/registry.py`) | "register_toolset"; "add_to_toolset"; "plugin toolset"; path `tools/registry.py` | #110527 | OVERLAPS #110527 | same surface (plugin-owned toolsets on `PluginContext` + `tools/registry.py`), different concept: #110527 adds ephemeral session-owned toolsets (`session_toolset`, disposal); ours persistent named toolsets and bundle membership (`register_toolset` / `add_to_toolset`). Reference; the registry hunks rebase if it lands first |
| #123978 | 9 (`agent/codex_runtime.py`) | "post_api_request cost"; "Codex app-server usage"; "per-call cost hook"; path `agent/codex_runtime.py` | #70690, #99968 | OVERLAPS #70690 | the Codex app-server half is the same fix: #70690 fires `post_api_request` for Codex app-server turns in `agent/codex_runtime.py`, as our `_fire_codex_post_api_request` does. Ours also adds a per-call `cost` to every `post_api_request`. Reference #70690 and drop or rebase the Codex half; #99968 (retain `_last_turn_usage`) is another symptom |
| #123977 | 4 (`tools/approval.py`) | "command_guard"; "terminal command hook plugin"; "pre_terminal_command"; path `tools/approval.py` | none | UNIQUE | no open PR adds a `command_guard` / pre-terminal-command plugin hook |
| #123976 | 5 (`gateway/run_inbound.py`) | "busy_policy"; "plugin slash command gateway"; "gateway_context"; path `gateway/run_inbound.py` | #68112, #91527, #75950 | OVERLAPS #68112 | same API: #68112 adds an opt-in `gateway_context=True` on plugin `register_command` and routes plugin commands past the active-session queue; ours adds `gateway_context` too, plus `busy_policy="dispatch"` so only opted-in commands bypass. #91527 passes sender context by handler arity. The strongest overlap in the set: rebase onto #68112's context type, or close in its favour and offer `busy_policy` there |
| #123892 | 2 (`agent/shell_hooks.py`) | "shell hook backslash"; "shell_hooks Windows"; "hook script path Windows"; path `agent/shell_hooks.py` | #116628 | UNIQUE | #116628 runs a bare `.sh` hook through bash on Windows; ours makes the consent allowlist recognise a backslash path as the script path. Different symptom, adjacent function |
| #123891 | 3 (`gateway/lifecycle_ledger.py`) | "lifecycle sentinel"; "loop heartbeat"; "shutdown_watchdog"; path `gateway/lifecycle_ledger.py` | #122885, #103215 | UNIQUE | both touch `shutdown_watchdog.py` (a forensic dump file; a `gateway_state.json` restamp); neither keeps the sentinel and heartbeat in the launch home |
| #123890 | 2 (`evals/postmortem/live_ab/cache_concurrency_probe.py`) | "cache_concurrency_probe"; "evals NameError"; "live_ab"; path `evals/postmortem/live_ab/cache_concurrency_probe.py` | none | UNIQUE | no open PR on `cache_concurrency_probe` |
| #123876 | 1 (`.gitignore`) | "gitignore .claude"; ".claude directory gitignore"; "gitignore agent"; path `.gitignore` | none | UNIQUE | no open PR ignores `.claude/` |
| #123874 | 2 (`.gitattributes`) | "gitattributes eol"; "CRLF LF gitattributes"; "line endings gitattributes"; path `.gitattributes` | #78571, #72738 | DUPLICATE-OF #78571 | the same line, `* text=auto eol=lf`, plus per-extension `eol=lf` rules; #72738 is `* text=auto` alone. Ours adds only the renormalisation of one CRLF file in the index: offer that on #78571 and close ours |
| #121646 | 8 (`tools/tirith_security.py`) | "TIRITH_ENABLED"; "TIRITH_FAIL_OPEN"; "tirith env"; path `tools/tirith_security.py` | #29547 | OVERLAPS #29547 | #29547 (2026-05-21) routes the same `cli.py` tirith warning gate through `_load_security_config()` for the same ignored-`TIRITH_ENABLED` symptom; ours covers every reader (`gateway/run.py`, `approval_context`) through `hermes_cli/tirith_config.py`. Reference it; the `cli.py` hunk is the shared one. Still REBASE per §7 |
| #121645 | 4 (`tools/file_tools_paths.py`) | "POSIX guard Windows"; "write guard Windows path"; "file_tools_write_guards"; path `tools/file_tools_paths.py` | none | UNIQUE | no open PR; the merged side is §7 REBASE only (0a99750128, 641c49f841 moved import lines) |
| #121644 | 2 (`tools/file_operations.py`) | "python -c snippet Windows"; "_run_python_snippet"; "snippet backslash"; path `tools/file_operations.py` | bd258480d3 (merged via 27df3b8847) | DUPLICATE-OF bd258480d3 | merged: `_exec_python_snippet` (base64) replaced every `_run_python_snippet` caller. CLOSED 2026-09-27 per §7; no open PR |
| #121643 | 7 (`tools/environments/daytona.py`) | "POSIX separators remote"; "as_posix remote path"; "ssh mkdir Windows"; path `tools/environments/daytona.py` | bd258480d3, 92686159d1 | OVERLAPS bd258480d3 | merged: the Daytona parent via `PurePosixPath` and `iter_skills_files` `.as_posix()` are upstream; Modal / SSH `posixpath.dirname`, `iter_cache_files` and `OptionalSkillSource` keys survive (§7 PARTIAL). No open PR |
| #121642 | 4 (`hermes_cli/auth_nous.py`) | "Nous inference URL allowlist"; "inference_base_url validate"; "nous inference url"; path `hermes_cli/auth_nous.py` | #90900, #65946 | UNIQUE | the open hits accept loopback Portal URLs / scope the endpoint override; none validates the device-login `inference_base_url` or heals it at store load (§7 FRESH) |
| #121641 | 2 (`agent/image_routing.py`) | "extract_image_refs Windows"; "image_routing drive"; "Windows drive image path"; path `agent/image_routing.py` | bd258480d3 | DUPLICATE-OF bd258480d3 | merged: the same `_LOCAL_IMAGE_PATH_RE` drive-letter anchor. CLOSED 2026-09-27 per §7; no open PR |
| #121640 | 5 (`hermes_cli/uninstall.py`) | "uninstall git history"; "stale references docs cli"; "uninstall dry run"; path `hermes_cli/uninstall.py` | none | UNIQUE | the uninstall hits (#65864, #62451) are other leftovers; §7 REBASE |
| #121226 | 10 (`tests/tools/test_file_tools_live.py`) | "bash POSIX path test Windows"; "tests Windows bash"; "resolve bash Windows test"; path `tests/tools/test_file_tools_live.py` | bd258480d3, #102577 | OVERLAPS bd258480d3 | merged: 6 of 10 files gated `platforms("linux")` instead of fixed (§7 PARTIAL). Open #102577 fixes the same `test_completion.py` `bash -n` test by picking a non-WSL bash; ours pipes the script on stdin. Reference it |
| #121225 | 4 (`tests/tools/test_process_registry.py`) | "POSIX-only os APIs test"; "geteuid Windows test"; "mode bits Windows"; path `tests/tools/test_process_registry.py` | bd258480d3 | OVERLAPS bd258480d3 | merged: the `geteuid` collection guard and one Linux gate; the mode-spy / getpgid hunks survive (§7 PARTIAL). No open PR |
| #121224 | 13 (`tests/hermes_cli/test_projects_db.py`) | "compare paths Windows test"; "path spelling test"; "os.path.join test Windows"; path `tests/hermes_cli/test_projects_db.py` | bd258480d3, 427d4936c2 | OVERLAPS bd258480d3 | merged: the same asserts fixed in 7 of 13 files (§7 PARTIAL). No open PR |
| #121222 | 5 (`tests/gateway/test_runtime_footer.py`) | "USERPROFILE test"; "HOME USERPROFILE"; "expanduser Windows test"; path `tests/gateway/test_runtime_footer.py` | bd258480d3 | OVERLAPS bd258480d3 | merged: `USERPROFILE` in 2 files, 2 gated; `test_runtime_footer` survives (§7 PARTIAL). No open PR |
| #121221 | 5 (`tests/hermes_cli/test_debug.py`) | "LF fixture Windows"; "line endings test"; "newline test Windows"; path `tests/hermes_cli/test_debug.py` | bd258480d3, 3c08d16ba7, 92686159d1 | DUPLICATE-OF bd258480d3 | merged: the same LF pins in all 5 files. CLOSED 2026-09-27 per §7; no open PR |
| #121219 | 1 (`tests/hermes_cli/test_win_pty_bridge.py`) | "ConPTY wrap"; "win_pty_bridge"; "ConPTY"; path `tests/hermes_cli/test_win_pty_bridge.py` | none | UNIQUE | upstream only re-marked the file `platforms("windows")` (9b8ad35ee6, 59624b7ace); the ConPTY hits are desktop / dashboard fixes |
| #121218 | 1 (`tests/hermes_cli/test_early_recovery.py`) | "early recovery import guard"; "early_recovery"; "relative import guard"; path `tests/hermes_cli/test_early_recovery.py` | 8b7eae99ef | DUPLICATE-OF 8b7eae99ef | merged: the guarded test was deleted. CLOSED 2026-09-27 per §7; no open PR |
| #121023 | 2 (`hermes_cli/plugin_compat.py`) | "plugin_compat"; "bundled skip plugin"; "disable_reason"; path `hermes_cli/plugin_compat.py` | #102904, #102952 | UNIQUE | the plugin-compat hits gate category-owned providers / the guarded scanner; ours restates the bundled-skip invariant in `disable_reason` |
| #119071 | 2 (`tests/hermes_cli/test_kanban_core_functionality.py`) | "kanban dispatcher poll"; "zombie reaper Windows"; "kanban Windows reap"; path `tests/hermes_cli/test_kanban_core_functionality.py` | none | UNIQUE | bd258480d3 gated two other kanban tests Linux-only; the fakes ours gives `poll()` are unchanged upstream |
| #119069 | 2 (`hermes_cli/gateway.py`) | "legacy_launchd_labels"; "pwd import Windows"; "launchd Windows"; path `hermes_cli/gateway.py` | #113971 | UNIQUE | #113971 routes launchd status probes; the `pwd` import in `legacy_launchd_labels_for_install` is untouched there and upstream |
| `chore/ruff-f821` | 1 (`pyproject.toml`) | "F821"; "ruff undefined name"; "ruff select"; path `pyproject.toml` | none | UNIQUE | no open PR selects F821; the hits are single undefined-name fixes |
| `feat/atomic-write-newline` | 1 (`utils.py`) | "atomic_write_text newline"; "atomic write newline"; "_atomic_write"; path `utils.py` | #122451, #109685 | DUPLICATE-OF #122451 | #122451 carries the identical `utils.py` change (`newline: str \| None = None` on `_atomic_write` and `atomic_write_text`, handed to `os.fdopen` as `newline=None if binary else newline`) and uses it at 10 call sites; #109685 hard-codes `newline=""` instead. Delete the held branch |
| `feat/auth-on-verification` | 41 (`hermes_cli/auth_nous.py`) | "on_verification"; "device code callback login"; "login verification callback"; path `hermes_cli/auth_nous.py` | none | UNIQUE | upstream has `on_verification` for Nous only; no open PR extends it to codex / xAI / MiniMax |
| `feat/kanban-crash-evidence` | 2 (`hermes_cli/kanban_db_dispatch.py`) | "kanban crash"; "dead worker reclaim"; "crash evidence"; path `hermes_cli/kanban_db_dispatch.py` | #114458, #44686 | OVERLAPS #114458 | same symptom (why a reclaimed worker died), different artifact: #114458 attaches a 2 KB ANSI-stripped log tail to reclaim events and diagnostics, #44686 a log snippet; ours writes a redacted crash-evidence file with sidecar discovery. Reference both in the body |
| `feat/mcp-test-env` | 2 (`hermes_cli/mcp_config.py`) | "mcp test --env"; "hermes mcp test"; "mcp test env"; path `hermes_cli/mcp_config.py` | none | UNIQUE | the `hermes mcp test` hits surface the binary / PATH or fix the exit status; none adds `--env` |
| `feat/plugin-cli-commands` | 5 (`hermes_cli/main.py`) | "plugin CLI commands manifest"; "register_cli_command"; "plugin subcommand"; path `hermes_cli/main.py` | none | UNIQUE | no open PR adds manifest-declared CLI commands or `parent=` |
| `feat/plugin-session-info-tool-names` | 1 (`agent/system_prompt.py`) | "session_info tool_names"; "system prompt section plugin"; "tool_names"; path `agent/system_prompt.py` | none | UNIQUE | no open PR adds `tool_names` to the section session info |
| `fix/bytecode-sweep-lock` | 3 (`hermes_cli/_bytecode_sweep.py`) | "bytecode sweep"; "stale bytecode"; "__pycache__ sweep lock"; path `hermes_cli/_bytecode_sweep.py` | none | UNIQUE | no open PR touches the stale-bytecode sweep |
| `fix/copilot-direct-http-client` | 2 (`agent/process_bootstrap.py`) | "copilot httpx"; "githubcopilot"; "copilot http client"; path `agent/process_bootstrap.py` | none | UNIQUE | the Copilot hits are token refresh / host matching, not the plain httpx client |
| `fix/memory-plugin-publish-module` | 2 (`plugins/memory/__init__.py`) | "memory plugin cli"; "memory provider cli module"; "plugins/memory"; path `plugins/memory/__init__.py` | none | UNIQUE | the memory-plugin hits are install hints / activation, not the provider cli-module binding |
| `fix/pet-atlas-extraction` | 2 (`agent/pet/generate/atlas.py`) | "pet atlas"; "sprite atlas"; "pet generate"; path `agent/pet/generate/atlas.py` | #107796 | OVERLAPS #107796 | same function family (strict vs lenient row validation in `agent/pet/generate/atlas.py`), different fix: #107796 adds `UnsegmentableStripError` / `CollapsedRowError` and skips paid strict retries; ours a context-aware floor erase, a vertical box merge and `strict=` soft validation. Reference; rebase if it lands first |
| `fix/process-notification-redaction` | 2 (`tools/process_registry_notifications.py`) | "process notification redact"; "notification ANSI"; "process_registry_notifications"; path `tools/process_registry_notifications.py` | #124217 | OVERLAPS #124217 | the ANSI half is the same fix: #124217 wraps the same three notification sites in `strip_ansi`. Ours also redacts secrets (`redact_sensitive_text`, fail-closed) and bounds each field. Reference it; if it lands first keep only the redaction and bounds |
| `fix/providers-discovery-import` | 2 (`providers/__init__.py`) | "plugins_discovery"; "providers entry point"; "providers import"; path `providers/__init__.py` | #112926 | DUPLICATE-OF #112926 | #112926 makes the identical `providers/__init__.py` change (import `_get_disabled_plugins` / `_get_enabled_plugins` from `hermes_cli.plugins_discovery`) with an import-cost test. Delete the held branch |
| `fix/reasoning-relay-native` | 2 (`agent/turn_response_intake.py`) | "reasoning.available"; "native reasoning relay"; "reasoning relay"; path `agent/turn_response_intake.py` | #124031 | DUPLICATE-OF #124031 | #124031 relays `agent._extract_reasoning(assistant_message)` (native fields first) as `reasoning.available` and also stops relaying reply text: a superset of ours, which keeps the reply-text fallback. Delete the held branch |
| `fix/state-db-small-fixes` | 3 (`hermes_state_messages.py`) | "finish_reason"; "session list order"; "started_at tie"; path `hermes_state_messages.py` | #53811 | OVERLAPS #53811 | the listing half is the same fix: #53811 adds `ORDER BY s.started_at DESC, s.id DESC` to `list_sessions_rich` (against the pre-split `hermes_state.py`). `finish_reason` on every role is ours alone. Drop the order hunk and reference #53811 |
| `fix/tool-registry-probe-cache` | 2 (`tools/registry.py`) | "registry probe"; "check_fn cache"; "registry_epoch"; path `tools/registry.py` | #65251, #85763 | UNIQUE | those re-check availability after compression / a dotenv reload; none bounds the grace re-probe or adds `registry_epoch` |
| `fix/win-gateway-task-console` | 3 (`hermes_cli/gateway_windows.py`) | "gateway scheduled task console"; "schtasks console"; "gateway_windows"; path `hermes_cli/gateway_windows.py` | #124300 | UNIQUE | #124300 flags a scheduled task that never ran; ours warns on a legacy console-mode task action. §6 CONFLICTS stands |
| `perf/ssl-ca-memo` | 4 (`agent/process_bootstrap.py`) | "CA bundle"; "ssl context cache"; "verify_ca_bundle"; path `agent/process_bootstrap.py` | 2f20ceb6f7, #119580 | OVERLAPS 2f20ceb6f7 | merged (2f20ceb6f7, via 27df3b8847, after this branch's base 30565b2db2):`agent/ssl_guard.py`, whose `verify_ca_bundle` ours memoizes, is deleted and trust moved to the OS store via truststore, so half of ours has no target and the other half keys a certifi fingerprint that no longer names the trust input. Open #119580 caches the urllib `SSLContext` for the same parse-once symptom. Re-measure on truststore before re-cutting; otherwise delete |
| `refactor/oauth-flow-catalog` | 3 (`hermes_cli/provider_catalog.py`) | "provider_catalog oauth"; "oauth flow dashboard"; "status_fn"; path `hermes_cli/provider_catalog.py` | none | UNIQUE | the provider_catalog hits are `excluded_providers` fixes |
| `refactor/profile-bootstrap-extraction` | 2 (`hermes_cli/main.py`) | "profile bootstrap"; "_apply_profile_override"; "main.py profile"; path `hermes_cli/main.py` | #67048 | UNIQUE | #67048 adds a run-once sentinel inside `_apply_profile_override`; no open PR extracts the bootstrap. §6 CONFLICTS stands (8684bf3ddc) |
| `test/platform-markers-linux` | 5 (`tests/hermes_cli/test_linux_desktop_entry.py`) | "platforms linux marker"; "linux only test"; "pytest.mark.platforms"; path `tests/hermes_cli/test_linux_desktop_entry.py` | #98200 | UNIQUE | #98200 gates two gateway diagnostics files; ours marks five other `tests/hermes_cli` files |
| `test/test-hygiene` | 7 (`tui_gateway/server.py`) | "local runtime unload"; "stale docstring test"; "test hygiene"; path `tui_gateway/server.py` | none | UNIQUE | no open PR on the stale docstrings or the local-runtime unload stub |
| `test/win-env-var-case` | 2 (`tests/tools/test_mcp_tool.py`) | "environment variable case Windows"; "PROGRAMFILES"; "env var case insensitive"; path `tests/tools/test_mcp_tool.py` | bd258480d3, #49684 | DUPLICATE-OF bd258480d3 | merged (via 27df3b8847, after this branch's base c882636db2): the same `(?i)` on the proxy-message match and the same upper-cased `PROGRAMFILES` / `PROGRAMDATA` / `PROGRAMW6432` keys in `test_mcp_tool.py`. #49684 instead preserves canonical names in `_build_safe_env`. Delete the held branch |
| `test/win-test-fixes-2` | 6 (`tests/tools/test_modal_sandbox_fixes.py`) | "Windows test fixes"; "msys cwd test"; "platform root pin"; path `tests/tools/test_modal_sandbox_fixes.py` | #78092, #102577 | UNIQUE | those fix conftest / completion / diff-command; none of our six files |

Counts over 64 items (40 PRs + 24 held branches): **UNIQUE 35 · OVERLAPS 19 · DUPLICATE-OF 10.**
- Against open upstream PRs by others: DUPLICATE-OF 5 (#124192, #123874, `feat/atomic-write-newline`,
  `fix/providers-discovery-import`, `fix/reasoning-relay-native`), OVERLAPS 13 (and #121226, verdicted on its merged
  side, also meets #102577 on one test).
- Against merged upstream commits: DUPLICATE-OF 5 (#121644, #121641, #121221, #121218, all already closed per §7;
  `test/win-env-var-case`), OVERLAPS 6 (#121643, #121226, #121225, #121224, #121222 — §7's PARTIAL rows — and
  `perf/ssl-ca-memo`).
- New since §7: `test/win-env-var-case` and `perf/ssl-ca-memo` are overtaken on the merged side (their bases predate
  27df3b8847), and 18 items meet an open PR by someone else; §1–§7 compared against merged commits only.

To close (upstream PR, on the owner's word): **#124192** (→ #114578), **#123874** (→ #78571; offer our one-file
renormalisation there). Already closed: #121644, #121641, #121221, #121218.

To delete (held branch, origin only): **`feat/atomic-write-newline`** (#122451), **`fix/providers-discovery-import`**
(#112926), **`fix/reasoning-relay-native`** (#124031), **`test/win-env-var-case`** (bd258480d3); and
**`perf/ssl-ca-memo`** unless a truststore re-measure still shows the cost (2f20ceb6f7).

To reference (name the other PR in our body; rebase if it lands first): #125265 → #114658 · #125264 → #78162 ·
#125263 → #122252 (and #66253) · #125260 → #65096 · #124190 → #74639 · #123979 → #110527 · #123978 → #70690 (drop or
rebase the Codex half) · #123976 → #68112 (strongest: same `gateway_context` API; rebase onto it or close in its favour)
· #121646 → #29547 · #121226 → #102577 · `feat/kanban-crash-evidence` → #114458, #44686 · `fix/pet-atlas-extraction` →
#107796 · `fix/process-notification-redaction` → #124217 (keep redaction + bounds) · `fix/state-db-small-fixes` →
#53811 (drop the `ORDER BY` hunk). The merged-side OVERLAPS rows keep §7's rebase-to-survivors call.

Overlapping lanes at commit time: #123976 was CLOSED and `feat/atomic-write-newline` deleted from origin by the
DOOR-FIT closures (ec36647867) while this sitting ran; their rows above stand as the record of why.
