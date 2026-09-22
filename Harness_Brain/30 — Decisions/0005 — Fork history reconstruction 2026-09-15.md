---
type: adr
id: 0005
status: accepted
date: 2026-09-15
tags: [adr, upstream, git]
---

# 0005 — Fork history reconstruction 2026-09-15

> [!summary]
> On 2026-09-15 the fork's history was REPLACED by a same-tree reconstruction: `ed9ac406be` "fork: runtime storage" (and siblings such as `5a411b1657` "fork: build test platform") are grouped source-review checkpoints of tree `c112a9347a`, pinned to upstream `110baa095b`. The historical commits live on `codex/pre-history-replacement-20260915`.

## Context

The pre-reconstruction history carried thousands of commits across the fork's own work and merged upstream, with contributor credit spread across many machine identities. The reconstruction groups the fork's additions into reviewable checkpoints on top of a pinned upstream and records credit in the commit body.

## Decision

`main` = pinned upstream + grouped fork checkpoints + everything since (1,958 commits by 2026-09-21). `git log --follow` on a fork file stops at its checkpoint; older provenance is on the archived branch.

## Consequences

- Any doc or session note citing a pre-09-15 SHA cites a commit that is not in `main`'s history. `tests/test_docket_stage_claims.py` already reds `duplicate-implementation-retirement.md` for exactly this (row in [[fork-hygiene-queue]]). Session memory SHAs from before 09-15 are provenance, not `git show` targets.
- Upstream merges after the reconstruction are ordinary: `c62bd9f207` (2026-09-18) merged cleanly by hand; the merge base with upstream is the last such merge.

## Alternatives

Keep the full history (rejected by the operator for review and credit reasons); squash to one commit (rejected: the checkpoints are the review units).
