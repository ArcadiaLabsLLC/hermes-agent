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

- [ ] **`reset_fingerprint_home`** · `agent_runtime/core_cache/home.py` · 21 · TEST SEAM · R3 (2026-09-25 CHANGE): its one production caller `lane.reset_process_state` is itself test/script-only, and `tests/agent_runtime/conftest.py` resets the home around every test through it — a deletion needs that sandbox re-plumbed first, so the row stays a TEST SEAM, not a DELETE **TAKEN 2026-09-29 h10-fhrel** · VERDICT 2026-09-29 h10-fhrel: its three row-mates (`fingerprint_home_capture` + its `FingerprintHomeCapture`, `iter_fingerprint_paths`, `BUILD_SELF_PERTURBED_CLASSES`) moved to `tests/_downstream/_seams.py` with a tombstone; this one stays until `lane.reset_process_state`'s callers are re-plumbed — owed: move `reset_process_state` and this reset together to the seam, retargeting `tests/agent_runtime/conftest.py` and the scripts that call it, as one TEST SEAM change
- [ ] **`READ_ONLY_ALLOWLIST_PROFILE`** · `agent_runtime/mcp_admission/vocabulary.py` · 1 · TEST SEAM · 09-21 §4.1 row, unchanged · R3 · VERDICT 2026-09-25 lane B4: TEST SEAM confirmed — `git grep -n READ_ONLY_ALLOWLIST_PROFILE -- agent_runtime hermes_cli tools plugins` = the def + the package re-export, 0 readers; 6 reads in `tests/agent_runtime/test_mcp_admission_r2.py`. Per sheet `mcp_admission.md` §5 the move to `tests/_downstream/_seams.py` (+ tombstone) lands under "Working a slice", not in B4's two commits; claim released

## Second instalment — the reach census (W0-D), filed 2026-09-24 by lane W0

106 rows, one per cold function or cold arm; evidence note `docs/agent-runtime-harness/planned/downstream-god-file-refactor-reach-census.md` (population, traced suite, the 4 unrelated reds). Class DECIDE until the owning lane rules it (§4.3 of the 09-21 plan); a DELETE ruling lands under "Working a slice".

- [ ] **`_skill_realm_sync`** · `agent_runtime/prompt_observability/skills_context.py` 247-274 · 28 · DECIDE (delete / field-only / untested live) · census: `agent_runtime/prompt_observability.py:2917-2944 _skill_realm_sync function 28 lines, 0 hits` (re-anchored by lane R2's MOVE) · VERDICT 2026-09-25 (sheet prompt_observability.md §5): untested live — `_skill_row` calls it for every shared skill · R2

## Owed censuses (rows arrive when they run)

- [ ] **The argv census (09-21 plan §4.2)** · `fork / refactor` · which `_cmd_*` the launcher still lowers to argv; rows where "method exists, launcher no longer lowers" are deletions with their parser family entry and tests · H1 builder runs it; the launcher-side read is the launcher queue's **TAKEN 2026-09-29 h10-fhrel** · VERDICT 2026-09-29 h10-fhrel: the census is two-sided and the hermes half alone cannot rule a deletion: which `_cmd_*` the launcher still lowers to argv is read in `EterniaLauncher` (the launcher queue owns that read), and a "no longer lowered" verdict also needs the operator-CLI and script callers checked. Owed: the H1 builder lane runs both halves at once and files one DELETE row per handler with its parser-family entry and tests

## Working a slice

Campaign rule, every deletion: **delete and add the tombstone-registry row in the SAME commit, with the `git grep` proof in the commit body** (`git grep -nw <symbol> -- '*.py'` at the parent commit, pasted, showing only the definition and the tests being deleted with it); **reintroduce the symbol; watch `tests/agent_runtime/test_tombstone_registry.py` go red naming the row; revert; confirm green.** A TEST SEAM row is a deletion from production plus a move under `tests/_downstream/_seams.py`, same proof. Where nothing covers a deletion (a name with a live declaration elsewhere, so a tombstone would fire on correct code), that absence is reported as a finding under "Named absences" below — it is not a reason to delete quietly.

A "dead" verdict computed before a lane's commits is stale. Re-verify each row against the tree at dispatch time with the same grep; the census is a worklist, not a warrant. A deletion never rides a MOVE or a CHANGE commit (program rule 3): it is the lane's own DELETE commit.

## Named absences

(none yet)

## Closing a row

Delete it. When the last row of an instalment closes, the program ledger (`god-file-program-2026-09-24.md` §8) takes the count in the same commit.

## Filed on arrival — 2026-09-25, lane B3


## Filed on arrival — 2026-09-26, lane ACP-DROP

