# Hermes Agent — fork-side session rules

This file is fork-owned; it does not exist in `NousResearch/hermes-agent`. Upstream's
development guide is [AGENTS.md](AGENTS.md); the fork's working contract is
[docs/downstream-development.md](docs/downstream-development.md); the runtime canon is
[docs/agent-runtime-harness/00-index.md](docs/agent-runtime-harness/00-index.md). Those
three own the facts. This file owns how a session works in this repository: the brain,
subagents, git, and where the test rules live. A rule is
stated once, as a fact, with the measurement or incident that bought it where one exists.

# Obsidian Brain Network

This repo carries its project vault at `Harness_Brain/`. It is the hermes fork's child
brain: navigation, decision rationale, in-flight snapshots, handoff primers, operational
gotchas. It never duplicates the canon.

Start here:

- `Harness_Brain/Brain Index.md` — routing table and the brain network.

Brain network links from this repo (paths are repo-relative; the launcher is under the
Unreal tree, not beside this checkout):

- Launcher sibling brain: `../../Unreal Engine/Engine/Launcher/EterniaLauncher/Launcher_Brain/`
- Parent/company brain: `../../Unreal Engine/Engine/ArcadiaLabs_Brain/`
- Backend sibling brain: `../../Unreal Engine/Engine/EterniaBackend/eternia-backend/EterniaBackend_Brain/`

Brain-routing rules:

