---
type: evidence
tags: [evidence, tests, upstream]
---

# Stale fork-test sweep — 2026-10-18 (lane q-stale, branch `q/q-stale`)

Evidence for the fork-hygiene row "Stale fork tests" (classes a–h). Pinned tag: v0.22.2
(`d923a5eb48`, the upstream manifest's base); previous merged release `71d34bad10`
(v0.21.7); fork point `110baa095b` (newest first-parent commit of `main` inside the tag).

**Population:** `git ls-tree -r --name-only v0.22.2 tests` against HEAD `c31397c492`:
1,128 fork `tests/**/test_*.py` files. A file not named below showed no class signal
(no skip construct, no missing name, no removed-feature, archive or twin hit) and is kept.

## How each class was found

| class | method | candidates |
|---|---|---|
| a every test skips | static pre-filter (a skip/xfail/importorskip construct, or a fork file named in `tests/_downstream/id_markers/`), then those files run with junit output | 175 |
| b names that no longer exist | AST: imports and `patch`/`setattr`/`patch.object` targets resolved statically, then confirmed by import + `hasattr` | 13 names |
| c removed / unused features | keyword hits (mission lane, kanban, `--scope full`), then read | 29 + 32 |
| d campaign censuses | every `test_sNN_*` / `test_stageNN_*` file read against `test_tombstone_registry.py` | 46 |
| e split duplicates | identical test bodies across files (AST hash) | 4 pairs |
| f archived-plan spec | tests citing `docs/agent-runtime-harness/archive/`, then read | 32 |

## Deleted (one commit per class)

- (b) fixed in place, `3667057ff3`: `test_snapshot_demote_deferral::test_a_prewarm_that_stood_DOWN…` was vacuous (passed on `registry_off`); two dead `raising=False` patches dropped.
- (c) `ab4ef1e7f6`: `test_stage38_fixtures.py` + `tests/fixtures/mission_control/stage38/` (goal-create wire, mission lane removed).
- (d) `93fa394a3e`: `test_stage52_role_envelopes.py` (registry s5 row), `test_mission_goal.py` (new s-q-stale MODULE row).
- (e) `e42eefaa64`: `test_stage19_visibility.py` (twin of `test_s9_snapshot_read_model`).

## Kept, with the verdict

- **Kanban (c-unused, ADR 0015)** — `tests/hermes_cli/test_kanban_blocked_pm_hook.py`, `test_kanban_blocked_pm_tick.py`, `test_kanban_db_crashed_workers_downstream.py`, `test_kanban_db_downstream.py`, `test_kanban_write_guard_downstream.py`: they test fork-owned code the eternia-harness plugin still registers at boot (`route_blocked_kanban_cards`, `record_kanban_crash_evidence`), so the code is live; it and its tests leave together (runtime-queue § Fork-owned row). `tests/cron/test_cron_kanban_env_isolation_downstream.py` keeps: two of its three tests cover the live `process_env_defaults`.
- **Mission-lane absence stubs without a registry row** — `test_dirty_state.py`, `test_runtime_instances.py` (`agent_runtime.goal_hygiene`, `persona_diagnostics`), `test_stage12_freshness.py` (`blueprints.store`): kept until those names get MODULE rows; then the stubs can go (four `goal_hygiene` copies in `test_runtime_instances.py`).
- **Other `test_sNN_*` files (43)** — each holds a live pin, a parser/parameter/frame absence the registry cannot express, or is a gate in `11-gate-directory.md`.
- **Archive citers (32)** — every one tests live code; the archived doc is history, not the only spec. None is f.
- **Body twins** — `test_s43/test_s54 ::test_the_live_neighbours_survive` (same body, disjoint parametrize tables); the two contract-dump `…committed_dump_is_missing` tests (different dumps); `test_chat_lane_drop_accounting`/`test_mcp_lane_visibility` (same assertion shape on different producers).
- **Class (a)** — see below.

## Class (a): run results

175 candidate files, run 2026-10-18 in 22 chunks of 8 (`pytest -q -p no:cacheprovider --junitxml`).
Two skipped every test: `tests/scripts/test_mutation_cap_matches_workflow.py`
(`importorskip("yaml")`; the test venv has no PyYAML) — fixed to read through `yaml_io`,
`749c085788`; `tests/agent/test_pet_generate_downstream.py` (18 skipped) — opt-in by design
(`HERMES_RUN_SLOW_PET_TESTS=1`), kept. One red in the run,
`test_discussion_group_compute.py::test_compute_question_lost_answer_ack_and_confirmed_stop`,
was green alone (box under five test processes); not filed.

## Production side (g, h) — `scripts/upstream_retirement_scan.py`

| arm | findings | outcome |
|---|---|---|
| imports (gated, `tests/tooling/test_upstream_retirement_scan.py`) | 3 at the base: `auth_noninteractive` imported upstream's inlined `_api_key_default_label` (custom-pool `set-key` raised ImportError); `windows_env` imported a `hermes_logging.log_warn` that never existed (PATH-write failures silent); one dead test patch | fixed `fb01a81fca`; gate green |
| hunks | 15 fork hunks inside upstream functions v0.22.2 rewrote (`agent/agent_init.py::init_agent`, `tools/tool_search.py` ×3, `tools/connectors/search.py` ×3, `tui_gateway/*` ×5, `hermes_cli/runtime_provider_custom.py`, `pm/environment.py`, `tools/environments/local.py`) | re-read by lane w2-seams: 15 still correct, 0 re-seat, 0 delete (below) |
| twins | 2 identical bodies: `agent_runtime/file_locks.py::unlock_fd` = upstream `hermes_cli/local_runtime/bootstrap.py::_unlock_boot_fd`; `agent_runtime/skill_resolution.py::_is_package_owned_markdown` = `tools/skills_tool.py::_is_package_owned_markdown` | kept: both upstream twins are `_private` (the layers gate bans the import); adopt only through a widening |
| carried | 0: no carried-PR hunk is contained in the tag | — |
| (g) test-only production functions | not re-censused here: the deletions above freed no production symbol (the stubs asserted absences), and the reach census (`dead-code-burn-down-queue.md`) owns the population | — |

Found by a `git log -G` variant of arm imports and dropped by the shipped one: `hermes_cli/gateway.py`
re-exports `_detect_venv_dir` from `hermes_cli/gateway_downstream.py`, a name upstream retired
before the fork point; `tests/hermes_cli/test_gateway_launcher_managed_python.py` patches it there.
The gateway-as-a-service is ADR 0015 unused; no row (the seam goes when that service code does).

## Hunks arm re-read (lane w2-seams, 2026-10-18)

Each hunk read against its v0.22.2 body (`d923a5eb48`, the release `main` carries) and against
`upstream/main` `9e01b44dd2`. Verdict: all 15 still correct and still placed right; no re-seat,
no delete, no hook upstream offers yet.

| hunk | v0.22.2 body | upstream/main `9e01b44dd2` |
|---|---|---|
| `agent/agent_init.py::init_agent` (init-timing marks) | marks sit after the phase they name | a `safe_worker_enabled()` prelude lands above `_install_safe_stdio`; the first mark stays first |
| `hermes_cli/runtime_provider_custom.py::_match_new_style_provider` (`_key_env_secret` → `provider_secret`) | still after identity/endpoint validation | returns `(result, ep_name)`; the key line is unchanged |
| `pm/environment.py::PythonEnvironment.sync` (uv sharing-violation retry) | before the bytecode-compile retry | unchanged |
| `tools/connectors/search.py` ×3 (lazy bridge imports) | every `NOT_SET_UP`/`SIGN_IN_EXPIRED`/`UNREACHABLE` use is covered | unchanged |
| `tools/environments/local.py::_make_run_env` (Windows system PATH) | wraps the PATH fixer | the env tuple gains `toolchain_environ(...)` on the line above: a textual neighbour, no semantic clash |
| `tools/tool_search.py` ×3 (`_search_description` text, hit parameters, direct describe) | the text describes the fork's `attach_hit_parameters` | unchanged |
| `tui_gateway/compute_host.py::_handle_respond` (pre-registration answers) | `resolve_response(..., session_id=sid)` still verifies the owner | unchanged |
| `tui_gateway/methods_session_interrupt.py`, `session_auto_continue.py` | guards precede upstream's first effect | unchanged |
| `tui_gateway/prompt_turn.py::_prepare_turn_input` (app-function scope) | bound and released in `_release_turn_scopes` | `_persisted_turn_receipt` moved to `agent.persisted_turn_receipt`; no fork hunk there |
| `tui_gateway/server.py::_make_agent` (`create_agent`) | wraps the one `AIAgent(` call | **moves**: `_make_agent`, `_resolve_session_source`, `_TOOL_LIFECYCLE_UI_TOOLS` to `tui_gateway/agent_factory.py`; `_start_agent_build`, `_init_session`, `_deferred_session_record`, `_schedule_agent_build`, `_fallback_session_info` to `tui_gateway/session_registry.py`. upstream still never defines `_sanitize_client_source` and `_fallback_session_info` still drops its session; both fork hunks stay needed |

The next release merge re-seats the `server.py` hunks into those two modules
(`FORK-SUPERSESSION-PASS-V0216` owns the pass).
