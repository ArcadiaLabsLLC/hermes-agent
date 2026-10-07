# Carried upstream PR refresh — 2026-10-07

Job 1, branch `sync/carried-prs`, starts from fork main
`9dc57e199d7ce0353d804b7026d6a56901427c98`. This prepares a branch for operator
landing; it does not land main or perform Jobs 2–3.

The reviewed current PR heads, fetched ref names, per-file comparisons and explicit
exceptions are recorded in [`tests/fixtures/carried_prs.json`](../../../tests/fixtures/carried_prs.json).
Each `reviewed_head` is a full commit SHA; an advanced fetched head requires a new
review. The footprint ledger identifies independently retained fork behavior.
Existing upstream files were refreshed by reviewed PR changes, not replaced with
whole newer upstream files. Behavior changes and pure moves have separate commits.

## Refreshed and already matching PRs

The checker finds drift on pinned main for **21 PRs** whose reviewed selections
match after this refresh (including comment-only refreshes):

`121224`, `121226`, `121640`, `121642`, `121645`, `123890`, `123891`, `123892`,
`124210`, `125259`, `125260`, `125263`, `125264`, `125265`, `128648`, `128650`,
`128651`, `128843`, `129412`, `129582`, `131905`.

Reviewed selections already match for **12 PRs**:

`119069`, `121219`, `121643`, `125261`, `125262`, `128652`, `128653`, `128654`,
`128840`, `128841`, `129413`, `129414`.

These lists describe checked selections, not adoption of every change in each PR.
Five PRs also have deferred surfaces: `121643`, `121645`, `124210`, `128843`, `129413`.

## Deferred surfaces

**41 ledger/file pairs across 25 PRs are not verified by the drift comparison.**
The manifest gives each pair's exact reason; the checker prints it as `SKIP`.

| Reason | PRs |
|---|---|
| Future generic hooks or public-name widening, not copied into the fork; independent fork implementation/private-reader seam remains | `87515`, `114578`, `123977`, `123978`, `123979`, `124190`, `124193`, `124194`, `124195`, `129695`, `129700`, `129702`, `129704`, `131902`, `131903`, `131904` |
| Redesigned skills PR depends on upstream tiered roots/catalog absent from fork; public-reader widening also unadopted | `124191`, `129698` |
| Current PR targets a newer generated-cache loop absent from fork; existing comprehension already uses `.as_posix()` | `121643` (credential files only) |
| Generic native-row/runtime hooks are not adopted; direct fork projectors/environment implementation remain | `124210` (persistence and MCP surfaces only) |
| Ledger caller hunks are explicitly follow-ups outside the PR's current patch | `128843` (dispatch helper and MCP startup only) |
| Independently adapted implementation prevents exact byte comparison: root-only LF policy, path-identity delegation, or relaunch recovery/ABI/phone behavior | `78571`, `121645` (write guards only), `129413` (bootstrap only) |
| Current PR has no delta for the recorded test path; stale attribution retained explicitly for review | `121225` |

PR `121646` is closed and no longer belongs to the open-PR checker inventory.
**Job 1 does not remove Tirith.** Its approved retirement belongs to Job 3.

## Checker evidence and limits

Using the same reviewed manifest and current ledger, the pinned-main comparison
reports **34 drift, 0 errors**; the refreshed working tree reports **0 drift, 0
errors**. Both cover **106 distinct PR/file pairs: 65 checked and 41 deferred**.
The 65 checked pairs comprise **42 full reverse-patch checks** and **23 partial
addition-fragment checks**. The count deduplicates repeated ledger references.

Run `python scripts/check_carried_prs.py` after fetching the manifest's refs;
`--fork-ref 9dc57e199d7ce0353d804b7026d6a56901427c98` reproduces the baseline
comparison with this manifest. Missing classifications/refs or changed reviewed
heads are errors; a missing expected fork file is drift. Tests include planting
an altered carried hunk and requiring drift exit status 1.

A zero exit status means **no detected drift in reviewed selections**, not that
all upstream PRs have been adopted. Fragment checks validate exact lines against
current PR additions before comparing the fork; reviewed helper-name mappings
and relocated files are explicit. They do not verify removed/unselected lines,
function placement, or behavioral equivalence. Deferred surfaces remain
unverified by this checker and require their recorded review and applicable
behavioral tests. The command is offline: it does not discover or fetch newer
remote heads itself.

## Tests and baseline evidence

The [exact selections and comparisons](carried-pr-sync-2026-10-07-tests.json)
record **1,555 distinct files** invoked through `scripts/run_tests.sh`, never a
bare/default/full-tree selection. Each invocation validated nonempty explicit
files and freeze-risk exclusions, used isolated homes and immutable logs, and
bounded each file to 180 seconds and its enclosing process group to 30 minutes.
Python was 3.14.7. Initial optional-dependency errors were retried after installing
the repository versions; later installer retries used runbook uv 0.12.3.

