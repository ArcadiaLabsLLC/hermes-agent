# Reach census (W0-D) — 2026-09-24, `main` @ `4e73892724`

Instrument: `scripts/refactor_reach_census.py` (plan [`downstream-god-file-refactor.md`](downstream-god-file-refactor.md) §2 Wave 0 W0-D and §4.3; [`god-file-program-2026-09-24.md`](god-file-program-2026-09-24.md) §5). This note is EVIDENCE; the rows it produced live in `Harness_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md`.

- **Population:** every fork production `.py` over 800 raw lines — 62 files (`scripts/god_file_probe.py`'s population).
- **Traced suite:** 653 test files enumerated from the tree (every tracked test naming `agent_runtime`, `hermes_cli.harness`, `harness_parts`, or a population file's module/path), run through `scripts/run_tests.sh` under `coverage` (branch). Not the whole suite: a file only a test OUTSIDE this set reaches reads as cold here.
- **Suite verdict:** exit 1 — 4 tests red, none of them a population file's own test: `tests/agent/test_switch_model_reasoning_override.py`, `tests/agent/test_run_agent.py`, `tests/test_hermetic_env_blanking.py`, `tests/tui_gateway/test_tui_gateway_server_downstream.py` (1 each).
- **Rows:** 106 — 65 cold functions (>= 10 lines, no body line executed; outermost only) and 41 cold arms (>= 10-line `if`/`elif`/`else` arm whose test ran and whose body never did).

**0 hits is not dead.** Field-only paths (Windows-only, service-mode, peer-only) read the same way. The lane owning each file rules each row: delete, field-only (kept, field proof named), or untested live code (kept, test owed) — §4.3.

```
agent/charsheet/pipeline.py:1706-1716 detect_mirrored_art [if @1705] arm 11 lines, 0 hits
agent/charsheet/pipeline.py:1643-1654 detect_mirrored_art [if @1642] arm 12 lines, 0 hits
agent/charsheet/pipeline.py:2098-2138 mirrored_art_error [if @2097] arm 41 lines, 0 hits
agent/charsheet/pipeline.py:2059-2095 mirrored_art_error [if @2058] arm 37 lines, 0 hits
agent/charsheet/pipeline.py:2343-2367 validate_sheet [if @2342] arm 25 lines, 0 hits
agent_runtime/board_store.py:242-272 BoardStore.update_board function 31 lines, 0 hits
agent_runtime/board_store.py:706-721 BoardStore.resolve_conflict [else @701] arm 16 lines, 0 hits
agent_runtime/board_store.py:853-864 BoardStore._rebalance_column function 12 lines, 0 hits
agent_runtime/config.py:811-834 mission_chat_compaction_threshold_tokens function 24 lines, 0 hits
agent_runtime/mission_chat_outcome.py:763-836 _guard_turn_outcome_vocabulary function 74 lines, 0 hits
agent_runtime/mission_chat_turns.py:270-347 _guard_turn_state_vocabulary function 78 lines, 0 hits
agent_runtime/persona_assignments.py:1305-1314 PersonaInstanceStore.repair_missing_chat_session_bindings [if @1304] arm 10 lines, 0 hits
agent_runtime/persona_chat_actor_prewarm.py:670-679 _ensure_worker function 10 lines, 0 hits
agent_runtime/persona_chat_continuity.py:1789-1805 PersonaChatClarifyTicketStore._scan_open_ticket_for_session function 17 lines, 0 hits
agent_runtime/persona_chat_continuity.py:2139-2154 PersonaChatRuntimeRegistry.finish function 16 lines, 0 hits
agent_runtime/persona_runtime.py:878-890 chat_runtime_tool_contract function 13 lines, 0 hits
agent_runtime/profile_runner.py:1317-1326 ProfileAgentRunner._execute_agent_run.interrupt_for_budget [if @1316] arm 10 lines, 0 hits
agent_runtime/profile_runner.py:1581-1596 _emit_agent_ready_callback_warning function 16 lines, 0 hits
agent_runtime/prompt_observability.py:1978-1990 _backfill_derived_fields [if @1977] arm 13 lines, 0 hits
agent_runtime/prompt_observability.py:2917-2944 _skill_realm_sync function 28 lines, 0 hits
agent_runtime/realm_sync.py:1427-1440 sync_artifacts_for_workspace_agent function 14 lines, 0 hits
agent_runtime/repo_context.py:109-119 isolated_repo_context_for_run [if @108] arm 11 lines, 0 hits
agent_runtime/repo_context.py:379-398 existing_run_worktrees function 20 lines, 0 hits
agent_runtime/repo_context.py:484-494 remove_harness_worktree_for_repo function 11 lines, 0 hits
agent_runtime/serve_socket.py:2734-2754 ServeSocketClient.set_timeout function 21 lines, 0 hits
agent_runtime/skill_promotion.py:351-362 classify_promotion [if @350] arm 12 lines, 0 hits
agent_runtime/snapshot.py:2429-2448 _agent_tool_detail function 20 lines, 0 hits
agent_runtime/store.py:354-363 WorkspaceStore.add_agent function 10 lines, 0 hits
agent_runtime/stream.py:1584-1603 stream_frames [if @1583] arm 20 lines, 0 hits
agent_runtime/terminal_envelope.py:443-460 TerminalEnvelopeDecision.explain function 18 lines, 0 hits
agent_runtime/terminal_envelope.py:592-605 resolve_terminal_envelope_grants [if @591] arm 14 lines, 0 hits
hermes_cli/harness.py:2107-2126 _harness_entry function 20 lines, 0 hits
hermes_cli/harness.py:2129-2143 _install_harness_entries function 15 lines, 0 hits
hermes_cli/harness.py:2154-2172 _machine_root_config_paths function 19 lines, 0 hits
hermes_cli/harness.py:2185-2207 _cmd_roots_set function 23 lines, 0 hits
hermes_cli/harness.py:2210-2221 _cmd_roots_unset function 12 lines, 0 hits
hermes_cli/harness.py:2521-2562 _cmd_roots_migrate function 42 lines, 0 hits
hermes_cli/harness.py:2565-2582 _cmd_persona_instance_detail function 18 lines, 0 hits
hermes_cli/harness.py:2585-2607 _cmd_skills_catalog function 23 lines, 0 hits
hermes_cli/harness.py:2806-2816 _cmd_skills_promote [if @2805] arm 11 lines, 0 hits
hermes_cli/harness.py:3302-3324 _cmd_prompt_context_show function 23 lines, 0 hits
hermes_cli/harness.py:3348-3429 _cmd_workspace_create function 82 lines, 0 hits
hermes_cli/harness.py:3432-3461 _cmd_workspace_delete function 30 lines, 0 hits
hermes_cli/harness.py:3474-3487 _known_persona_ids function 14 lines, 0 hits
hermes_cli/harness.py:3501-3518 _cmd_workspace_add_agent function 18 lines, 0 hits
hermes_cli/harness.py:3521-3532 _workspace_agent_sync_warnings function 12 lines, 0 hits
hermes_cli/harness.py:3546-3555 _cmd_workspace_rename function 10 lines, 0 hits
hermes_cli/harness.py:3596-3605 _cmd_realm_bind_server function 10 lines, 0 hits
hermes_cli/harness.py:3668-3683 _cmd_realm_adopt function 16 lines, 0 hits
hermes_cli/harness.py:3795-3805 _cmd_realm_sync_resolve [if @3794] arm 11 lines, 0 hits
hermes_cli/harness.py:4003-4026 _cmd_agent_list [if @4002] arm 24 lines, 0 hits
hermes_cli/harness.py:5837-5855 _cmd_providers function 19 lines, 0 hits
hermes_cli/harness.py:5887-5907 _resolve_active_provider_id function 21 lines, 0 hits
hermes_cli/harness.py:6534-6562 _cmd_skills_inventory function 29 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:365-376 cmd_gateway_pair [if @361] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:546-557 _install_and_certificate [if @545] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:532-543 _install_and_certificate [if @531] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:1524-1535 cmd_gateway_introduce [if @1520] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:2025-2035 cmd_gateway_peers_join [if @2024] arm 11 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:2012-2023 cmd_gateway_peers_join [if @2011] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:1993-2006 cmd_gateway_peers_join [if @1992] arm 14 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:1830-1840 cmd_gateway_peers_join [if @1829] arm 11 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:351-389 _cmd_persona_permission_set function 39 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:411-424 _cmd_persona_assignment_task_id_migration function 14 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:1005-1016 _cmd_persona_instance_open_chat [if @1004] arm 12 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:1018-1033 _cmd_persona_instance_open_chat [elif @1017] arm 16 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:1767-1777 _cmd_persona_chat_delete [if @1766] arm 11 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:1740-1753 _cmd_persona_chat_delete [if @1739] arm 14 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:1938-1948 _cmd_mission_chat_steer [if @1937] arm 11 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:3960-4040 _mission_chat_commit_turn [if @3959] arm 81 lines, 0 hits
hermes_cli/harness_parts/persona_commands.py:5284-5293 _cmd_mission_chat_dispatch_redeliver [if @5283] arm 10 lines, 0 hits
hermes_cli/harness_parts/runtime_commands.py:435-451 _cmd_verify [if @434] arm 17 lines, 0 hits
hermes_cli/harness_parts/serve.py:2352-2380 _prewarm_provider_runtime function 29 lines, 0 hits
hermes_cli/harness_parts/serve.py:2383-2412 _prewarm_persona_chat_actors function 30 lines, 0 hits
hermes_cli/harness_parts/serve.py:5527-5538 serve_loop._handle_message [if @5501] arm 12 lines, 0 hits
hermes_cli/harness_parts/serve.py:5199-5209 serve_loop._handle_message [if @5194] arm 11 lines, 0 hits
hermes_cli/harness_parts/serve.py:6270-6289 _raw_fd_lines function 20 lines, 0 hits
hermes_cli/harness_parts/serve.py:6292-6313 _claim_protocol_pipes function 22 lines, 0 hits
hermes_cli/harness_parts/serve.py:6340-6352 _cmd_serve [if @6334] arm 13 lines, 0 hits
hermes_cli/harness_parts/serve.py:6324-6333 _cmd_serve [if @6323] arm 10 lines, 0 hits
hermes_cli/harness_parts/serve.py:6358-6369 _cmd_serve._wake_reader function 12 lines, 0 hits
hermes_cli/harness_parts/serve.py:6473-6484 _cmd_serve_connect [if @6472] arm 12 lines, 0 hits
scripts/changed_line_mutation_check.py:730-744 _path_matches function 15 lines, 0 hits
scripts/changed_line_mutation_check.py:747-757 _symbol_matches function 11 lines, 0 hits
scripts/changed_line_mutation_check.py:760-804 _claims_for function 45 lines, 0 hits
scripts/changed_line_mutation_check.py:853-866 _refuse_because_locked function 14 lines, 0 hits
scripts/changed_line_mutation_check.py:1073-1146 main function 74 lines, 0 hits
scripts/doc_cite_adjacency.py:888-903 run [if @887] arm 16 lines, 0 hits
scripts/doc_cite_adjacency.py:866-884 run [if @865] arm 19 lines, 0 hits
scripts/run_tests_bundled.py:198-215 changed_paths function 18 lines, 0 hits
scripts/run_tests_bundled.py:649-670 _split_argv function 22 lines, 0 hits
scripts/run_tests_bundled.py:673-744 _print_summary function 72 lines, 0 hits
scripts/run_tests_bundled.py:747-867 main function 121 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:341-356 _sys_modules_identity_is_restored [if @340] arm 16 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:553-568 _node_version function 16 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:571-597 _web_build_prereq_failure function 27 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:633-652 _local_model_probe_failure function 20 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:776-796 _no_posix_mode_bits function 21 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:829-854 _git_name_only_ignores_cr_at_eol function 26 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:860-889 _no_shebang_script_execution function 30 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:892-908 _test_python_outside_project_venv function 17 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:911-922 _unelevated_windows_shell function 12 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:1321-1331 pytest_terminal_summary [if @1320] arm 11 lines, 0 hits
tools/agent_chat_dispatch.py:188-215 _get_executor function 28 lines, 0 hits
tools/agent_chat_dispatch.py:489-503 _kill_child function 15 lines, 0 hits
tools/agent_chat_dispatch.py:1074-1097 dispatch_detached_turn function 24 lines, 0 hits
```

## Re-run 2026-09-25 (lane Q-DEAD-B) — with the static-reach pre-filter (`a8f33b836c`)

Same instrument, traced once on base `13602d97fc` before the lane rebased onto `5e60ed0d1c` (population now 41 files, 657 traced test files, suite exit 1 — 14 red test files, none of them this lane's), then read twice from the one coverage document:

- **Before** (`--no-static-reach`, the unfiltered census): **62 rows** — 40 functions, 22 arms.
- **After** (default): **25 rows filed** — 3 functions, 22 arms — and **36 struck**, each listed with the production reference that reaches it (own-file call, a value passed or tabled, a registration, an import). One function row fewer in total because `chat_runtime_tool_contract` was deleted between the two reads (`48b1b2887d`).
- The 3 function rows left are the honest kind: `existing_run_worktrees` and `remove_harness_worktree_for_repo` (tests-only, DESIGN verdict on their queue rows) and `PersonaChatRuntimeRegistry.finish` (a method; cross-file attribute calls are outside the pre-filter by design).
- Arms are never struck (they are not symbols); rows in a child-process file say so (`serve/`, the MCP servers, any `__main__`-guarded script).

Known gap, filed on arrival in `fork-hygiene-queue.md`: the suite is chosen by substring, so a test that spells `from scripts import <module>` is not traced — `tests/scripts/` reaches `_claims_for` and still read 0 hits.

Filed rows after the filter:

```
agent/charsheet/pipeline.py:1706-1716 detect_mirrored_art [if @1705] arm 11 lines, 0 hits
agent/charsheet/pipeline.py:1643-1654 detect_mirrored_art [if @1642] arm 12 lines, 0 hits
agent/charsheet/pipeline.py:2098-2138 mirrored_art_error [if @2097] arm 41 lines, 0 hits
agent/charsheet/pipeline.py:2059-2095 mirrored_art_error [if @2058] arm 37 lines, 0 hits
agent/charsheet/pipeline.py:2343-2367 validate_sheet [if @2342] arm 25 lines, 0 hits
agent_runtime/persona_chat_continuity.py:2139-2154 PersonaChatRuntimeRegistry.finish function 16 lines, 0 hits
agent_runtime/repo_context.py:109-119 isolated_repo_context_for_run [if @108] arm 11 lines, 0 hits
agent_runtime/repo_context.py:379-398 existing_run_worktrees function 20 lines, 0 hits
agent_runtime/repo_context.py:484-494 remove_harness_worktree_for_repo function 11 lines, 0 hits
agent_runtime/skill_promotion.py:351-362 classify_promotion [if @350] arm 12 lines, 0 hits
agent_runtime/stream.py:1584-1603 stream_frames [if @1583] arm 20 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:365-376 cmd_gateway_pair [if @361] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:546-557 _install_and_certificate [if @545] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:532-543 _install_and_certificate [if @531] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:1524-1535 cmd_gateway_introduce [if @1520] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:2025-2035 cmd_gateway_peers_join [if @2024] arm 11 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:2012-2023 cmd_gateway_peers_join [if @2011] arm 12 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:1993-2006 cmd_gateway_peers_join [if @1992] arm 14 lines, 0 hits
hermes_cli/harness_parts/gateway_commands.py:1830-1840 cmd_gateway_peers_join [if @1829] arm 11 lines, 0 hits
hermes_cli/harness_parts/runtime_commands.py:451-467 _cmd_verify [if @450] arm 17 lines, 0 hits
hermes_cli/harness_parts/serve/handle_message.py:479-490 MessageHandling._join_stream [if @453] arm 12 lines, 0 hits — runs under serve child process (`hermes harness serve`)
scripts/doc_cite_adjacency.py:888-903 run [if @887] arm 16 lines, 0 hits — runs under script entry (`__main__` guard, run as a process)
scripts/doc_cite_adjacency.py:866-884 run [if @865] arm 19 lines, 0 hits — runs under script entry (`__main__` guard, run as a process)
tests/_downstream/hermes_cli_conftest.py:349-364 _sys_modules_identity_is_restored [if @348] arm 16 lines, 0 hits
tests/_downstream/hermes_cli_conftest.py:1280-1290 pytest_terminal_summary [if @1279] arm 11 lines, 0 hits
```
