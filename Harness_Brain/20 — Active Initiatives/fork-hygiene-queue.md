---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue

The repository AS A FORK: upstream sync and the boundary, CI, the suite and its gates, the god-file refactor, this vault. Runtime and Mission Control rows do NOT go here — they go to `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` (both repos). Rows: one line + a pointer, never a restatement; claim with `**TAKEN <date> <who>**` before starting; a landing deletes its row.

## Filed on arrival — 2026-09-21 (upstream sync assessment)

- [ ] **The fork's CI has not run on `main` since 2026-09-07** · `fork / ci` · `gh run list --branch main` shows only the 09-07 "Publish E2E evidence" runs against 22c5684b98 while pushes landed through 09-18; a merge candidate nobody tests is the deleted sync branch again. Find why `tests-os.yml` / `tests.yml` stopped firing (trigger set? billing? inert workflow — `docs/downstream-development.md` § "Unattended reporting" already calls the fork CI "largely inert") and either fix the trigger or register `scripts/hermes-unattended-suite-task.xml` on this box · evidence: this session's `gh run list` **UNCLAIMED**
- [ ] **Land the 2026-09-21 upstream merge** · `fork / upstream` · branch `merge/upstream-2026-09-21`, worktree `X:/Eternia/worktrees/merge-upstream-20260921`; 40 conflicted files / 51 hunks at dispatch; operator lands fast-forward after the validated suite · evidence: [[Upstream Sync]] cursor **TAKEN 2026-09-21 merge lane**
- [ ] **Retarget the scheduled Codex sync job** · `fork / upstream` · it must produce a tested merge candidate weekly (merge, resolve by the rules in [[Upstream Sync]], `scripts/run_tests.sh` on the validated scope, push `merge/upstream-<date>`, report conflicts + results), never per-file copies; its old branches are deleted and `docs/agent-runtime-harness/planned/upstream-sync-automation.md` on `main` is a stale copy of the retired method — delete it in the commit that lands the retargeted job description · evidence: [[0006 — Upstream sync is a real merge, per-file reconciliation retired]] **UNCLAIMED**
- [ ] **Dispatch Stage 0b + Stage 1 of the harness-plugin plan** · `fork / upstream` · the plan is `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md` (landed 2026-09-21); Stage 0b = the `[up-fp]` ratchet + the disposition ledger, one commit after the merge lands; Stage 1 = the harness registers its CLI through `register_cli_command`, MEASURED against the 500–650 ms plugin-discovery cost before any deletion, fallback = the manifest-declared deferred CLI entry PR · evidence: plan §2 Stage 0–1, [[Upstream Sync]] **UNCLAIMED**
- [ ] **`scripts/upstream_sync_gate.py` — what does it gate, and does anything run it?** · `fork / upstream` · fork-only script found by the boundary census; read before writing the ratchet above · evidence: [[Fork Boundary Map]] **UNCLAIMED**

## Filed on arrival — 2026-09-21 (god-file refactor plan)

- [ ] **Dispatch Wave 0 + S1** · `fork / refactor` · one sitting: the four gates + the reach census, then the `scripts/changed_line_mutation_check.py` split (S1) because every later landing runs it · evidence: plan §2 Wave 0, §3 **UNCLAIMED**
- [ ] **H1 alone: the seven exec'd parts become modules** · `fork / refactor` · the only lane with a trap (263 `harness.<name>` patches; W0-G4 flips from xfail); `scripts/retarget_harness_patches.py` output pasted into the commit · evidence: plan §2 Wave 1 **UNCLAIMED**
- [ ] **`tests/test_docket_stage_claims.py::test_every_stage_that_says_it_shipped_names_a_commit_that_landed_here` is RED on `main`** · `fork / docs-gates` · `duplicate-implementation-retirement.md` claims stages EXECUTED with shas not in this history (the 2026-09-15 reconstruction moved them); pre-existing, not owned by the refactor; fix the doc's shas or its status header · evidence: this session's gate run **UNCLAIMED**
- [ ] **`harness-runtime-model/SKILL.md` over its 16,384-byte ceiling since 2026-09-03** · `fork / skills` · rewritten LAST from the refactor's field notes per the field-notes ruling; until then the ceiling gate is the only reader · evidence: [[Agent Runtime Harness]] **UNCLAIMED**
- [ ] **12 production functions only tests call** · `fork / refactor` · plan §4.1 rows (`backfill_instance_profile_ids` 138 lines is the one real deletion; the rest are test seams to move under `tests/`); each lane applies its row · evidence: plan §4.1 **UNCLAIMED**

## Filed on arrival — 2026-09-21 (brain)

- [ ] **The launcher's brain has no pointer back to this vault** · `fork / brain` · `EterniaLauncher/Launcher_Brain/40 — Cross-Brain/` has Parent / Backend / Website pointers; add `Harness Brain Pointer.md` (relative path from there: `../../../../../Eternia/hermes-agent/Harness_Brain/`) and a line in its Brain Index network tree; the parent `ArcadiaLabs_Brain` index routes to hermes only through two contract notes · evidence: [[Launcher Brain Pointer]] **UNCLAIMED**
- [ ] **Session memory facts that belong here** · `fork / brain` · the operator's Claude session memory (`~/.claude/projects/X--Eternia-hermes-agent/memory/`) holds ~50 project entries; the standing rulings are now ADRs 0001–0011 and the cursors are on the program notes; the remaining per-program detail (queue waves, delete audit, skills realm) graduates on the next touch of each program, not as a sweep · evidence: [[Brain Index]] § source-of-truth routing **UNCLAIMED**
