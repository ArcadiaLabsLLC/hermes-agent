---
type: moc
tags: [moc, handoff]
---

# Agent Handoffs — Index

Pre-baked context primers for common task shapes in the hermes fork. Each compresses "what an agent needs to know before touching X" into one page. A brief names ONE of these (or the refactor EXEC_CARD) as its one page to read — it never pastes the paragraph (`CLAUDE.md` § Briefing a subagent).

## Primers

**Per surface:**

- [[Touching the harness CLI]] — `harness.py`, the exec'd parts, the 263 patch targets, the contract dump.
- [[Touching a chat turn]] — the v3 ledger, the pre-admit span, the three skill walkers, what a turn must not do.
- [[Touching serve and boot]] — `serve_loop`, the restart fence, the receipts, what a boot proof looks like.

**Per task shape:**

- [[Merging upstream]] — the weekly merge: worktree, rules, tests, landing.
- [[Running the suite]] — `run_tests.sh`, the validated scope, timeouts, what "green" means here.
- [[Dispatching a lane]] — the brief shape, model tiering, the batched landing.
- [[God-file program — handoff 2026-09-25]] — population ZERO on 2026-09-25; landing protocol, known reds and their owners, open owner calls, what is left in order, the traps the program measured. Read before touching any package the program split.
