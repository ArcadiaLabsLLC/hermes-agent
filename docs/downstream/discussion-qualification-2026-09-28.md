# Discussion qualification — September 28

Status: verification in progress; not a closeout.

## Executed baseline comparison

Candidate `351ff56e1e` ran 70 files: 1,785 passed, 108 failed, 139 error
outcomes, 52 skipped and four expected failures. The runner's headline omits
errors; its exit code was 1. Two additional files refused collection because
their marker registry names deleted tests. Peak process-tree memory was 817 MB.

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
| `tests/hermes_cli/test_install_cua_driver.py` | collection refused: stale markers |
| `tests/hermes_cli/test_kanban_block_kinds.py` | 3✓ 1e |
| `tests/hermes_cli/test_kanban_dispatch_claim_allowlist.py` | 3✓ 6e |
| `tests/hermes_cli/test_kanban_dispatch_tick_hook.py` | 2✓ 1e |
| `tests/hermes_cli/test_kanban_memory_guard.py` | 5✓ 6e |
| `tests/hermes_cli/test_kanban_host_cap.py` | 4✓ 9e |
| `tests/hermes_cli/test_kanban_db.py` | 49✓ 1✗ 1s 1e 2xf |
| `tests/hermes_cli/test_kanban_worker_lifecycle_hooks.py` | 2✓ 2e |
| `tests/hermes_cli/test_linux_desktop_entry.py` | 23✓ 4✗ 26s |
| `tests/hermes_cli/test_lazy_secrets_dispatch.py` | 5✓ 1✗ |
| `tests/hermes_cli/test_macos_tcc_anchor.py` | collection refused: stale markers |
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
lifetime and packaged speech changes. The continuation included Discussion and
admission regressions again. No second runtime, catalog or scheduler was added.

## Host freeze — qualification interrupted

The owner reported a whole-PC freeze and manual restart. The single-worker
continuation completed 27 of 458 files: 376 passed and one expected failure;
there is no terminal runner or guard receipt. The 131 Discussion regressions,
parent-watch tests and changed bundle tests passed before interruption.

Last completed file: `test_source_check.py`, September 28 at 18:32:20 local.
The surviving next-file fixture identifies `test_source_launcher_publication.py`;
its newest test directory is `test_running_source_launcher_can_republish_itself`,
updated at 18:32:35. That test republishes a running native Windows wrapper.
These files match main; neither is changed by Discussion. This establishes the
execution boundary, not causation. Preserve the fixture for investigation.

Windows recorded Kernel-Power 41 at 18:37:42, BugcheckCode 0 and a nonzero
PowerButtonTimestamp, consistent with the reported manual restart. No crash dump
was returned by the inspected standard locations. A concurrent read-only process
query and subsequent shell launches stalled. Neither fact identifies the cause.
The test run remains a possible trigger, not an exonerated workload.

The guard used one worker, a 3 GB process-tree budget, 12 GB free-memory reserve
and 40-minute deadline. Those are sampled user-space checks, not kernel-enforced
containment; no final peak-memory reading survived. Do not rerun this wrapper
test or resume the broad population on the operator desktop blindly. Inspect it
statically, then reproduce in a disposable isolated Windows environment with
process/commit limits and persisted per-file diagnostics. No reproduction or
system-settings change was attempted after the restart. Qualification and joint
landing remain open.

## Contained continuation

The resumed canonical runner excluded the wrapper-publication file and ran one
worker inside a Windows Job with 3 GB commit and 24-process limits. The process
limit was exercised by a control; resource samples were persisted every two
seconds. These bounds are not filesystem isolation or driver-failure protection.

The release-channel fixture reached `update_owning_install`, which started a child
in the primary installation. That child rejected the pytest arguments (exit 2);
it did not execute an update. Both encodings failed. The stale PID-guard file also
refused collection because its marker names a removed test. Neither failure is
classified by rerunning this unsafe boundary on the desktop.

The batch was deliberately stopped after its last completed result showed 152
passes and two failures, plus the collection refusal. The verified runner was
terminated; closing its owning Job reaped descendants. Primary Git remained clean.
No full-population pass is claimed. The remaining broad updater/lifecycle tests
belong in an isolated environment, not another desktop retry. Discussion's 131
native regressions and incoming runtime checks had already passed separately.
