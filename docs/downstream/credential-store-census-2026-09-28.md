# Credential-store census — 2026-09-28

Embedded-hermes plan D0 item 6 (`EterniaLauncher/docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md`,
architecture §4 "Credentials seam"). Research only: no code changed. Stage 2 binds
every row below to the OS secure-store seam; D1 uses the **Scope** column to prove a
bundled Hermes and a full Hermes never discover each other's credentials.

Taken at `origin/main` `aadfb387f2`. Owner is the FILE's owner by
`tests/fixtures/upstream_manifest.txt` (**U** = upstream, **F** = fork-only); a fork
seam inside an upstream file is called out in the row. `file:line` is the function's
`def` line. Ops: **R** read, **W** write, **Rf** refresh (network rotation plus
write-back), **D** delete/clear.

## Scope keys

| Key | Resolved by | What it scopes |
|---|---|---|
| `HERMES_HOME` (profile home) | `hermes_constants.py:111` `get_hermes_home` | every per-profile store below unless another key overrides it |
| `HERMES_AUTH_HOME` | `agent_runtime/profile_home.py:77` `get_hermes_auth_home` (ContextVar override set at `:69`, reset `:74`; env second) — **F** | `auth.json`, its `auth.lock`, `credential_rotation.json`. Written only by `agent_runtime/profile_context.py:175` `persona_profile_context` (also `:360` `persona_profile_scope`, `:407` `process_home_scope`); `hermes_cli/auth_noninteractive.py:74` `resolve_target_home` (**F**) picks the home for non-interactive logins |
| default Hermes root | `hermes_constants.py:216` `get_default_hermes_root` — `~/.hermes`, or `HERMES_HOME` itself (or its `profiles/` parent) when `HERMES_HOME` is outside `~/.hermes` | global-root fallbacks and write-throughs; the shared Nous store |
| `HERMES_SHARED_AUTH_DIR` | `hermes_cli/auth_nous.py:330` `_nous_shared_auth_dir` (else `<root>/shared/`) | `nous_auth.json` — deliberately cross-profile |
| user home | `Path.home()` | borrowed third-party CLI stores (`~/.claude`, `~/.codex` or `CODEX_HOME`, `~/.qwen`, `gh`), gated by `auth.adopt_external_logins` (`agent/credential_sources.py:32`, default on) |
| process env | `.env` loaded into `os.environ` | API keys and platform tokens; env-seeded pool rows |
| OS keychain | macOS `security` CLI | Claude Code's credential item (borrowed) |
| explicit path | env var | `HERMES_REALM_SYNC_CREDENTIAL`, `GOOGLE_APPLICATION_CREDENTIALS` |

## 1. `auth.json` — provider logins and the credential pool

