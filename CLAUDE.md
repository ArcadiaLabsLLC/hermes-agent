# Hermes Agent — fork-side session rules

This file is fork-owned (it does not exist in `NousResearch/hermes-agent`). The
development guide is [AGENTS.md](AGENTS.md); the fork's contract is
[docs/downstream-development.md](docs/downstream-development.md); the runtime
canon is [docs/agent-runtime-harness/00-index.md](docs/agent-runtime-harness/00-index.md).
Read those first. This file carries only the rulings that apply to how a
session runs subagents in this repo.

## Briefing a subagent (owner ruling 2026-09-21, adopted from the launcher)

A brief is a work order, not an essay. It carries: the setup commands; the one
page to read (for the god-file refactor,
`docs/agent-runtime-harness/planned/downstream-god-file-refactor-EXEC_CARD.md`)
and the sheet or plan section; the steps, in order; the report fields with a
length cap. Nothing else — no history, no rationale, no warnings, no restated
rules. A rule is stated once as a fact ("one MOVE commit, one CHANGE commit").
A judgment call gets a one-line decision rule ("if the tree differs from the
sheet, follow the tree and say so in the commit"). Forty lines at most;
twenty-five for a mechanical lane. The report is capped the same way (thirty
lines) and files at most three queue rows, for defects in code or design only.
The owner reads these briefs; "a bunch of what feels heckin extra" is the
failure this rule retires. Rulings, history and the reasons behind a rule live
in the plan and the field notes, where a lane that needs them can follow the
pointer.

How a many-lane program is run — bulk mode, cluster lanes, one batched landing
at a time with concurrent gates, tool-call counts per lane, and the measured
journey that bought each rule — is the launcher's
`EterniaLauncher/docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`
(sibling repo, under the Unreal tree). Read it before orchestrating more than
two subagents on one program. Its rules are restated for this repo in
`docs/agent-runtime-harness/planned/downstream-god-file-refactor.md` §6.

## Repo facts a session must not re-learn

- Concurrent sessions share ONE git index: stage and commit in one breath.
- No pre-push hooks by ruling (2026-09-03); gates are tests and the lander runs
  them. CI (`.github/workflows/tests-os.yml`) runs the full suite per OS on the
  push and is watched, not waited for.
- Every heavy command: background, explicit timeout, log file, exit code
  captured unpiped (`; rc=$?; exit $rc`), never polled, never piped through
  `tail`.
- Never `git checkout`/`switch` in the primary checkout; cut worktrees from a
  neutral cwd; never remove a worktree a lane could resume in.
