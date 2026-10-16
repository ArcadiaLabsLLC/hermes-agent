# A revert arm for realm-synced levels, and one count for them (design)

Status: PLAN — written 2026-10-15; owner approval owed for the slice order (the
substance is ruled: 2026-10-10, "fold the `levels` status row into
`store_drift` (one count)"). Row: runtime-queue, "A realm-synced LEVEL has no
revert arm, so `realm sync status` reports it and the operator cannot act on it".

## Build status (lane h4-seeds, 2026-10-16)

- **S1 built** — `realm_revert._FAMILY_ARMS` is the one dispatch table; the arm
  functions for the store rows live in `realm_revert_writes`.
- **S2 built** — `realm_sync/level_drift.py` (rows + `store_drift.levels`), the arm in
  `realm_revert_level.py`; the top-level `levels` row is still emitted. Two choices
  the plan left open: a HELD level has no drift row (the skill family's rule — the
  hold's exit is `realm sync resolve`), and ARCHIVE_LOCAL writes to
  `level_conflicts/archive/`, a subfolder, so an archived level never reads as held.
- **S3 not built here** — the launcher mirror is a launcher-repo change for the paired
  landing. Until it lands, the launcher already shows a level row under its wire word
  (`RealmDriftItemFamily.unknown`) and can revert it by selector.
- **S4** waits one release after S3. **Live proof** (edit, status, revert) needs the
  owner's machine.
- Gap: `realm_revert_version._upstream_moved_rows` has no level family, so
  `revert --to <version>` restores a drifted level but not one whose published copy
  moved between versions (filed as its own row).

## In plain English

Realm sync can tell the operator "this level differs from the published copy",
but gives no button to put it back. Every other synced thing (boards, office,
personas, skills, the canvas) has that button, called revert. Levels were kept
off the revert list on purpose, because adding a family there without a revert
path crashes `revert --all`. The owner ruled the end state: levels become an
ordinary drift family, counted once. This plan orders the work so nothing
crashes on the way and the Launcher's mirror changes in the same landing.

## Evidence (tree at `origin/main` 428e2b0dd09)

- Status: `agent_runtime/realm_sync/status.py::_level_status_row` (l.300) —
  top-level `levels` key `{publishable, unpublished, held, refused}`, docstring
  explains why it is not a `store_drift` family.
- Revert: `agent_runtime/realm_revert.py` — `_PROCESS_ORDER` (l.177, direct
  subscript), family tuple (l.150), the `_Upstream.lookup` if-ladder (l.444–466,
  grandfathered W0-G5), the per-family name table (l.475), the refuse-door table
  (l.787), `_apply_revert` (l.813) dispatching on family.
- Families: `agent_runtime/realm_sync/drift.py` (`SyncFamily`).
- Level store and baseline: `agent_runtime/level_sync.py` (`LevelStore` l.279,
  `level_baseline_key`, `read_level_baseline`).
- Pin that forces the decision: `tests/agent_runtime/test_realm_sync_level_artifact.py::test_the_level_family_is_not_a_store_drift_family`
  (l.282).
- Launcher mirror: `EterniaLauncher/lib/features/mission_control/sync/realm_sync_status_report.dart`
  (`levels: RealmDocumentFamilyStatus.fromStatusJson(body, 'levels')`, l.326;
  per-family `*StoreDrift.fromStoreDriftJson` l.284–312).

## Target shape

- **One family table** replacing the three per-family dispatch sites:
  `_FAMILY_ARMS: dict[SyncFamily, FamilyArm]` where `FamilyArm` carries
  `process_order`, `upstream_lookup`, `baseline_hash`, `apply(action)`,
  `refuse_door`. `_PROCESS_ORDER`, the lookup ladder and `_apply_revert`'s
  ladder read the table. A gate asserts every `SyncFamily` that appears in
  `store_drift` has an arm — enumerated from `SyncFamily` itself.
- **Level arm:** `DRIFT_FAMILY_LEVEL`; upstream lookup = the level artifact in
  the realm; baseline = `read_level_baseline`; RESTORE/ADOPT write through
  `LevelStore`; ARCHIVE_LOCAL per the level conflict folder (`held`).
- **One count:** `store_drift.levels` replaces the top-level `levels` key;
  `held`/`refused` become row states, as for the other families.
- **Launcher:** `LevelStoreDrift.fromStoreDriftJson` beside its siblings; the
  revert action appears on level rows through the existing revert UI.

## Owner decisions (recommendation first)

1. **Table first, then the arm** (recommended): converting the grandfathered
   ladder is the precondition the W0-G5 rule sets ("may not grow an arm"), and
   it makes the next family a table row.
2. **Wire compatibility.** Recommend hermes emits BOTH the old top-level
   `levels` and `store_drift.levels` for one release, launcher prefers the new
   key, then the old key is deleted — because launcher and hermes ship apart.
   Alternative: one paired cut with no overlap — simpler, but an older launcher
   against a newer hermes loses the level count.
3. **ARCHIVE_LOCAL for a local-only level.** Recommend it archives to the level
   conflict folder (recoverable), never deletes.

## Slices (build order)

- **S1 — family table (hermes, no behaviour change).** All current families
  move to `_FAMILY_ARMS`. Killing mutation: drop one family's arm → the
  enumeration gate (from `SyncFamily`) reds; existing revert tests stay green.
- **S2 — level arm + `store_drift.levels`** (old key still emitted). Flip the
  pin test to assert levels ARE a drift family with an arm. Killing mutations:
  (a) remove the level arm → `revert --all` test with a drifted level reds
  (no `KeyError`, a typed refusal is the old behaviour being removed); (b) skip
  `_realign_baseline` for levels → the next status still shows drift → red.
- **S3 — launcher mirror** (paired landing): parse `store_drift.levels`, revert
  action on level rows; fall back to top-level `levels` when absent. Killing
  mutation: ignore the new key → widget test over a fixture with a drifted
  level shows no revert action → red.
- **S4 — delete the old `levels` key** in hermes and the launcher fallback,
  after one release.
- **Live proof (S2+S3):** edit a level locally, status shows one drift row,
  revert restores the published body, status clean.

## Blast radius

Hermes: `realm_revert.py` (table conversion touches every family's dispatch —
the riskiest part, covered by the existing revert suite), `realm_sync/status.py`,
`level_sync.py`. Launcher: the status report model and the revert row UI.

## What it retires

The last realm-synced family the operator cannot revert, the grandfathered
lookup ladder, and the double shape (top-level key vs drift rows) for one
concept.
