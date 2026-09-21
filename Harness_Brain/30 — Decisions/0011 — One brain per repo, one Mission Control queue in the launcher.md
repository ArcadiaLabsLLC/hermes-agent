---
type: adr
id: 0011
status: accepted
date: 2026-09-21
tags: [adr, brain, process]
---

# 0011 — One brain per repo, one Mission Control queue in the launcher

> [!summary]
> This vault (`Harness_Brain/`) is the hermes fork's child brain, shaped like `Launcher_Brain/` and routed from the same parent. It adopts the launcher's ADR 0025 work-tracking rule (one master TODO of pointers, one queue per DOMAIN, reports split on arrival, claim-before-start). **Mission Control's queue stays in the launcher's vault and covers both repos** — the domain is the surface, not the checkout. This vault holds exactly one queue, [[fork-hygiene-queue]], for the repository as a fork.

## Context

The hermes side had no brain: standing rulings lived in one operator's per-machine session memory (~50 entries), cursors in plan headers, and the launcher's Mission Control queue already carried hermes rows. Opening a second Mission Control queue here would create the "two copies of a moving list" defect ADR 0025 retires. The operator asked for the vault on 2026-09-21 ("populate the new obsidian brain … with our fork specific logic").

## Decision

- Folders mirror the launcher: `00 — Maps`, `10 — Programs`, `20 — Active Initiatives`, `30 — Decisions`, `40 — Cross-Brain`, `50 — Agent Handoffs`, `60 — Operations`, `Templates`.
- Truth routing: the canon (`docs/agent-runtime-harness/`) and the fork contract (`docs/downstream-development.md`) own facts; this vault owns navigation, WHY, cursors, handoffs and gotchas; session memory is scratch that graduates here.
- Cross-repo cites use a repo prefix in backticks, never a link (the launcher's dead-link gate reads a bare `docs/…` token as its own; this repo's `doc_cite_adjacency` walks `docs/` only, but the convention is shared).
- The vault is committed (like `Launcher_Brain/`); `.obsidian/` is runtime state, read only for Obsidian setup.

## Consequences

- The launcher's brain owes a `Harness Brain Pointer` (queue row). The parent brain routes to hermes only through two contract notes today.
- Runtime findings are filed in the launcher's queue from a hermes session — cross-repo, on arrival.

## Alternatives

A brain in the parent for both (rejected: repo-relative links break across machines); no brain, memory only (rejected: per-machine, per-operator, invisible to lanes).
