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

- [ ] **`backfill_instance_profile_ids`** · `agent_runtime/persona_profile_binding.py` · 138 · DELETE · one-time migration whose field run is in `docs/agent-runtime-harness/08-performance-and-debt-ledger.md`; census: 0 production references outside its file, 1 test file; if R4 finds `harness_doctor --fix` reaches it by string, it becomes KEEP · R4
- [ ] **`fingerprint_home_capture`, `iter_fingerprint_paths`, `BUILD_SELF_PERTURBED_CLASSES`** · `agent_runtime/core_cache.py` · 23 + 5 + 5 · TEST SEAM · the `core-cache-home-capture-timing.md` instrument; 0 production callers, 2–3 test files each · R3
- [ ] **`reset_unreadable_instance_rows`** · `agent_runtime/persona_assignments.py` · 12 · TEST SEAM · 0 production, 1 test · R1
- [ ] **`reset_runtime_resolve_cache`** · `agent_runtime/profile_runner.py` · 5 · TEST SEAM · 0 production, 2 tests · R3
- [ ] **`hud_field`, `volatile_hud_keys`** · `agent_runtime/runtime_hud.py` · 4 + 4 · TEST SEAM · 0 production, 2 tests each · R2
- [ ] **`active_workspace_lifts`** · `agent_runtime/store.py` · 4 · TEST SEAM · 0 production, 1 test · R1
- [ ] **`ORPHAN_ACTOR_REASONS`** · `agent_runtime/harness_doctor.py` · 5 · DECIDE · KEEP if the doctor's report cites its members by string, else TEST SEAM (09-21 plan §4.1 row, unchanged) · R3
- [ ] **`READ_ONLY_ALLOWLIST_PROFILE`** · `agent_runtime/mcp_admission.py` · 1 · TEST SEAM · 09-21 §4.1 row, unchanged · R3
- [ ] **`repo_execution_context_for_task`, `isolated_repo_context_for_run`** · `agent_runtime/repo_context.py` · 27 + 35 · DECIDE · 0 production callers, 4 and 6 test files — either the isolated-worktree entry the task lane will call (then KEEP with the caller named) or a seam the tests kept alive; program §3.2 names `isolated_repo_context_for_run` as the module's seam, so the R4 sheet rules it · R4
- [ ] **`_split_discovery_roots`** · `scripts/run_tests_parallel.py` · 3 · TEST SEAM · 0 callers in the script, 1 test · S2
- [ ] **`ids_marked`** · `tests/_downstream/id_markers.py` · 6 · TEST SEAM (already under `tests/`; the row is that nothing in the hooks reads it — delete or make a hook read it) · T2
- [ ] **`build_parser`** · `hermes_cli/harness.py` 282–283 · 2 · DELETE · pre-plugin entry; the two fork callers (`scripts/dump_cli_contract.py`, `serve.py::_build_harness_parser`) retarget to `populate_parser` in the same commit · evidence: `god-file-layout-sheets/harness.md` §5 · H2
- [ ] **the eight `_cmd_gateway_*` trampolines** · `hermes_cli/harness.py` 2473–2518 · 32 · DELETE · only reader is `set_defaults(func=…)`; the parser points at `gateway_commands.cmd_*`; contract fixture surface unchanged · sheet `harness.md` §5 · H2
- [ ] **`_cmd_persona_instance_archive`** · `hermes_cli/harness_parts/persona_commands.py` 5591–5592 · 2 · DELETE · a shim onto `_cmd_persona_instance_retire`; bound only at `harness.py:1335` · sheet `persona_commands.md` §5 · H3
- [ ] **module-level `_emit_chat_frame` and `_emit_chat_final`** · `hermes_cli/harness_parts/persona_commands.py` 6420–6429 · 8 · TEST SEAM · one production caller for `_emit_chat_final` (2400) and none for the module-level `_emit_chat_frame` beyond three test patches; the emitter METHOD of the same name is the survivor and the pair is renamed in H3's MOVE · sheet `persona_commands.md` §5 · H3
- [ ] **`_persona_chat_fault_injection` and `_maybe_inject_boot_fault`** · `persona_commands.py` 156–161, `serve.py` 1440–1456 · 6 + 17 · DECIDE · env-driven fault seams read by production at boot/turn time (`HERMES_PERSONA_CHAT_FAULT`); one ruling for both: keep as production seams (they are how the field proofs inject faults) or move behind the plugin's test hook · sheets §5 · H3 / H4
- [ ] **`_capture_core_cache_fingerprint_home`** · `hermes_cli/harness.py` 2066–2104 · 39 · KEEP, MOVE · called once from `_harness_entry`; it is the core-cache instrument living in the CLI entry file — R3 takes it into `core_cache/` · sheet `harness.md` §5 · R3

## Owed censuses (rows arrive when they run)

- [ ] **The reach census (09-21 plan W0-D)** · `fork / refactor` · one `coverage` run of the suite restricted to the 62 files; every function ≥ 10 lines and branch arm ≥ 10 lines with zero hits becomes a row here with a class (`delete` / `field-only` / `untested live code`) · Wave 0
- [ ] **The argv census (09-21 plan §4.2)** · `fork / refactor` · which `_cmd_*` the launcher still lowers to argv; rows where "method exists, launcher no longer lowers" are deletions with their parser family entry and tests · H1 builder runs it; the launcher-side read is the launcher queue's

## Working a slice

Campaign rule, every deletion: **delete and add the tombstone-registry row in the SAME commit, with the `git grep` proof in the commit body** (`git grep -nw <symbol> -- '*.py'` at the parent commit, pasted, showing only the definition and the tests being deleted with it); **reintroduce the symbol; watch `tests/agent_runtime/test_tombstone_registry.py` go red naming the row; revert; confirm green.** A TEST SEAM row is a deletion from production plus a move under `tests/_downstream/_seams.py`, same proof. Where nothing covers a deletion (a name with a live declaration elsewhere, so a tombstone would fire on correct code), that absence is reported as a finding under "Named absences" below — it is not a reason to delete quietly.

A "dead" verdict computed before a lane's commits is stale. Re-verify each row against the tree at dispatch time with the same grep; the census is a worklist, not a warrant. A deletion never rides a MOVE or a CHANGE commit (program rule 3): it is the lane's own DELETE commit.

## Named absences

(none yet)

## Closing a row

Delete it. When the last row of an instalment closes, the program ledger (`god-file-program-2026-09-24.md` §8) takes the count in the same commit.
