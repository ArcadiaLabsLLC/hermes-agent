# Verification of the 51 rows lane-1010 returned as "upstream" (2026-10-10, read-only Opus lane)

FF = fork-fixable (route), UO = upstream-only, AH = already handled.

L1.05 · FF · partial: web-search share via L3.06's memo; the other ~41 ms of build_kwargs needs a breakdown before a fix
L2.04 · FF · caller-side memo in agent_runtime/mission_chat_turn_context._default_build_preloaded_skills_prompt keyed on skill-file stat (~30 lines); it skips upstream's usage write, so bump usage itself
L3.03 · FF · additive alias `_sanitize_client_source = _resolve_session_source` in tui_gateway/server.py (1 line, file already carried)
L3.05 · FF · additive owner candidate in pm/environments.owning_home_root, e.g. an env-named root the launcher passes (~4 lines, +1 footprint file)
L3.06 · FF · caller-side door rebinding agent.web_search_registry.get_active_search_provider (codex imports lazily) with a memo keyed on config+credential epoch (~30 lines); cost: stale-credential risk
L3.10 · FF · additive marker on agent before the reasoning.available callback in _relay_thinking (2 lines, carried) + progress.py reader (~10 lines)
L3.11 · FF · plugin llm_request/post_api_request hook logs the effort as a receipt (~10 lines, no upstream edit)
L3.13 · FF · door swaps skill_utils._RAW_CONFIG_CACHE for a bounded-LRU dict whose clear() evicts (~20 lines); low value
L3.16 · FF · additive contextvar set from self.cwd before Popen in local.py._run_bash (1 line, carried) + overlay read; misses an in-command `cd`
L3.17 · FF · fork-only: persona_slots.load_slot_context skips files already on the prompt_builder cwd chain (~20 lines)
L3.18 · FF · additive `elif evt_type == "mcp_job_finished": requeue.append(evt)` in gateway/run.py (2 lines, carried)
L3.19 · FF · fork SQL keyset page over SessionDB's connection replacing `_read_all` (~60 lines); cost: coupled to upstream's schema
L3.22 · FF · over-attach is the fork's own hunk in hermes_cli/main.py; port #128648's argv-only attach into it (~20 lines, no footprint growth)
L4.01 · FF · id-mark the two PM nodes (timeout node as skip); the 4 encoding nodes are green under the runner
L4.03 · FF · plugin rebinds agent.tool_guardrails.IDEMPOTENT_TOOL_NAMES with mcp__filesystem__* names (default_factory reads the global at call time); ~6 lines, zero footprint
L4.04 · FF · additive `if os.name == "nt":` stdout-and-return block at the top of write_tty (~5 lines, +1 file)
L4.06 · FF · additive stat-memo rebind of read_home_selection in pm/plugins_state.py (callers resolve by global name); 2 lines + ~20-line fork helper, +1 file
L4.12 · FF · F821 per-file-ignore for an upstream-owned line (pyproject, carried, 1 line); PR #128657 stays open
L4.14 · FF · lint red only: per-file-ignore (1 line); the latent NameError is upstream-only
L5.05 · FF · fork serve verb: FTS MATCH joined to messages on session_id (~100 lines); cost: duplicates CJK/trigram routing
L5.15 · FF · registry_epoch is a fork addition (absent upstream); delete it + 2 docstrings; footprint shrinks
L6.12 · FF · additive Windows ownership guard in _launchers.expose path (~25 lines, +1 file; verdict option b)
L6.17 · FF · id-marker or unbundled-list entry once a second red is logged
L6.23 · FF · cherry-pick da0ccd09bb/47028bf432 into the carried atlas.py and live_system_guard.py
L7.01 · FF · tests/_downstream fixture unpinning hermes_state.DEFAULT_DB_PATH for the multiplex files, or an unbundled pair (~15 lines)
L7.06 · FF · additive public accessor in tests/conftest.py (carried), 2 fork call sites (~8 lines)
L7.16 · FF · id-marker or unbundled entry (still unreproduced)
L7.19 · FF · test: env-restore fixture in tests/_downstream; product: snapshot/restore env around the reconcile chore in carried gateway/run_profile_reconcile.py (~10 lines)
L7.32 · FF · additive tolerant `process.wait(timeout=60)` try/except before the 5 s wait in pm/client._request (~4 lines, +1 file)
L8.12 · FF · additive `_EXCLUDED_NAMES.add("serve_socket.lock")` in hermes_cli/backup.py (1 line, +1 file)

L3.09 · UO · deletes fork hunks after upstream merges the doors
L4.02 · UO · `_DUMMY_HASH` is a module-scope call; a test-side memo would weaken the auth tests
L4.17 · UO · all three costs are module-scope lines
L7.12 · UO · module-scope `_OPENER` cannot be made lazy additively; stripping SSLKEYLOGFILE was rejected

AH: L1.15 (hold_title_upgrade) · L1.19 (job_wake wrap) · L2.31 (recorded parallels) · L3.01 (fd1e4cfde6) · L3.12 (h-conn-pool drain_settled_stream) · L3.15 (rebound load_config_readonly) · L3.21 (interpreter_abi seam) · L3.24, L3.25 (carried parallels, moved auth transport) · L6.15 (config_switch gates carried) · L6.18 (runner fix e0dafc4e27) · L7.14 (_pid_exists swaps carried) · L7.18 (13 secret_files seams) · L8.02, L8.18, L8.28 (_up_red marks) · L8.30 (strict xfail in fork_marks)
