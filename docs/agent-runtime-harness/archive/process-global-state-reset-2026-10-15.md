> **BUILT** — archived 2026-10-27 from `planned/` (lane w1027j-h-tri-b); landed: S1-S2 `116deb8170`, S3 `ec775d1226` (2026-10-16); S5's upstream PR is deferred (row `FH-DEFER-PR-REGISTRY-SNAPSHOT-RESTORE`).
> History, not truth: the domain docs and the queues hold what is current.

# One owner for process-global state between tests (design)

Status: BUILT 2026-10-16 except S5's posting; approved by the owner 2026-10-15 (all
recommendations). Row: fork-hygiene-queue, "Process-global state, the CLASS" (closed by lane
r-isolation).

- S1: `agent_runtime/process_state.py`, the owners' registrations (lane h2-redact) and the
  fixture swap (`tests/_downstream/conftest_plugin.py::_reset_snapshot_catalog_memos` calls
  `reset_all_process_state()`, lane r-isolation; killing mutation recorded in its commit).
- S2: `builds.detect` registers its reset (h2-redact).
- S3: `tests/_downstream/tool_registry_scope.py`, autouse through the plugin; tested by
  `tests/tooling/test_tool_registry_scope.py` (killing mutation named in that file, recorded
  in its commit).
- S4: the census, REPORT mode, allowlist seeded with 162 rows "reason owed" (h2-redact).
- S5: the PR body (`docs/agent-runtime-harness/upstream-prs/registry-snapshot-restore-body.md`)
  is drafted; the code lands upstream, never as a fork edit to `tools/registry.py`. Posting
  waits with the idle PR branches; S3's fixture switches to the door when it merges.

## In plain English

Several modules keep state for the whole Python process: the tool registry,
build detection's on/off switch, the resident-chat registry, the idle keeper,
assorted memos. When one test leaves that state changed, a test much later in
the same bundle fails for no reason of its own. Each time, someone finds the
leak, adds one more line to a cleanup fixture, and waits for the next. The fix
is to make "I hold process-global state" something a module **declares**, with
its reset beside it, and have one fixture reset everything declared — plus a
gate that finds state nobody declared.

## Evidence

- The ad-hoc version today: `tests/_downstream/conftest_plugin.py`
  `_reset_snapshot_catalog_memos` (l.432–481) hand-resets two memos, the chat
  lane bundle, the resident-chat registry (added by `53ccebb5e1`, L7.07) and the
  idle keeper — five owners in one fixture, each found by a red.
- Other instances: `Harness_Brain/20 — Active Initiatives/queue-sweep-2026-10-10/L6-outcomes.md`
  L6.08 (`builds.detect` enabled by a serve boot leaked `no_slots_declared` into
  a golden; fixed `f8e473b846` by pinning detection off in one generator) and
  L6.30 (585 leaked tool registrations; fixed `276fba379b` by running the arm
  in a fresh interpreter).
- Upstream tool registry (`tools/registry.py`) has per-name
  `snapshot_registration` (l.534), `deregister` (l.768) and
  `restore_registration` (l.826), but no whole-registry snapshot/restore.

## Target shape

- `agent_runtime/process_state.py` (`models`-layer, no imports): 
  `register_process_state(name, reset)` and `reset_all_process_state()`. Each
  fork module that owns a process global registers its own reset **at import**,
  next to the global (memos, registries, keeper, `builds.detect._ENABLED`).
- One autouse fixture calls `reset_all_process_state()` before each test and
  replaces the hand-written lines in `_reset_snapshot_catalog_memos`.
- Tool registry, fork side now: a fixture records registered names (per scope)
  before the test and, after it, deregisters names added and restores names
  replaced, using the existing per-name API — no upstream edit.
- Tool registry, upstream later: a door PR adding `ToolRegistry.snapshot()` /
  `restore(snapshot)`; the fork fixture switches to it when merged.
- **Gate (negative, source walk is right here):** fork module-level assignments
  of a mutable value (`dict`, `list`, `set`, a class instance, a `global`
  rebinding) that are not registered and not in an allowlist with a reason →
  red.

## Owner decisions (recommendation first)

1. **Declared registry vs keep growing the fixture.** Recommend the registry;
   a fixture list is exactly the hand-maintained enumeration the gate rules warn
   about.
2. **Fresh interpreter for heavy arms (the L6.30 fix) stays?** Recommend keep it
   for the live-registry arm only; do not spread it — it costs a process start
   per arm.
3. **Upstream door.** Recommend drafting `snapshot()`/`restore()` as an upstream
   PR body in the up/ lane, posted by the owner in the next posting sitting
   (nekwo cannot open PRs). The fork-side fixture does not wait on it.
4. **Gate strictness.** Recommend starting with the census REPORTED and an
   allowlist seeded from today's population, flipping to enforced once the
   allowlist only holds reasoned entries.

## Slices (build order)

- **S1 — `process_state.py` + fixture**, migrate the five owners in
  `_reset_snapshot_catalog_memos`. Killing mutation: drop the resident-chat
  registry's registration → the L7.07 leaker node plus its two victim files in
  one process reds (the control recorded in `53ccebb5e1`). Record it.
- **S2 — `builds.detect`** registers its reset. Killing mutation: remove it and
  run the serve-boot test then the hydrate golden in one process → red.
- **S3 — tool-registry fixture** (fork side). Killing mutation: skip the
  deregister step → a test that registers a throwaway tool followed by one that
  asserts the registry's names reds.
- **S4 — census gate** (`tests/tooling/test_process_globals_declared.py`),
  REPORT mode with the seeded allowlist. Killing mutation: add an unregistered
  module-level `_CACHE = {}` in a scratch fork module → it appears in the report
  (and reds once enforced).
- **S5 — upstream draft** for `ToolRegistry.snapshot()/restore()` with tests.

## Blast radius

`tests/_downstream/conftest_plugin.py`, one new fork module, a one-line
registration in each owning module (~10 to start), one new tooling test. No
upstream file changes until the door PR.

## What it retires

Leak-by-leak fixture growth, the next "585 leaked registrations", and the class
row itself once the census is enforced.
