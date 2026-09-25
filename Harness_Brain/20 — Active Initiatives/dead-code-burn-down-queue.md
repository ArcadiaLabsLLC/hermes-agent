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
- [ ] **`repo_execution_context_for_task`, `isolated_repo_context_for_run`** · `agent_runtime/repo_context.py` · 27 + 35 · DECIDE · 0 production callers, 4 and 6 test files — either the isolated-worktree entry the task lane will call (then KEEP with the caller named) or a seam the tests kept alive; program §3.2 names `isolated_repo_context_for_run` as the module's seam, so the R4 sheet rules it · R4 · VERDICT 2026-09-25 (lane Q-DEAD-B): DESIGN — 0 production callers of the run-worktree CREATOR (these two, `existing_run_worktrees`, `remove_harness_worktree_for_repo`); the delivery-directive janitor suite builds real worktrees through it and S43/S54 pinned it KEEP (`test_s54_individual_dead_symbols.test_the_repo_context_worktree_lane_was_NOT_cut`). Recommended: TEST SEAM as ONE unit at R4's repo_context split (the creator plus its exclusive private chain to `tests/_downstream/_seams.py`, the reaper stays), inverting the S54 pin — an owner call because it reverses an operator-ruled KEEP **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`_split_discovery_roots`** · `scripts/run_tests_parallel.py` · 3 · TEST SEAM · 0 callers in the script, 1 test · S2
- [ ] **`ids_marked`** · `tests/_downstream/id_markers.py` · 6 · TEST SEAM (already under `tests/`; the row is that nothing in the hooks reads it — delete or make a hook read it) · T2
- [ ] **`_default_session_db`** · `agent_runtime/persona_chat_history/history_rows.py` 91-100 · 10 · DELETE (sheet persona_chat_history.md §5) once `agent_runtime/persona_assignments` (scan.py, R1's CHANGE) stops importing it: lane R2's CHANGE retargeted every package-internal reader to `chat_session_scope.open_chat_session_db`, so R1's lazy import is its last reader · R2

## Second instalment — the reach census (W0-D), filed 2026-09-24 by lane W0

106 rows, one per cold function or cold arm; evidence note `docs/agent-runtime-harness/planned/downstream-god-file-refactor-reach-census.md` (population, traced suite, the 4 unrelated reds). Class DECIDE until the owning lane rules it (§4.3 of the 09-21 plan); a DELETE ruling lands under "Working a slice".

- [ ] **`detect_mirrored_art [if @1705]`** · `agent/charsheet/pipeline.py` 1706-1716 · 11 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:1706-1716 detect_mirrored_art [if @1705] arm 11 lines, 0 hits` · C1 **TAKEN 2026-09-25 lane B1**
- [ ] **`detect_mirrored_art [if @1642]`** · `agent/charsheet/pipeline.py` 1643-1654 · 12 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:1643-1654 detect_mirrored_art [if @1642] arm 12 lines, 0 hits` · C1 **TAKEN 2026-09-25 lane B1**
- [ ] **`mirrored_art_error [if @2097]`** · `agent/charsheet/pipeline.py` 2098-2138 · 41 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:2098-2138 mirrored_art_error [if @2097] arm 41 lines, 0 hits` · C1 **TAKEN 2026-09-25 lane B1**
- [ ] **`mirrored_art_error [if @2058]`** · `agent/charsheet/pipeline.py` 2059-2095 · 37 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:2059-2095 mirrored_art_error [if @2058] arm 37 lines, 0 hits` · C1 **TAKEN 2026-09-25 lane B1**
- [ ] **`validate_sheet [if @2342]`** · `agent/charsheet/pipeline.py` 2343-2367 · 25 · DECIDE (delete / field-only / untested live) · census: `agent/charsheet/pipeline.py:2343-2367 validate_sheet [if @2342] arm 25 lines, 0 hits` · C1 **TAKEN 2026-09-25 lane B1**
- [ ] **`PersonaChatClarifyTicketStore._scan_open_ticket_for_session`** · `agent_runtime/persona_chat_continuity.py` 1789-1805 · 17 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/persona_chat_continuity.py:1789-1805 PersonaChatClarifyTicketStore._scan_open_ticket_for_session function 17 lines, 0 hits` · R1
- [ ] **`PersonaChatRuntimeRegistry.finish`** · `agent_runtime/persona_chat_continuity.py` 2139-2154 · 16 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/persona_chat_continuity.py:2139-2154 PersonaChatRuntimeRegistry.finish function 16 lines, 0 hits` · R1
- [ ] **`_skill_realm_sync`** · `agent_runtime/prompt_observability/skills_context.py` 247-274 · 28 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/prompt_observability.py:2917-2944 _skill_realm_sync function 28 lines, 0 hits` (re-anchored by lane R2's MOVE) · VERDICT 2026-09-25 (sheet prompt_observability.md §5): untested live — `_skill_row` calls it for every shared skill · R2
- [ ] **`isolated_repo_context_for_run [if @108]`** · `agent_runtime/repo_context.py` 109-119 · 11 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/repo_context.py:109-119 isolated_repo_context_for_run [if @108] arm 11 lines, 0 hits` · R4 · VERDICT 2026-09-25 (lane Q-DEAD-B): DESIGN — one unit with the `repo_execution_context_for_task` row above **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`existing_run_worktrees`** · `agent_runtime/repo_context.py` 379-398 · 20 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/repo_context.py:379-398 existing_run_worktrees function 20 lines, 0 hits` · R4 · VERDICT 2026-09-25 (lane Q-DEAD-B): DESIGN — one unit with the `repo_execution_context_for_task` row above **TAKEN 2026-09-25 lane Q-DEAD-B**
- [ ] **`remove_harness_worktree_for_repo`** · `agent_runtime/repo_context.py` 484-494 · 11 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/repo_context.py:484-494 remove_harness_worktree_for_repo function 11 lines, 0 hits` · R4 · VERDICT 2026-09-25 (lane Q-DEAD-B): DESIGN — one unit with the `repo_execution_context_for_task` row above **TAKEN 2026-09-25 lane Q-DEAD-B**
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

## Filed on arrival — 2026-09-25 (lane S3, class row)

- [ ] **three empty `_ENV_GAPS` registries and the mark-only lane behind them (`apply_marks`, `StaleEntryTracker`, `EnvGapRegistry`, `register_marks` + the two marks)** · `fork / suite` · asserted empty by `test_env_gap_registry`; program §9 Q30 default: delete fork-wide — lane B5 deletes the hermes_cli copy, siblings + shared helpers on Q30's word · evidence: program §9 Q30, hermes_cli_conftest.md §5 · filed by lane S3 2026-09-25 **UNCLAIMED**

