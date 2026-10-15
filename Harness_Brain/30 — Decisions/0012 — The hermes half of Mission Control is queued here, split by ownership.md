---
type: adr
id: 0012
status: accepted
date: 2026-09-22
tags: [adr, brain, process, fork]
---

# 0012 — The hermes half of Mission Control is queued here, split by ownership

> [!summary]
> Mission Control stays ONE domain, but its queue is split by REPOSITORY: rows whose fix lives in hermes are in this vault's [[runtime-queue]], grouped by the [[Fork Boundary Map]]'s three kinds of file (fork-owned, seams, upstream-owned); rows whose fix lives in the launcher stay in its `mission-control-queue.md`. Forty-four hermes rows moved on 2026-09-22; the fork-hygiene ones went to [[fork-hygiene-queue]]. This amends the queue clause of [[0011 — One brain per repo, one Mission Control queue in the launcher]].

## Context

ADR 0011 put every Mission Control row in the launcher's queue because the domain is the surface. Measured one day later: the launcher's queue-grinding waves (`EterniaLauncher/docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`, "The queue-grinding protocol") claim rows by heading and dispatch a lane into a launcher worktree; a hermes row in that queue is unworkable by every such lane, so forty-four of them sat for up to three weeks, four were ROUTED back by the 2026-09-22 verdict sheet, and one finding (the `harness-runtime-model` preload ceiling) was filed three separate times because nobody on the hermes side read the launcher's queue. The owner asked on 2026-09-22 for the rows to come over, distinguished by whether the fork or upstream owns the fix.

## Decision

- **A row lives in the repository whose tree must change.** A cross-repo finding is filed on the side that must move FIRST and names the other side in the row; it is never filed twice.
- [[runtime-queue]] holds the hermes half under three headings that are the Fork Boundary Map's three kinds of file — because the heading tells a lane what it may do: refactor freely, additive seam edits only, or never edit (memo on our side, marker, or upstream issue).
- Fork-hygiene findings (CI, the suite, the mutation gate, upstream reds) go to [[fork-hygiene-queue]] whichever repo noticed them.
- Both vaults' TODO files point at both halves. The launcher's queue header, `TODO.md`, `CLAUDE.md` and Brain Index say "the launcher half" where they said "both repos".
- Nothing enforces this; the claim-before-start rule and the wave landings' claim-mark grep are the only readers.

## Consequences

- A hermes lane reads one queue for runtime work and one for fork work; the launcher's grinding waves never again claim a row they cannot open.
- The two halves can disagree about one finding; the rule that the side moving first owns the row is what keeps that to one pointer each.
- The launcher's vault owes the `Harness Brain Pointer` (row in [[fork-hygiene-queue]]); the move closes three rows by folding and three by naming their landed commits (in the moving commit's message).

## Alternatives

Keep one queue in the launcher (rejected: measured unworkable for hermes lanes, and the launcher's waves route hermes rows back rather than working them). A queue per LAYER inside hermes (rejected: ADR 0025's "a layer is not a domain"; the ownership headings are a lane-rights map, not a domain split).
