# Planned — dispositions for `hermes_cli/`, `tools/` and `agent/` (2026-09-24, read-only)

Lane DISP-C. It gave each of the 121 `unreviewed` ledger rows under the three directories a disposition, a reason and a stage. The ledger is [`upstream-footprint-ledger.md`](upstream-footprint-ledger.md), and the rules are §1 and "No duplicate authority" in [`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md). Each row was read the way [`seam-s4-s5-s6-inventory-2026-09-23.md`](seam-s4-s5-s6-inventory-2026-09-23.md) §2 reads: `git diff d337b736aa HEAD -- <path>`, where `d337b736aa` is the manifest base. Every name the fork adds or changes was then looked up in `upstream/main` (`6b2c23ae42`). Upstream commits after the base were also scanned for fork-added lines that upstream now carries.

The owner's 2026-09-24 addendum was applied. An edit that only supports something the fork has retired is disposition `upstream`, reason `REVERT: …`. Tombstone check: the names in `tests/agent_runtime/test_tombstone_registry.py` (1,328 names including the removal gates' string literals) were matched against every fork-added line in the 121 files. It found no retired identifier; every hit was an English word such as `verified` or `running`. The two REVERT classes below were found by reading the code.

## 1. Per directory

Bucket = the row's primary disposition. A row whose reason also names a secondary part is counted once.

| directory | rows | already-upstream | generic | hook | carry-movable | carry-fixed | revert |
|---|---|---|---|---|---|---|---|
| `hermes_cli/` | 57 | 4 | 30 | 6 | 5 | 4 | 8 |
| `tools/` | 36 | 3 | 16 | 2 | 10 | 5 | 0 |
| `agent/` | 28 | 7 | 6 | 6 | 0 | 9 | 0 |
| total | 121 | 14 | 52 | 14 | 15 | 18 | 8 |

Ledger dispositions written: `upstream` 74 (14 + 52 + 8), `hook` 14, `carry` 33 (15 + 18).

## 2. Already-upstream (adopt theirs, delete ours) — each one is a duplicate-authority defect

Size = added + deleted in the ledger row.

| row | size | fork name(s) | upstream equivalent @ sha |
|---|---|---|---|
| `hermes_cli/codex_models.py` | 114 | gpt-6 defaults/templates; `fetch_codex_catalog_entries` use; `_extract_chatgpt_account_id` | tier rows @`79ec1f2a34`, catalog @`1d10cef836`; `agent.codex_headers.codex_account_headers` @`0bbf7b7997`. **Also a live defect:** `_fetch_verified_models_from_api` imports `CODEX_MODELS_CATALOG_URL`, which the fork deleted from `agent/model_metadata.py`, and `except Exception` swallows the ImportError. So `get_verified_codex_model_ids` answers None ("unverified") on every call, and `hermes_cli/model_picker_policy.py` never reports `verified` |
| `agent/turn_api_call.py` | 71 | `_fork_first_byte_s`, provider_dispatch timing | `agent._last_api_first_chunk_at` + `post_api_request(first_chunk_at, api_duration)` @`e17276c7b4` |
| `agent/model_metadata.py` | 66 | gpt-6 tier context rows, `fetch_codex_catalog_entries`, `CODEX_NEWEST_CLIENT_VERSION`, `CODEX_MODELS_CATALOG_URLS` | @`79ec1f2a34`, @`1d10cef836` (upstream dropped `gpt-6-terra`) |
| `agent/usage_pricing.py` | 66 | gpt-6 Sol/Luna pricing rows | @`79ec1f2a34` |
| `agent/auxiliary_client.py` | 61 | `agent_runtime.auxiliary_probe` aliased over upstream's deleted probe (−42) | `aux_probe_mode` / `_AuxProbeClientStub` @`55f9e472a0` |
| `hermes_cli/commands_platforms.py` | 57 | `discord_skill_commands` (a byte copy with no caller) | `hermes_cli.commands.discord_skill_commands` @`8ffd44a6f9` |
| `tools/file_operations.py` | 19 | `_shell_arg_safe_path` in both escapes | `ShellFileOperations._escape_native_tool_arg` @`07ee4a2ec8` |
| `agent/turn_usage.py` | 7 | TTFB log token (`_format_ttfb_token(_fork_first_byte_s)`) | @`e17276c7b4` |
| `agent/reasoning_effort.py` | 6 | `GPT6_TIER_PREFIXES` | @`79ec1f2a34` |
| `agent/shell_hooks.py` | 5 | `_split_command` alias (test readers only) | `split_command_line` @`ee472a7fdb` |
| `hermes_cli/model_switch.py` | 5 | `astra` suffix rank | @`79ec1f2a34` |
| `hermes_cli/models_catalog_static.py` | 5 | gpt-6 OpenRouter / openai-api rows | @`79ec1f2a34` |
| `tools/environments/modal.py` | 4 | `_snapshot_store_path` (no caller) | lazy `_snapshot_store()` @`adf23550f5` |
| `tools/environments/singularity.py` | 4 | `_snapshot_store_path` (no caller) | lazy `_snapshot_store()` @`adf23550f5` |

The following sit inside rows filed under another bucket:

- `tools/environments/local.py` (generic): `_find_windows_git_bash` duplicates upstream `_find_bash` @`c4622a1d5b`. `hermes_cli/dep_ensure.py::_git_bash_available` and `ensure_git_bash` call it. `_shell_arg_safe_path` supersedes upstream `_escape_native_tool_arg` @`07ee4a2ec8`.

Parallels that are unavoidable until a PR lands. Each is named here with the upstream symbol it shadows:

| fork | shadows | retires when |
|---|---|---|
| `hermes_cli/_bytecode_sweep.py` | `main_web_build._sweep_stale_bytecode_if_checkout_changed`, `_record_bytecode_fingerprint` | G12 PR (single-winner lock) |
| `hermes_cli/gateway.py::_command_matches_profile` | `_scan_gateway_pids._matches_current_profile` (upstream's own body, extracted) | G11 PR |
| `agent_runtime.pool_rotation.PoolRotationMixin` + `agent_runtime.provider_probes._select_pool_entry` | `CredentialPool._select_unlocked` strategy branch, `pool.select` | a persisted-rotation-cursor PR |
| `agent_runtime.mcp_environment._ENV_VAR_NAME_RE` | `hermes_cli/mcp_config.py::_ENV_VAR_NAME_RE` | restore upstream's constant; nothing to retire |
| `tools/tool_search.py::tool_describe_schema` (single `name`) | upstream's bridge `tool_describe` (`names`) | one schema; decide which |

## 3. Generic — PR-candidate classes

The files counted are the rows whose reason names the class, including secondary parts.

| class | files | what |
|---|---|---|
| G1 turn-safe lazy installs | 4 | `deny_venv_installs` / `RuntimeInstallDenied`: no lazy pip install into the running venv during a turn (the 2026-08-09 incident). `tools/lazy_deps.py`, `agent/anthropic_adapter.py`, the `run_conversation` wrapper, `hermes_cli/tools_config_cua.py` |
| G2 Windows paths and identity | 18 | `tools/path_identity.denotes_same_file` and POSIX match forms, `as_posix()` container paths, MSYS spellings, Git Bash discovery via `git.exe`, System32 shim exclusion, PTY EOF, drive-path image regex, extended-length readlink |
| G3 pet atlas extraction | 1 | context-aware strip-scale line erase, vertical merge, lenient rows |
| G4 SSL/CA cost | 2 | memoized SSL context; memoized CA-bundle verification |
| G5 reasoning relay | 1 | native reasoning emitted as `reasoning.available` |
| G6 security hardening | 2 | Nous inference-URL validation; redacted and bounded process notifications |
| G7 no silent caps | 2 | Slack 50-command clamp named in the log and the manifest output |
| G8 read-only config | 4 | `load_config_readonly` refuses mutation and never scaffolds the home |
| G9 kanban | 5 | crash evidence on dead-worker reclaim, `--claim-ttl`, `claim_ttl_seconds` default |
| G10 call-time home | 5 | doctor modules resolve the home per call instead of at import |
| G11 gateway launcher hardening | 3 | `resolve_managed_python`, pinned named-profile wrappers, console-less task warning, home receipt |
| G12 boot/build robustness | 1 | single-winner bytecode sweep, loud build-stamp failures |
| G13 MCP env | 3 | `mcp test --env`, child `HERMES_HOME` |
| G14 plugin-loader cost | 3 | bundled-plugin compat-scan skip, shared read-only config read, discovery timing |
| G15 OAuth catalog hoist | 3 | login-flow rows moved out of the dashboard into `provider_catalog` |
| G16 doc accuracy | 3 | wrong docker test name, a pre-push gate neither tree has, uninstall history warning |
| G17 updater fork safety | 3 | a fork's failed fast-forward never resets; no `--force-with-lease` |
| G18 tirith config authority | 2 | one reader for the tirith flags; fail-closed on an unsupported platform is announced, not silent |
| G19 tool search | 1 | `tools.tool_search.never_defer` config |

Suggested PR order: small and obviously wanted first. G16, G7, G2 in slices, G8, G4, G1.

## 4. Hook

| row | seam | surface |
|---|---|---|
| `agent/system_prompt.py` | tool-conditional guidance sections | has it (`register_system_prompt_section`, callable content), S2 with the `prompt_builder.py` row |
| `agent/turn_finalizer.py` | per-call usage ledger | has it (`post_api_request.usage`) |
| `tools/terminal_tool.py` | envelope gate + provenance | has it (`pre_tool_call` block, `transform_tool_result`) |
| `tools/skills_tool_plugin.py` | active-surface skill compatibility | has it (`pre_tool_call`) |
| `hermes_cli/skills_hub.py`, `hermes_cli/subcommands/skills.py` | `skills link-external` | has it (`register_cli_command`, as a harness verb), S1 |
| `agent/codex_runtime.py` | provider timing | partly: `pre/post_api_request`, `on_stream_*` cover dispatch, TTFB and usage. Client_resolve and stream_consume phases need widening |
| `agent/turn_api_request.py` | request-build phase stamps | partly: `pre_api_request` gives the bracket. Per-phase durations need widening |
| `agent/turn_response_check.py` | response-validate stamp | needs widening |
| `agent/skill_commands.py` | required-skill activation note | needs widening |
| `hermes_cli/auth_commands.py`, `hermes_cli/subcommands/auth.py` | `auth set-key` / `auth login` | needs widening (sub-verbs on a builtin parser), or rehome as `harness auth …` (S1) |
| `hermes_cli/plugins.py`, `hermes_cli/plugins_manifest.py` | manifest-declared CLI commands | needs widening (the Stage 1 PR) |

Four observability hooks the surface already has (`turn_finalizer`, plus the covered parts of `codex_runtime`, `turn_api_call` and `turn_usage`) have no owning stage; their stage is `-`. Stage 2 covers only tools and prompt sections.

## 5. Carry-movable — targets and recovered `deleted_lines`

| row | target | recovers |
|---|---|---|
| `tools/session_search_tool.py` | `tools/downstream_schema.py` BRIEF_DESCRIPTIONS | 13 |
| `tools/todo_tool.py` | same | 11 |
| `tools/browser_tool.py` | same (already wired for `browser_navigate`) | 9 |
| `tools/close_terminal_tool.py` | same | 6 |
| `tools/file_tools.py` | same | 5 |
| `tools/read_terminal_tool.py` | same | 4 |
| `tools/clarify_tool.py` | same | 3 |
| `tools/vision_tools.py` | same | 3 |
| `tools/web_tools.py` | same | 2 |
| `tools/code_execution_tool.py` | same | 1 |
| `hermes_cli/config_defaults.py` | harness plugin manifest `config_schema` (the comment rewraps revert) | 4 |
| `hermes_cli/status_auth.py` | `hermes_cli/harness.py` adds the Anthropic row | 1 |
| `hermes_cli/status.py` | `hermes_cli/harness.py` imports `status_auth._API_KEYS` | 0 |
| `hermes_cli/kanban_db.py` | readers import `hermes_cli.kanban_crash_evidence` | 0 |
| `hermes_cli/web_server_config.py` | plugin manifest `config_schema` | 0 |
| **total** | | **62** |

The ten tool-description rows are one class. The fork's own `tools/downstream_schema.py` states the rule: keep upstream's text and send the brief on the wire. These ten files rewrote upstream's text in place anyway. Moving them into `BRIEF_DESCRIPTIONS` leaves one registration line per file. `tools/tool_full_descriptions.py` already holds the full texts.

## 6. REVERT (supports a retired thing, or dead)

| row | why | recovers |
|---|---|---|
| `hermes_cli/kanban.py`, `approvals_test.py`, `bundles.py`, `curator.py`, `subcommands/computer_use.py` | `list_flag_or_empty` respellings of upstream lines. They served the UNSCOPED flag-binding ban, which was retired on 2026-09-21: `tests/hermes_cli/test_flag_binding_boundary.py` now reports fork-authored lines only (`tests/_fork_scope.is_fork_authored`). Behaviour-neutral. The `mcp_config.py` `cmd_args` line is the same class, inside a generic row | 6+1+1+1+2 = 11 |
| `hermes_cli/commands.py` | `deprecated_aliases` + `alias_deprecation_warning`: test-only (no production caller), announcing a `/tasks` removal "after Stage 44". The `queue-status` CommandDef in the same row → hook `register_command` | 3 |
| `hermes_cli/auth_codex.py` | a comment narrating the global-root fallback that theme-7 (2026-09-17) retired. Upstream `93889b770d` already removed the code | 0 |
| `hermes_cli/web_server.py` | dead re-export of `promote_profile_endpoint` (no reader through `web_server`) | 0 |
| **total** | | **14** |

Also dead, inside rows filed elsewhere: the `update_cmd.py` tail import `_warn_legacy_console_gateway_task` (no reader), `tools/environments/local.py::_bash_probe_failure_details` (no caller), and `_snapshot_store_path` ×2 (counted above as already-upstream).

## 7. Defects found (code, not ledger)

1. `hermes_cli/codex_models.py::_fetch_verified_models_from_api` imports the deleted `CODEX_MODELS_CATALOG_URL`. Live Codex catalog verification is dead (§2).
2. `agent/ssl_guard.py`: the fork's hunk deletes upstream's `# ---- BEGIN PLUGIN-COMPAT …` marker (the ledger's −4) and keeps its `END` marker. `verify_ca_bundle_with_fallback` now sits in an unopened compat block.
3. Duplicate TTFB authority: `agent._fork_first_byte_s` (fork) beside `agent._last_api_first_chunk_at` (upstream, `e17276c7b4`), both set per call.

Queue rows handed to the parent for `Harness_Brain/20 — Active Initiatives/runtime-queue.md` § Seams. They are in the lane report verbatim.

## 8. Regeneration

`python scripts/upstream_footprint.py --ledger` after the three ledger commits printed `[up-fp] files=448 deleted_lines=2800 heavy=12`. Zero rows under the three directories still read `carry | unreviewed`. The only generated-cell change was `README.md` 6 → 7 added, a row outside this lane that drifted on `origin/main`.
