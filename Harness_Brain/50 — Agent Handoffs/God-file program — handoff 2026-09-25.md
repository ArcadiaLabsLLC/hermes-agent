# God-file program — handoff (2026-09-25, end of day)

Written by the orchestrator session that ran Wave 0 through Wave 3. Read this
before touching anything the program left open. The program's plan is
`docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md` (§3.1a–e
record every wave's sheets and hashes, §9 the rulings Q1–Q32); the layout
sheets are under `docs/agent-runtime-harness/planned/god-file-layout-sheets/`.

## Where it stands

- **Population zero.** `python scripts/god_file_probe.py --check` on `main`
  reads `[ds-size] units=0 total=0` (code counter, ceiling 800). Wave 0 baseline
  was 40 files / 73,870 code lines (2026-09-24); the morning of 09-25 was
  37 / 58,300. Every one of the 62 files the owner listed is a package now,
  with a skeleton map in its `__init__`, declared layers, tables in place of
  ladders, and a MOVE commit carrying a sha256 span proof followed by one
  CHANGE commit carrying its killing mutations and their recorded reds.
- **Owner rulings that bind any continuation** (all 2026-09-25, recorded in
  §9 and the queues): the goal is READABILITY for agents, not shaving under
  800 — a sheet opens with a skeleton, new modules target 100–300 code lines,
  floor 100 unless vocabulary/errors/table, cap 500, no flow across more than
  three modules; a lane is sized by RAW LINES (~5–7k), never file count; gates
  run ONCE per landed batch, not per landing; lanes commit one MOVE + one
  CHANGE per file, no fix-ups.
- **The last lane, W3-D, LANDED** on `main` at `105b3bbfba` (2026-09-25, after this
  note was first written): the read-model opens the chat SessionDB read-only
  (`snapshot/details.py::_default_persona_session_db`, upstream's own
  `SessionDB(read_only=True)`), the spurious `state.reconciled` is gone and its
  xfail marker deleted; the persona-id hoist's last two readers; the
  `mcp_lane` line logs a WARNING naming the exception instead of answering
  `""` silently; `patch_where_bound` reaches fork readers outside the package
  and the silent-patch gate walks its sites; the doc-cite gate is green.
  Two rows it filed: `open_chat_session_db` callers do not declare read vs
  write (runtime-queue); a fingerprint-cache test names a kill that does not
  kill (fork-hygiene-queue). **No lane is running. Step 1 below is done.**

## Landing protocol (what every landing did)

1. `git fetch origin`; `git merge-base --is-ancestor origin/main <tip>` (else
   rebase and CHECK THE RC before anything else — a push never shares a
   command chain with a rebase); prefold check
   `git merge-base --is-ancestor 0d5b7b8abc <tip>`.
2. No upstream file: `git diff --name-only origin/main <tip> | grep -Fxf
   tests/fixtures/upstream_manifest.txt` must be empty.
3. Mojibake: touched `.md`/`.json` grep for `\xc3\xa2` must be empty (Haiku
   lanes get `PYTHONUTF8=1` in the brief).
4. No `TAKEN` mark of the lane left, except on rows it ended `DESIGN`.
5. Push the tip to `main` (`git push origin <tip>:main`), then in the live
   checkout `git fetch origin && git merge --ff-only origin/main`, then
   `git worktree remove` the lane's worktree.
6. Gates once per BATCH of landed lanes, on `main`: probe `--check`,
   `pytest tests/tooling`, the footprint + inventory + doc-cite tests, ruff,
   `scripts/changed_line_mutation_check.py --list`. File what they show as
   rows; run them UNPIPED with the rc captured to a log.

## Known reds on `main` (re-measured 2026-09-25 evening, after the rulings wave)

- ~~`test_fork_import_layers.py` last assertion (no `acp` extra)~~ — CLOSED `478fcc5ba5`: `agent-client-protocol==0.9.0` pinned in `requirements-fork-dev.txt`, installed in the shared venv.
- ~~`test_upstream_footprint.py` 195 → 200~~ — CLOSED `478fcc5ba5`: fixture raised with a reasons row per file; the move behind the plugin surface is a runtime-queue § Seams row.
- ~~`test_no_silent_package_patches.py` timeout~~ — CLOSED `6bae3f2484` (lane GATES2): the census was already cached; the walk now has its own timeout budget and a test pins one walk per tree.
- `tests/test_coverage_claims_resolve.py` — stale test citations in `docs/gateway/` and the layout sheets. Row in `fork-hygiene-queue.md`.
- `tests/agent_runtime/test_no_kanban_dependency.py` — red since `7d28e958ad` (2026-09-24). Row in `runtime-queue.md` § Fork-owned.
- `ruff check .` — seven F821 in `tui_gateway/plugin_inject.py` since `177f275b77`. Row in `fork-hygiene-queue.md`.
- The validated suite on `7df3bee189`: **22,140 passed / 25 failed in 18 files**, the same 25 under a serial rerun; one closed at `cdd4d6dac5`, the 24 left are one class row in `fork-hygiene-queue.md` (mostly Linux-premise `hermes_state` tests running on Windows). Logs: `X:/wt/_holds/gates-0925/`.
- `test_toolset_manifest` — upstream `tools/connectors` drift, not fork work.

## Owner calls — RULED 2026-09-25 (owner: "take the recommendations"), and what each became

- The four `repo_context` rows → TEST SEAM as one unit, S54 pin inverted. **Landed** `3357c585cb` + `e9f8880283` (lane SEAM); rows closed.
- The 66 undeclared modules (+ the three upward-edge modules, found already closed) → one design sitting. **Sheet landed** `docs/agent-runtime-harness/planned/god-file-layout-sheets/layers-undeclared-2026-09-25.md` (lane LAYERS-DESIGN): MOVE 28 · RE-DECLARE 5 · DECLARE 33, five exec lanes L1–L5 by raw lines with landing order. Rows stay `DESIGN` until the exec lanes cut.
- The llama rename → one coordinated wave; the persona keeps its preset model id, only the provider id gains the alias. **Hermes half landed** `dd7ad19e73` (lane LLAMA-ALIAS): `is_local_llama_provider` is the one chokepoint, set-model accepts both ids. The launcher switch is a row in the launcher's `mission-control-queue.md`; the hermes drop row waits on it.
- GAP-PR-1/2 → stay paused; fold into the next upstream-PR lane (ruling on the row).
- The H2 bundle → split: the `runtime_commands` MOVE stays a row; the clock fold, the promote/realm tables and the `_pid_exists` check **landed** `0a4fac8aa2`..`d1c76146a8` (lane H2-REST; the launcher parses `reset_at`/`fetched_at` with `DateTime.tryParse`, so the Q22 wire question is closed for that envelope). The tables' flag reads were respelled at `cdd4d6dac5` so the flag-reachability gate sees them.
- The next upstream merge → design first. **Note landed** `docs/agent-runtime-harness/planned/upstream-merge-2026-09-25-design.md` (lane MERGE-DESIGN): 55 conflicts sized from the tree, two re-seats (serve prewarm → `agent.ssl_verify.install_truststore`; postinstall → upstream `pm`), seven ledger rows retire, Q1–Q8 with defaults. Prerequisite before the merge lane: `truststore` into the hermes-test venv.
- Plugin discovery → DISCOVER FIRST, **landed** `fbb6a3af2f` (lane GATES2); the office-subscribe flake → no change without the failing case id (ruling on the row); `runtime.level.get` → stays console (row closed; the launcher's scope-denied state is its row).

## What is left to do, in order

1. ~~Land W3-D~~ · ~~gate set on `main`~~ · ~~program-end suite~~ — all done 2026-09-25; the program is CLOSED with its reds filed (above).
2. The LAYERS exec lanes L1–L5 from the sheet (L1 before L2, L4 before L5, L3 independent), then the `runtime_commands` MOVE row.
3. The upstream merge lane per the design note, after the owner answers Q1–Q8 (each has a default) and `truststore` is in the test venv.
4. The queue rows that are lane work: the 24-red suite triage row, the kanban gate row, the coverage-claims and F821 rows, the auth-transport plugin-surface row, and the earlier `fork-hygiene-queue.md` / `runtime-queue.md` / `dead-code-burn-down-queue.md` rows unchanged from the morning list.
5. One launcher wave: the `llamacpp` switch, the level scope-denied state, the Update/Repair venv check (all in the launcher's `mission-control-queue.md`).
6. Owner-owed manual steps unchanged: paste the scheduled sync-job prompt into Codex cloud; delete `origin/automation/upstream-sync`; live venv re-sync.

## Traps this program measured (do not relearn them)

- A lane must never mutate the test guard's refusal list as a "killing
  mutation": one such mutation booted a REAL `hermes serve --port 8090` from
  the operator runtime. Refusal tests spawn a non-existent `hermes`. A lane
  reports a pid and never stops a process; the orchestrator matches the
  command line and creation time against the live serve before killing.
- The reach census used to file rows for what its TRACER could not reach:
  45 of 45 harness-family rows were live. It now pre-filters by static reach
  (`scripts/refactor_reach_census.py`); read the census note before spending
  a lane on its rows.
- A package-attribute monkeypatch reaches no module that bound the name by
  import — after every split, re-point patches to the binding module
  (`tests/_downstream/split_package_source.py::patch_where_bound`); the gate
  `test_no_silent_package_patches.py` holds it.
- The W0-G5 vocabulary arm is scoped to vocabularies a module declares or
  imports and counts name/Enum-member compares; a word spelled fork-wide gets a
  named constant in its single reader, not an enum.
- `store_events.emit_store_event` drops None-valued keys; check before folding
  any emitter onto it.
- Briefs say "touched tests = the files that import a module you changed, run
  ONCE"; a lane told "the agent_runtime tests" ran 330 files three times.
- Haiku cite lanes stop early unless the brief says the gate must be rc 0
  before the commit.

## Stale worktrees on the orchestrator's machine (local, not repo state)

`X:/wt/h-desk` (`feat/generic-desk-no-ownership`), `X:/wt/h-pr-bundled`
(`up/plugin-compat-bundled-skip`, a held upstream-PR branch), `X:/wt/upsync`
(`automation/upstream-sync-next`) — all predate this program; leave or prune
with `git worktree remove`, never `rm -rf`.