Path: `hermes_cli/auth.py:495` `_auth_file_path` (**U** file, **F** seam: `HERMES_AUTH_HOME`
first, else `HERMES_HOME`; the one resolver). Lock: `:669` `_auth_store_lock` (`auth.lock`
beside it). Scope: `HERMES_AUTH_HOME` → `HERMES_HOME`; global-root reads via `:520`
`_global_auth_file_path` / `:532` `_load_global_auth_store`. Plaintext JSON,
`_save_private_json` (`:735`, 0600).

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R | hermes_cli/auth.py:687 | `_load_auth_store` | U | the store read chokepoint |
| R | hermes_cli/auth.py:532 | `_load_global_auth_store` | U | default-root `auth.json`, read-only fallback |
| R | hermes_cli/auth.py:896 | `read_credential_pool` | U | `credential_pool` section |
| R | hermes_cli/auth.py:1139 | `get_provider_auth_state` | U | per-provider section |
| R | agent/credential_pool.py:3030 | `load_pool` | U | pool assembly; seeds singletons below |
| R | agent/auxiliary_client.py:967 | `_auth_json_path` | U | resolves through `_auth_file_path` at call time; the import-time `_AUTH_JSON_PATH` (`:963`) wins only when a test patches it |
| W | hermes_cli/auth.py:744 | `_save_auth_store` | U | the store write chokepoint (all W rows funnel here) |
| W | hermes_cli/auth.py:820 | `_save_provider_state` | U | |
| W | hermes_cli/auth.py:825 | `_save_active_provider_state` | U | |
| W | hermes_cli/auth.py:833 | `_persist_provider_state_to_store` | U | |
| W | hermes_cli/auth.py:843 | `_save_provider_state_to_source` | U | writes back to the store the state came from (profile or root) |
| W | hermes_cli/auth.py:1043 | `write_credential_pool` | U | |
| W | hermes_cli/auth.py:1099 | `suppress_credential_source` | U | also `unsuppress_credential_source` |
| W | agent/credential_pool.py:913 | `persist_pool_entries` | U | sanitized by `agent/credential_persistence.py` (borrowed rows stripped of secrets) |
| W | agent/credential_pool.py:1136 | `CredentialPool._persist` | U | |
| W | agent/credential_pool.py:790 | `_write_through_provider_state_to_global_root` | U | **cross-scope write** into the default root's `auth.json` |
| W | agent/credential_pool.py:1451 | `_sync_device_code_entry_to_auth_store` | U | |
| W | agent/credential_pool_admin.py:110 | `add_entry` | U | `hermes auth add` |
| W | hermes_cli/auth_nous.py:836 | `persist_nous_credentials` | U | also `_login_nous`, `_restore_active_provider` |
| W | hermes_cli/auth_codex.py:174 | `_save_codex_tokens` | U | |
| W | hermes_cli/auth_xai.py:127 | `_save_xai_oauth_tokens` | U | |
| W | hermes_cli/auth_xai.py:100 | `_write_through_xai_oauth_to_global_root` | U | **cross-scope write** |
| W | hermes_cli/auth_minimax.py:161 | `_minimax_save_auth_state` | U | |
| W | hermes_cli/auth_qwen.py:104 | `_mark_qwen_oauth_active` | U | |
| W | hermes_cli/auth_spotify.py:314 | `login_spotify_command` | U | |
| W | hermes_cli/anon_auth.py:373 | `_mint_locked` | U | Nous guest credential; also `_reconcile_and_provision`, `mark_guest_notice_shown` |
| W | hermes_cli/auth_oauth_grants.py | `_heal_forked_single_use_oauth_grants`, `strip_cloned_single_use_oauth_grants` | U | repairs profile clones sharing one single-use refresh family |
| W | hermes_cli/provider_browser_login.py:13 | `_persist` | F | the fork's browser sign-in driver (codex/xai/minimax/nous) |
| W | hermes_cli/proxy/adapters/nous_portal.py | `_save_state` | U | |
| W | hermes_cli/web_routers/oauth.py | `_run` | U | dashboard OAuth |
| W | tui_gateway/methods_complete.py | (anonymous handler) | U | |
| Rf | hermes_cli/auth_nous.py:600 | `_refresh_access_token` | U | with `refresh_nous_oauth_pure` `:766`, `refresh_nous_oauth_from_state` `:791`, `_resolve_nous_runtime_credentials` `:1075` |
| Rf | hermes_cli/auth.py | `resolve_nous_access_token` | U | |
| Rf | hermes_cli/auth_codex.py:518 | `_refresh_codex_auth_tokens` | U | single-use refresh family |
| Rf | hermes_cli/auth_xai.py:354 | `_refresh_xai_oauth_tokens` | U | with `refresh_xai_oauth_pure` `:300` |
| Rf | hermes_cli/auth_minimax.py:232 | `_refresh_minimax_oauth_state` | U | |
| Rf | hermes_cli/auth_spotify.py:173 | `_refresh_spotify_oauth_state` | U | via `resolve_spotify_runtime_credentials` `:200` |
| Rf | agent/credential_pool.py:1520 | `CredentialPool._refresh_entry` | U | `_refresh_entry_impl` `:1709`, `_try_refresh_current_unlocked` `:2415` |
| D | hermes_cli/auth.py:1311 | `clear_provider_auth` | U | |
| D | hermes_cli/auth.py:1333 | `deactivate_provider` | U | |
| D | hermes_cli/auth.py:2412 | `logout_command` | U | |
| D | agent/credential_sources.py:154 | `_remove_auth_store_oauth` | U | `hermes auth remove`; also `_remove_xai_oauth_device_code` `:173`, `_remove_codex_device_code` `:181` |
| D | agent/credential_pool.py | `_clear_terminal_nous_state`, `_clear_terminal_tokens_state` | U | on terminal refresh errors |
| D | hermes_cli/auth_xai.py:385 | `_quarantine_xai_oauth_tokens` | U | also minimax `:273`, `auth.py:1716` `_quarantine_flat_oauth_state` |
| D | hermes_cli/anon_auth.py | `clear_dead_guest` | U | |
| D | hermes_cli/credential_lifecycle.py | `_prune_env_pool_entries` | U | |
| D | hermes_cli/model_setup_flows_common.py | `_prune_replaced_custom_model_config_credentials` | U | |

## 2. `credential_rotation.json` — pool rotation state (fork)

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R | agent_runtime/auth_extensions.py:41 | `_load_rotation_state` | F | beside `auth.json` (`:24` `_rotation_state_path` derives from `_auth_file_path`), so `HERMES_AUTH_HOME` scoped; holds cooldown state, no secret values |
| W | agent_runtime/auth_extensions.py:81 | `_write_rotation_state_file` | F | via `write_pool_rotation_state` `:108` |

## 3. `.anthropic_oauth.json` — Hermes PKCE for Anthropic

