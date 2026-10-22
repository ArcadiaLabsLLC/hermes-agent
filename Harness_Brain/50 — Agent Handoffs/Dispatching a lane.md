---
type: handoff
tags: [handoff, process, agents]
---

# Dispatching a lane

The hermes deployment book: how an orchestrating session runs subagents on THIS repo. Rules of record:
`CLAUDE.md` § Briefing a subagent (the brief format); [[Running the tests]] (every test a lane or a
landing runs); [[Merging upstream]] (release and daily-branch lanes). The launcher's
`docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md` is the general method; this page is what
differs here, each rule with the incident that bought it.

> [!important] A brief is a work order — ≤ 40 lines, one page to read, steps, capped report
> Setup commands; the one page (a handoff here, or the plan section); the steps in order; the report
> fields with a cap (≤ 30 lines, ≤ 3 rows). No history, no rationale, no restated rules. A judgment
> call gets a one-line decision rule.

## 1. Cut lanes thick, by domain

One Opus lane per DOMAIN (a plan section, a queue heading, a set of files that move together), never
one lane per queue row. The 2026-10-16 queue sweep cut twelve thin lanes; with a peer session's lanes
the box sat at 100% CPU over 16 cores and ~100 python processes, and four red-triage lanes had to be
stopped because nothing they measured could be trusted. Thick lanes mean fewer worktrees, fewer setups,
one owner who can tell load from a real red across a whole domain.

- Design: the strongest model, ONE sitting at a time (owner may ask for more); the doc is the product.
- Review, exec, landing: Opus. Nothing on Sonnet.
- Lanes report a tool-call count.

## 2. The box is shared — budget the heavy work

Every lane, every peer session (`ListAgents`), the live serve and the gate share one workstation.

- **Light lanes** (read, edit, run only the tests of the files they touched): ~6 at once is safe.
- **Heavy lanes** (a release merge, the daily branch, anything running `run_tests_bundled.sh`): one at a
  time, and never beside a landing gate.
- **Quiet-box lanes**: a lane that JUDGES a timeout or a flake runs only when nothing heavy is running —
  under load anything times out, and the lane "fixes" the machine. Check first:
  `wmic cpu get loadpercentage` and the python process count.
- **Search with `git grep -n <pattern> -- <paths>` or the Grep tool, never `grep -rn` over the tree**, and wait
  for a background command's completion notice instead of an `until grep …; do sleep` loop. In the launcher on
  2026-10-21, slow `grep -r` searches cost lanes 279 minutes and polling loops 280.
- A lane runs its tests with `-j 4` at most while other lanes are live. `-j` is `scripts/run_tests.sh`'s
  flag; never write `-n` in a brief (the test venv has no pytest-xdist).

## 3. Shared state a lane can break

| shared thing | hazard | rule |
|---|---|---|
| git index, stash, rerere cache | one lane's `stash pop` applied another's entry (2026-09-29); a merge records rerere preimages every worktree then sees | never stash; check any rerere answer by hand; a stopped merge is `--abort`ed |
| worktree paths | `git -C <clone> worktree add worktrees/x` resolves INSIDE the clone (2026-10-15) | always an ABSOLUTE path beside the clone under a `.worktrees` parent: `X:/Eternia/.worktrees/<lane>` (pm reclaims install states only there; owner 2026-10-18) |
| `.git` packs | interrupted concurrent fetches left `.idx` without `.pack` | fetch once at setup; no background `git log --all` (it triggers partial-clone fetches) |
| the test venv `~/.venvs/hermes-test` | an install while a gate ran half-removed a package; a held `.pyd` blocks uv | never change the venv while any test runs; install at a landing, on a quiet box |
| the uv cache | `os error 32` under concurrent lanes | each lane sets `UV_CACHE_DIR=<scratch>/uv-cache` |
| scratch files | concurrent sessions share one scratchpad | `<scratch>/<lane>/` only |
| `upstream/main` | a peer's fetch moves it mid-run | read the SHA once at setup and pin `--base <sha>` |

## 4. Upstream files, the footprint, and the fixtures

- A lane that moves fork code out of an upstream file: one MOVE commit (`git mv`/move + import
  re-points, ledger rows re-derived with `scripts/upstream_footprint.py --ledger`), one CHANGE commit.
- **A lane never edits `tests/fixtures/upstream_footprint.json`.** The landing lowers it once, after the
  batch merge, to what `scripts/upstream_footprint.py` prints. A lane's footprint test red that says FELL
  is expected; ROSE is the lane's to fix.
- `--ledger` also rewrites rows other lanes left stale; a lane reverts any row that is not its own and
  reports it.
- A moved body that reads a private upstream name adds a row to
  `tests/fixtures/import_layers_grandfathered.json` naming the door it waits for.
- A lane that depends on another lane's moves is cut from THAT lane's branch
  (`worktree add … -b pb/f origin/pb/r`), not from main.

## 5. Landing a batch (one landing lane at a time)

1. Start when the first few lanes report; do not wait for the last one. Keep ONE landing agent and one
   `land/<batch>` worktree for the whole batch, and hand it each next group of branches with `SendMessage`.
   Each group is merged and its lanes' touched tests run at once, so conflicts and reds are found while the
   other lanes are still working. The gate (step 4) still runs once, after the last branch is merged. In the
   launcher's three end-of-wave landings on 2026-10-21, merging took two minutes and the remaining hour was
   one agent working one step at a time through about 250 tool calls.
