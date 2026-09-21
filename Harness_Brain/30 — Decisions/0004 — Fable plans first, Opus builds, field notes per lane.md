---
type: adr
id: 0004
status: accepted
date: 2026-08-24
tags: [adr, process, agents]
---

# 0004 — Fable plans first, Opus builds, field notes per lane

> [!summary]
> A Fable agent writes the implementation-ready staged plan FIRST (house format: numbered stages, gates, rulings, a ledger); an Opus agent builds from it; the verification and landing loop is the orchestrator's. **Every subagent writes its own running-record note in the repo it stands in** (two files when the work spans two repos, split by repo not subject); the skill is written LAST from those notes. Amended 2026-09-21 by the launcher playbook: cluster layout sheets instead of per-file notes, terse briefs, one review-and-fix lane that runs the killing mutations.

## Context

"Write your own document" had produced prose reports; the operator wants a staged implementation plan. Builders that did not keep notes left evidence only in chat. Plans that cited notes that did not exist reddened the docs gates — hence "land a field-notes stub with any plan that cites it".

## Decision

Plan → (sheet review) → build → land. Field notes beside the plan (`*-field-notes-<date>.md`), appended per lane, evidence never backlog. Briefs ≤ 40 lines (`CLAUDE.md`).

## Consequences

Two documents per program minimum (plan + notes); the skill folder is rewritten only at the end. Model tiering: design on the strongest model one lane at a time; review, exec and landing on Opus; nothing on Sonnet.

## Alternatives

One agent plans and builds (rejected: the plan is the review surface; a builder that writes its own spec reviews nothing).