Latest per-file outcomes, deduplicating retries: **20,995 passed, 91 failed,
141 errors, 344 skipped, 17 xfailed**. Two successful files lacked parsed
individual outcome counts; those outcomes are not guessed or included in these
totals. Off-host and opt-in skips do not establish Windows/macOS/live coverage.

**44 red files have every reported failure/error ID reproduced on pinned main
(224 distinct IDs); seven timeout-bound files remain unverified.** The baseline
comparison ran 64 distinct explicit files. Counts of error outcomes and unique
IDs differ because collection/fixture errors can represent multiple outcomes.
This is not a green-suite claim. Installer, sandbox/home-path and dependency
failures remain coverage limits even where the same failure reproduces on main.
After all first-pass files completed, automatic serial timeout retries were
stopped; no successful result is claimed for those files.

Confirmed refresh issues repaired and rechecked:

- Readonly config warmup suppressed later writable backups: both original tests
  passed on main and failed after the refresh. Cache promotion now preserves
  backups without readonly writes; **34 config files, 347 passed, four skipped**.
- Quoted Windows media paths followed by literal escaped newlines were rejected:
  the original fork test passed on main. Quoted termination is restored while
  keeping bare-path hardening. **30 media files, 285 passed, three baseline-matched
  Slack failures, one skipped**; all five fork platform-base and ten PR hardening
  cases passed.
- The copied lock-sweep test intercepted psutil's legitimate POSIX signal-zero
  internals. Its portable public-API check and live-guard setup-cost tests passed
  **four cases**; production remains the PR's `pid_exists` implementation.
- Two fork warning assertions expected old wording. They now require the PR's
  explicit local commits, branches, uncommitted work and no-backup warning;
  **15 uninstall files, 74 passed, four skipped**.

The checker regression file passed **18 tests**, including an altered carried
hunk producing exit 1, missing refs, advanced heads, empty coverage and explicit
deferrals. The new runner retry regression passed; its file's existing grandchild
cleanup failure also reproduces on main. Final undefined-name checks passed for
all **69 changed Python files**; no obsolete `config.config_switch` imports remain.

### Remaining baseline-matched red files

