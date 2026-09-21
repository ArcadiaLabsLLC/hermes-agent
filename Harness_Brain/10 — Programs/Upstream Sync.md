---
type: program
program: upstream-sync
status: active
cursor: "2026-09-21 — main is 3,002 upstream commits behind (merge base c62bd9f207, 2026-09-18); a merge lane is running on branch merge/upstream-2026-09-21 in worktree X:/Eternia/worktrees/merge-upstream-20260921 (40 conflicted files, 51 hunks measured by merge-tree before dispatch). The per-file Codex reconciliation branches were DELETED 2026-09-21 (backup refs kept locally). Next: land the merge, retarget the scheduled Codex job to produce a tested merge candidate weekly, start the seam program."
tags: [program/upstream-sync, program, upstream]
---

# Upstream Sync

Goal (owner, 2026-09-21): **easy upstream syncs without much conflict.** The fork tracks `NousResearch/hermes-agent`, which moves ~850 commits a day. Conflicts come from exactly one place — fork edits inside upstream-owned files where upstream also moves — so the program has two halves: merge often (cadence) and shrink the delta (seams).

> [!info] Cursor
> `cursor::` see frontmatter.

## The state of the boundary (2026-09-21, [[Fork Boundary Map]])

- 1,439 fork-only files: never conflict.
- 449 upstream files carry fork edits (+18,300 / −2,300): 246 are tests (13,700 lines); ~140 production files; 118 files ≤ 5 lines; **22 files > 200 lines** — the heavy tail is the whole problem.
- A trial merge today: 40 conflicted files, 51 hunks, all in the heavy tail. `hermes_constants.py` (+286), `hermes_cli/main.py` (−187 upstream lines replaced), `scripts/run_tests_parallel.py`, the four `conftest.py` files.

## The rulings

- [[0006 — Upstream sync is a real merge, per-file reconciliation retired]] — the scheduled Codex job copied single upstream files ("reconcile X with upstream <sha>", tests NOT RUN) and never advanced the merge base; 6 files in 3 days against 3,000 commits. Retired; branches deleted.
- Cadence: a history-preserving `git merge upstream/main` **weekly**, in a worktree, conflicts resolved by rule, the validated suite run, landed fast-forward by the operator. A three-day gap already costs 40 conflicts.
- Conflict resolution rules (the merge lane's brief): keep both when additive; prefer upstream's version of upstream logic and re-apply the fork's addition on top; the fork's seams must survive (`_downstream_cli`, `_profile_bootstrap`, `_boot_clock`, harness registration, `process_registry` durable completions, profile scoping); never drop a fork test; keep the fork's `pyproject`/`uv.lock` pair plus new upstream rows.

## The seam program (not yet a plan — rows in [[fork-hygiene-queue]])

1. Every fork touch on an upstream file becomes additive: one import, one call, at a stable anchor. The 22 heavy files are the work; `hermes_cli/main.py`'s replaced 200-line block is the pattern to undo.
2. Fork tests leave upstream test files: fork-only test modules; the 1,266 lines in `tests/hermes_cli/conftest.py` become a fork conftest plugin loaded by one line.
3. Upstream what upstream would take (boot-clock marks, durable-completion restore, generic fixes) — a merged PR is zero delta. Material for PRs: `docs/upstream-prs/` (not yet populated), `agent_runtime/docs/upstream_sync_workflow.md`.
4. Two ratchets: the refactor plan's W0-G2 (no new fork edits to upstream files from refactor lanes) and a new gate counting upstream files the fork edits + upstream lines it deletes, both only going down.
5. `scripts/upstream_sync_gate.py` exists — read what it checks before writing a new gate.

## Related

- The fork's own CI has not run on `main` since 2026-09-07 (gh run list) — a merge candidate nobody tests is the old branch again. Row in [[fork-hygiene-queue]].
- The upstream tool dividend (26 upstream-only tool names, three renames) is recorded in the launcher's Mission Control program note as "planned, deliberately not rowed"; the SessionDB dividend (+146 upstream commits on `hermes_state*`, fork touch +98/−5) merges nearly free.
- The 2026-09-15 history reconstruction pinned upstream `110baa095b` — [[0005 — Fork history reconstruction 2026-09-15]].