Path: `agent/anthropic_credentials.py:732` `_get_hermes_oauth_file` = `HERMES_HOME/.anthropic_oauth.json`
— **not** `HERMES_AUTH_HOME` (unlike `auth.json`). Root copy: `:736` `_root_hermes_oauth_file`.

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R | agent/anthropic_credentials.py:809 | `read_hermes_oauth_credentials` | U | `HERMES_HOME` |
| R | hermes_cli/auth_oauth_grants.py:329 | `_singleton_as_row` | U | profile and root singletons |
| W | agent/anthropic_credentials.py:754 | `run_hermes_oauth_login_pure` | U | the PKCE login (the D0 item 3 driver wraps this) |
| W | agent/anthropic_credentials.py:815 | `_write_hermes_oauth_credentials` | U | target may be the root copy |
| W | agent/credential_pool.py:2547 | `_seed_anthropic_singletons` | U | reads the singleton into the pool (R) |
| Rf | agent/anthropic_credentials.py:450 | `refresh_anthropic_oauth_pure` | U | |
| Rf | agent/credential_pool.py:1635 | `CredentialPool._commit_anthropic_rotation` | U | writes to the profile or **root** singleton (`_singleton_target_for_entry` `:823`) |
| D | agent/credential_sources.py:139 | `_remove_hermes_pkce` | U | unlinks the profile file |
| D | hermes_cli/web_routers/oauth.py | `_clear_anthropic_auth` | U | dashboard |

## 4. Borrowed third-party CLI stores (user home, not Hermes scope)

All gated by `adopt_external_logins_enabled` (`agent/credential_sources.py:32`). These are
the **cross-install discovery** surface: any Hermes on the machine, bundled or full, sees
the same files.

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R | agent/anthropic_credentials.py:351 | `read_claude_code_credentials` | U | `~/.claude/.credentials.json` (`:337`) then macOS Keychain (`:331`, `:284`, `:255`) |
| W | agent/anthropic_credentials.py:535 | `_write_claude_code_credentials` | U | write-back after refresh |
| W | agent/anthropic_credentials.py:574 | `_mirror_claude_code_credentials_to_keychain` | U | macOS Keychain write |
| Rf | agent/anthropic_credentials.py:465 | `_refresh_oauth_token` | U | refreshes the borrowed Claude Code token |
| R | agent/credential_pool.py:1256 | `_sync_anthropic_entry_from_credentials_file` | U | |
| R | hermes_cli/auth_codex.py:563 | `_import_codex_cli_tokens` | U | `CODEX_HOME` or `~/.codex/auth.json`; also `_recover_codex_tokens_from_cli` `:217` |
| R | agent/auxiliary_client.py:2129 | `_read_codex_singleton_token` | U | |
| R | hermes_cli/auth_qwen.py:29 | `_read_qwen_cli_tokens` | U | `~/.qwen/oauth_creds.json` (`:25`) |
| W | hermes_cli/auth_qwen.py:45 | `_save_qwen_cli_tokens` | U | |
| Rf | hermes_cli/auth_qwen.py:60 | `_refresh_qwen_cli_tokens` | U | |
| R | hermes_cli/copilot_auth.py:116 | `_try_gh_cli_token` | U | `gh auth token` subprocess; `resolve_copilot_token` `:57` also reads `COPILOT_GITHUB_TOKEN`/`GH_TOKEN`/`GITHUB_TOKEN` |
| W | hermes_cli/copilot_auth.py:164 | `copilot_device_code_login` | U | token saved to `.env` by `hermes_cli/model_setup_flows.py:504` `_copilot_obtain_token` |
| D | agent/credential_sources.py:199 | `_remove_copilot_gh` | U | clears env copies; the `gh` store is left and hinted |

## 5. `nous_auth.json` — shared Nous store (cross-profile by design)

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R | hermes_cli/auth_nous.py:456 | `_read_shared_nous_state` | U | `HERMES_SHARED_AUTH_DIR` or `<default root>/shared/`; also `_try_import_shared_nous_state` `:566` |
| W | hermes_cli/auth_nous.py:430 | `_write_shared_nous_state` | U | written on login AND every refresh |
| D | hermes_cli/auth_nous.py:480 | `_clear_shared_nous_state` | U | |

## 6. `.env` — API keys, platform tokens, integration secrets