| File | Latest parsed outcomes | Baseline comparison |
|---|---|---|
| `tests/agent/lsp/test_broken_set.py` | 4✓ 1✗, 5.8s | All 1 reported IDs reproduce |
| `tests/agent/lsp/test_install_and_lint_fixes.py` | 2✓ 1✗, 5.8s | All 1 reported IDs reproduce |
| `tests/agent/test_auxiliary_client.py` | 218✓ 1✗, 111.2s | All 1 reported IDs reproduce |
| `tests/agent/test_prompt_builder.py` | 51✓ 2✗ 1xf, 7.1s | All 2 reported IDs reproduce |
| `tests/agent/test_run_agent_codex_responses_downstream.py` | 4✓ 4✗, 20.0s | All 4 reported IDs reproduce |
| `tests/agent/test_shell_hooks_tree_kill.py` | 5✓ 1✗, 10.3s | All 1 reported IDs reproduce |
| `tests/agent/test_treekill_consolidation.py` | 3✓ 1✗, 11.0s | All 1 reported IDs reproduce |
| `tests/agent/test_verification_evidence.py` | 16✓ 12✗, 9.3s | All 12 reported IDs reproduce |
| `tests/agent/test_vision_routing.py` | 8✓ 1✗, 17.1s | All 1 reported IDs reproduce |
| `tests/agent_runtime/test_serve_rpc_provider.py` | 22✓ 1✗, 11.2s | All 1 reported IDs reproduce |
| `tests/docker/test_immutable_install.py` | 3e, 1.8s | All 3 reported IDs reproduce |
| `tests/docker/test_tui_prebuilt_bundle.py` | 3e, 2.0s | All 3 reported IDs reproduce |
| `tests/gateway/test_media_download_retry.py` | 8✓ 3✗, 16.9s | All 3 reported IDs reproduce |
| `tests/gateway/test_process_home_ignores_override.py` | 3✓ 3✗, 6.5s | All 3 reported IDs reproduce |
| `tests/hermes_cli/test_anon_surfaces.py` | 5✓ 1✗, 14.0s | All 1 reported IDs reproduce |
| `tests/hermes_cli/test_auth_codex_self_heal.py` | 4✓ 1✗, 13.7s | All 1 reported IDs reproduce |
| `tests/hermes_cli/test_custom_provider_extra_headers.py` | 11✓ 1✗, 7.7s | All 1 reported IDs reproduce |
| `tests/hermes_cli/test_gateway_spawn_fence.py` | 37✓ 1✗, 7.2s | All 1 reported IDs reproduce |
| `tests/hermes_cli/test_home_directory_diagnostics.py` | 2✓ 15✗, 7.2s | All 15 reported IDs reproduce |
| `tests/hermes_cli/test_isolated_serve_ledger_marker.py` | 1✗, 7.1s | All 1 reported IDs reproduce |
| `tests/hermes_cli/test_plugin_install_manifest_version.py` | 3e, 35.0s | All 3 reported IDs reproduce |
| `tests/hermes_cli/test_plugin_install_ref.py` | 31e, 33.9s | All 31 reported IDs reproduce |
| `tests/hermes_cli/test_plugin_update_transaction.py` | 16e, 8.8s | All 16 reported IDs reproduce |
| `tests/hermes_cli/test_plugin_worker_lifecycle.py` | 12e, 27.2s | All 12 reported IDs reproduce |
| `tests/hermes_cli/test_plugins_admission_setter.py` | 6e, 34.4s | All 6 reported IDs reproduce |
| `tests/hermes_cli/test_plugins_cmd.py` | 41✓ 8e, 45.5s | All 8 reported IDs reproduce |
| `tests/hermes_cli/test_plugins_cmd_catalog.py` | 1✓ 13e, 34.9s | All 13 reported IDs reproduce |
| `tests/hermes_cli/test_plugins_cmd_enable_disable_nested.py` | 7e, 27.0s | All 7 reported IDs reproduce |
| `tests/hermes_cli/test_plugins_picker_effective_state.py` | 2e, 30.5s | All 2 reported IDs reproduce |
| `tests/hermes_cli/test_profile_export_default_path.py` | 2✓ 7✗, 5.3s | All 7 reported IDs reproduce |
| `tests/hermes_cli/test_update_finish.py` | 3✓ 8✗ 2s, 72.8s | All 8 reported IDs reproduce |
| `tests/hermes_cli/test_update_wedged_gateway.py` | 25✓ 6✗, 21.8s | All 6 reported IDs reproduce |
| `tests/hermes_cli/test_worktree_selfheal.py` | 7✓ 1✗, 11.3s | All 1 reported IDs reproduce |
| `tests/pm/test_cold_runtime_e2e.py` | 1✗ 1s, 25.7s | All 1 reported IDs reproduce |
| `tests/pm/test_plugin_survival_contract.py` | 7✓ 2✗, 100.3s | All 2 reported IDs reproduce |
| `tests/pm/test_worker_publication.py` | 1✓ 37e, 30.9s | All 29 reported IDs reproduce |
| `tests/scripts/test_run_tests_parallel.py` | 21✓ 1✗ 1s, 51.7s | All 1 reported IDs reproduce |
| `tests/tools/test_browser_use_harness.py` | 1✓ 1✗, 7.7s | All 1 reported IDs reproduce |
| `tests/tools/test_mcp_stability.py` | 12✓ 2✗, 21.0s | All 2 reported IDs reproduce |
| `tests/tools/test_modal_sandbox_fixes.py` | 26✓ 1✗, 6.5s | All 1 reported IDs reproduce |
| `tests/tools/test_web_keyless_fallback.py` | 47✓ 2✗, 12.4s | All 2 reported IDs reproduce |
| `tests/tui_gateway/test_profiles_describe_secret_scope.py` | 1✗, 7.5s | All 1 reported IDs reproduce |
| `tests/tui_gateway/test_projects_rpc.py` | 25✓ 2✗, 11.6s | All 2 reported IDs reproduce |
| `tests/tui_gateway/test_tui_gateway_server.py` | 653✓ 5✗, 91.5s | All 5 reported IDs reproduce |

### Timeout-bound coverage (unverified)

- `tests/agent/test_compression_rotation_state.py` — 39 tests, 180.0s.
- `tests/agent/test_context_compressor.py` — 130 tests, 180.0s.
- `tests/agent/test_run_agent.py` — 248 tests, 180.1s.
- `tests/e2e/core/kanban/test_kanban_decompose_billing.py` — 3 tests, 180.1s.
- `tests/hermes_cli/test_model_switch_custom_providers.py` — 70 tests, 180.0s.
- `tests/hermes_cli/test_model_validation.py` — 56 tests, 180.0s.
- `tests/hermes_cli/test_web_server.py` — 186 tests, 180.2s.

### Safety exclusions

- `tests/agent/test_turn_liveness_watchdog.py`
- `tests/gateway/test_loop_liveness_watchdog.py`
- `tests/gateway/test_session_stall_watchdog.py`
- `tests/gateway/test_shutdown_watchdog.py`
- `tests/gateway/test_startup_watchdog.py`
- `tests/hermes_cli/test_source_build.py`
- `tests/hermes_cli/test_source_channel_integration.py`
- `tests/hermes_cli/test_source_check.py`
- `tests/hermes_cli/test_source_launcher_publication.py`
- `tests/hermes_cli/test_source_release_channels.py`
- `tests/scripts/test_source_update_command.py`

No P0/watchdog/VM lane was run. No main push, force push, rebase, amend, PR action
or GitHub comment occurred. The branch is prepared for operator review; it has
not landed. Jobs 2–3 and Tirith retirement were not performed here.