2. Merge the branches into `land/<batch>` (a worktree beside the clone). Two conflict classes recur and
   have scripts: sorted one-entry-per-line lists (the grandfathered fixture) take the sorted union; the
   footprint ledger takes, per row, the side that changed it against the merge base. Validate JSON
   after.
3. Lower the footprint fixture; run its two gates.
4. Send peer sessions **"freeze"**; merge `origin/main` once; run the gate once
   ([[Running the tests]] § "What a landing runs, once"); a session-chain edit runs the chain's contract
   plus a sample, at a landing and at a release merge alike; nothing runs the whole tree (owner rulings 2026-10-16 and 2026-10-17, [[0016 — No whole-tree run, ever]]). Never gate before the last lane is merged, and
   never restart the gate because a peer landed — Phase B paid three ~75-minute passes for both.
5. Triage each named red with `scripts/run_tests_bundled.sh --confirm-red <file>` (pre-existing / load /
   caused). A caused red that one lane's change explains goes back to THAT lane: the landing names the lane and
   stops. The orchestrator revives that lane with `SendMessage` (same agent, same context), and the lane fixes the
   red on its own branch (`fix(<lane>):`, red-before/green-after in the body), in parallel with the other lanes'
   fixes. The landing re-merges and re-runs only the failing files. The landing itself fixes only a red that
   needs two lanes' changes to appear. In the launcher's land-w1021e, about eight of ten fix commits were one
   lane's own red, fixed one at a time by an agent that had not written the code. Regenerate generated files a move touched
   (`scripts/gen_gateway_contracts.py`).
6. Push `HEAD:main` (fast-forward), send **"main open"**, delete the landed rows, update memory.

## 6. Peer sessions

- Before a batch, send each live peer the file list your lanes touch (its fence); ask for theirs.
- A collision is sequenced, not shared: the earlier lane lands first, the later lane is cut after it
  (2026-10-16: the peer's H1 lineage stamp landed before lane H moved code into the same file).
- "freeze" holds every hermes `main` push, queue rows included, from every session — a backend
  session's queue commit landed mid-freeze once; name every session in `ListAgents`.
- A peer's held commits travel with a release merge as tags `held/<lane>/<sha>`.

## 7. Lane recipes

| lane kind | base | runs | lands |
|---|---|---|---|
| move / refactor (footprint) | `origin/main` or its dependency's branch | touched files' tests, `test_fork_import_layers`, `test_upstream_footprint` | batch |
| red triage | `origin/main` | each file alone, on a quiet box; `classify_reds_on_tag.py` for upstream reds | batch |
| release merge | `origin/main`, merge the TAG | [[Merging upstream]] Steps 1–6 | its own landing, owner approves the push |
| daily branch | `integration/upstream-daily` | [[Merging upstream]] § Daily | never lands; pushes the branch |
| upstream PR prep | `upstream/main` pinned SHA | `scripts/check --base <sha>`, the test red on the base | an idle branch + a body in the operator's `pr-bodies/`; the owner's PR branches stay idle while upstream is not taking them |
| design | `origin/main` | nothing | one doc commit, landed with the next batch |

The daily branch may be RESET when main has diverged from it past repair (owner 2026-10-16: 131
conflicts after v0.22.2 + Phase B): tag the old tip `archive/upstream-daily-<date>`, rebuild from
`origin/main` + `upstream/main`, replay only the `fix(merge)` commits that still apply, then move the
branch with `--force-with-lease=integration/upstream-daily:<old tip>`.

## The brief skeleton

```
<Lane name>: <one sentence of the outcome>. Never push main.
Setup (cwd X:/Eternia): fetch; worktree add X:/Eternia/.worktrees/hermes-<lane> -b <branch> <base>.
Scratch X:/Eternia/.worktrees/<lane>-scratch/, own UV_CACHE_DIR there.
Read: <one page> + <plan section / queue row>.
Steps: 1. … 2. … (decision rules inline: "if the tree differs from the plan, follow the tree and say so in the commit")
Run: per `Running the tests.md` § "What a lane runs" (name it; do not restate it). `scripts/run_tests.sh -j 4` while other lanes are live; never `-n`.
Host: shell scripts run with Git Bash's absolute path (`C:/Program Files/Git/bin/bash.exe`) — a bare `bash` from Python is WSL; never start a real serve or gateway; a test whose red writes real machine state runs once by hand.
Upstream files / fixtures: § 4 of this page (the brief names which apply).
Commits: one MOVE, one CHANGE; push per commit; never main; never amend/force/stash; leave the worktree.
Report (≤30 lines): tip SHA; per-file outcome; test counts + reds marked caused/pre-existing/load; ≤3 rows verbatim; tool-call count.
Trailer: Co-Authored-By: <the lane's model> <noreply@anthropic.com>
```

## What the orchestrator keeps

A RESUME line in session memory after every report (branch tips, what is merged, what is owed). A
lane's report lives only in its notification — copy what matters the moment it arrives, and file its
rows on arrival, by surface ([[TODO]]).

Before the closing queue commit of a landing, run `python scripts/remap_cited_shas.py --onto origin/main
<queue files>`; pin each HELD commit with `git tag held/<lane>/<sha> <sha>` (pushed).

## Never

Dispatch a follow-up into another lane's worktree (message the lane); remove a worktree a lane could
resume in; let a lane run the full suite; change the shared venv while tests run; paste this page into
a brief.
