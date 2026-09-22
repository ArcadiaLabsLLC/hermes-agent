---
type: program
program: upstream-sync
status: active
cursor: "2026-09-22 — LANDED: upstream ea0c2b820b merged into main (candidate tip 24fac52fbf, fast-forwarded by the operator). Merge base is now 2026-09-21. Three named reds carried by ruling (residual doctor vendor-slug test, frozen-home gate on two upstream names, docket gate), all rowed in fork-hygiene-queue. Next: retarget the scheduled Codex job to produce a tested weekly merge candidate; then the seam program S0 (ratchet) on the merged tree."
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

## The plan: the harness as a plugin, the fork as the thin vehicle for core changes

[`docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md`](../../docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md) (2026-09-21). The hybrid end state the owner asked for: stay a fork if need be, detach if the measurement allows, keep core changes welcome.

- **Three dispositions** for every fork edit in an upstream file — `upstream` (PR), `hook` (behind the plugin surface, widening it by PR when it lacks something), `carry` (ours, additive where possible, on the ratchet with a reason).
- **The ratchet** `[up-fp] files= deleted_lines= heavy=` only goes down; a wanted core change raises the fixture in the same commit with a `reason:` row. **Detach is a measurement:** `files=0` means the plugin runs on stock upstream and the fork is optional.
- **Stages:** S0 merge + ratchet → **S1 the harness registers its CLI as a plugin (first step; measured against the 500–650 ms plugin-discovery cost; fallback = a manifest-declared deferred CLI entry PR)** → S2 tools + prompt sections → S3 five upstream PRs (P1 = the profile-bootstrap extraction, the one replacement-shaped hunk in `main.py`) → S4 profile-home diff → S5 fork tests out of upstream test files (−242 files) → S6 desktop → S7 detach on the read (private repo on the owner's word).
- Upstream's own direction, read from its tree: core stays a narrow waist; products go to standalone repos; "plugins never touch core"; the plugin surface is an additive-only contract; the catalog is discovery only for plugins that want listing. `scripts/upstream_sync_gate.py` is read before Stage 0b writes the ratchet.

## Related

- The fork's own CI has not run on `main` since 2026-09-07 (gh run list) — a merge candidate nobody tests is the old branch again. Row in [[fork-hygiene-queue]].
- The upstream tool dividend (26 upstream-only tool names, three renames) is recorded in the launcher's Mission Control program note as "planned, deliberately not rowed"; the SessionDB dividend (+146 upstream commits on `hermes_state*`, fork touch +98/−5) merges nearly free.
- The 2026-09-15 history reconstruction pinned upstream `110baa095b` — [[0005 — Fork history reconstruction 2026-09-15]].
