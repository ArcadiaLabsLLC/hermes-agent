---
type: adr
id: 0013
status: accepted
date: 2026-09-22
tags: [adr, fork, upstream, refactor, process]
---

# 0013 — Seams before the god-file refactor, and main's reds classified first

> [!summary]
> Two staged plans are ready. They run in this order: (0) classify `main`'s 194 pre-existing validated-scope reds so a landing can tell its own reds from the noise; (1) the seam plan's Stage 0b (the `[up-fp]` ratchet) and Stage 1 (the harness CLI registered as a plugin, measured first); (2) the god-file refactor from Wave 0 through H4; (3) the seam plan's Stage 2 onward. Owner ruling 2026-09-22.

## Context

The 2026-09-21 upstream merge landed ([[upstream-merge-2026-09-21]]). Two implementation-ready plans wait on it:

- `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md` — shrink the fork's footprint in upstream files so weekly merges stop hurting; optionally detach. Program cursor: [[Upstream Sync]].
- `docs/agent-runtime-harness/planned/downstream-god-file-refactor.md` — 41 fork-owned files over 800 code lines, 13 lanes. Program cursor: [[Downstream Refactor]].

The refactor touches fork-owned files only, so it never changes the upstream footprint. The two programs share exactly one file: refactor lane H2 splits `hermes_cli/harness.py`, and seam Stage 1 changes how that file's parser is registered. And both programs land through the validated suite, which today reads 194 reds on `main` that predate the merge (row in [[fork-hygiene-queue]]).

## Decision

1. **Classify `main`'s reds first** (a read, not fixes): every red in the validated scope gets a cause and a class (product defect / Windows-only upstream test / environment), recorded in the row's evidence, so each later landing diffs against a known set. Never baselined ([[0010 — Stale sweep and ratchets first, never baseline]]).
2. **Seam Stage 0b + Stage 1 next.** The ratchet lands before any program that could move the footprint; Stage 1 lands before H2 so the refactor splits the plugin-shaped `harness.py`, not the old dispatch seam. Both are one-sitting lanes.
3. **Then the refactor**, Wave 0 → S1 → H1 → the parallel lanes → H4, one batched landing at a time ([[0007 — Flat 800-line ceiling and bulk mode]]).
4. **Then seam Stage 2 onward.** After H2 the programs are on disjoint files and could interleave, but one landing at a time and the owner's launcher focus rule out running them side by side.

## Consequences

- The queue rows for the two dispatches carry their order in the row text; a lane that claims the refactor's Wave 0 before seam Stage 1 has landed is out of order.
- The seam plan's Stage 0 gains the classification read as its first act.
- This ADR is the pointer [[TODO]] carries for program order; the queues carry the rows.
