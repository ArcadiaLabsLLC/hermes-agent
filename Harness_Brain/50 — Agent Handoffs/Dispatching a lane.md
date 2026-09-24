---
type: handoff
tags: [handoff, process, agents]
---

# Dispatching a lane

How an orchestrating session runs one or many subagents on this repo. Rules of record: `CLAUDE.md` § Briefing a subagent; the launcher's `docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`; the refactor plan §6.

> [!important] A brief is a work order — ≤ 40 lines, one page to read, steps, capped report
> Setup commands; the one page (a handoff here, or the EXEC_CARD) plus the sheet or plan section; the steps in order; the report fields with a cap (≤ 30 lines, ≤ 3 rows). No history, no rationale, no restated rules. A judgment call gets a one-line decision rule.

## The brief skeleton

```
<Lane name>: <one sentence of the outcome>.
Setup (from a neutral cwd, never inside X:/Eternia/hermes-agent): fetch; worktree add X:/Eternia/worktrees/<lane> -b <branch> origin/main; read <one page> and <section>.
Steps: 1. … 2. … (decision rules inline: "if the tree differs from the sheet, follow the tree and say so in the commit")
Run: touched tests directly, background, log, `; rc=$?; exit $rc`, timeout N. Never the suite. Never `| tail`.
Commit/push rules: one MOVE, one CHANGE; push per commit; never main; never amend/force/rebase; leave the worktree.
Report (≤30 lines): tip SHA; per-file/per-step outcome; test counts + reds marked merge-caused/pre-existing; ≤3 open rows; tool-call count.
End commit bodies with: Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
```

## Tiering and concurrency

- Design sittings: strongest model, ONE at a time; commit each note as it finishes.
- Review-and-fix, exec, landing: Opus. Nothing on Sonnet.
- Exec lanes uncapped in parallel (they only run touched tests). ONE landing lane at a time; it lands every branch finished when it starts; gates run concurrently; after a forced re-rebase only the tooling gates re-run.
- Lanes report tool-call counts — the per-unit efficiency number (210 → 38–61 under this method on the launcher).
- A landing runs the touched tests and the tooling gates only. The validated suite (tests/agent_runtime tests/hermes_cli tests/hermes_state, ~1 h) runs ONCE at the end of a program and before any upstream PR goes up — never per landing. Owner ruling 2026-09-23.

## What the orchestrator keeps

A holding file per landing outside the repo (branch tips, commits to review, rows verbatim, expected count) and a RESUME line in session memory after every report. A lane's report lives only in its notification — copy it the moment it arrives. File findings into the queue on arrival, by surface ([[TODO]]).

## Never

Dispatch a follow-up into another lane's worktree (message the lane); remove a worktree a lane could resume in; run two design sittings at once; let a lane run the full suite; paste this page into a brief.
