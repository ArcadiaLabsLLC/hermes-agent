# Planned — the page-open write storm and the cold-open degrade window

**Status:** planned 2026-10-28 (lane w1028p-officestorm) for row
`RT-OFFICE-PAGE-OPEN-WRITE-STORM`. Not built. Un-archived from `archive/`
(parked there 2026-10-27 as "never measured since 2026-08-16"); the
measurement is below, and it is the first one this plan has ever carried.
**Owner doc:** [06 — Office and board](../06-office-and-board.md).
**Launcher consumer:** `MC-OFFICE-ARGV-WRITE-ARMS`
(`EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`),
whose observation window starts after S2 below lands.
**Origin:** named unfixed by three 2026-08-16 plans — `OFFICE_WRITE_VERBS_RPC_PLAN`
§4 ("item 9", "item 10"), `UNIFIED_GESTURE_PREDICTION_PLAN` §4,
`OFFICE_OPTIMISTIC_RENDER_REGRESSION_PLAN` §6 — all in
`archive/2026-08-22-pre-consolidation/`.

## In plain English

1. A Mission Office open can re-send to hermes exactly what hermes just told it
   — every actor and the folder list — and hermes **writes all of it again**:
   a new revision per actor, a new surface revision, two events per write,
   every subscriber woken. Measured: nothing changed, four files rewritten.
2. On a healthy open with no gesture today's launcher sends nothing; the
   re-sends come from three named seeds (the one-shot import, the first flush
   of a session before a read has seeded the folder basis, a held flush
   drained at the ready edge) and from any content-key drift between the
   launcher's layout and the server's projection.
3. The fix that makes every one of those harmless lives in hermes: a
   content-equal write is a **no-op** — no file, no revision, no event, the
   same ack shape, one receipt word that says so. Three slices, store first.
4. The `laneAbsent` window is real and is the serve child's spawn-to-ready
   (5.6 s on this box, 21.9 s cold on record); the method manifest rides the
   same `ready` greeting the launcher marks `serveReady` on, so the window
   closes at that frame. What can fall into it is the launcher's question.
5. After S2 the launcher row's window is a grep: `office_write … noop=1` lines
   under a page-open token, and `laneAbsent` never beside a write-lane `ready`.

## 1. Evidence — measured 2026-10-28 on `main` `c965e7abf0`, Linux, sandboxed `HERMES_HOME`

### 1.1 Hermes has no dirty check on either office write verb

A replay of the frames an office page open can send, through the real
`serve_loop` (`hermes_cli/harness_parts/serve/session.py::serve_loop`) against a
seeded store of three actors (`neko_supervisor` agent+desk, the instance-bound
`personainst_qa_agent_9c8a382f` agent+desk, the furniture desk `desk_a1`) and
the default folders. Each open: `runtime.office.get`, then one
`runtime.office.upsert` per actor with the payload built from the get's own
items exactly as the launcher's `officeActorPayloadFromRpcItems` builds it and
`expect_revision` = the item's revision, then `runtime.office.surface.update`
with the get's own folder list and no token (the page-open folder write sends
none — launcher `mission_office_surface_lane_test.dart`, "the FIRST folder
write of a session sends NO token"). Payloads byte-equal to server truth.

| open | frames | files rewritten | revisions | events appended | `office_write` lines | wall |
|---|---|---|---|---|---|---|
| #1 (3 actors + folders) | 4 | 4 (`actors/*.json` ×3, `office.json`) | every row 1 → 2 | 8 (`state.patched` ×4, `office.actor.upserted` ×3, `office.surface.updated` ×1) | 4 | 58 ms |
| #2 (same) | 4 | 4 | every row 2 → 3 | 8 | 4 | 57 ms |
| #3 (folders only) | 1 | 1 (`office.json`) | surface 3 → 4 | 2 | 1 | 29 ms |

