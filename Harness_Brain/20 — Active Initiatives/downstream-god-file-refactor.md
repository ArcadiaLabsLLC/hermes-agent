---
type: initiative
program: downstream-refactor
status: planned
blocking: "none — Wave 0 is dispatchable; the operator owes only the H4 boot and the §4.2 argv rulings, both late"
docs: "docs/agent-runtime-harness/planned/downstream-god-file-refactor.md"
tags: [initiative, program/downstream-refactor]
---

# downstream-god-file-refactor

41 fork-owned production files over 800 code lines → 0, in 13 lanes and ≤ 27 commits, with a dead-code delete list, a duplicate-collapse list and an upstream fence. Plan landed 2026-09-21 (`042f58edf8`). Program note: [[Downstream Refactor]].

## Files

**Plan:** `docs/agent-runtime-harness/planned/downstream-god-file-refactor.md` · **Notes:** `…-field-notes-2026-09-21.md` · **Instrument:** `scripts/refactor_census.py` · **Rules for sessions:** `CLAUDE.md` § Briefing a subagent.
**Wave 0 creates:** `tests/tooling/test_downstream_size_ceiling.py`, `test_refactor_stays_downstream.py`, `test_harness_namespace_is_thin.py` (xfail until H1), the widened `test_duplicate_helper_bodies.py`, `tests/fixtures/{downstream_manifest.txt,upstream_manifest.txt,size_ceiling_grandfathered.json}`, `scripts/downstream_manifest.py`, `scripts/refactor_reach_census.py`, the EXEC_CARD.

## Resume

1. Wave 0 + S1 in one sitting (one Opus lane each; W0 is ONE commit).
2. H1 alone — read [[Touching the harness CLI]] first; the patch-retarget script's output goes in the commit body.
3. Then any of R1–R4, C1, T1, D1 in parallel; H2/H3 after H1; H4 last with the operator boot.
4. Each lane: brief ≤ 40 lines → layout sheet → one review-and-fix lane → exec → batched landing. Tool-call count in every report.
5. After every landing: the `[ds-size]` line in the commit; the ledger row in plan §8; file findings into [[fork-hygiene-queue]] on arrival.
