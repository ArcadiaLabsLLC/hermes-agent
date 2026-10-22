---
type: handoff
tags: [handoff, process, tests]
---

# Running the tests

Read this before you run any test, gate or suite in this repository, and before you brief a lane
that will. `CLAUDE.md` carries only the pointer and the one rule that does damage before anyone
opens a page (never bare `pytest` over a directory). The fork's gate definition is
`docs/downstream-development.md` § "The fork landing gate"; this page is how a session uses it.

## The commands

```bash
$HERMES_PYTHON -m pytest -q -p no:cacheprovider <file>          # ONE file, debugging only (the test venv's python; see below)
scripts/run_tests_bundled.sh tests                              # THE LANDING GATE: --scope fork over `tests` (fork files + the upstream files the change reaches)
scripts/run_tests_bundled.sh --confirm-red <file>               # one named red: alone on HEAD and on origin/main → caused / pre-existing / load
scripts/run_tests_bundled.sh --affected [--fail-fast]           # fast loop: the tests your uncommitted edits can break; never a gate
# --scope full: RETIRED (owner ruling 2026-10-17, ADR 0016) — exits 2 unless every PATH is a file; nothing runs the whole tree
scripts/run_tests_bundled.sh --scope features tests             # on-demand quiet-box measurement → diagnosis.jsonl; never a gate
scripts/run_tests_bundled.sh --since-merge <merge-sha> tests   # a release merge's landing gate (Merging upstream.md step 7)
scripts/run_tests.sh <file>                                     # the per-file authority: one file, a leak, a disagreement
scripts/run_tests_idle.sh                                       # the timing files, ONLY on an idle box (refuses otherwise)
python scripts/dump_cli_contract.py --check                     # after any argparse change
python scripts/dump_payload_contract.py --check                 # after any character payload change
python scripts/doc_cite_adjacency.py --exclude archive --exclude planned          # the ruled doc-cite scope
python scripts/changed_line_mutation_check.py --list --base origin/main           # mutation inventory (safe unattended)
```

### When each run happens

Owner rulings 2026-10-17 ([[0015 — Upstream features the fork does not ship leave the suite and the boot path]],
[[0016 — No whole-tree run, ever]]). The purpose of every row is fast dev: each run proves what the
change can break, and nothing more. Nothing runs the whole tree.

| moment | who | command | covers |
|---|---|---|---|
| While writing code | a lane | `scripts/run_tests.sh <file>` | the one file; no cache |
| While writing code (fast loop) | a lane or the owner | `scripts/run_tests_bundled.sh --affected` | the tests your edits can break; never a gate |
| End of a lane | a lane | one `python -m pytest -q -p no:cacheprovider <files>` run over only the test files importing what it touched, plus the two name census gates when it touched Python | its blast radius and its own new names; no other gates, no scopes |
| Landing a batch | the landing session, once per batch, peers frozen | `scripts/run_tests_bundled.sh tests` (`--scope fork`) | fork files + the upstream files the change reaches, minus the skip list (unused features included, even when reached); cached greens skipped; a session-chain edit runs contract + sample |
| Release merge | the release lane | `scripts/run_tests_bundled.sh --since-merge <sha> tests` | the same, over what the merge produced (a chain edit: contract + sample) |
| Judging a red | anyone, quiet box | `scripts/run_tests_bundled.sh --confirm-red <file>` | that file alone on HEAD and on `origin/main` |
| Measuring the suite | on demand, quiet box | `scripts/run_tests_bundled.sh --scope features tests` | every file not on the skip list; writes `diagnosis.jsonl`; never a gate |
| Timing guards | after a landing that touches the turn-cost path, idle box | `scripts/run_tests_idle.sh` | the absolute-budget timing files |

Rare flags: `--rerun-known-reds`; `--no-cache` / `--cache-dry-run` / `--cache-reset`; `--git-audit`;
naming a skip-listed or idle-box file on the command line to run it.

**Never:** bare `pytest` over a directory; `--scope full` (it exits 2 unless every PATH is a file, and
then runs only those files); a timing run beside other work; a gate per lane.

### The rules behind the table

