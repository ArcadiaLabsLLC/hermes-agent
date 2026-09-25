---
type: queue
program: downstream-refactor
status: open
tags: [queue, program/downstream-refactor, dead-code]
---

# Dead code burn-down — the hermes half

**This is a QUEUE, not evidence.** Every row is one line and a pointer. The census that wrote the first instalment is `docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md` §0.1 (its third instrument) and §5; the per-file reads are the layout sheets under `docs/agent-runtime-harness/planned/god-file-layout-sheets/`. Nothing is restated here — a second copy of a fact is free to disagree with the first. The launcher's queue of the same name (`EterniaLauncher/Launcher_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md`) is the format's origin; this file is the hermes half and holds only fork code (the program's scope rule).

## Why this is listed apart from the domain queues

[[TODO]] files work by the surface it serves. A dead-code deletion serves no surface — it is the execution register of one program (the god-file refactor, cursor in [[Downstream Refactor]]), and split by surface its rows would stop sharing a gate (the tombstone registry, `tests/agent_runtime/test_tombstone_registry.py`), a census, and a definition of done. Each row names the lane that owns the file, and its deletion lands in that lane's DELETE commit (never inside the MOVE, never inside the CHANGE). If this queue ever holds a row that is not a deletion, a test-seam move or a "kept, with reason" verdict, it is misfiled — send it to [[runtime-queue]] or [[fork-hygiene-queue]].

Row grammar: `- [ ] **symbol** · file · lines · class · evidence · lane`. Classes: **DELETE** (no caller anywhere; tombstone row), **TEST SEAM** (production has no caller, tests do — moves to `tests/_downstream/_seams.py` and is deleted from production; tombstone row), **KEEP** (a caller the census cannot see, named; the row closes as a verdict, not a deletion), **DECIDE** (an owner call).

## First instalment — filed 2026-09-24 by lane GOD-D (census over the 62 files; struck: 24 `@method`-registered `serve_rpc` handlers, false positives by construction)

- [ ] **`fingerprint_home_capture`, `iter_fingerprint_paths`, `BUILD_SELF_PERTURBED_CLASSES`, `reset_fingerprint_home`** · `agent_runtime/core_cache/` · 23 + 5 + 5 + 21 · TEST SEAM · the `core-cache-home-capture-timing.md` instrument; 0 production callers, 2–3 test files each · R3 · `reset_fingerprint_home` joined 2026-09-25 (R3 CHANGE): its one production caller `lane.reset_process_state` is itself test/script-only, and `tests/agent_runtime/conftest.py` resets the home around every test through it — a deletion needs that sandbox re-plumbed first, so the row stays a TEST SEAM, not a DELETE
- [ ] **`reset_runtime_resolve_cache`** · `agent_runtime/profile_runner/` · 5 · TEST SEAM · 0 production, 2 tests · R3
- [ ] **`READ_ONLY_ALLOWLIST_PROFILE`** · `agent_runtime/mcp_admission.py` · 1 · TEST SEAM · 09-21 §4.1 row, unchanged · R3
- [ ] **`repo_execution_context_for_task`, `isolated_repo_context_for_run`** · `agent_runtime/repo_context.py` · 27 + 35 · DECIDE · 0 production callers, 4 and 6 test files — either the isolated-worktree entry the task lane will call (then KEEP with the caller named) or a seam the tests kept alive; program §3.2 names `isolated_repo_context_for_run` as the module's seam, so the R4 sheet rules it · R4 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`_split_discovery_roots`** · `scripts/run_tests_parallel.py` · 3 · TEST SEAM · 0 callers in the script, 1 test · S2
- [ ] **`ids_marked`** · `tests/_downstream/id_markers.py` · 6 · TEST SEAM (already under `tests/`; the row is that nothing in the hooks reads it — delete or make a hook read it) · T2
- [ ] **`_default_session_db`** · `agent_runtime/persona_chat_history/history_rows.py` 91-100 · 10 · DELETE (sheet persona_chat_history.md §5) once `agent_runtime/persona_assignments` (scan.py, R1's CHANGE) stops importing it: lane R2's CHANGE retargeted every package-internal reader to `chat_session_scope.open_chat_session_db`, so R1's lazy import is its last reader · R2
- [ ] **`chat_live_log_failures`** · `agent_runtime/chat_live_log/files.py` · 5 · DECIDE · 0 production readers, 1 test; the "counted" half of the mirror's best-effort contract (the package docstring) — KEEP as the operator-visible tally (default) or delete with that sentence · evidence: `god-file-layout-sheets/chat_live_log.md` §7 · filed by lane 2B-B 2026-09-25 **TAKEN 2026-09-25 lane Q-DEAD-B**

## Second instalment — the reach census (W0-D), filed 2026-09-24 by lane W0

106 rows, one per cold function or cold arm; evidence note `docs/agent-runtime-harness/planned/downstream-god-file-refactor-reach-census.md` (population, traced suite, the 4 unrelated reds). Class DECIDE until the owning lane rules it (§4.3 of the 09-21 plan); a DELETE ruling lands under "Working a slice".

- [ ] **`detect_mirrored_art [if @1705]`** · `agent/charsheet/pipeline.py` 1706-1716 · 11 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:1706-1716 detect_mirrored_art [if @1705] arm 11 lines, 0 hits` · C1
- [ ] **`detect_mirrored_art [if @1642]`** · `agent/charsheet/pipeline.py` 1643-1654 · 12 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:1643-1654 detect_mirrored_art [if @1642] arm 12 lines, 0 hits` · C1
- [ ] **`mirrored_art_error [if @2097]`** · `agent/charsheet/pipeline.py` 2098-2138 · 41 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:2098-2138 mirrored_art_error [if @2097] arm 41 lines, 0 hits` · C1
- [ ] **`mirrored_art_error [if @2058]`** · `agent/charsheet/pipeline.py` 2059-2095 · 37 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:2059-2095 mirrored_art_error [if @2058] arm 37 lines, 0 hits` · C1
- [ ] **`validate_sheet [if @2342]`** · `agent/charsheet/pipeline.py` 2343-2367 · 25 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:2343-2367 validate_sheet [if @2342] arm 25 lines, 0 hits` · C1
- [ ] **`repair_missing_chat_session_bindings [if @260]`** (was `PersonaInstanceStore.…` `[if @1304]`; moved by lane R1, 2026-09-25) · `agent_runtime/persona_assignments/repair.py` 261-270 · 10 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/persona_assignments.py:1305-1314 PersonaInstanceStore.repair_missing_chat_session_bindings [if @1304] arm 10 lines, 0 hits` · R1 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`PersonaChatClarifyTicketStore._scan_open_ticket_for_session`** · `agent_runtime/persona_chat_continuity.py` 1789-1805 · 17 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/persona_chat_continuity.py:1789-1805 PersonaChatClarifyTicketStore._scan_open_ticket_for_session function 17 lines, 0 hits` · R1
- [ ] **`PersonaChatRuntimeRegistry.finish`** · `agent_runtime/persona_chat_continuity.py` 2139-2154 · 16 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/persona_chat_continuity.py:2139-2154 PersonaChatRuntimeRegistry.finish function 16 lines, 0 hits` · R1
- [ ] **`chat_runtime_tool_contract`** · `agent_runtime/persona_runtime.py` 878-890 · 13 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/persona_runtime.py:878-890 chat_runtime_tool_contract function 13 lines, 0 hits` · R2 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`AgentRunExecution.interrupt_for_budget [if hasattr(agent, "interrupt")]`** · `agent_runtime/profile_runner/execute.py` · 10 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/profile_runner/runner.py:724-733 ProfileAgentRunner._execute_agent_run.interrupt_for_budget [if @1316] arm 10 lines, 0 hits` · R3 · re-keyed 2026-09-25 (R3 CHANGE: the closure is a method; the arm is unchanged) **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`_backfill_derived_fields [if @604]`** · `agent_runtime/prompt_observability/context_store.py` 605-617 · 13 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/prompt_observability.py:1978-1990 _backfill_derived_fields [if @1977] arm 13 lines, 0 hits` (re-anchored by lane R2's MOVE, 2026-09-25) · R2 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`_skill_realm_sync`** · `agent_runtime/prompt_observability/skills_context.py` 247-274 · 28 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/prompt_observability.py:2917-2944 _skill_realm_sync function 28 lines, 0 hits` (re-anchored by lane R2's MOVE) · VERDICT 2026-09-25 (sheet prompt_observability.md §5): untested live — `_skill_row` calls it for every shared skill · R2
- [ ] **`isolated_repo_context_for_run [if @108]`** · `agent_runtime/repo_context.py` 109-119 · 11 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/repo_context.py:109-119 isolated_repo_context_for_run [if @108] arm 11 lines, 0 hits` · R4 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`existing_run_worktrees`** · `agent_runtime/repo_context.py` 379-398 · 20 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/repo_context.py:379-398 existing_run_worktrees function 20 lines, 0 hits` · R4 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`remove_harness_worktree_for_repo`** · `agent_runtime/repo_context.py` 484-494 · 11 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/repo_context.py:484-494 remove_harness_worktree_for_repo function 11 lines, 0 hits` · R4 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`classify_promotion [if @350]`** · `agent_runtime/skill_promotion.py` 351-362 · 12 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/skill_promotion.py:351-362 classify_promotion [if @350] arm 12 lines, 0 hits` · R4 **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`stream_frames [if @1583]`** · `agent_runtime/stream.py` 1584-1603 · 20 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/stream.py:1584-1603 stream_frames [if @1583] arm 20 lines, 0 hits` · R3

## Owed censuses (rows arrive when they run)

- [ ] **The argv census (09-21 plan §4.2)** · `fork / refactor` · which `_cmd_*` the launcher still lowers to argv; rows where "method exists, launcher no longer lowers" are deletions with their parser family entry and tests · H1 builder runs it; the launcher-side read is the launcher queue's

## Working a slice

Campaign rule, every deletion: **delete and add the tombstone-registry row in the SAME commit, with the `git grep` proof in the commit body** (`git grep -nw <symbol> -- '*.py'` at the parent commit, pasted, showing only the definition and the tests being deleted with it); **reintroduce the symbol; watch `tests/agent_runtime/test_tombstone_registry.py` go red naming the row; revert; confirm green.** A TEST SEAM row is a deletion from production plus a move under `tests/_downstream/_seams.py`, same proof. Where nothing covers a deletion (a name with a live declaration elsewhere, so a tombstone would fire on correct code), that absence is reported as a finding under "Named absences" below — it is not a reason to delete quietly.

A "dead" verdict computed before a lane's commits is stale. Re-verify each row against the tree at dispatch time with the same grep; the census is a worklist, not a warrant. A deletion never rides a MOVE or a CHANGE commit (program rule 3): it is the lane's own DELETE commit.

## Named absences

(none yet)

## Closing a row

Delete it. When the last row of an instalment closes, the program ledger (`god-file-program-2026-09-24.md` §8) takes the count in the same commit.

## Filed on arrival — 2026-09-25 (owner ruling: no fragmentation)

- [ ] **Fold review of the batch-1 packages against the no-fragmentation rule (floor 100 code lines unless vocabulary/errors/table; no flow across more than three modules)** · `fork / god-file` · 50 of the 193 landed modules are under 100 code lines; the census classifies most as vocabulary, errors, models or tables, which the rule allows, and names nine fold CANDIDATES to read rather than assume: `serve_rpc/{scope,agent,chat}.py` (2–4 functions each), `prompt_observability/{catalog_store,catalog_lookup}.py` (one catalog concept in two files, split to break a cycle), `persona_assignments/{profile,scan}.py`, `profile_runner/{toolsets,mcp_lane,resident_actor,workdir,runtime_resolve}.py` (five runner phases at 37–76 lines), `harness_parts/serve/loop.py` (a 7-line trampoline). Verdict per candidate: FOLD (one MOVE commit, hash proof) or KEEP with the concept named · evidence: `X:/wt/_holds/fragmentation-census-2026-09-25.log` · filed by orchestrator 2026-09-25 **UNCLAIMED**
