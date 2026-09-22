---
type: adr
id: 0006
status: accepted
date: 2026-09-21
tags: [adr, upstream, process]
---

# 0006 — Upstream sync is a real merge, per-file reconciliation retired

> [!summary]
> The scheduled Codex job's method — copy single upstream files into a persistent branch (`sync: reconcile X with upstream <sha>`), tests NOT RUN, never advancing the merge base — is retired. Its branches `automation/upstream-sync` and `automation/upstream-sync-next` were deleted 2026-09-21 (tips kept as local backup refs). **Upstream is integrated by a history-preserving `git merge upstream/main`, weekly, in a worktree, tested on the validated scope, landed fast-forward by the operator.** The goal of record: easy syncs without much conflict.

## Context (measured 2026-09-21)

- Upstream moves ~850 commits/day; `main` was 3,002 behind after three days.
- The sync branch had 12 commits: every changed source file was a verbatim upstream blob (12 equal to current upstream, 2 to an older upstream version); none of the 40 files a real merge conflicts on; zero fork-authored code; no CI run, no test run. Six files reconciled in three days.
- A trial merge (`git merge-tree`) read 40 conflicted files / 51 hunks — a half-day for a lane with the suite, which is how the 2026-09-18 merge was done by hand.

## Decision

Cadence: weekly merge, or sooner when a needed upstream fix lands. The scheduled job is retargeted to produce the merge CANDIDATE (merge, resolve by the rules in [[Upstream Sync]], run `scripts/run_tests.sh` on the validated scope, push `merge/upstream-<date>`, report), never per-file copies. The conflict count is driven to zero by the seam program, not by more careful copying.

## Consequences

- `docs/agent-runtime-harness/planned/upstream-sync-automation.md` on `main` describes the retired method; it is deleted with the retargeted job description (queue row).
- The first merge under this ruling is [[upstream-merge-2026-09-21]].

## Alternatives

Rebase the fork onto upstream (rejected: 1,958 fork commits, published history, and [[0005 — Fork history reconstruction 2026-09-15]] already rewrote it once); keep per-file reconciliation for "safe" files (rejected: it buys nothing a merge does not bring, and it is untested).
