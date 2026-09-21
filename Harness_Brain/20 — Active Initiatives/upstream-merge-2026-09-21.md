---
type: initiative
program: upstream-sync
status: in-progress
blocking: "the merge lane's report; then the validated suite on the candidate; then operator landing"
docs: "docs/agent-runtime-harness/planned/"
tags: [initiative, program/upstream-sync]
---

# upstream-merge-2026-09-21

Bring `main` (56 ahead, 3,002 behind `NousResearch/hermes-agent:main` at `ea0c2b820b`) up to date with one history-preserving merge. Dispatched 2026-09-21 to an Opus lane after the per-file Codex reconciliation branches were deleted ([[0006 — Upstream sync is a real merge, per-file reconciliation retired]]).

> [!warning] Blocking
> The lane's report. Then `scripts/run_tests.sh` on the validated four-directory scope against the exact candidate SHA. The operator lands it fast-forward; nobody else pushes `main`.

## Files

**Worktree:** `X:/Eternia/worktrees/merge-upstream-20260921`, branch `merge/upstream-2026-09-21`, cut from `main` @ `042f58edf8`.
**Measured before dispatch** (`git merge-tree --write-tree main upstream/main`): 40 conflicted files, 51 hunks — 29 production (`agent/` 7, `gateway/` 3, `hermes_cli/` 9, `tools/` 8, `hermes_constants.py`, `scripts/run_tests_parallel.py`) and 11 tests/docs. Worst file: `tests/hermes_cli/test_doctor.py` (3 hunks). Nothing in `agent_runtime/` or `harness_parts/` conflicts.
**Resolution rules given to the lane:** keep both when additive; upstream's version of upstream logic with the fork's addition re-applied; the seams survive (`_downstream_cli`, `_profile_bootstrap`, `_boot_clock`, harness registration, `process_registry.restore_durable_completions`, profile scoping); never drop a fork test; `pyproject`/`uv.lock` = fork pair + new upstream rows.

## Resume

1. Read the lane's report (≤ 30 lines: tip SHA, per-file rule, test counts, reds marked merge-caused vs pre-existing, ≤ 3 open rows).
2. In a landing worktree: `git fetch origin && git checkout merge/upstream-2026-09-21`; run `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/cli tests/state` in the background with a log (≥ 25 min); `scripts/dump_cli_contract.py --check`; `scripts/dump_payload_contract.py --check`.
3. Land: `git push origin merge/upstream-2026-09-21:main` only if fast-forward from `main`; otherwise re-merge `main` into the branch first (never rebase a merge).
4. Update [[Upstream Sync]]'s cursor, delete this note's row in [[fork-hygiene-queue]], remove the worktree, delete the branch.
5. Do not touch the primary checkout's index while landing ([[Known Pitfalls]]).
