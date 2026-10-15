---
type: adr
id: 0010
status: accepted
date: 2026-09-02
tags: [adr, process, gates]
---

# 0010 — Stale sweep and ratchets first, never baseline

> [!summary]
> After a swarm lands: (1) re-derive every open queue row against the tree — delete a row only with the check named that proves it closed; (2) burn the ratchet lists (frozen-home ledger, tombstone census, duplicate-body baseline, size grandfather list) BEFORE new feature rows; (3) **never baseline to pass** — a red gate is fixed or its row is filed, not added to an allowlist.

## Context

The queue waves of 2026-09-02 → 06 (18 waves, hundreds of rows, both repos) showed the failure modes: rows closed by a lane that never checked the tree, a Mission Control queue that drifted to 137 stale rows before a sweep took it to 78, and a hermes CI that had run zero tests since 08-04 while everyone assumed green. The "claim-before-start" rule (`TAKEN <date> <who>`) came from two lanes picking the same row in one day (2026-09-03).

## Decision

The sweep is a lane of its own after every wave. Ratchets only shrink; the commit that shrinks one names the check. A gate that reds on `main` gets a row with the red quoted, never a widened baseline.

## Consequences

- Every gate in this repo carries a "list only shrinks" arm (`test_no_frozen_hermes_home.py` fails on a stale entry; `_GRANDFATHERED` in the duplicate gate; the refactor's size ceiling).
- Re-measure before re-design: a filed row is often right that something is wrong and wrong about why.

## Alternatives

Baseline-and-move-on (rejected: every allowlist grew and nobody read it again).
