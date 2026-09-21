---
type: adr
id: 0007
status: accepted
date: 2026-09-21
tags: [adr, refactor, process]
---

# 0007 — Flat 800-line ceiling and bulk mode

> [!summary]
> Adopted from the launcher's refactor program (owner amendments 2026-09-18 → 21): **every fork-owned production file ≤ 800 code lines, no exceptions list; split to a responsibility layout, never shave; MOVE and CHANGE never share a commit; one MOVE + one CHANGE commit per lane ("big moves, few commits"); LOC is not the objective — grandfathered units → 0 and one authority per helper are.**

## Context

The launcher measured its method over a whole program: per-file design notes with review loops retired 2 units/day; cluster sheets + bulk mode retired 17/day; SHA span receipts caught 0 defects while applied positive controls caught all of them. The reason of record for a flat number: this code is read and edited mostly by agents, whose cost scales with file size twice (a whole-file read per method; every lane that touches a big file collides with every other). The hermes tree had 41 production files over the ceiling on 2026-09-21.

## Decision

The plan is `docs/agent-runtime-harness/planned/downstream-god-file-refactor.md` (13 lanes, ≤ 27 commits). Gates: size ceiling with a shrink-only grandfather list, upstream fence, widened duplicate-body gate, thin harness namespace. Method: design sittings one at a time on the strongest model; review-and-fix lanes that RUN the named killing mutations; uncapped exec lanes on touched tests only; one batched landing with concurrent gates; tool-call counts per lane; briefs ≤ 40 lines.

## Consequences

- Cites by symbol and file, never line number.
- Format AFTER a grandfather row is deleted, never before (a formatter grows a file and the GREW arm has no legal repair).
- A step that ADDS code and moves none never lands alone on a grandfathered file.

## Alternatives

A 30 % LOC reduction target (the launcher retired it on 2026-09-20: decomposition RAISES the total by construction); a "one thing, not too long" exception tier (rejected: "one thing" cannot be measured).