**`--affected` reads the gate store's records; it never writes them.** The change is the working tree
against HEAD plus untracked files (`--since REF` adds `REF...HEAD`). It runs: each edited test file; each
file whose latest record names a changed path — a module its process imported AND its own static imports
reach within two hops (a recorded module set is the whole process's: 4,847 of 6,733 records named
`agent_runtime/locks.py`), a non-`.py` file it opened itself, a non-session directory it listed that a path
joined or left (a path inside a whole new directory joins every ancestor that directory joined: a lane's new package reaches `test_duplicate_helper_bodies`, which lists `agent_runtime/`, `FH-GATE-CACHE-WHOLE-TREE-FALSE-GREEN`); for a changed path no record names, the `--scope fork` reach rules; the chain's contract
when a chain path changed. An ALL-sentinel file (it spawned an unrecorded program) runs only when a code
path changed and its imports reach it. A file tied only by a `.py` it opened (a whole-tree source walker) is counted in the header, never run. The skip and idle-box lists win; nothing is cached, sampled or
audited; `--cache-dry-run` lists without running; `--fail-fast` runs edited → direct importers → the rest
as waves. A session-chain or dynamic-import reach is not selected: the landing gate is the backstop. The
import memo lives beside the store (`.pytest_cache/hermes_affected_imports.json`; cold build ~8 s). The `Affected:` line prints
`Σ` (the selection's quiet estimates), `floor = Σ / -j` and the verdict: a **hub edit** is one whose Σ exceeds
`-j × 60 s` (`HUB_SECONDS_PER_JOB`), anything else an **under-a-minute edit**. An under-a-minute edit's bar is a
60 s wall; a hub edit's bar is `1.25 × floor + 20 s` (packing and start-up), and a floor over 60 s is the edit's
width, not a runner defect. The run closes with `wall W s vs bar B s` and `=== affected wall over its bar ===` when
W > B — a printed verdict, never an exit code (p10-suite B.1, pending the owner's ruling).

**A one-file debugging run names the test venv's interpreter, and reads a red twice.** A bare
`python` on this box is the system Python 3.12 without the test venv, so its import errors are
false reds; use the shared venv (`HERMES_PYTHON`, the venv under `~/.venvs/hermes-test`) or `scripts/run_tests.sh <file>`. With no `HERMES_PYTHON`, `scripts/run_tests.sh` uses the shared venv (`HERMES_TEST_VENV`, default
`~/.venvs/hermes-test`) and refuses when it is missing; it refuses any interpreter inside the live Hermes
home (owner ruling 2026-10-15; CI keeps upstream's activation path). `run_tests.sh` exports `PYTHONUTF8=1`, which hides a
`write_text`/`open` with no `encoding=`: a file red under the venv's bare pytest and green under
`run_tests.sh` is that difference, not a product bug — check it before filing a row (L6.19, L6.25,
L4.01 in `queue-sweep-2026-10-10/`).

**Upstream-PR and sync lanes pin the base by SHA and own their uv cache.** Run
`UV_CACHE_DIR=<lane scratch>/uv-cache python scripts/check --base <sha>`, with the SHA read once
(`git rev-parse upstream/main`) at the start of the lane. The default base (the merge-base with
`origin/main`) is thousands of commits behind upstream: ~313 blocking findings over 2,756 files and
its 900 s timeout (lanes up-door-*, 2026-10-07). A bare `--base upstream/main` moves when another
lane fetches mid-run and the code-health ratchet reports false `FILE_LINES`/`BLE001` reds
(up-sync-2, 2026-10-08). The shared uv cache locks under concurrent lanes (`os error 32`), hence the
per-lane `UV_CACHE_DIR`; if `uvx ruff@0.15.10` still fails on it, use the test venv's `ruff`.

**A sync lane runs `scripts/check --base <sha>` on EVERY branch it merges, not only the conflicted ones.**
A clean merge is not a clean check: upstream's ruff selection moves (RUF022/RUF100/UP006/RUF013/PIE807/PLW1510 at the
v0.21.7 sync), and four clean-merged branches carried reds only the check caught (up-sync-1015-c, follow-up up-check-1015).

**The landing gate runs over `tests`, not over three directories.** `--scope fork` (the default)
runs every fork-owned test file plus each upstream test file the change reaches by name, import or
conftest. Given `tests/agent_runtime tests/hermes_cli tests/hermes_state` it only searches those
three, and misses the upstream tests of an upstream file the change edits: on 2026-10-05 (landing
h-turn1, one edit to `agent/conversation_loop.py`) the three-directory form selected 689 files, the
whole tree 908 — 176 more fork files and the 42 `tests/agent/` files that test that function. The
whole tree on that day: 865 fork files (~9,400 test functions), 5,201 upstream (~43,200); the gate
ran 908 files / 13,621 tests in minutes.

**A session-chain edit runs the chain's contract plus a sample, at every landing and at the release
merge** (owner rulings 2026-10-16 and 2026-10-17 / [[0016 — No whole-tree run, ever]]). The
fork's root `conftest.py`, `tests/conftest.py`, anything under `tests/_downstream/`, `tests/_fixtures/` or
`scripts/_bundle_plugin/` (docs excepted), `pyproject.toml` and `requirements-fork-dev.txt` are loaded by
every test process. On an ordinary landing such a change reaches no file by itself: the gate runs
`tests/tooling/test_session_chain_contract.py` (one test per promise those files make — home isolation,
env scrub, process-state reset, the timeout, the `test-tmp` root, the dependency recorder, the root
conftest's git lock), every fork-owned `pytest.mark.gate` file (a gate proves a property of the tree,
not of what a change reaches; `scripts/gate_mark.py` is the one reader of the mark, the gate directory
asks it too), the files fork-owned or inherited that the rest of the change reaches (touched,
source, conftest, importer), and the smallest file of every test folder nothing else reached, and prints
`chain: contract + gates + sample — N contract file(s) + G gate file(s) + M sample(s)`. On land/q2 (9 chain
paths) that was 333 files where the whole tree was 6,675; on 2026-10-22 the gates add 72 files (land/w1021j's
chain-only scope ran none of them and missed three gate reds: FH-SCOPE-FORK-DROPS-SOURCE-GATES). A new promise the chain makes
gets its test there, with its killing mutation. The release merge (`--since-merge`) treats a chain path
the same way: contract + sample, never every file; an interaction no promise names is caught by a promise
added when it is found, not by a whole-tree backstop.

**No whole-tree run, ever** ([[0016 — No whole-tree run, ever]], owner 2026-10-17). `--scope full` and
every-file runs are retired (`--scope full` exits 2 unless every PATH is a file): a landing runs
`--scope fork`, a release merge runs `--since-merge`, and both run fork files plus the upstream files
the change reaches, minus the skip list (P0 freeze files, proven reds, and the features ADR 0015 marks
unused — upstream's Docker image among them — which a landing or release merge never selects, even
when the change reaches them). `--scope features` runs every file not on the skip list: an on-demand
measurement on a quiet box that writes `diagnosis.jsonl`, never a gate. If a scope is in doubt, list what it will
run before running it (`select_scope` in `scripts/run_tests_bundled.py`). After a freeze or a killed
run, read the interrupted log's last lines before re-running.

**The upstream skip list.** `tests/fixtures/upstream_skip_list.txt` names upstream-owned test files
the bundled runner does NOT run, in any scope: the four P0 freeze files today, and upstream reds
as they are proven (one row per file: `path · why · upstream SHA`, `why` starting `P0`, `env` or
`upstream`). A listed file runs only when NAMED on the command line — reaching it by import, source
or conftest does not (owner ruling O1); the run prints every file it skipped and why. A fork file is
never listed (fork reds are fixed): `tests/scripts/test_upstream_skip_list.py` refuses one. A row is
added only after the file was run once, bare, and seen red on `origin/main`; the weekly merge lane
re-checks the `env`/`upstream` rows (`Merging upstream.md` step 5b). The P0 four run only under the watchdog/VM the P0 row names.

**What a run prints about itself.** After the Summary line, `=== Run cost (Stage 0) ===`: processes
by kind (bundles, solos, known reds run once, shards and whole checks, re-runs, straggler retries), worker-seconds and utilization, Σ per-file seconds and the floor at that worker count,
start-up seconds, the seconds spent re-running red members, the critical-path process, the idle tail
and the 20 slowest files. The same numbers, with every red file's failing node ids, are appended as
one JSON line to the gate store's `runs.jsonl` (below; it was `.pytest_cache/hermes_bundled_runs.jsonl`
in the checkout, which a landing worktree took with it), with the
files whose last attempt timed out (`timed_out`) and the test count of every file that took ≥ 90 s
(`tests`, the shard planner's input) and the cache's block (`cache`: skipped, sampled, seed, misses
by reason, audit defects and flakes). Quote that line in a landing report instead of reconstructing
timings from the log.

**The diagnosis also counts tests, per file** (p10 S-A1, row `FORK-PATCH-IN-TEARDOWN`):
`body_patches` is the tests whose body left a `monkeypatch` entry live into fixture teardown;
`late_fixture_patches` is the tests where a fixture the body requested late (`request.getfixturevalue`)
pushed one; `teardown_errors` is the teardown-phase errors, with up to 20 node ids. They ride
`diagnosis.jsonl`, the `counts` block of the `runs.jsonl` line and the `=== Diagnosis ===` block. The knob
`HERMES_TEST_BODY_PATCH_UNDO` (default `on` since p10 S-A3, after a clean ON/OFF features diff;
`pytest.mark.body_patch_undo("on"|"off")` wins) undoes a body's own entries at call end, before any fixture
tears down (`tests/_downstream/body_patch_scope.py`). `=off` is the way back, kept one release; a file that
needs it is marked `body_patch_undo("off")` through `id_markers` with a dated row, never allowlisted in the hook.

An abnormal bundle also records `bundle_diagnostics` in that same line: original process/session
statuses, ordered members, last observed member, failing IDs and bounded, redacted output. The
terminal prints it even when isolated retries pass. Summary counts describe final attempts;
a zero exit after retries is not a clean first attempt. This receipt survives scratch cleanup
and worktree removal. `scripts/run_tests_bundled_plan.py::RunLedger` owns it.

**Bundles are planned by duration.** A bundle closes at `--bundle-size` files (20) or before its
cached seconds pass `--bundle-seconds` (120); a file cached slower than `--solo-seconds` (60) runs
alone, and solos are submitted before bundles. Both read the store's `durations.json` (clean-pass
seconds, repo-relative POSIX keys only), over the legacy `test_durations.json` files for one release;
pass `0` to either flag to switch it off.

**The green-result cache skips a file nothing it depends on changed since its last green on this box**
(fast-gate §1; owner rulings Q1, Q2, Q6). Every pytest process of a bundled run loads
`-p hermes_dep_record`, which records what each test file imported, opened, listed and spawned; a
green writes that record and a key (the blobs of every recorded path against the tree the run started
from, what builds a test process — `scripts/_bundle_plugin/`, `run_tests.sh`, `run_tests_parallel.py`,
`_fork_runner.py`; never the bundled runner's own scheduling — `uv.lock`/`pyproject.toml`, the
interpreter and its packages, the `HERMES_*`/`TZ`/`LANG` environment) to the GATE STORE: `<primary checkout>/.pytest_cache/hermes_gate/`,
per clone, shared by every worktree, git-ignored, never committed. A file that spawned a process
depends on every tracked file outside `docs/` and `Harness_Brain/`. The start-up line says
`Green-result cache: N of M file(s) skipped as cached green; audit re-runs S hit(s) (seed X, 5%,
min 25); misses: <reason> <count>, …`; a skipped file's progress line reads `(cached; green <date>
<s>s, 0.0s)`. Never cached: a NAMED file (O1), a known red, a red, a FLAKY file (two greens in a row
before it is cached again), an isolation leak, an unreached member, a straggler retry, a sharded file,
any run with a pytest argument other than `-q`/`-v`, and a green older than 14 days. **The audit**
re-runs `max(25, 2 %)` of the hits (5 % for the first three skipping runs) as ordinary members; a
sampled hit red in the run and red again alone prints `=== ✗ CACHE AUDIT: N cached-green file(s) red
on re-execution ===`, exits 1 and bumps the store's generation (the next run is cold). **A CACHE AUDIT
red is a defect row (a key missed a dependency) in `fork-hygiene-queue.md` with that block, never a
reason to clear the store and move on.** Opt out for one run: `--no-cache` or `HERMES_GATE_CACHE=0`;
report without skipping: `--cache-dry-run` (lists the would-skips and why the rest run); make every
green miss: `--cache-reset`; reproduce a sample: `--cache-seed <seed>`; another store: `--cache-dir`
or `HERMES_GATE_CACHE_DIR`. A lane's `scripts/run_tests.sh <files>` never touches the cache.

**A slow file is sharded only when the run is tail-bound** (fast-gate §3). When Σ estimates / jobs
is under twice the longest estimate — a small run whose makespan is its longest file — a file cached
green ≥ 90 s with ≥ 2k recorded tests runs as k = min(4, ceil(s/45)) processes, each
`-p hermes_shard --hermes-shard=i/k` (a crc32 of the node id picks the shard). The start-up line says
`tail-bound: sharding N files into M shards` or `work-bound: no sharding`; a cold `--scope features`
run and a normal landing are work-bound. A file is green only when every shard is; a red shard runs the file
once whole (`whole-check`): green whole is printed before the Summary as a candidate for
`scripts/test_files_unsharded.txt` with the observed shard diff (its tests depend on each other's
order — add the line and file a row), red whole is an ordinary red. A known red and a listed file
are never sharded. Test counts come from the run record, so the first run after a reset only records.

**A red is not paid for twice** (owner ruling O5; fast-gate §2). A file red or timed out in the last
recorded run is a KNOWN red: it runs once, alone (`known-red` in the progress line), with no flake
retry, no straggler retry and a capped timeout — `min(300, max(60, 2 × its last green seconds))`, or
120 s when it has never been green on this box (owner ruling Q5; the first load-induced false timeout
lifts 120 to 180 in the plan). Its failure output ends with the cap and, when its failing set moved
since the record, `failing set changed: +N −M` with the ids; a capped timeout prints
`known-red timeout cap <N>s; run alone: scripts/run_tests.sh <file>`. A NEW red still runs bundle →
re-run alone, and an isolation leak is still named. To see a known red at full time:
`scripts/run_tests.sh <file>`. A known red whose file and recorded dependencies (the green cache's key) are
unchanged since its red is not run at all: it prints `known-red, skipped` and still counts red;
`--rerun-known-reds` runs every one (row q-gate, 2026-10-16: 24 known reds were Σ 2,958 s).

**Bare `pytest` over a directory is forbidden.** It runs the updater tests in-process, and those run
`git branch -f main origin/main`: it detached 11 unpushed commits from the primary checkout on
2026-08-01. The runners isolate files in hermetic subprocesses, find the shared test venv, and run
8 workers per file run; the bundled landing gate defaults to 12 (`DEFAULT_JOBS` in
`scripts/run_tests_bundled.py`: quiet 16-thread box 2026-10-18, --scope fork, 0 reds at 8/10/12/16,
646.7 / 585.2 / 539.2 / 512.1 s, CPU avg 64 / 71 / 78 / 88 %; do not raise it further).

A test whose wait bound exceeds 30 seconds declares `@pytest.mark.timeout(N)`: `addopts` carry
`--timeout=30`, and pytest-timeout kills a longer test before it can say what went wrong.

## Environment notes (carried from the retired "Running the suite" page)

- `tests/acp` cannot collect from a worktree (the editable install resolves to the primary) — run
  it from the primary or name the lanes explicitly.
- `HERMES_TEST_TMP_ROOT` → a Defender-excluded throwaway dir speeds a run; `X:/Eternia` is already
  excluded on this box. It is set once and defaulted by the runners: `scripts/run_tests.sh` (and the
  bundled runner, which sources it) uses a `test-tmp` directory beside the checkout or beside a
  worktree's primary checkout when the variable is unset, and exports it as TEMP/TMP for the RUNNER
  too, so its `hermes-pytest` scratch and upstream's `hermes-test-home-*` stay out of `%TEMP%`
  (D3.08). The plugin's hourly prune also removes this repo's own aged leftovers from the system
  temp dir (`tests/_downstream/temp_prefixes.py`) and names each in `<root>/.temp-sweep.log`. Bare
  pytest gets none of this — one more reason not to run it.
- A failure seen only in a parallel or bundled run is compared as a SET against a serial
  `scripts/run_tests.sh` run of that file before it is believed (the bundled runner names an
  isolation leak itself: red bundled, green alone → `scripts/test_bundles_unbundled.txt`). A
  `known-red` line ran alone once, capped, never in a bundle this time; it is not evidence of a leak
  either way.
- Pre-existing reds are never baselined ([[0010 — Stale sweep and ratchets first, never baseline]]).
- **A bare `bash` spawned from Python on Windows is WSL, not Git Bash.** `CreateProcess` searches
  `C:\Windows\System32` before `PATH`, so `subprocess.run(["bash", …])` reaches
  `C:\Windows\System32\bash.exe` even from a Git Bash shell whose own `bash` is Git's (build-1011-B1
  built a 558 MB test env under the WSL home that way). A helper or lane that needs bash from Python
  names Git Bash by its absolute path, `C:\Program Files\Git\bin\bash.exe`; the upstream tests that
  spawn a bare `bash` are judged by the shell they reach (env-gap rows `782e29b1e28`, `bd9ed2faf98`).
- A stale `index.lock` after a killed run (zero bytes, no git alive) is `rm`'d once the interrupted
  log's last lines are read. The fork's root `conftest.py` sets `GIT_OPTIONAL_LOCKS=0` for every test
  process, and the bundled runner passes it to its own git, so git's opportunistic index refresh no
  longer takes the lock (design sweep D3.16). To name a test that still runs git against the checkout,
  run the gate with `--git-audit` (`scripts/run_tests_bundled.sh --git-audit tests`) and read
  `.pytest_cache/hermes_git_in_checkout.jsonl` (`{file, nodeid, argv, cwd}` per call; it
  over-approximates — every verb, and a positional repo path is not parsed).

## How to run a heavy command (measured — do not improvise)

The launcher mined 24 days of agent transcripts (`EterniaLauncher/docs/tooling/AGENT_WALL_TIME_2026-09-18.md`):
five habits cost about 390 minutes a day.

- **Pass an explicit `timeout` on every test, build or census call.** The 120-second default killed
  646 calls and returned nothing; 329 more died at the 600-second ceiling.
- **Run a long command as a BACKGROUND task and wait for the completion notification.** Never
  `sleep`, never an `until … grep` loop, never `tail -f | grep -m 1` — 772 polling calls cost 35 hours.
- **Never re-run a byte-identical heavy command with no edit in between.** 731 did; 17 hours.
- **Never pipe a heavy command through `tail` / `head`.** Redirect to a log file, capture the exit
  code UNPIPED (`; rc=$?; exit $rc`), read the log after. Under `pipefail` a gate piped through
  `tail` hides its own red.
- **Every watcher has a bound** (owner ruling 2026-10-21, `FORK-ORPHAN-GREP-WATCHERS`). A log watcher
  — `tail -f log | grep --line-buffered -E "exit=|DONE"` and kin — does not die with the session that
  started it: 17 were found with dead parents on 2026-10-19 and three more by 2026-10-21, and one
  `grep -rln … /` from a launcher session burned ~16,000 CPU-s and skewed a measured A/B. So a
  watcher is either the Monitor tool's until-loop (it carries its own timeout) or wrapped in
  `timeout <seconds>` no longer than the command it watches
  (`timeout 900 tail -f "$log" | grep -m 1 --line-buffered -E "exit=|DONE"`); a search names a
  directory, never `/` or a drive root. Bounding is the fix, not a periodic kill. A fork script that
  follows a log carries the same bound in code (checked 2026-10-21: none under `scripts/` follows
  one — `unattended_suite_run.ps1` reads `-Tail 40` once after its child exits).
- **One heavy run at a time on this box.** Two contend for the same cores; a second landing racing
  the first costs both a re-merge and a second gate run.
- **The bundled runner claims the launcher's machine-wide heavy-run slot** (owner ruling 2026-10-21,
  `FORK-HERMES-TEST-ENTRY-POINTS`): `scripts/run_tests_bundled.py`, run as a script, holds one of the
  slots of `EterniaLauncher/tool/heavy_run/slot_lock.dart` (default 2, `ETERNIA_HEAVY_SLOTS=off`
  disables) for its whole run, and a run that finds them all busy WAITS and names each holder every
  20 s — the cap working, not a hang. `scripts/run_tests_bundled_slot.py` speaks the Dart file
  contract (`<machine temp>/eternia-heavy-slots/slot-<i>.lock`, OS lock on byte 0, JSON note from
  byte 1); `_fork_test_env.sh` names the directory before TEMP moves to the test-tmp root. A child of
  a holder (`ETERNIA_HEAVY_SLOT_HELD`), a runner a test spawned, `--cache-dry-run` and `-h` claim
  nothing. The per-file `scripts/run_tests.sh` claims no slot.

## What a lane runs, and what it never runs
- **A contract change runs the tests that pin it, and the producer names them** (owner ruling
  2026-10-10, convention, no gate). A producer of a pinned contract — an envelope, a snapshot set,
  an event count, an argv, a producer walk — carries the pinning test files in its docstring, and a
  lane that changes the producer runs those files with its touched tests. Four contract-moving lanes
  left their pins red before this (`d677799521`).
- **While implementing:** `ruff` (or `pyflakes`) on the touched modules, foreground, explicit
  timeout. Nothing heavier.
- **At the end of the lane, before the report:** ONLY the test files that import a module you
  touched — `grep -l` the module paths under `tests/` — as one
  `python -m pytest -q -p no:cacheprovider <files>` run, in the background, with a log and the exit
  code captured unpiped, timeout at least 600000. That run is serial: the test venv carries no
  pytest-xdist (not a declared dependency), so `-n` errors `unrecognized arguments: -n`; a lane that
  wants parallelism names `scripts/run_tests.sh -j N <files>` (file paths only — a node id among
  its arguments runs nothing for the other files). A lane never runs the landing gate, the tooling
  gates, the docs gates or the contract dumps; those are the landing's job, once.
- **One exception: a lane that touched Python adds the two name census gates to that same run** —
  `tests/agent_runtime/test_duplicate_helper_bodies.py` and `tests/tooling/test_no_ladder_routing.py`
  (~50–70 s each). They walk the whole fork, so no importer `grep` and no `--affected` run reaches
  them from a new module, and only the lane can cheaply rename its own new names: two landings
  (f9ef5d33aa; hermes 76a5a16158, land/w1020-estore) found a lane's NEW `_read` /
  `_namespace_manifest` duplicate or NEW ladder only at the landing gate, each a fix-and-regate
  cycle (`FH-LANE-RUNS-NEW-NAME-GATES`). A red there that `main` shares is compared by its `NEW` /
  `GREW` lines, as § Calling a red pre-existing says, never fixed in passing.
- **Launcher lanes and landings run `*_test.dart` files only.** A `grep -l` under `test/` also
  matches fixtures and helpers; on 2026-10-05 it handed `flutter test` the helper
  `detached_serve_starter.dart` and the run hung ten minutes. Filter the list to `_test.dart`.
- **A fork test never goes inside an upstream test file.** A test of a fork seam in upstream code
  lives in a fork-owned `tests/**/*_downstream.py` that imports upstream's fixtures. Appending to an
  upstream test file adds a file to the fork's upstream footprint (`tests/scripts/test_upstream_footprint.py`);
  landing h-turn1 had to move one (`92be2b3a10`).
- **A raise of the upstream footprint cites an owner ruling.** A new `reasons` row in
  `tests/fixtures/upstream_footprint.json` carries `owner_ruling` (date + where recorded), or the
  edit moves into a fork module; `test_every_raise_cites_an_owner_ruling` reds otherwise (owner,
  2026-10-15; the field is described in `upstream-footprint-ledger.md`).
- **A CHANGE commit carries its positive control:** the defect planted on a throwaway copy, the red
  pasted into the commit body, reverted. A new gate lands with its killing mutation recorded. A
  control that has not been run is a belief.

## What a landing runs, once

**One landing gate (`--scope fork`) per BATCH, never per lane** (owner ruling 2026-10-06, after waves 11–13 each paid a
15–18 minute gate for a single lane). A finished lane waits for the batch; the landing merges every ready
lane, then runs the gate once. A lane that finishes while a gate is running joins the next batch unless it
touches nothing the running batch touches.

**Gate once, at the end, with main still** (owner 2026-10-16: "best to only run it at the end"). Start the gate only when every lane of the batch is merged; send peer sessions "freeze" first so `main` cannot move under it; merge `main` once, gate once, push, "main open". A peer batch that lands mid-gate never restarts the gate: the next batch picks it up. Phase B (2026-10-16) paid three ~75-minute passes on one batch by gating before its last lane and re-gating after each peer landing; a batch that edits hub files (`tools/registry.py`, `hermes_state.py`, `tui_gateway/server.py`) selects ~2,600 files, so each wasted pass is over an hour.

Concurrently: (a) the landing gate `scripts/run_tests_bundled.sh tests` in the one heavy slot;
(b) the tooling gates — `test_no_frozen_hermes_home`, `test_tombstone_registry`,
`test_duplicate_helper_bodies`, `test_cli_contract_dump`, `test_payload_contract_dump`, the
legibility floor, the upstream footprint and the namespace gates (they are fork files, so the
landing gate already runs them; run them alone after a re-merge); (c) `changed_line_mutation_check.py` for any new
gate; (d) the docs gates. For the launcher half, `flutter test` on the `*_test.dart` files that
import a touched file. After a re-merge, only (b) re-runs; the gate runs again only if an incoming
commit touches a file the batch touches.

## The idle-box files: after the gate, on an idle box

The timing positive controls and the turn-cost guard keep their absolute budgets and run only on an
idle box, serial, never inside a parallel gate (owner ruling 2026-10-10; design sweep D3.01 / D3.09:
under gate load the OS starves the GIL hog instead of the reader, and a 500 ms stall floor read
76–232 ms). `scripts/test_idle_box_files.txt` lists them; their tests skip unless
`HERMES_TEST_IDLE_BOX=1`, and the bundled gate does not select them unless named (it prints
`idle-box: N file(s) not run`). A lane running `scripts/run_tests.sh` on one of them sees it skipped,
by design.

When a batch touches `agent_runtime/send_window_receipt.py`, `agent_runtime/stream_gap_receipt.py`,
`agent_runtime/transport_phase_trace.py` or the turn-cost path (anything
`tests/agent_runtime/test_turn_cost_guard_downstream.py` imports), the landing runs
`scripts/run_tests_idle.sh` AFTER the gate, with nothing else running. It refuses (exit 3) and names
every live pytest / `run_tests` process while the box is busy; `--check` asks only that. It runs the
list at one worker with `HERMES_TEST_IDLE_BOX=1` and appends `{"kind": "idle", …}` to
the checkout's `.pytest_cache/hermes_bundled_runs.jsonl` (a receipt; the gate's own record is the
store's `runs.jsonl`, and the known-red read skips an idle line either way): quote it in the
landing report. An idle run that still reds is a new row carrying its receipt line
(`stall_samples`, `stall_max_ms`, `max_lag_ms`), never a lowered floor.

## The Launcher QA MCP from a session in this repo

`scripts/launcher_qa_mcp.py` starts the EterniaLauncher's `launcher_qa` MCP server with
everything machine-specific read from the environment: `STAGEC_QA_REPO_ROOT` (or
`ETERNIA_LAUNCHER_ROOT`) names the launcher checkout; `STAGEC_LAUNCH_HELPER` defaults to that
checkout's direct-EXE helper; the prebuilt server is used when present, else `dart run`. Register
it once with `claude mcp add launcher_qa -- python scripts/launcher_qa_mcp.py`; `--print` shows
what it resolved. A missing variable is a refusal naming it, never a half-configured server
(owner ruling 2026-10-15).

## After a landing that touches the chat path: the live latency check

Offline guards pass on small fixtures while live chat regresses on real-sized stores and a real
launcher (2026-10-06: the pre-request window went 0.4 → 1.2 s and the launcher rebuilt the whole page
per turn, with every gate green). So after any landing that touches the chat-turn path (admission,
prewarm, prompt/context build, the provider client, the stream, or the launcher's chat surfaces),
the operator rebuilds, waits about 2 minutes after boot, sends a few turns, and someone runs:

```
hermes harness observe turn-timing --check
```

It reads the last turns' receipts (and the launcher's `[MissionChatTiming]` lines when present),
groups them cold / after-idle / warm, and prints PASS or FAIL per span against the committed budgets
and the 2026-10-07 baseline (exit 1 on any FAIL). Provider spans are reported, never failed. A FAIL
is a regression to row before the next landing, not a number to loosen. The baseline, budgets and
groups are Decision 0014.

## Calling a red pre-existing

`main` is not green: on 2026-10-05 the whole-tree gate read 70 failing tests in 35 files on `main`
itself. A red is pre-existing only when it is PROVEN so, one file at a time and never by the suite (owner
ruling 2026-10-16): `scripts/run_tests_bundled.sh --confirm-red <file>` runs the file alone on HEAD and in
a detached worktree of `origin/main` cut under `worktrees/` beside the clone (removed after), compares node by
node and prints `caused` (with the nodes red only on the branch), `pre-existing` or `load` (green alone:
the bundle or the box, never the branch). By hand, for a launcher file:

1. Cut a detached worktree at the merge-base (`git merge-base HEAD origin/main`) — never in the
   primary checkout.
2. Run the SAME failing files there (`flutter test <files>`).
3. Compare test node by test node. A node red only on the branch is the branch's.
4. **For the drift gates, compare the violation lists, not the verdict.** The legibility floor,
   duplicate helpers, doc-cite adjacency, the upstream footprint and the method-lane chokepoint are
   red on `main` already, so a branch can add violations inside a test that was red anyway. Diff
   their `NEW` / `GREW` / cite / file lines between the two logs; landing h-turn1 found three of its
   own violations that way inside tests `main` also failed (`cd2ed22ea8`).

A pre-existing red is named in the report with that proof, never fixed in passing and never
baselined; if it is not already a row, file it in `fork-hygiene-queue.md`.

## The gates are tests, not hooks

There is no pre-push hook (deleted 2026-09-03, `504953f6ad`); nothing gates a push, and every check
above is something someone runs. `main` went red unreported twice because nobody did (`6979bad59`;
2026-09-04). Fork CI is running again: [main run 38312372163](https://github.com/ArcadiaLabsLLC/hermes-agent/actions/runs/38312372163)
passed on 2026-10-12. `fork-gates.yml` checks selected mutation claims, the tombstone registry and
docket stage claims; it does not run the bundled landing suite. The upstream `ci.yaml` workflow
is ACTIVE on `main` and has not finished green once since 2026-09-26 (checked 2026-10-21, lane
w1021h-tooling): its Python tests (now two slices, not eight), JS, Rust and Windows jobs ask for
`ubuntu-latest-32-core` / `windows-latest-32-core` / `windows-latest-32-arm-core`, which the fork's
organisation does not have, so they queue for a day; the queued run (39494050964, `79d3fa5754`)
holds the `ci-refs/heads/main` concurrency group, and every later push's run waits and is cancelled
by the next push. The jobs that do run on standard runners read 18 ruff (`UP006`/`RUF100`) and 2
Windows-footgun findings on `main`. GitHub Issues are on, so `notify-main-red` can file once a run
completes red. Verify the workflow, jobs and exact source SHA before treating a green run as evidence. `scripts/unattended_suite_run.ps1` is a report, never a gate.

**When a contract dump reds, read the diff before regenerating.** A removed command, flag or payload
key is a launcher button that now exits 2 or a stale default acted on; re-vendor the launcher's copy
in the same wave.