The echoed folder list was identical across all three opens. Per open with N
re-sent actors: **N+1 file rewrites, N+1 revision bumps, 2(N+1) events, N+1
patches to every subscriber** — for a write that changed nothing. The writers:

- `agent_runtime/office_store/actor_writes.py::upsert_actor` → `_next_actor`
  always builds `revision = base_revision + 1` and `_write_actor` always
  writes; `_emit_actor_patch` and `office.actor.upserted` always append.
- `agent_runtime/office_store/surface_writes.py::update_surface` →
  `surface.revision += 1`, `_write_surface`, `_emit_surface_patch`,
  `office.surface.updated`, unconditionally once `check_revision` passes.
- `agent_runtime/office_store/store.py` (module docstring) says "upserts are
  naturally idempotent (identical content re-writes converge on the same
  file)". The revision and `updated_at` move on every write, so the file does
  not converge; the table above is that sentence's refutation.

The receipt already exists and joins on the gesture token:
`office_write op=runtime.office.upsert corr=open1 workspace=… actor_key=desk_a1 revision=2`
(`agent_runtime/serve_rpc/office_read.py::log_office_write`). It cannot yet
say "nothing changed", because nothing on the path knows.

### 1.2 What today's launcher sends on an open (read from the tree, not measured)

The only writer is `MissionOfficeLayoutController.applyLayout` →
`MissionOfficeFlushEngine.schedule`
(`EterniaLauncher/lib/features/mission_control/office/layout/mission_office_flush_engine.dart`).
Its actor loop skips every actor whose content key equals the server's
(`office/policy/mission_office_write_predicate.dart::missionOfficeActorNeedsWrite`),
and its folder arm fires iff `!listEquals(sync.desiredFolders, sync.serverFolders)`.
`applyLayout` runs only from a gesture
(`state/cockpit/mission_cockpit_office_lane.dart::_saveLayout` behind
`mutateLayout` / `replaceViewport`; the canvas reports a viewport only on pan
end and wheel zoom, `office/mission_office_mount.dart::_notifyViewportChangedIfDirty`
and `_zoomCameraByNotches`) or from the one-shot import
(`office/mission_office_layout_controller.dart`, the `applyLayout` call inside
`resolveLayout`'s migration arm). So a healthy open with no gesture sends
**zero** writes. The re-sends come from three seeds:

- **S-a, the import.** `resolveLayout`'s one-shot SharedPreferences import
  pushes every actor of the legacy blob once per surface, after
  `restoringPositionsFrom(sceneCache)` repairs it (owner ruling 2026-09-28).
  Legitimate once; its content-equal subset is free after S1.
- **S-b, the first flush before a seeded basis.** `MissionOfficeWorkspaceSync.serverFolders`
  starts `const <String>[]` and is seeded only by a read that gets past the
  degrade return; a gesture (or the import) that flushes before that writes the
  taxonomy with no token — the "page-open surface write" the launcher's own
  suite names (`test/features/mission_control/office/mission_office_surface_lane_test.dart`,
  `addOpsFolder`: "the very first layout applied to a workspace writes the
  taxonomy too"). The 2026-08-15 session that took the degrade return on every
  read re-wrote the taxonomy once per flush for its whole life (the flush
  engine's folder-arm comment). Launcher defect; row
  `MC-OFFICE-FOLDER-FLUSH-NO-BASIS`.
- **S-c, the held drain.** `_flushHeldWorkspaces` on the write lane's
  `waiting → ready` edge re-flushes whatever `desired` holds, which `applyLayout`
  replaces wholesale and no read prunes (the 2026-08-27 resurrector,
  `EterniaLauncher/docs/mission_control/04-office-scene.md` "The delete lane").
  Ordered after the baseline fold since then; its content-equal subset is free
  after S1.

Three content-key drift candidates turn "equal" into a re-upsert on open and
are the plausible "re-upserts the desk off a stale cache": positions repaired
from the scene cache (`positionRepairs` / `restoringPositionsFrom`), an
old-format desk dropped at the layout constructor (`droppedLegacyDeskCount` →
the actor is upserted with one fewer item), and item order within an actor
(`officeActorContentKey`'s `_canonical` sorts map keys, not list items; the
layout's item order and the RPC projection's are two different lists). None is
measured; row `MC-OFFICE-OPEN-CONTENT-KEY-DRIFT` carries the probe.

### 1.3 The `laneAbsent` window

- `hermes harness serve --ndjson` in a sandbox home on this box: `booting`
  frame at 4176 ms (interpreter + import tax), `ready` greeting at
  **5689 ms** cold and 5598 ms warm (the OS file cache was warm either way; the
  21.9 s of 2026-08-17 remains the recorded worst case —
  `office/mission_office_layout_controller.dart::kMissionOfficeHoldEscalation`).
- The method manifest rides that greeting: `hermes_cli/harness_parts/serve/boot_phases.py`
  puts `"ops": ops_manifest(...)` on the `ready` frame. The launcher adopts it
  (`facts.acceptGreeting`) and marks `serveReady` in the same router step
  (`core/services/hermes/runtime/data/serve/mission_serve_frame_router.dart::_completeGreeting`),
  and `missionOfficeRpcRefusal` answers `laneAbsent` iff `!manifest.present`
  (`core/services/hermes/runtime/data/rpc/mission_office_rpc_taxonomy.dart`).
  So the window is exactly **spawn → `ready` greeting** and closes on that
  frame; hermes cannot shrink it below the boot and does not need to.
- What can fall into it is launcher-side: the write-lane posture flips `ready`
  from the boot paint's readiness
  (`state/mission_action_readiness.dart::resolveMissionOfficeWriteLanePosture`
  → `allowsWrites`), a signal independent of the greeting. A posture `ready`
  before the greeting, plus a gesture, is a flush that degrades to the argv
  arms — the launcher's own receipts record `0 rpc, 5 cli (fallback: laneAbsent)`
  in the undated log era
  (`EterniaLauncher/docs/mission_control/planned/duplicate-implementation-retirement.md`,
  "That window does not exist"). Whether that still happens is the
  observation `MC-OFFICE-ARGV-WRITE-ARMS` owns (§8).

## 2. Which writes are legitimate

| write on open | legitimate? | gate |
|---|---|---|
| upsert whose normalized row equals the live row | no — a write with no change and no gesture | S1a: store no-op |
| `surface.update` whose normalized folders equal the surface's | no | S1b: store no-op |
| the one-shot import (S-a) | once, as the import; its equal subset is not | S1 makes the subset free; nothing else |
| the held drain (S-c) | yes — staged operator intent | already ordered after the baseline; S1 makes its equal subset free |
| first folder flush with no seeded basis (S-b) | no — a write with no basis | launcher: `MC-OFFICE-FOLDER-FLUSH-NO-BASIS` |
| a repair re-upsert (positions, dropped desk) | only as an explicit repair, never as a side effect of opening | launcher: `MC-OFFICE-OPEN-CONTENT-KEY-DRIFT` |

A read-only open mode and a client-side debounce were considered and are not
the gate: the launcher already dedupes by content key and debounces 600 ms, and
a second client (the CLI, another launcher, the sync pull) reaches the same
store. The dirty check belongs where the file is written.

## 3. Target shape (hermes)

**Rule:** an office write whose normalized next row differs from the live row
only in `revision`, `updated_at`, `updated_by` (and `created_at`, which the
next row copies) **writes nothing, bumps nothing, emits nothing**, and acks the
live row. `expect_revision` is still checked first — a stale token on an equal
payload is refused exactly as today (the §8.3 ruling in
`mission_office_flush_engine.dart::_upsertToken`: "a guarded write either lands
or is REFUSED and retracted loudly; neither is a lost update"). Every fence
(class-key, tombstone, conflict sidecar, actor-kind) keeps its precedence and
runs before the comparison, so a refusal that stands today still stands. Only
a LIVE equal row is a no-op: a payload equal to an ARCHIVED copy is the
deliberate re-add and writes as today. `dry_run` is unchanged (it already
writes nothing).

- **Where:** a new pure module `agent_runtime/office_store/noop.py` —
  `unchanged(existing, candidate) -> bool` over `to_jsonable` minus the four
  volatile fields, and a frozen `WriteOutcome(row, written: bool)`. The store's
  existing public doors (`upsert_actor`, `update_surface`) keep returning the
  row, so the CLI verbs, `agent_create/perform.py` and `workspace_template.py`
  are untouched; two additive doors `upsert_actor_outcome` /
  `update_surface_outcome` return the `WriteOutcome`, and the two RPC handlers
  switch to them.
- **The receipt:** `log_office_write(..., noop=1|0)` on both verbs — a new
  `key=value` field in the existing line, never `-` (it is always known).
  `noop=1` carries the live `revision`. The ack frame shape is unchanged.
- **Consequences stated:** `updated_at` / `updated_by` do not move on a no-op
  (that is what "nothing changed" means); the subscribe lane receives no patch;
  `office_sync`'s content hash is unchanged, so a converged pull stays a no-op
  one level further out; `workspace_template.clone`'s `update_surface` with the
  source's own folders stops bumping the clone to revision 2 (its tests pin the
  value they see — the lane re-pins).

## 4. Slices — build order, file-disjoint, one lane each

| slice | row | files | done when |
|---|---|---|---|
| **S1a** actor no-op | `RT-OFFICE-NOOP-ACTOR-WRITE` | `agent_runtime/office_store/noop.py` (new), `agent_runtime/office_store/actor_writes.py`, `tests/agent_runtime/test_office_noop_actor_write.py` (new) | T1–T4 green; T1 recorded red first |
| **S1b** surface no-op | `RT-OFFICE-NOOP-SURFACE-WRITE` | `agent_runtime/office_store/surface_writes.py`, `tests/agent_runtime/test_office_noop_surface_write.py` (new); imports `noop.py` from S1a | T5–T6 green; T5 recorded red first |
| **S2** handler receipt + replay gate | `RT-OFFICE-NOOP-RECEIPT` | `agent_runtime/serve_rpc/office_actor_writes.py`, `agent_runtime/serve_rpc/office_surface_writes.py`, `agent_runtime/serve_rpc/office_read.py::log_office_write`, `tests/agent_runtime/test_serve_rpc_office_page_open_replay.py` (new), `06-office-and-board.md` (a "No-op writes" paragraph) and this file's fold-in | T7–T9 green; the replay gate's three-open table reads 0/0/0 |

S1a and S1b are file-disjoint and may run in parallel once `noop.py` exists
(S1a owns it; S1b waits for S1a's landing or is handed the module's final
spelling by the orchestrator). S2 waits for both.

## 5. Test plan — the red each test must show

| test | claim | red on today's tree / killing mutation |
|---|---|---|
| T1 | identical `upsert_actor` → actor file sha unchanged, revision unchanged, `events.jsonl` length unchanged, returned row equal to the live one | today: revision 1 → 2, +2 events (§1.1). Mutation: drop the `unchanged` branch |
| T2 | same payload with one field changed (a position, a folder) → writes, +1 revision, +2 events | positive control; red if `unchanged` over-approximates (e.g. compares keys only) |
| T3 | identical payload with a stale `expect_revision` → `StaleRevision`, nothing written | red if the no-op check is placed before `check_revision` |
| T4 | payload equal to an ARCHIVED row, live absent → writes (the re-add), as today | positive control for "live only" |
| T5 | `update_surface` with `["Agents","Desks"]`, with `[]`, and with `["Desks","Agents","Desks"]` against the default surface → no write, revision unchanged, no event | today: surface 3 → 4 on folders-only (§1.1 open #3). Mutation: compare the raw list instead of the normalized one (the third case goes red) |
| T6 | `update_surface` adding `"Ops"` → +1 revision, patch + domain event, echo normalized | positive control |
| T7 | RPC `runtime.office.upsert` of an equal actor → ack `{actor_key, revision: <live>}` (+ `correlation_id`), log line carries `noop=1`, `state.patched` count unchanged | today: no `noop` key, +1 patch |
| T8 | `test_serve_rpc_office.py::test_the_argv_lane_emits_the_same_bytes_with_the_method_lane_beside_it` and `test_serve_rpc_office_upsert.py`'s reconciliation round trip unchanged | regression fence |
| T9 | the §1.1 scenario as a test: three opens of three actors + folders → every revision at its seed value, `events.jsonl` +0, nine `noop=1` lines | today: +8 events and +1 revision per open |

Each test lands with its mutation applied, its failure output recorded in the
commit body and reverted (fork rule); the claim goes in
`tests/mutation_claims.json` when the lane's test is one the gate indexes.

## 6. Blast radius

- Callers of `upsert_actor`: `serve_rpc/office_actor_writes.py`,
  `hermes_cli/harness_parts/office.py` (argv verb), `agent_create/perform.py`
  (a create is never equal to a live row), `workspace_template.py` (a clone's
  rows are new). Callers of `update_surface`: the RPC handler, the argv
  `set-folders`, `workspace_template.py` (now a no-op for an unchanged list —
  the one behaviour change outside the RPC lane). `office_sync`'s adoption path
  writes through `office_store/adoption.py` and is untouched.
- Launcher: an ack whose `revision` equals the token it sent leaves
  `serverRevisions` and `serverSurfaceRevision` where they were; the overlay
  entry settles on the ack as today; no launcher change is required for S1/S2.
  The subscribe lane simply receives nothing, which is the point.
- Upstream: none of these files exist in `upstream/main`.
- Not in scope: shrinking the boot (the `laneAbsent` window IS spawn-to-ready);
  the launcher's three seeds (rows filed); the `office_sync` pull.

## 7. Owner decisions

None open. The two questions a lane would otherwise ask are settled by records
already on file, and the plan follows them:

- *Does an equal payload with a stale token still refuse?* Yes — §8.3 /
  `_upsertToken`'s ruling ("REFUSED and retracted loudly", EG-5.1) and
  `test_serve_rpc_office_upsert.py`'s "a refusal WRITES NOTHING".
- *Does a no-op move `updated_at`?* No — the remove verb's own ruling
  ("answering ok costs nothing and writes nothing",
  `history/serve_rpc.md` § `runtime.office.resolve_conflict`) and the dry-run
  byte-identical gates in `test_office_store.py` define "writes nothing" as
  the file not changing.

The launcher row's own question (`MC-OFFICE-ARGV-WRITE-ARMS`: N dated sessions
first, or this plan first) stays the owner's; this plan's recommendation is
unchanged from the row's — S2 lands first, then the window below.

## 8. The observation window the launcher row needs (after S2)

Five dated cold opens on the owner's box, each read from the two logs joined on
the page-open token: (a) every `office_write` line between `serveReady` and
the first `[MissionOfficeWrite] … write lane:` receipt that follows an operator
gesture carries `noop=1`, or there is none; (b) no `[MissionOfficeRpc] … (laneAbsent)`
or `[MissionOfficeSubscribe] … unavailable (start): laneAbsent` line lands
while the write-lane posture reads `ready` (the boot timeline's
`spawn_to_ready` beside the first posture-ready mark); (c) `cli=0` on every
`write lane:` receipt. Five clean opens close `MC-OFFICE-ARGV-WRITE-ARMS`'s
precondition; one dirty open names the seed (S-a / S-b / S-c or a drift) and
goes to its launcher row, not back here.