Path: `hermes_cli/config.py:477` `get_env_path` = `HERMES_HOME/.env`. Loaded into the process
environment, so every `os.environ` / `get_env_value` reader is a secret read.

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R | hermes_cli/config.py:2488 | `load_env` | U | file → dict |
| R | hermes_cli/config.py:2782 | `reload_env` | U | file → `os.environ` |
| R | hermes_cli/config.py:2811 | `get_env_value` | U | env first; `get_env_value_prefer_dotenv` `:2826` file first |
| R | agent/credential_pool.py:2911 | `_seed_from_env` | U | API keys become pool rows (not persisted with secrets) |
| W | hermes_cli/config.py:2690 | `save_env_value` | U | the write chokepoint; ~60 setup/wizard callers (platform adapters' `interactive_setup`, `gateway_setup_wizard`, `main_provider_setup._prompt_api_key`, `web_routers/config_env`, `web_routers/messaging`, `tools/connectors`, `gateway_enroll`, `secrets_cli`, `onepassword_secrets_cli`, `model_setup_flows*`) |
| W | hermes_cli/config.py:2770 | `save_env_value_secure` | U | |
| D | hermes_cli/config.py:2726 | `remove_env_value` | U | |
| D | agent/credential_sources.py:95 | `_remove_env_source` | U | `hermes auth remove` for env-sourced keys |

## 7. MCP OAuth tokens — `mcp-tokens/`

Path: `tools/mcp_oauth.py:229` `_get_token_dir` = `HERMES_HOME/mcp-tokens/<server>{.json,.client.json,.meta.json}`.
Child MCP processes inherit the home via `tools/mcp_tool_config.py:129` `_inject_child_hermes_home`.

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R | tools/mcp_oauth.py:486 | `HermesTokenStorage.get_tokens` | U | also `get_client_info`, `load_oauth_metadata` |
| W | tools/mcp_oauth.py:490 | `HermesTokenStorage.set_tokens` | U | the SDK's refresh writes back here too |
| W | tools/mcp_oauth.py:557 | `HermesTokenStorage.set_client_info` | U | dynamic client secret |
| D | tools/mcp_oauth.py:520 | `HermesTokenStorage.strip_refresh_token` | U | |
| D | tools/mcp_oauth.py:588 | `HermesTokenStorage.remove` | U | via `remove_oauth_tokens` `:917` |

## 8. Other secret stores

| Op | file:line | Function | Owner | Scope / note |
|---|---|---|---|---|
| R/W | agent/secret_sources/bitwarden.py:148 / :125 | `_read_encrypted_disk_cache` / `_write_encrypted_disk_cache` | U | `HERMES_HOME/cache/bws_cache.enc.json` (`:57`); secret VALUES, encrypted with the BWS access token |
| R/W | agent/vault_backends/unlock.py:102 / :113 | `get_session_token` / `store_session_token` | U | in-memory vault unlock tokens; `lock` `:124`, `release_session` `:137` clear them |
| R | agent/proxy_sources/iron_proxy.py:297 | `_management_token_path` | U | proxy state dir `management.token` |
| R/W | hermes_cli/webhook.py:27 / :38 | `_load_subscriptions` / `_save_subscriptions` | U | `HERMES_HOME/webhook_subscriptions.json` (per-route HMAC secrets) |
| R/W | gateway/pairing.py:243 / :279 | `_load_json_file` / `_save_json_file` | U | `HERMES_HOME/pairing/` pending codes and approved users (`:58` `_default_pairing_dir`) |
| R/Rf | skills/productivity/google-workspace/scripts/gws_bridge.py:84 / :32 | `get_valid_token` / `refresh_token` | U | `HERMES_HOME/google_token.json` (`:21`); `auth/google_oauth.json` client secret |
| R | agent/vertex_adapter.py:148 | `get_vertex_credentials` | U | service-account file at `GOOGLE_APPLICATION_CREDENTIALS` |
| R | agent_runtime/realm_membership.py:113 | `load_realm_sync_credential` | F | explicit `--credential-file` or `HERMES_REALM_SYNC_CREDENTIAL` |
| — | tools/credential_files.py:63 | `register_credential_file` | U | mounts `HERMES_HOME` credential files into sandboxes (a read path by proxy) |

## What the seam has to cover (for Stage 2 / D1)

- **`HERMES_AUTH_HOME` scopes only `auth.json` and its siblings.** `.anthropic_oauth.json`,
  `.env`, `mcp-tokens/`, `pairing/`, webhook and Google stores follow `HERMES_HOME`; the
  Nous shared store follows the default root. Binding "the auth store" alone leaves those
  on disk.
- **Three cross-scope writers** push credentials out of the active profile:
  `_write_through_provider_state_to_global_root`, `_write_through_xai_oauth_to_global_root`,
  and the root-singleton branch of `_commit_anthropic_rotation`; plus the shared Nous store.
  A bundled Hermes whose `HERMES_HOME` sits outside `~/.hermes` gets its own default root,
  so these stay inside it — D1 must pin that `HERMES_HOME` placement.
- **Section 4 is machine-wide.** Bundled Hermes must run with `auth.adopt_external_logins`
  off (or the seam must refuse user-home reads), or it and full Hermes share one Claude
  Code / Codex / Qwen token family and log each other out.
