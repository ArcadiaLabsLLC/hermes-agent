# Footprint full audit 2026-10-15 — the other 174 ledger files, and the fork tests still inside upstream test files

Design lane `fp-full`. Design only: no code moves here. This extends
[`footprint-audit-2026-10-15.md`](footprint-audit-2026-10-15.md) (the 48 post-2026-10-06 files;
its verdict format and lanes C/R/P/M/D are not redone) to every other row of
[`upstream-footprint-ledger.md`](upstream-footprint-ledger.md) on `origin/main` (`28b444fc756`,
ratchet `[up-fp] files=222 deleted_lines=1050 heavy=4`): 174 files, 4,758 added / 906 deleted lines.

Measured against `v0.21.7` (the fork hunk: `git diff v0.21.7 origin/main -- <path>`) and `v0.22.2`
(`7b77e29eedd`, the drop test and the door test). The release merge's collision set is
`git merge-tree --write-tree origin/main v0.22.2`: nine content conflicts
(`agent/auxiliary_client.py`, `gateway/platforms/base.py`, `hermes_cli/runtime_provider_custom.py`,
`hermes_state.py`, `pm/environment.py`, `pyproject.toml`, `tools/environments/local.py`,
`tools/tool_search.py`, `tui_gateway/server.py`) plus two `contributors/emails/*` add/add. A lane that
edits one of those is marked **after release**.

Verdicts, asked in this order: **drop** (upstream now does it; the test is named) / **extract-now**
(an extension point that already exists in `v0.22.2` lets the logic leave the file) /
**extract-module** (the body moves behind ≤ a few call lines into a fork module; no door needed) /
**upstream** (needs a new door or is a generic fix; the open PR, prepared branch or doors-sheet section
is named) / **kept** (why). Open PRs are nekwo's unless marked third-party; `gh pr list --author @me`
on 2026-10-15: 63 open, **0 merged**, so no row drops because a PR landed.

## 0. Doors: what `v0.22.2` added, and did not

- **No new plugin door.** The hook catalog is the same 33 names in `v0.21.7` and `v0.22.2`
  (`hermes_cli/hooks.py`, `plugins.py`, `plugins_dispatch.py` are byte-identical across the two tags),
  and the `PluginContext.register_*` set is unchanged. Every `hook` / "NO DOOR YET" row waits on a door
  the fork must still open. None of them is an extract-now.
- `on_stream_delta` is still not fired on the Codex app-server path (`agent/codex_runtime.py` has no
  `invoke_hook` in `v0.22.2`), so the stream-gap receipt there cannot ride the existing stream hooks.
- **Doors the fork has already built, unmerged:** `feat/optional-module-door` (`b472d428cf1`,
  `hermes_constants.module_shipped()` — door A of
  [`upstream-doors-2026-10-06.md`](upstream-doors-2026-10-06.md), 13 rows below) and
  `feat/sdk-fallback-door` (`36ba53ebda7`, `process_bootstrap.register_sdk_fallback()` — door B, 5 rows).
  Doors C (secret-file store, 14 rows), D (provider access, 10 rows), F (psutil), G (MCP session hooks,
  5 rows), H (terminal-result evidence), I (live foreground commands) and J1–J3 (Group Chat host surface)
  are designed on that sheet and not yet branches.
- Upstream movements the merge must carry: `_managed_local_netloc` left `agent/auxiliary_client.py` for
  the new `agent/auxiliary_managed_local.py` (the fork's `shipped("hermes_cli.local_runtime")` guard
  follows it, a new ledger row); `tools/mcp_oauth.py::HermesTokenStorage.credential_stamp` is the same
  stat-stamp idea as the fork's `hermes_cli/auth.py::authentication_owner_stamps` (a precedent, not a
  door); `hermes_cli/plugin_validate_private_imports.py` now lints plugins that import core privates —
  the fork plugin's import-layers exception list meets that lint at detach (Stage 7).
- `v0.22.2` took `httpx2==2.12.0` itself and deleted the whole `[tool.uv.exclude-newer-package]` table
  (`exclude-newer = "3 days"`, no exemptions): the fork's three pin lines, their five-line carry comment
  and the `onnx-asr = false` row **drop** at the merge (§3).

## 1. The table

`+a/-d` is the ledger's count. "lane" names a lane in §2 (MOVE), §3 (drop) or §5 (tests); `—` means
the row waits on its PR or door. **rel** = the file is in the release merge's conflict set.

### 1.1 Root, packaging, generated

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `.gitattributes` | 7/0 | carry-permanent | kept | ruled 2026-09-24; third-party #78571 retires it | — |
| `README.md` | 7/1 | carry-permanent | kept | ruled (licence notice) | — |
| `pyproject.toml` | 104/4 | carry-permanent | **drop (partial)** + kept | `v0.22.2` pins `httpx2==2.12.0` in `mcp`, `computer-use`, `dev` and drops the exclude-newer table: −3 pin lines, −5 comment lines, −1 `onnx-asr` row; proof `tests/agent_runtime/test_bundle_vuln_floors.py` green on upstream's pin. Rest kept: `agent_runtime` in `packages.find` (ruled, Stage 7), speech extras (carry), ruff `F821` select + per-file ignores (PR candidate, unfiled) | D2 · **rel** |
| `uv.lock` | 51/13 | carry | kept | regenerated from `pyproject.toml` at every merge; never hand-edited | — |
| `apps/shared/src/gateway-contract.generated.ts` | 118/0 | carry | kept | generated from `tui_gateway/contracts/*`; regenerated at the merge; retires with a plugin-registered gateway-method seam | — |
| `apps/shared/src/gateway-contract.openrpc.json` | 811/5 | carry | kept | same; the one heavy row that no lane here lowers | — |

