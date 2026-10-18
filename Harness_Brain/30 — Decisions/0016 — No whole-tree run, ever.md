---
type: adr
id: 0016
status: accepted
date: 2026-10-17
tags: [adr, tests, gate]
---

# 0016 — No whole-tree run, ever

> [!summary]
> Owner ruling 2026-10-17: "we don't need the full runner at all". **Nothing runs the whole tree** —
> not a landing, not a release merge, not a weekly lane. A landing runs `--scope fork`; a release merge
> runs `--since-merge`; both run every fork file plus the upstream files the change reaches, minus the
> skip list. A session-chain edit runs the chain contract + one sample per folder at a release merge
> too. `--scope full` is retired.

## Context

The last whole-tree run (v0.22.2 release gate, 2026-10-16) took 9,657 s at 8 workers; upstream test
files are 31,504 of the gate store's 38,887 serial seconds. The fork does not ship much of what those
files test ([[0015 — Upstream features the fork does not ship leave the suite and the boot path]]),
and a whole-tree pass re-proves upstream code the change did not touch. Upstream tests its own code at every release; the fork proves only what it changes and what it ships (owner). Evidence: [[r-perf-2026-10-17]].

## Consequences

- A gap a whole-tree backstop used to catch is closed by a new chain-contract promise or a reach rule,
  added when it is found, with its killing mutation.
- The runner stops offering `--scope full` and stops widening `--since-merge` to every file on a chain
  path (fork-hygiene row, lane q-runner).
- Upstream files still run when a change reaches them, and when named on the command line.
