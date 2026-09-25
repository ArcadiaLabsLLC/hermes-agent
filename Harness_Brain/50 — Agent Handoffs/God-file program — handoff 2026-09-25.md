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

## Known reds on `main` and who owns them

- `tests/tooling/test_fork_import_layers.py` — its LAST assertion only: the
  test venv has no `acp` extra. **Owner:** `pip install -e ".[acp]"` in the
  hermes-test venv. The layer list itself is EMPTY.
- `tests/scripts/test_upstream_footprint.py` — 195 → 200 files from the
  owner's auth/provider commits (`98f8a8caf9`, `38f9345633`, `09d722bb30`).
  **Owner:** raise the fixture with a `reasons` row per file, or move the
  edits behind the plugin.
- `tests/tooling/test_no_silent_package_patches.py` — times out under load
  (walks the tree once PER TEST; 15 s alone). Rowed in `fork-hygiene-queue.md`.
- `test_toolset_manifest` — upstream `tools/connectors` drift, not fork work.

## Owner calls open (rows carry `VERDICT … DESIGN`)

- The four `repo_context` dead-code rows: S43/S54 rulings said KEEP; lane
  Q-DEAD-B recommends reversing into one test seam.
- The 66 W0-G6-undeclared modules: each is imported by a DECLARED lower-layer
  module, so declaring it makes an upward edge — the importer's layer is wrong
  or the import must move (W3-B's row, four examples). Design work, one lane.
- The llama provider rename (needs a model-id ruling, then one coordinated
  wave with the launcher), GAP-PR-1/2 (resume upstream PRs?), the H2 sheet
  leftovers.
- The next upstream merge needs a design lane first (upstream `27df3b8847`
  rewrote the installer and deleted two modules serve imports).

## What is left to do, in order

1. ~~Land W3-D~~ — done (`105b3bbfba`). Run the gate set once on `main` before step 2.
2. **Program-end gate on the owner's word:** the full fork suite once
   (`scripts/run_tests_bundled.sh --scope fork --since 627f5ea4fa` or the
   validated-suite command in `50 — Agent Handoffs/Running the suite.md`),
   ~1 h; file every red as a row; that closes the program.
3. The queue rows that are lane work, not owner calls: `fork-hygiene-queue.md`
   (release-validation cluster, the silent-patch gate cache, the stage42 flag
   source-walk gate, the census substring suite selection), `runtime-queue.md`
   (the mcp_lane and canonical-id rows if W3-D left any, the delivery None
   rules across event emitters), `dead-code-burn-down-queue.md` (what the
   repaired census still files — read the census note first).
4. Cross-repo launcher rows in one launcher wave (auth argv, config keys →
   plugin manifest, llama rename, office-subscribe flake).
5. Owner-owed manual steps unchanged: paste the scheduled sync-job prompt into
   Codex cloud; delete `origin/automation/upstream-sync`; live venv re-sync.

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