### 1.2 `agent/`

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `agent/agent_init.py` | 39/2 | hook | **extract-module** + upstream | `_managed_local_marker` and the `_allow_managed_local_context` predicate → `agent_runtime/managed_local_floor.py::allows_main_context(agent, ctx)`; `_enforce_minimum_context` keeps one `or` operand; 39 → ~22. The seven `_emit_init_timing` marks stay (issue #125255) | F |
| `agent/agent_runtime_helpers.py` | 14/7 | hook | upstream + kept | `sdk_free_client` branch → door B (`feat/sdk-fallback-door`); the steering requeue/rows are already the seam form (`agent/steering.py`); the one-line `display_metadata.steering` merge guard stays | — |
| `agent/anthropic_adapter.py` | 6/0 | hook | upstream | door B | — |
| `agent/anthropic_credentials.py` | 14/2 | hook | upstream | doors C (`secret_files.view/bound/write_json`) and D (`provider_secret`, `provider_credential_file`) | — |
| `agent/auxiliary_client.py` | 32/2 | hook | upstream | door B (three hunks), door D (`_scoped_key_env`), held PR h-conn-pool (`drain_settled_stream`), door A for the managed-local guard — which the merge re-places in `agent/auxiliary_managed_local.py` (new row) | — · **rel** |
| `agent/client_lifecycle.py` | 4/0 | hook | upstream | door A (`feat/optional-module-door`) | — |
| `agent/codex_runtime.py` | 6/0 | hook | upstream | `record_usage` → #123978 (open); the stream-gap receipt and `install_transport_phase_trace` have no door (`on_stream_delta` is not fired on this path, §0) | — |
| `agent/conversation_compression.py` | 14/3 | hook | **extract-module** + upstream | the `managed_local_same_model` predicate → `managed_local_floor.allows_aux_floor(agent, aux_model, aux_context, aux_base_url)` (it uses upstream's own `_aux_inherits_main_route`, passed in); 14 → ~5; `child_model_config` stays (#87515 third-party) | F |
| `agent/conversation_loop.py` | 36/1 | hook | upstream | `reuse_current_user_message` → #124210; timing marks → #125255; prewarm adopt/defer → held PRs h-turn1 A3 / h-turn1-conn | — |
| `agent/credential_pool.py` | 15/19 | upstream | upstream | #124193 (open) for the rotation branch; door D for `provider_configuration` / `provider_secret` | — |
| `agent/credential_sources.py` | 5/0 | hook | upstream | door C | — |
| `agent/pet/generate/atlas.py` | 116/14 | upstream | upstream | #128650 (open) | — |
| `agent/process_bootstrap.py` | 5/1 | upstream | upstream | door B | — |
| `agent/prompt_builder.py` | 32/10 | hook | upstream | `_bot_screen_hint` guard → door A; shared skills root → #124191; all-context-files load → #125257; the skill runtime-compatibility threading (`skill_surface`, `skill_root_node_mode` through four signatures and the cache key) has no door and cannot leave a signature | — |
| `agent/relay_cwd.py` | 4/0 | hook | upstream | door A | — |
| `agent/relay_runtime.py` | 13/1 | hook | upstream | optional `nemo_relay` binding → PR candidate (unfiled, generic: `RelayUnavailable` + Noop host at INFO) | — |
| `agent/secret_scope.py` | 4/0 | hook | upstream | door C | — |
| `agent/secret_sources/bitwarden.py` | 5/2 | carry | kept | held offer (no upstream defect) | — |
| `agent/session_persistence.py` | 8/2 | hook | upstream | #124210 (persisted-row hook) | — |
| `agent/shell_hooks.py` | 6/2 | upstream | upstream | #123892 (open) | — |
| `agent/skill_utils.py` | 8/3 | hook | upstream | #124191 (open); the shared root is TIER_LOCAL (writable), which `skills.external_dirs` cannot express, so no extract-now | — |
| `agent/system_prompt.py` | 12/0 | hook | upstream | `tool_names` → #128653; `_chat_lane_compact_skill_categories` → held PR h-prompt S3; **new PR candidate**: the h10b-fix anchor repair in `_restore_plugin_prompt_sections` / `_frozen_plugin_prompt_sections` — upstream's anchor still never matches when the profile line precedes the timestamp in `v0.22.2` (unfiled) | — |
| `agent/title_generator.py` | 3/0 | hook | upstream | held PR h-title-defer | — |
| `agent/tool_dispatch_helpers.py` | 3/0 | upstream | upstream | #128843 consumer (`mcp_client_enabled`) | — |
| `agent/turn_api_error.py` | 4/0 | upstream | upstream | doors sheet §H (`provider_failure`) | — |
| `agent/turn_api_request.py` | 8/0 | hook | upstream | held PR h-turn1 A5 / #125255 — a `pre_api_request` hook fires after the laps it would measure | — |
| `agent/turn_context.py` | 33/8 | hook | upstream + kept | `reuse_current_user_message` → #124210; the `trace_turn_context` decorator + eleven `note_turn_context_part` marks are the attribution seam (kept; log-only) | — |
| `agent/turn_facade.py` | 2/0 | hook | upstream | #124210 | — |
| `agent/turn_response_check.py` | 6/0 | hook | upstream | #125255 (no response-validation hook) | — |
| `agent/turn_response_intake.py` | 15/1 | upstream | upstream | third-party #124031 (open) | — |

### 1.3 `cron/`, `evals/`, `gateway/`, bootstrap

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `cron/worker_bootstrap.py` | 5/0 | carry | kept | already the seam form (one import, one call into `hermes_cli/interpreter_abi.py`); PR candidate with the PM generation contract | — |
| `evals/postmortem/live_ab/cache_concurrency_probe.py` | 16/4 | upstream | upstream | #123890 (open) | — |
| `gateway/hosted_room_discussion.py` | 181/44 | hook | **extract-module** + upstream | `DiscussionLimits`, `DEFAULT_LIMITS`, `_conclude`, `task_round_index` (≈75 self-contained lines; callers `agent_runtime/discussions/room_state.py`, fork) → `gateway/hosted_room_limits.py`, imported back by name; the `limits=` threading, `response_from_payload` uses and the `ready_tasks` batch stay (doors sheet J2/J3 branches); 181 → ~105, **heavy −1** (225 → ~150) | G |
| `gateway/hosted_room_driver.py` | 11/5 | hook | upstream | J3 (`permits_overlap` import is already the seam form) | — |
| `gateway/hosted_room_policy_checkpoint.py` | 12/4 | hook | upstream | J2 (`published_watermark` is already a fork import) | — |
| `gateway/hosted_rooms.py` | 72/4 | hook | **extract-module** + upstream | `pin_room_history` / `unpin_room_history` (50 lines; sole caller `room_state.py`, fork) → `gateway/hosted_room_history_pins.py`, importing `_transaction`, `_room_row`, `_require_authority`, `_SELECT_ROOM_WITH_BYTES`, `table_exists` (import-layers exceptions, door J2); the prune changes, `MAX_RETAINED_ROOM_HISTORIES`, `RoomHistoryRetentionFullError` and the `_DEPENDENT_TABLES` entry stay; 72 → ~22 | G |
| `gateway/lifecycle_ledger.py` | 8/4 | upstream | upstream | #123891 (open) | — |
| `gateway/pairing.py` | 7/0 | hook | upstream | door C | — |
| `gateway/platforms/base.py` | 22/6 | upstream | upstream | #125264 (open); the import line also moved upstream (`CONNECTOR_DOWNLOADS_SUBDIR`) | — · **rel** |
| `gateway/run.py` | 5/0 | upstream | upstream | doors sheet §G (completion-event formatter registry) | — |
| `gateway/run_adapters.py` | 17/1 | hook | upstream | #128843 (open) | — |
| `gateway/run_agent_cache.py` | 4/1 | hook | upstream | door A | — |
| `gateway/shutdown_watchdog.py` | 4/3 | upstream | upstream | #123891 | — |
| `hermes_bootstrap.py` | 26/26 | carry | upstream + kept | `relaunch_if_needed` move → #129413 (open); the 14-line registry-fence fallback is test infrastructure for minted trees (kept; it dies when `_registry_write_fence.py` joins `BOOT_FILES`, a fork-hygiene row) | — |

### 1.4 `hermes_cli/`, `hermes_constants_scratch.py`, `hermes_state*`

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `hermes_cli/auth.py` | 34/3 | hook | **extract-module** + upstream | `authentication_owner_stamps` (18 lines; callers `agent_runtime/provider_probes.py`, `profile_runner/execute.py`, `models_reasoning_caps.py` — all fork or lane R) → `agent/provider_access.py`, importing `_auth_file_path` / `_global_auth_file_path` (exception list); 34 → ~16. Rest: `provider_credential_file` → door D / #124190, store view/write → door C, `_heal_persisted_nous_inference_urls` call → #121642 | H |
| `hermes_cli/auth_codex.py` | 33/2 | carry | upstream | `on_verification` / `on_expiry` → #128842 (open); `external_logins_refused` → door C; **new PR candidate**: `_codex_pool_row_refused` — the pool fallback served a row the pool itself had marked EXHAUSTED/DEAD (`_exhausted_until` not consulted); 20 lines, unfiled, not in the ledger reason | — |
| `hermes_cli/auth_codex_browser.py` | 8/1 | carry | upstream | #128842 | — |
| `hermes_cli/auth_minimax.py` | 10/2 | carry | upstream | #128842 (+ `persist=` kwarg) | — |
| `hermes_cli/auth_nous.py` | 59/9 | upstream | upstream | #121642 (open: `_nous_stored_inference_url`, `_heal_persisted_nous_inference_urls`, device-login validation) + door C (shared store view/delete) | — |
| `hermes_cli/auth_qwen.py` | 2/0 | hook | upstream | door C | — |
| `hermes_cli/auth_xai.py` | 9/1 | carry | upstream | #128842 | — |
| `hermes_cli/cli_voice_mixin.py` | 5/0 | hook | upstream | #128843 | — |
| `hermes_cli/config.py` | 38/12 | hook | upstream + kept | read-only loads never scaffold the home (`ensure_home`, `require_writable`) → #125259 (open); `.env` I/O → door C; the one-line `project_readonly_config` projection stays (fork-only) | — |
| `hermes_cli/copilot_auth.py` | 3/0 | hook | upstream | door C | — |
| `hermes_cli/doctor.py` | 38/7 | upstream | upstream + kept | #125260 (open: `__getattr__`, `_LIVE_HOME_NAMES`, per-run dotenv); `check_gateway_launcher` registration held (needs a doctor-check widening) — the import from `agent_runtime.doctor_extensions` is already the seam form | — |
| `hermes_cli/doctor_config.py` | 8/3 | upstream | upstream | #125260 | — |
| `hermes_cli/doctor_platform.py` | 5/1 | upstream | upstream | #125260 | — |
| `hermes_cli/doctor_state.py` | 13/5 | upstream | upstream | #125260 | — |
| `hermes_cli/env_loader.py` | 5/0 | hook | upstream | door C | — |
| `hermes_cli/gateway.py` | 18/4 | upstream | upstream + kept | `pwd` guard → #119069 (open); `getuid` guard dropped upstream-side already by marker; the `gateway_downstream` tail import and `_emit_gateway_home_receipt` call are the seam form (held offer) | — |
| `hermes_cli/gateway_windows.py` | 4/2 | upstream | kept | tail rebind through `gateway_windows_launcher` (seam form); G11 held | — |
| `hermes_cli/inventory.py` | 6/1 | hook | upstream | door A (`_local_runtime_row`) + door D (`provider_configuration`) | — |
| `hermes_cli/main.py` | 97/16 | hook | **extract-module** + upstream + kept | `_builtin_verb_subparsers`, `_declared_cli_command_argv`, `_attach_declared_plugin_cli_command` (≈50 lines) → `hermes_cli/plugins_manifest_cli_commands.py` (fork, exists) taking `subparsers` and `_BUILTIN_SUBCOMMANDS` as arguments; `_register_plugin_cli_commands` keeps a two-line head and `_attach_plugin_cli_command` its `parent` branch (#128648); 97 → ~45. Kept: boot-clock marks, `HERMES_PROFILE_RESOLUTION` receipt, `is_hermes_cli_entrypoint` gate, desktop store bind, gettext memo, `set-profile` scan (held, §0.3 of the ledger) | E |
| `hermes_cli/main_web_build.py` | 2/47 | upstream | upstream | #128840 (open) | — |
| `hermes_cli/mcp_config.py` | 18/2 | upstream | upstream | held `feat/mcp-test-env` (G13); machine-root tokens are fork imports already | — |
| `hermes_cli/mcp_startup.py` | 12/0 | upstream | upstream | #128843 consumer | — |
| `hermes_cli/model_switch.py` | 4/0 | hook | upstream | door D | — |
| `hermes_cli/plugins.py` | 83/6 | hook | **extract-module** + upstream | `cli_command_key`, `_materialize_declared_cli_command`, `discover_declared_cli_commands` (≈60 lines; callers `main.py` and the fork module) → `hermes_cli/plugins_manifest_cli_commands.py`, importing `get_plugin_manager`, `manifest_key`, `collect_directory_manifests`, `gate_manifest`, `_get_disabled_plugins`, `_get_enabled_plugins`, `_env_enabled` from `hermes_cli.plugins` / `plugins_discovery`; `register_cli_command`'s `parent` kwarg, the `register_provider_access` registrar row (door D), `elapsed_ms` and `cached_plugin_home_key` stay; 83 → ~22. #128648 carries its own copy | E |
| `hermes_cli/plugins_discovery.py` | 6/6 | upstream | upstream | #125259 | — |
| `hermes_cli/plugins_manifest.py` | 5/0 | hook | upstream | #128648 (already the parser-import seam form) | — |
| `hermes_cli/process_identity.py` | 4/1 | upstream | upstream | #129412 (open); `v0.22.2` added `is_local_desktop_backend`, not the guard | — |
| `hermes_cli/runtime_provider.py` | 4/1 | hook | upstream | door D + PR candidate (`auto` landing on a disabled provider; unfiled) | — |
| `hermes_cli/runtime_provider_custom.py` | 4/2 | hook | upstream | door D; the merge must fold `resolve_credentials=` (new upstream kwarg on `_match_new_style_provider`) into the fork's `_key_env_secret` line | — · **rel** |
| `hermes_cli/secret_prompt.py` | 5/2 | upstream | upstream | #129411 (open) | — |
| `hermes_cli/service_manager.py` | 1/1 | upstream | upstream | #121640 | — |
| `hermes_cli/subcommands/mcp.py` | 10/0 | upstream | upstream | held `feat/mcp-test-env` | — |
| `hermes_cli/uninstall.py` | 3/1 | upstream | upstream | #121640 | — |
| `hermes_cli/update_cmd.py` | 14/1 | upstream | upstream + kept | #125265 (open); the `_UPDATE_CRITICAL_FILES +=` line is fork (kept, 2 lines) | — |
| `hermes_cli/update_cmd_git.py` | 5/2 | upstream | kept | owner keep 2026-09-27 (never-force) | — |
| `hermes_cli/update_cmd_windows.py` | 3/1 | upstream | kept | G11 held; already one call into `gateway_windows_launcher` | — |
| `hermes_cli/update_inventory.py` | 22/0 | upstream | upstream | #125265 | — |
| `hermes_cli/venv_sync.py` | 62/0 | upstream | upstream | #129413 (open) | — |
| `hermes_cli/web_routers/oauth.py` | 4/26 | upstream | upstream | #128654 (open) | — |
| `hermes_cli/web_server_config.py` | 12/2 | hook | upstream | #128843 family (lazy `tools.wake_word` import; generic) | — |
| `hermes_cli/web_server_oauth.py` | 8/31 | upstream | upstream | #128654 | — |
| `hermes_cli/webhook.py` | 5/1 | hook | upstream | door C | — |
| `hermes_cli/worktree_ops.py` | 1/1 | upstream | upstream | #121640 | — |
| `hermes_constants_scratch.py` | 8/2 | upstream | upstream | doors sheet §F (sibling of #129412) | — |
| `hermes_state.py` | 12/1 | carry | **extract-module** | `SessionDB.update_meta` (9 lines; sole caller `tui_gateway/session_execution.py`, fork) → `hermes_state_history_controls.SessionHistoryControlsMixin` (fork; already on the class); 12 → 3. Upstream removed `SessionToolRetriesMixin` from the same base-class lines | H · **rel** |
| `hermes_state_messages.py` | 24/6 | upstream | upstream + **extract-module** | `finish_reason` on every role, `through_row_id`, digest/receipt → #128652 (open) + held reviewed-restore PR; `get_resume_message_watermark` (6 lines; sole caller `tui_gateway/session_recovery.py`, fork) → the same history mixin; 24 → ~18 | H |
| `hermes_state_sessions.py` | 2/2 | upstream | upstream | third-party #53811 (open) | — |

### 1.5 `model_tools.py`, `plugins/`, `pm/`, `providers/`, `scripts/`, `tests/` fixtures

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `model_tools.py` | 12/0 | hook | upstream + kept | memo counters → #125255; plugin discovery before a miss / `with_tool_describe` → #123979 / #114578; the `app_function_tool_scope()` cache-key operand stays (one line) | — |
| `plugins/dashboard_auth/_shared.py` | 4/3 | upstream | upstream | #125259 | — |
| `plugins/memory/__init__.py` | 8/2 | upstream | upstream | #128651 (open) | — |
| `pm/extras.py` | 2/0 | carry | kept | speech-pack anchors (carry with the extras) | — |
| `providers/__init__.py` | 1/1 | upstream | upstream | third-party #112926 (open) | — |
| `scripts/run_tests.sh` | 181/1 | upstream | **extract-module** | every fork block — shared-venv probe, `ensure_fork_dev_deps`, test-temp root, `SYSTEMDRIVE`, the `REAL_HERMES_ROOT` fence probe with its 40-line comment, the in-store interpreter refusal, the cygpath runner path, the coverage note — becomes functions in `scripts/_fork_test_env.sh` (fork, exists, already sourced here): `fork_pick_python`, `fork_test_tmp_root`, `fork_real_root_fence`, `fork_runner_path`; the script keeps the source line, ≤ 6 call lines, the three `${VAR:+…}` forwards and `"$RUNNER_PATH"`; 181 → ~14. Nothing of it is in #125263 except cygpath | A |
| `scripts/run_tests_parallel.py` | 145/16 | upstream | upstream + **extract-module** | retry / worker cap / `CREATE_NO_WINDOW` → #125263 (open); the coverage seam (`_pytest_argv`, `_COVERAGE_RC_ENV`, 18 lines) → `scripts/_fork_runner.py` behind one call; 145 → ~127 | A |
| `tests/_fixtures/env_filter.py` | 10/1 | upstream | kept | held offer (timing-only) | — |
| `tests/_fixtures/live_system_guard.py` | 40/9 | upstream | upstream + kept | lazy children → #129582 (open); the Windows console-event refusal (9 lines) is a **PR candidate** (unfiled, sibling of #131905); `refuse_backend_spawn` is the seam form | — |
| `tests/conftest.py` | 10/10 | upstream | upstream + kept | #131905 (open); `real_hermes_root_candidates` accessor (5 lines) stays for the fork guard | — |
| `tests/fixtures/resolution_allowlist.json` | 19/1 | upstream | upstream + kept | #129414 (open) for the rename; three fork rows are data (kept) | — |
| `tests/test_live_system_guard_self_test.py` | 4/0 | carry | kept | in-place platform guard on an upstream test (carry; retires with the signal-safety PR) | — |

### 1.6 `tools/`

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `tools/approval_context.py` | 35/0 | hook | **extract-module** | `_surface_policy`, `scoped_approval_policy`, `approval_policy_mode`, `approval_policy_modes` (28 lines; sole caller `agent_runtime/session_controls.py`) → `agent_runtime/approval_surface_policy.py` importing `_VALID_MODES` and `_get_approval_mode` (exception list); the two read sites in `_is_gateway_approval_context` / `_get_approval_mode` become one call each; 35 → ~8 | B |
| `tools/approval_detection.py` | 43/7 | upstream | upstream | #125262 (open) | — |
| `tools/async_delegation.py` | 15/1 | hook | upstream | #124190 | — |
| `tools/browser_tool_lifecycle.py` | 2/1 | upstream | upstream | #125262 | — |
| `tools/code_execution_env.py` | 3/2 | upstream | upstream | #125262 | — |
| `tools/credential_files.py` | 1/1 | upstream | upstream | #121643 (open) | — |
| `tools/environments/base.py` | 5/0 | upstream | kept | already the seam form (one import, publish/retract); doors sheet §I is the retirement | — |
| `tools/environments/local.py` | 7/1 | upstream | upstream + kept | `augment_windows_system_path` → #125261 (open) — re-wrapped over upstream's new `_user_tools_first` at the merge; the slot-overlay seams (4 lines) stay | — · **rel** |
| `tools/file_tools.py` | 9/4 | upstream | upstream | #121645 (open) | — |
| `tools/file_tools_write_guards.py` | 5/4 | upstream | upstream | #121645 | — |
| `tools/image_generation_tool.py` | 2/2 | carry | upstream | #125259 ("read-only sites use `load_config_readonly`") | — |
| `tools/mcp_oauth.py` | 7/0 | hook | upstream | door C | — |
| `tools/mcp_tool_common.py` | 31/2 | hook | upstream | #128843 (`mcp_client_enabled`, `mcp_stdio_servers_allowed`) | — |
| `tools/mcp_tool_config.py` | 41/1 | hook | upstream | #124210 (`HERMES_HOME` for stdio children, `server_name`/`runtime_env`); machine-root tokens → held G13 | — |
| `tools/mcp_tool_handlers.py` | 3/0 | hook | upstream | doors sheet §G (`post_mcp_call`) | — |
| `tools/mcp_tool_health.py` | 2/0 | hook | upstream | §G (`on_mcp_notification`) | — |
| `tools/mcp_tool_transport.py` | 9/3 | hook | upstream | #124210 (transform hooks) + §G (`on_mcp_session`) | — |
| `tools/process_registry.py` | 4/6 | upstream | upstream | PTY EOF → #125261; `checkpoint_path` → #124190; `wait_ceiling_seconds` held | — |
| `tools/process_registry_notifications.py` | 3/0 | hook | upstream | §G formatter registry | — |
| `tools/registry.py` | 180/36 | upstream | **extract-module** + upstream | `scan_registered_tools` + `ToolScan` (≈70 lines; sole caller `scripts/dump_toolset_manifest.py`, fork) → `tools/toolset_scan.py` (fork, exists; it already owns `registration_rows`): 0 lines left; probe accounting (`_probe_state`, `_check_fn_epoch`, `_note_check_fn_probe`, `_probe_round`, `probe_rounds_this_thread`, `check_fn_epoch`; callers `agent_runtime/chat_lane_bundle.py`, `harness_parts/persona/chat_admission.py`) → `tools/registry_probe_accounting.py`, leaving two `_note_check_fn_probe()` calls, two `with _probe_round():` lines and one `epoch += 1`; the `generation` property (12 lines, 20 fork callers) is a PR candidate; the cache-tuple widening and grace re-probe stay (#128841, open); `_mcp_progress_relay` enter/exit stay (§G); 180 → ~85, **heavy −1** (216 → ~120) | C |
| `tools/skills_hub_official.py` | 1/1 | upstream | upstream | #121643 | — |
| `tools/skills_tool.py` | 51/66 | hook | upstream | #124191 (`resolve_skill` adopt) + #125257 (nested categories, `identifier`/`tags`) | — |
| `tools/terminal_tool.py` | 30/0 | hook | upstream | #123977 (`command_guard`); the `gated_terminal_call` wrapper is already one tail import plus one wrapper (seam form) | — |
| `tools/terminal_tool_backends.py` | 15/1 | hook | upstream | #128843 | — |
| `tools/terminal_tool_result.py` | 3/1 | upstream | upstream | #125262 + `timed_out` field (PR candidate, unfiled) | — |
| `tools/tool_search.py` | 30/16 | hook | upstream | third-party #114578 (partial); the tail rebinds through `tool_search_downstream.py` are the seam form; upstream rewrote `_search_description` and added `call=` to both dispatchers — the fork's `mark_direct_hits` wrapper must pass `**kwargs` | — · **rel** |
| `tools/tts_tool.py` | 5/4 | carry | upstream | #125259 (readonly) + #125262 (identity) | — |
| `tools/tts_tool_delivery.py` | 3/2 | upstream | upstream | #125262 | — |
| `tools/tts_tool_local.py` | 13/3 | carry | upstream | PR candidate (unfiled, generic): `tts.piper.download_voices` + `HF_HUB_OFFLINE` honour | — |
| `tools/vision_tools.py` | 4/4 | carry | upstream | #125259 | — |

### 1.7 `tui_gateway/`

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `tui_gateway/agent_callbacks.py` | 8/5 | hook | upstream | door A | — |
| `tui_gateway/compute_host.py` | 56/5 | carry | kept | native conversation recovery + subagent controls (`observe` frame, `adopt`/`control`, `session_construction`, `compute_model_selection` route); PR candidate once quiet (ledger); no door | — |
| `tui_gateway/compute_host_bridge.py` | 30/7 | carry | kept | same family (`_answer_compute_host_request`) | — |
| `tui_gateway/contracts/__init__.py` | 1/0 | carry | kept | `recovery` contract module registration | — |
| `tui_gateway/contracts/prompt_voice.py` | 3/0 | carry | kept | `reject_if_busy`, `execution_id`, `session_id` fields (plugin-registered method seam) | — |
| `tui_gateway/contracts/sessions.py` | 3/0 | carry | kept | `observe_only`, `expected_execution_id`, `include_events` | — |
| `tui_gateway/event_replay.py` | 20/0 | carry | **extract-module** | `forget_session` + `checkpoint` (callers: the fork hunks in `session_lifecycle.py` and `methods_session.py`) → `tui_gateway/recovery_history.py` (fork, exists) importing `_replay_lock`, `_replay_buffers`, `_replay_buffer_bytes`, `_replay_next_seq`, `_replay_evicted_through`, `_REPLAY_EPOCH`, `_thaw_params` (exception list); 20 → 0, **the file leaves the ledger** | H |
| `tui_gateway/git_probe.py` | 10/1 | hook | upstream | #128843 | — |
| `tui_gateway/host_supervisor.py` | 76/10 | upstream | upstream + kept | `_pid_alive` → third-party #97022 / #97187; `_PendingTurn`, `observe`, the hello cold-start grace, `existing_only` are native-recovery carry. **Merge hazard:** `v0.22.2` adds `has_pending_turn`, which unpacks `_pending_turns.values()` as `(s, _cb)` tuples — the fork's `_PendingTurn` dataclass breaks it silently (auto-merge, no conflict); the merge lane rewrites it to `turn.sid` | — · after release |
| `tui_gateway/hosted_room_driver.py` | 41/5 | hook | **extract-module** + upstream | `request_reconciliation` and `_observe_independent_members` (27 lines) → `HostedRoomIndependentMembersMixin` in `agent_runtime/discussions/hosted_room_driver_ext.py`, one base-class line on `HostedRoomRuntime`; the `independent` branches in `_scan_room` / `_execute_attempt`, `stop_unresolved`, `inspection.active` and the `error` field stay (J1/J3); 41 → ~16 | G |
| `tui_gateway/methods_config_set.py` | 6/7 | hook | upstream | door D / shared-provider seam (`compute_model_selection.forward`) | — |
| `tui_gateway/methods_prompt.py` | 38/110 | carry | kept + upstream | native admission (`session_execution` admit/submitted/rejected/uncertain, `reject_if_busy`, `spawn_context_thread`, `_answer_compute_host_request`) kept; the −110 `pdf.attach` move drops at the merge that carries #129414 (`deleted_lines` −110) | — |
| `tui_gateway/methods_session.py` | 17/7 | carry | kept | native recovery (`observe_only`, `session_construction`, compute-host `session.events.since`) | — |
| `tui_gateway/methods_voice.py` | 13/1 | hook | upstream | #128843 + door B (`contract_seam`) | — |
| `tui_gateway/model_switch.py` | 2/1 | hook | upstream | door D | — |
| `tui_gateway/prompt_turn.py` | 39/18 | carry | kept + upstream | native recovery (`checkpoint_guard`, `native_execution`, launcher app-function scopes) kept; the `process_registry` guard → door A | — |
| `tui_gateway/rpc_dispatch.py` | 34/24 | carry | kept | `_enqueue_rpc` + queued response relay: PR candidate (generic shape) once the native-recovery family is offered | — |
| `tui_gateway/server.py` | 55/15 | upstream | kept + upstream | `_gateway_extensions.prepare/register` and `contract_seam` are the seams; `mcp_client_enabled` → #128843; `_sanitize_client_source = _resolve_session_source` is an upstream NameError fix (M2.02) — **PR candidate, unfiled**; `_live_session_identity`, `RLock`, lazy-on-native are native-recovery carry. Upstream reshaped the method-module import block (`methods_machine`, `methods_plugin_catalog`, `methods_tools_plugin_servers`, no `methods_start_chat`) | — · **rel** |
| `tui_gateway/server_requests.py` | 11/2 | carry | kept | answer receipts (`AnswerReceipts`, `session_id=`); `contract_seam` → door B | — |
| `tui_gateway/session_auto_continue.py` | 1/1 | carry | kept | `observe_only` guard | — |
| `tui_gateway/session_lifecycle.py` | 13/3 | carry | kept | native recovery (`control(session)`, `close_app_functions`, `discard_history`, `forget_session`, `expected_execution_id`) | — |
| `tui_gateway/session_notifications.py` | 8/0 | hook | upstream | door A (two guards) | — |
| `tui_gateway/session_reaper.py` | 11/2 | carry | kept | native-execution eviction rule + `prune_history` | — |
| `tui_gateway/session_workdir.py` | 15/3 | carry | upstream + kept | two door-A guards; `display_metadata` on the submit row (native recovery, kept) | — |

### 1.8 Upstream test files (the S5 half is §5)

| path | +a/-d | ledger | verdict | proof / module / PR / door | lane |
|---|---|---|---|---|---|
| `tests/hermes_cli/test_auth_nous_provider.py` | 167/4 | upstream | upstream + move | the roundtrip O_CREAT spy → #121225 (open); the eight fork tests move (§5) | T1 |
| `tests/hermes_cli/test_backup.py` | 33/7 | upstream | upstream | #121224 / #121225; the `.bat` wrapper hunk held (R10) | — |
| `tests/hermes_cli/test_deleted_profile_tombstone.py` | 4/1 | upstream | upstream | #121224 | — |
| `tests/hermes_cli/test_doctor.py` | 19/19 | upstream | upstream | #125260 test half (`setenv` for `setattr`) | — |
| `tests/hermes_cli/test_setup_hermes_script.py` | 19/1 | upstream | upstream | #121226 | — |
| `tests/hermes_cli/test_win_pty_bridge.py` | 41/3 | upstream | upstream | #121219 | — |
| `tests/scripts/test_run_tests_parallel.py` | 180/3 | upstream | upstream + move | `_root_the_probe` and the decode fixes → #125263 test half; the five fork tests move (§5) | T2 |
| `tests/tools/test_execution_flag_detection.py` | 11/2 | upstream | upstream | #121226 | — |
| `tests/tools/test_file_tools_live.py` | 35/4 | upstream | upstream | #121226 (`_sh`, the `test -ef` tilde check) | — |
| `tests/tui_gateway/test_compute_host_pending_model_switch.py` | 25/3 | upstream | kept + move | the in-place rename is the held shared-provider regression; the one fork test moves (§5) | T3 |
| `tests/tui_gateway/test_local_model_session_identity.py` | 17/0 | upstream | **move** | the fork test and its fixture line move; the file returns to upstream's bytes and leaves the ledger (§5) | T3 |

**Counts (174 files, primary verdict per row):** drop 1 (partial, `pyproject.toml`) · extract-now 0 ·
extract-module 13 · upstream 130 · kept 29 · move (S5) 1. A row may cite several retirements; by
family over all 174 (substring count over the proof column): door A 9, door B 6, door C 12, door D 10,
§G 6, an open nekwo PR or issue 96, a third-party PR 7, a held PR or prepared branch 24, a PR
candidate still unfiled 9.

## 2. The MOVE lanes, by footprint fall

Same rules as the first audit: one MOVE commit per lane, behaviour identical, ledger rows re-derived in
the commit (`scripts/upstream_footprint.py --ledger`), fixture lowered in a CHANGE commit after the
gate, one gate per batch. A moved body that imports a private upstream name declares it in the
import-layers exception list with the door it waits for. Every new module is a fork-only path.

| lane | files | target module | tests that must stay green | fall (added lines) |
|---|---|---|---|---|
| **A — test runner** | `scripts/run_tests.sh`, `scripts/run_tests_parallel.py` | `scripts/_fork_test_env.sh` (functions), `scripts/_fork_runner.py` (new; `pytest_argv`) | `tests/scripts/test_run_tests_parallel.py` + `_downstream.py`, `tests/scripts/test_run_tests_bundled_*_downstream.py`, `tests/scripts/test_fork_test_env*.py`, one real `scripts/run_tests_bundled.sh tests/scripts` run | 326 → ~141 (**−185**) |
| **G — Group Chat host surface** | `gateway/hosted_rooms.py`, `gateway/hosted_room_discussion.py`, `tui_gateway/hosted_room_driver.py` | `gateway/hosted_room_history_pins.py`, `gateway/hosted_room_limits.py` (new), `agent_runtime/discussions/hosted_room_driver_ext.py` (new) | `tests/gateway/test_hosted_room*`, `tests/tui_gateway/test_hosted_room_driver_runtime_downstream.py`, `tests/agent_runtime/test_discussions_*` | 294 → ~143 (**−151**); heavy 4 → 3 |
| **E — plugin CLI commands** | `hermes_cli/plugins.py`, `hermes_cli/main.py` | `hermes_cli/plugins_manifest_cli_commands.py` (exists) | `tests/hermes_cli/test_plugins_cli_commands*.py`, `test_main_*downstream.py`, upstream `tests/hermes_cli/test_plugins*.py`, `test_main*.py`; `hermes --help` and one declared command (`hermes harness …`) run | 180 → ~67 (**−113**) |
| **C — tool registry accounting** | `tools/registry.py` | `tools/toolset_scan.py` (exists), `tools/registry_probe_accounting.py` (new) | `tests/tools/test_registry*`, `tests/scripts/test_dump_toolset_manifest*`, `tests/agent_runtime/test_chat_lane_bundle*` | 180 → ~85 (**−95**); heavy 4 → 3 |
| **H — history and replay** | `tui_gateway/event_replay.py`, `hermes_state.py`, `hermes_state_messages.py`, `hermes_cli/auth.py` | `tui_gateway/recovery_history.py` (exists), `hermes_state_history_controls.py` (exists), `agent/provider_access.py` (exists) | `tests/tui_gateway/test_session_recovery*`, `test_event_replay*`, `tests/test_hermes_state_history_controls*`, `tests/agent_runtime/test_provider_probes*`, upstream `tests/test_hermes_state*.py`, `tests/hermes_cli/test_auth*.py` | 90 → ~37 (**−53**); files −1 (`event_replay.py`) |
| **B — approval surface policy** | `tools/approval_context.py` | `agent_runtime/approval_surface_policy.py` (new) | `tests/agent_runtime/test_operator_session_controls.py`, upstream `tests/tools/test_approval*.py` | 35 → ~8 (**−27**) |
| **F — managed-local floor** | `agent/agent_init.py`, `agent/conversation_compression.py` | `agent_runtime/managed_local_floor.py` (new; beside `local_llama_adapter`) | `tests/agent_runtime/test_local_llama_*`, `tests/agent/test_agent_init_context_floor*`, upstream `tests/agent/test_conversation_compression*.py` | 53 → ~27 (**−26**) |

Order: A, G, E, C may run concurrently (disjoint files; none in the conflict set). H and B after
them; **H is after release** (`hermes_state.py` conflicts). F after lane R of the first audit (R
re-points `agent_init` imports). Together with the first audit's lanes: added lines across the
222 files ≈ 5,790 → ≈ 4,380; `heavy` 4 → 1 (only `gateway-contract.openrpc.json` remains).

## 3. The drop lane (CHANGE at the merge)

| file | change | proof | when |
|---|---|---|---|
| `pyproject.toml` | the merge takes upstream's `httpx2==2.12.0` in `mcp` / `computer-use` / `dev` and deletes the five-line "FORK CARRY" comment; the `onnx-asr = false` row goes with upstream's deleted `[tool.uv.exclude-newer-package]` table | `tests/agent_runtime/test_bundle_vuln_floors.py` (green on the identical pin); `hermes pm lock` resolves the speech extras under `exclude-newer = "3 days"` | the `v0.22.2` merge (D2, **rel**) |
| `tui_gateway/methods_prompt.py` | `deleted_lines` −110 when the merge that carries #129414 lands (`pdf.attach` already lives in `methods_pdf.py` upstream-side on that PR) | `tests/tui_gateway/test_methods_pdf*` | the merge after #129414 |

Fall at the `v0.22.2` merge: added −9, `deleted_lines` unchanged (1050); `files` unchanged.

## 4. Rows that read wrong (file them from the lane that lands the fix)

- `hermes_cli/auth_codex.py` — the reason names only `on_verification`; `_codex_pool_row_refused` is
  an unfiled bug-fix PR candidate hiding under a carry row.
- `agent/system_prompt.py` — the h10b-fix anchor repair is an upstream defect, not a hook wait.
- `tui_gateway/server.py` — `_sanitize_client_source` (M2.02) is an upstream NameError, not shared-provider carry.
- `tools/image_generation_tool.py`, `tools/tts_tool.py`, `tools/vision_tools.py` — "fork-only read
  projection … not an upstream PR": #125259's title says "read-only sites use `load_config_readonly`";
  the rows ride it.
- `scripts/run_tests.sh` — disposition `upstream` for 181 lines of which #125263 carries ten; the row is a
  fork test-infrastructure carry (lane A names its module).
- `tui_gateway/host_supervisor.py` — add the `has_pending_turn` tuple-unpack hazard so the merge lane reads it.
- `tests/_fixtures/live_system_guard.py` — the Windows console-event refusal is not in #129582.

## 5. Part 2 — fork tests still inside upstream test files (S5)

Every upstream test file in the ledger, classified. **MOVE** = the fork only adds its own tests (or a
fork test plus its private helpers) and those can move to a fork-owned sibling; **in-place** = the fork
edits upstream's own tests (Windows spellings, PR test halves, held rewrites) — those are the ledger's
PR verdict and stay until the PR merges. Fork siblings import upstream helpers from the upstream
module (the pattern `tests/scripts/test_run_tests_parallel_downstream.py` and
`tests/hermes_cli/test_nous_inference_url_validation_downstream.py` already use); source-pin census
first (refactor rule 1.6); any node id named in `tests/` or `scripts/` registries is retargeted in the
MOVE commit (S5 inventory §1 item 4); the `--collect-only` id set is unchanged modulo file names.

| upstream test file | +a/-d | fork tests added | in-place hunks (stay, with their PR) | class |
|---|---|---|---|---|
| `tests/hermes_cli/test_auth_nous_provider.py` | 167/4 | 8: `test_device_login_refuses_portal_inference_url_outside_allowlist`, `…_non_https_…`, `…_keeps_allowlisted_…`, `test_restart_heals_persisted_foreign_nous_inference_url`, `…_keeps_persisted_allowlisted_…`, `…_matching_operator_override`, `…_parser_invalid_…` (parametrized), `test_heal_parser_invalid_guest_inference_url_selects_welcome_host` + helpers `_run_device_login_with_portal_inference_url`, `_restart_and_swap_in_nous_pool_row`, two constants (≈135 lines) | `test_shared_store_write_and_read_roundtrip` O_CREAT spy (#121225) | **MOVE** (T1) |
| `tests/scripts/test_run_tests_parallel.py` | 180/3 | 5: `test_windows_worker_does_not_inherit_runner_console`, `test_isolation_retry_keeps_the_scaled_timeout_and_counts_skips`, `test_node_id_selector_runs_the_named_test`, `test_explicit_k_wins_over_node_id_inference`, `test_multiple_absolute_paths_split_on_pathsep` (≈142 lines) | `_root_the_probe` + its six call sites, `pytest.ini` seeds, utf-8 decode (#125263) | **MOVE** (T2) |
| `tests/tui_gateway/test_compute_host_pending_model_switch.py` | 25/3 | 1: `test_idle_model_change_returns_the_compute_owners_receipt` (20 lines) | `test_config_set_model_defers_on_busy_compute_host_session` rename/rewrite (held, shared-provider) | **MOVE** (T3) |
| `tests/tui_gateway/test_local_model_session_identity.py` | 17/0 | 1: `test_unbuilt_session_reports_its_selected_model` (15 lines) + the `server._hermes_home` line in `local_route` that only it needs | none | **MOVE** (T3); the file leaves the ledger |
| `tests/tools/test_windows_agent_loop_papercuts.py` | 23/0 | 2 (class methods) | — | PR-bound: #123892's test half; leaves with it |
| `tests/agent/test_run_agent_codex_responses.py` | 6/7 | 1 + a replaced autouse fixture | — | PR-bound: held branch `upstream/codex-retry-isolation` |
| `tests/tui_gateway/test_serve_exit_flush.py` | 68/37 | 0 (rewrite) | whole | in-place: held branch `upstream/shutdown-test-isolation` |
| `tests/tui_gateway/test_bot_relay_methods.py` | 6/3 | 0 (parametrize) | whole | in-place: #137478 |
| `tests/hermes_cli/test_auth_commands.py` | 3/3 | 0 | whole | in-place: #121642 |
| `tests/hermes_cli/test_backup.py` | 33/7 | 0 | whole | in-place: #121224 / #121225 (+ held `.bat` hunk) |
| `tests/hermes_cli/test_deleted_profile_tombstone.py` | 4/1 | 0 | whole | in-place: #121224 |
| `tests/hermes_cli/test_doctor.py` | 19/19 | 0 | whole | in-place: #125260 |
| `tests/hermes_cli/test_launcher_runtime_selection.py` | 1/0 | 0 (fixture line) | — | first audit lane D (drop) |
| `tests/hermes_cli/test_setup_hermes_script.py` | 19/1 | 0 | whole | in-place: #121226 |
| `tests/hermes_cli/test_source_launcher_publication.py` | 1/0 | 0 (fixture line) | — | first audit lane D (drop) |
| `tests/hermes_cli/test_uninstall_dry_run.py` | 1/0 | 0 | whole | in-place: #121640 |
| `tests/hermes_cli/test_win_pty_bridge.py` | 41/3 | 0 (helper `_unwrapped`) | whole | in-place: #121219 |
| `tests/gateway/test_api_server_active_work_drain.py` | 2/0 | 0 | whole | in-place: #132989 follow-up |
| `tests/tools/test_execution_flag_detection.py` | 11/2 | 0 | whole | in-place: #121226 |
| `tests/tools/test_file_tools_live.py` | 35/4 | 0 (helper `_sh`) | whole | in-place: #121226 |
| `tests/test_live_system_guard_self_test.py` | 4/0 | 0 | whole | in-place: signal-safety carry |

`tests/conftest.py`, `tests/_fixtures/*` and `tests/fixtures/resolution_allowlist.json` are fixtures,
not tests (§1.5).

### 5.1 The test MOVE lanes, by footprint fall

| lane | files | target sibling | notes | fall |
|---|---|---|---|---|
| **T2 — scripts** | `tests/scripts/test_run_tests_parallel.py` | `tests/scripts/test_run_tests_parallel_downstream.py` (exists; imports `_probe_root`, `_root_the_probe`, `_make_probe_dir` from the upstream module) | `test_windows_worker_does_not_inherit_runner_console` keeps its `platforms("windows")` + `timeout(75)` marks; grep `tests/` and `scripts/` for the five ids (registries) | 180 → ~38 (**−142**) |
| **T1 — hermes_cli** | `tests/hermes_cli/test_auth_nous_provider.py` | `tests/hermes_cli/test_nous_inference_url_validation_downstream.py` (exists; already imports the upstream module as `_upstream`) — or a new `test_auth_nous_provider_downstream.py` if the file would pass 300 lines | the moved tests import `_invoke_jwt`, `_future_iso` from `tests.hermes_cli.test_auth_nous_provider`; `_FOREIGN_INFERENCE_URL` / `_OPERATOR_INFERENCE_URL` move with them | 167 → ~32 (**−135**) |
| **T3 — tui_gateway** | `tests/tui_gateway/test_compute_host_pending_model_switch.py`, `tests/tui_gateway/test_local_model_session_identity.py` | `tests/tui_gateway/test_compute_model_selection.py` (fork, exists) and a new `test_local_model_session_identity_downstream.py` carrying its own `local_route` fixture (the 12 upstream lines + the `_hermes_home` line) | `test_local_model_session_identity.py` returns to upstream's bytes | 42 → 5 (**−37**); files −1 |

Order: T2, T1, T3 — all three may run concurrently with each other and with lanes A/G/E/C (disjoint
files; none in the conflict set). One gate per batch. Expected after all three:
added lines −314 on the tests rows, `[up-fp] files` −1.

## 6. After everything

First audit (C, R, P, M, D) + this one (A, G, E, C, H, B, F, D2, T1–T3):
`[up-fp] files=222 → 217` (`event_replay.py`, `test_local_model_session_identity.py`, and the first
audit's three), `deleted_lines ≈ 1038` (−110 more once #129414 merges), `heavy 4 → 1`; added lines
across the ledger ≈ 5,790 → ≈ 4,060. Everything left is a door (A–J), an open PR, or a ruled carry —
the Stage 7 detach read's residue is then the carry list plus the two generated contract files.
