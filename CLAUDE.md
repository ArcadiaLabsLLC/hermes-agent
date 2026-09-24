# Hermes Agent — fork-side session rules

This file is fork-owned; it does not exist in `NousResearch/hermes-agent`. Upstream's
development guide is [AGENTS.md](AGENTS.md); the fork's working contract is
[docs/downstream-development.md](docs/downstream-development.md); the runtime canon is
[docs/agent-runtime-harness/00-index.md](docs/agent-runtime-harness/00-index.md). Those
three own the facts. This file owns how a session works in this repository: the brain,
subagents, heavy commands, the end-of-lane test discipline, the gates, and git. A rule is
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
- Mission Control is the runtime's only product surface, and its queue is split by
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
python -m pytest -q -p no:cacheprovider <file>                  # ONE file, debugging only
scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state   # THE suite (validated scope, ≥25 min)
scripts/run_tests.sh tests/test_coverage_claims_resolve.py tests/scripts          # the two scopes outside it
python scripts/dump_cli_contract.py --check                     # after any argparse change
python scripts/dump_payload_contract.py --check                 # after any character payload change
python scripts/doc_cite_adjacency.py --exclude archive --exclude planned          # the ruled doc-cite scope
python scripts/changed_line_mutation_check.py --list --base origin/main           # mutation inventory (safe unattended)
python scripts/refactor_census.py <files.txt> <out.json>        # code-line counter + dead/duplicate census
```

### How to run a heavy command (measured — do not improvise)

The launcher mined 24 days of agent transcripts (`EterniaLauncher/docs/tooling/AGENT_WALL_TIME_2026-09-18.md`):
five habits cost about 390 minutes a day. The same habits apply here verbatim.

- **Pass an explicit `timeout` on every test, build or census call.** The 120-second
  default killed 646 calls and returned nothing; 329 more died at the 600-second ceiling.
- **Run a long command as a BACKGROUND task and wait for the completion notification.**
  Never `sleep`, never an `until … grep` loop, never `tail -f | grep -m 1` — 772 polling
  calls cost 35 hours.
- **Never re-run a byte-identical heavy command with no edit in between.** 731 did; 17 hours.
- **Never pipe a heavy command through `tail` / `head`.** Redirect to a log file, capture
  the exit code UNPIPED (`; rc=$?; exit $rc`), read the log after. Under `pipefail` a gate
  piped through `tail` hides its own red.
- **One full suite at a time on this box.** Two contend for the same cores; a second
  landing racing the first costs both a re-rebase and a second gate run.

**`scripts/run_tests.sh` is the test command, and the difference is not cosmetic.** Bare
`pytest` over a directory runs the updater tests in-process, and those run
`git branch -f main origin/main`: it detached 11 unpushed commits from the primary checkout
on 2026-08-01. The runner isolates each file in a hermetic subprocess, finds the shared test
venv on its own, and runs 8 workers — the ruled default (12 measured slower and load-flaked;
do not raise `HERMES_TEST_WORKERS`). Its validated scope is exactly the three directories
above; the whole tree is a DIFFERENT scope that reads ~142 environmental reds on a green
`main` (provider-network hangs, WSL bash shadowing Git Bash, `acp`/`ripgrep` holes).

A test whose wait bound exceeds 30 seconds declares `@pytest.mark.timeout(N)`: `addopts`
carry `--timeout=30`, and pytest-timeout kills a longer test before it can say what went
wrong.

### The end-of-lane test discipline (what a lane runs, and what it never runs)

- **While implementing:** `python -m pyflakes` or `ruff` on the touched modules, foreground,
  explicit timeout. Nothing heavier.
- **At the end of the lane, before the report:** ONLY the test files that import a module
  you touched — `grep -l` the module paths under `tests/` — as one
  `python -m pytest -q -p no:cacheprovider <files>` run DIRECTLY, in the background, with a
  log and the exit code captured unpiped, timeout at least 600000. A lane never runs the
  validated suite, the tooling gates, the docs gates or the contract dumps; those are the
  landing's job, once. A red the lane did not cause is named as pre-existing with the
  one-test run on `main` that proves it, never fixed in passing and never baselined.
- **At the landing, once, concurrently:** (a) the validated suite in the one heavy slot;
  (b) the tooling gates — `test_no_frozen_hermes_home`, `test_tombstone_registry`,
  `test_duplicate_helper_bodies`, `test_cli_contract_dump`, `test_payload_contract_dump`,
  and the refactor's size-ceiling, upstream-fence and thin-namespace gates once they land;
  (c) `changed_line_mutation_check.py` for any new gate; (d) the docs gates
  (`test_docket_stage_claims.py` — one pre-existing red on `main`, tolerated by name).
  (b)–(d) need no slot and do not wait on (a). After a forced re-rebase, only (b) re-runs;
  the suite runs again only if an incoming commit touches a file the batch touches.
- **A CHANGE commit carries its positive control:** the defect planted on a throwaway
  copy, the red pasted into the commit body, reverted. A new gate lands with its killing
  mutation recorded. A control that has not been run is a belief.

### The gates — retired as a hook, kept as tests (and nothing gates a push)

**There is no pre-push hook** (deleted 2026-09-03, `504953f6ad`, operator ruling in both
repos). The one hook is `post-merge` (`git config core.hooksPath .githooks`), which
re-installs the canonical skill packages. Every check above is something someone runs.
`main` went red unreported twice because nobody did (`6979bad59`; 2026-09-04). The fork's
CI has not fired on `main` since 2026-09-07 and is not evidence until that queue row closes.
`scripts/unattended_suite_run.ps1` is a report the operator may schedule, never a gate.

**When a contract dump reds, read the diff before regenerating.** A removed command, flag or
payload key is a launcher button that now exits 2 or a stale default acted on; re-vendor the
launcher's copy in the same wave.

## Git discipline

- Concurrent sessions share ONE git index: stage and commit in one breath, by pathspec.
- Cut worktrees from a NEUTRAL cwd (`X:/Eternia`, never inside the checkout):
  `git -C X:/Eternia/hermes-agent worktree add X:/Eternia/worktrees/<lane> -b <branch> origin/main`.
  A `fetch` + `worktree add` run inside the primary checkout yanked `main` back to its
  pre-merge tip once (2026-08-31) and both usual tells lied.
- Never `git checkout`/`switch` in the primary; never amend; never force-push; a lane never
  pushes `main`. Push after every commit. Never remove a worktree a lane could resume in.
- MOVE and CHANGE never share a commit. One MOVE and one CHANGE per lane. Commit messages
  end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Upstream files (present in `upstream/main`) are edited additively or not at all; refactor
  lanes never touch one. Upstream is integrated by a weekly history-preserving merge in a
  worktree, never a rebase, never per-file copies (`Harness_Brain/30 — Decisions/0006`).
- The history was reconstructed on 2026-09-15 (`ed9ac406be`); a SHA from before it is not
  in `main` and is not a `git show` target.

## Repo facts a session must not re-learn

- `HERMES_HOME` is resolved at CALL time, never at module scope; the live store on this box
  is `X:/Eternia/.hermes`, and the launcher's runtime uses `profiles/base`, not `alice`.
- Chat is the only lane (2026-07-30). Profile declaration is the sole MCP admission
  authority. Every write verb is an RPC method; argv is a fallback marked for delete.
- Observability lands as log receipts, never as new keys on the parity envelope.
- The 800-code-line ceiling is flat; cite code by symbol and file, never line number.
- Run the thing before fixing it: a filed row is often right that something is wrong and
  wrong about why.