- Runtime and fork truth belongs in `docs/`; the brain cites it and records the WHY.
- Mission Control and Intelligence consume the same runtime authorities through
  typed ports; Intelligence is Launcher's AI umbrella, with Chat one route.
  Provider catalog, authentication, credentials and health remain Hermes-owned.
  Runtime work is split by
  REPOSITORY: a row lives where its fix lives. The hermes half is
  `Harness_Brain/20 — Active Initiatives/runtime-queue.md`, grouped by the Fork Boundary
  Map's three kinds of file (fork-owned / seams / upstream-owned) so the heading says what
  a lane may edit; the launcher half is the launcher's
  `Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. A cross-repo finding
  is filed on the side that must move first and names the other. Fork findings (CI, the
  suite, the mutation gate, upstream reds) go to
  `Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md` whichever repo noticed
  them. Rulings: `Harness_Brain/30 — Decisions/0012` (amending `0011`).
- Cite a file in another repo with its repo prefix in backticks
  (`EterniaLauncher/docs/…`, `eternia-backend/…`), never as a link. No machine paths in
  committed notes.
- Treat `.obsidian/` as vault runtime state. Read it only for Obsidian setup.

Work tracking (adopted from the launcher's ADR 0025):

- `Harness_Brain/TODO.md` is the master pointer list and holds no items, counts or
  statuses. Work is filed by the SURFACE it serves, never the layer it lives in and never
  the lane that found it.
- **Claim a row before you start it:** fetch, append `**TAKEN <date> <who>**` to the row's
  line, commit that alone, push, then cut the worktree. A row already marked `TAKEN` is
  someone else's. The landing commit deletes the row.
- **File a finding when it arrives, not at the end of the session.** A report, a review
  verdict, an audit result is EVIDENCE; the queue rows point at it. The one exception is a
  finding you are fixing in this change, where the commit is the record.

When starting non-trivial work:

1. Read `Harness_Brain/Brain Index.md` before planning, coding, reviewing or QA.
2. Follow its links to the program note, the canon domain doc, and the plan under
   `docs/agent-runtime-harness/planned/` before editing.
3. If the work crosses into the launcher or backend, read the cross-brain pointer and
   the sibling note it names.
4. When spawning a subagent, the brief names the ONE page it reads (a handoff under
   `Harness_Brain/50 — Agent Handoffs/`, or a program's EXEC_CARD). Do not assume the
   parent's context carries over, and do not paste it.
5. Durable knowledge you discover goes into the brain note or the canon doc that owns it,
   not into chat or session memory alone.

## Briefing a subagent (owner ruling 2026-09-21, adopted from the launcher)

A brief is a work order, not an essay. It carries: the setup commands; the one page to
read and the sheet or plan section; the steps, in order; the report fields with a length
cap. Nothing else — no history, no rationale, no warnings, no restated rules. A rule is
stated once as a fact ("one MOVE commit, one CHANGE commit"). A judgment call gets a
one-line decision rule ("if the tree differs from the sheet, follow the tree and say so in
the commit"). Forty lines at most; twenty-five for a mechanical lane. The report is capped
the same way (thirty lines) and files at most three queue rows, for defects in code or
design only. The owner reads these briefs; "a bunch of what feels heckin extra" is the
failure this rule retires. Rulings, history and the reasons behind a rule live in the plan
and the brain, where a lane that needs them can follow the pointer.

How a many-lane program is run — bulk mode, cluster lanes, one batched landing at a time
with concurrent gates, tool-call counts per lane, model tiering, and the measured journey
that bought each rule — is
`EterniaLauncher/docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`, restated for
this repo in `docs/agent-runtime-harness/planned/downstream-god-file-refactor.md` §6 and
`Harness_Brain/50 — Agent Handoffs/Dispatching a lane.md`. Read it before orchestrating
more than two subagents on one program.

The tiering: design on the strongest model, ONE such lane at a time; review, apply,
execution and landing on Opus; nothing on Sonnet. Every lane reports its tool-call count.

## Commands

```bash
hermes harness serve                                            # the runtime the launcher spawns
python scripts/refactor_census.py <files.txt> <out.json>        # code-line counter + dead/duplicate census
```

**Before you run any test, gate or suite — or brief a lane that will — read
`Harness_Brain/50 — Agent Handoffs/Running the tests.md`.** It owns the commands, the landing
gate, what a lane runs, how a red is proven pre-existing, and the heavy-command habits. The one
rule that cannot wait for the page: never run bare `pytest` over a directory (it detached 11
unpushed commits on 2026-08-01); the landing gate is `scripts/run_tests_bundled.sh tests`.

## Git discipline

- There is no pre-push hook; nothing gates a push (the checks are tests someone runs —
  `Running the tests.md`).
- While the operator is testing a live serve, commit from a worktree and push `HEAD:main`,
  never in the primary checkout: a commit there moves the code tree the serve is built from
  and the Launcher restarts it (three queue-only commits did, 2026-10-05; vault-only paths stop
  counting once `Harness_Brain/` is in `NON_RUNTIME_PREFIXES`, landing h-turn1).
- Concurrent sessions share ONE git index: stage and commit in one breath, by pathspec.
- Cut worktrees from a NEUTRAL cwd (`X:/Eternia`, never inside the checkout):
  `git -C X:/Eternia/hermes-agent worktree add X:/Eternia/worktrees/<lane> -b <branch> origin/main`.
  A `fetch` + `worktree add` run inside the primary checkout yanked `main` back to its
  pre-merge tip once (2026-08-31) and both usual tells lied.
- Never `git stash`. The stash stack and the rerere cache are shared by every worktree of
  the clone: on 2026-09-29 one lane's `stash pop` applied another lane's entry and its own
  was lost. Park work as a WIP commit on your branch, or `git diff > file` / `git apply`;
  check any conflict rerere resolves for you by hand.
- Never `git checkout`/`switch` in the primary; never amend; never force-push; a lane never
  pushes `main`. Push after every commit. Never remove a worktree a lane could resume in.
- MOVE and CHANGE never share a commit. One MOVE and one CHANGE per lane. Commit messages
  end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Upstream files (present in `upstream/main`) are edited additively or not at all; refactor
  lanes never touch one. Upstream is integrated by a weekly history-preserving merge in a
  worktree, never a rebase, never per-file copies (`Harness_Brain/30 — Decisions/0006`).
- The history was reconstructed on 2026-09-15 (`ed9ac406be`); a SHA from before it is not
  in `main` and is not a `git show` target.

## Weakness escalation, per domain (owner ruling 2026-09-24, mirrored from the launcher's CLAUDE.md)

Whenever work in an area — a fix, a feature, a review, a lane report — reveals architecture that
is weak by the fork's bar (`docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md`
§2: routing as tables, one write path per state, typed reasons, one owner per helper, a module
map, the legibility floor), do NOT just patch the symptom and move on: **fix the immediate defect
narrowly, then RECORD the structural weakness as a row in the domain queue, in the same commit
as the work that revealed it.** A finding that lives only in a report, a chat message or a
session's head is one context window from being lost; the report is EVIDENCE, never a backlog.

- **Signals:** a ladder of `if x == "…"` on an op, kind, mode or step; a `str` reason where an
  Enum should be; the same state written from two sites; a helper with the same name in two
  modules; a closure reading more than three enclosing locals; a function over 150 lines; a fork
  module importing a `_private` upstream name; a gate that only proves a spelling.
- **The row is one line and a pointer** (`**what** · domain · evidence · lane`); the measurement
  and the argument live in the note the row points at. Where a row and its evidence disagree,
  the evidence wins.
- **Recurrence is itself the finding.** The third instance of one class files the CLASS, with the
  structural answer, not a third row that reads like the first two.
- **A gate proves a POSITIVE guarantee at runtime or through the AST/import graph** (build the
  thing and read it; walk resolved imports); **a source walk proves only a NEGATIVE** ("this is
  never written"), where over-approximation is the safe direction. A gate lands with its killing
  mutation NAMED and its red RECORDED in the commit body — an unrecorded red is a belief.
- **If you cannot write the queue** (you stand in another repo, or a worktree that should not
  fight a shared checkout for a docs file), put the row you would have written in your report
  VERBATIM and name the queue; the parent files it.

**The domains are the fork's queues** (`Harness_Brain/TODO.md` is the pointer list; it holds no rows):

| the weakness is in | queue | section |
|---|---|---|
| fork-owned runtime code (`agent_runtime/`, `hermes_cli/harness*`, `plugins/eternia-harness/`) | `Harness_Brain/20 — Active Initiatives/runtime-queue.md` | § Fork-owned |
| a fork edit inside an upstream file, or a reach into upstream internals that wants a door | `runtime-queue.md` | § Seams (additive only; a widening is a held PR row in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`) |
| upstream code the fork does not touch | `runtime-queue.md` | § Upstream-owned (a marker, a caller-side memo, or an upstream issue — never an edit) |
| the repository as a fork: sync, CI, the suite and its gates, the mutation gate, docs gates, the refactor's lanes, this vault | `Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md` | the dated "Filed on arrival" heading for your lane |
| a symbol nothing calls, a test-only production function, a kept-with-reason verdict | `Harness_Brain/20 — Active Initiatives/dead-code-burn-down-queue.md` | the current instalment; deletions land under its "Working a slice" |

The launcher half of a Mission Control finding goes to the launcher's `mission-control-queue.md`;
a finding that needs both sides is filed on the side that must move first and names the other.

## Repo facts a session must not re-learn

- `HERMES_HOME` is resolved at CALL time, never at module scope. Launcher passes its
  selected profile explicitly; read the serve receipt rather than assuming a home.
- Operator chat, independent native conversations and discussions share the runtime,
  not a session. Profile declaration is the sole MCP admission authority. Every
  write verb is an RPC method; argv is a fallback marked for delete.
- Observability lands as log receipts, never as new keys on the parity envelope.
- The 800-code-line ceiling is flat; cite code by symbol and file, never line number.
- Run the thing before fixing it: a filed row is often right that something is wrong and
  wrong about why.
