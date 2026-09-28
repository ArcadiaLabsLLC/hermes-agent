# Discussion qualification — September 28

Status: verification in progress; not a closeout.

## Executed baseline comparison

Candidate `351ff56e1e` ran 70 files: 1,785 passed, 108 failed, 139 error
outcomes, 52 skipped and four expected failures. The runner's headline omits
errors; its exit code was 1. Two additional files exited without a normal
pytest summary. Peak process-tree memory was 817 MB.

All 60 red files were then executed on detached main `6ebde5afa3`, using the
same interpreter, canonical per-file runner, single worker and Git Bash.
The baseline reproduced every red file, the same per-file result counts and
all 246 unique failed/error node IDs printed in pytest summaries. The runner's
139 error outcomes also include an error without a matching node-summary line.
The baseline passed 1,611 tests and exited 1, with 789 MB peak tree memory.
No fixture allowance, assertion or timeout was relaxed.

This classifies these failures as inherited from that executed baseline. It is
not a passing suite, a claim about their root causes, or qualification of the
remaining population. Existing fork-hygiene rows retain their repairs.

| File | Candidate and baseline result |
|---|---|
| `tests/agent_runtime/test_gateway_media_fetch_e2e.py` | 5✗ |
| `tests/agent_runtime/test_gateway_tls.py` | 10✓ 1✗ 1s |
| `tests/agent_runtime/test_gateway_peer_cross_install_media_e2e.py` | 2✗ |
| `tests/agent_runtime/test_lazy_install_door.py` | 2e |
| `tests/agent_runtime/test_local_llama_adapter_gateway.py` | 2✗ |
| `tests/agent_runtime/test_gateway_peer_cross_install_chat_e2e.py` | 3✗ |
| `tests/agent_runtime/test_no_kanban_dependency.py` | 1✓ 1✗ |
| `tests/agent_runtime/test_no_midtest_monkeypatch_undo.py` | 21✓ 2✗ |
| `tests/agent_runtime/test_gateway_peer_two_roots_e2e.py` | 9✗ |
| `tests/agent_runtime/test_scope_use_serve_acceptance.py` | 2✓ 3✗ |
| `tests/agent_runtime/test_serve_gateway_chat_reply_lanes.py` | 2✗ |
| `tests/agent_runtime/test_serve_gateway_lane.py` | 11✓ 17✗ |
| `tests/agent_runtime/test_serve_gateway_peer_lane.py` | 4✓ 24✗ |
| `tests/hermes_cli/test_anon_sign_in_flow.py` | 22✓ 1✗ |
| `tests/hermes_cli/test_apply_profile_override_downstream.py` | 1e |
| `tests/hermes_cli/test_auth_codex_self_heal.py` | 4✓ 1✗ |
| `tests/hermes_cli/test_auth_noninteractive.py` | 10✓ 1✗ |
| `tests/hermes_cli/test_backup.py` | 73✓ 2✗ 10s |
| `tests/agent_runtime/test_tombstone_registry.py` | 1200✓ 2✗ 1s |
| `tests/hermes_cli/test_cmd_update_docker.py` | 1✗ |
| `tests/hermes_cli/test_commit_build_cli.py` | 1✓ 6✗ |
| `tests/hermes_cli/test_commands.py` | 47✓ 1✗ |
| `tests/hermes_cli/test_config_read_guard.py` | 1✓ 1✗ |
| `tests/hermes_cli/test_dep_ensure_noninteractive_spawn.py` | 1e |
| `tests/hermes_cli/test_desktop_startup_cost.py` | 1✗ |
| `tests/hermes_cli/test_doctor_structural_corruption.py` | 1✓ 1✗ |
| `tests/hermes_cli/test_enable_no_capabilities.py` | 6e |
| `tests/hermes_cli/test_fleet_matrix_down_state.py` | 5✓ 2✗ |
| `tests/hermes_cli/test_flag_binding_boundary.py` | 13✓ 2✗ |
| `tests/hermes_cli/test_home_init_soul_symlink.py` | 2✓ 1✗ |
| `tests/hermes_cli/test_install_cua_driver.py` | 16 tests |
| `tests/hermes_cli/test_kanban_block_kinds.py` | 3✓ 1e |
| `tests/hermes_cli/test_kanban_dispatch_claim_allowlist.py` | 3✓ 6e |
| `tests/hermes_cli/test_kanban_dispatch_tick_hook.py` | 2✓ 1e |
| `tests/hermes_cli/test_kanban_memory_guard.py` | 5✓ 6e |
| `tests/hermes_cli/test_kanban_host_cap.py` | 4✓ 9e |
| `tests/hermes_cli/test_kanban_db.py` | 49✓ 1✗ 1s 1e 2xf |
| `tests/hermes_cli/test_kanban_worker_lifecycle_hooks.py` | 2✓ 2e |
| `tests/hermes_cli/test_linux_desktop_entry.py` | 23✓ 4✗ 26s |
| `tests/hermes_cli/test_lazy_secrets_dispatch.py` | 5✓ 1✗ |
| `tests/hermes_cli/test_macos_tcc_anchor.py` | 35 tests |
| `tests/hermes_cli/test_model_switch_openai_api_mode.py` | 4✓ 1✗ |
| `tests/hermes_cli/test_plugin_dependency_consent.py` | 1✓ 3e |
| `tests/hermes_cli/test_plugin_install_manifest_version.py` | 3e |
| `tests/hermes_cli/test_plugin_install_ref.py` | 30e 1xf |
| `tests/hermes_cli/test_plugin_provider_picker_residue.py` | 1✓ 2✗ |
| `tests/hermes_cli/test_plugin_provider_picker_admission.py` | 4✓ 1✗ |
| `tests/hermes_cli/test_plugin_worker_lifecycle.py` | 12e |
| `tests/hermes_cli/test_plugins_admission_setter.py` | 6e |
| `tests/hermes_cli/test_plugin_update_transaction.py` | 16e |
| `tests/hermes_cli/test_plugins_cmd_catalog.py` | 1✓ 11e 1xf |
| `tests/hermes_cli/test_plugins_cmd_enable_disable_nested.py` | 7e |
| `tests/hermes_cli/test_plugins_picker_effective_state.py` | 2e |
| `tests/hermes_cli/test_plugins_update_sync.py` | 6e |
| `tests/hermes_cli/test_plugins_cmd.py` | 41✓ 2s 6e |
| `tests/hermes_cli/test_relaunch.py` | 11✓ 1✗ 3s |
| `tests/hermes_cli/test_serve_runtime_inventory.py` | 12✓ 1e |
| `tests/hermes_cli/test_source_build.py` | 2✓ 1✗ 8s |
| `tests/test_no_frozen_hermes_home.py` | 4✓ 1✗ |
| `tests/scripts/test_upstream_footprint.py` | 6✓ 1✗ |

The seven other boundary gates passed: import layers, module size, thin namespace,
duplicate helpers, CLI contract, payload contract and docket claims. Three office
RPC files also passed; their earlier method-set failures no longer reproduce.

## Incoming main

Candidate `b02479f843` includes main `8110944532`, including parent-process
lifetime and packaged speech changes. The remaining canonical population and
these changed tests are running serially, with Discussion/admission regressions
included again. No second runtime, catalog or scheduler was added.
