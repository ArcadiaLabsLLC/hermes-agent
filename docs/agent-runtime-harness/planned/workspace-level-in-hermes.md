# A workspace's level lives in hermes — one map per workspace, carried by the realm

**Status: implementation-ready, written 2026-09-22. Owner ruling 2026-09-22: "one map per workspace, it should be in realms."** Program cursor: `Harness_Brain/20 — Active Initiatives/runtime-queue.md` (the row under "Owner asks — 2026-09-22"). Field notes: [workspace-level-in-hermes-field-notes-2026-09-22.md](workspace-level-in-hermes-field-notes-2026-09-22.md).

## 1. What is true today (measured on the live store, 2026-09-22)

- hermes already has the LEVEL realm family: one document per workspace, stored verbatim at `paths.level_path(workspace)` (`agent_runtime/level_sync.py::LevelStore`), published to the realm repo at `store/levels/<token>.json`, three-way merged on pull. CLI verbs `harness level show|set` (`hermes_cli/harness_parts/level.py`). Tests: `tests/agent_runtime/test_level_sync.py`, `test_harness_level_cli.py`, `test_realm_sync_level_artifact.py`.
- The launcher's office reads and writes its workspace level from `LocalSceneStore` (SharedPreferences on the one machine): `MissionOfficeHost.sceneStore` / `slotWriter` default to `const LocalSceneStore()` (`EterniaLauncher/lib/features/mission_control/office/mission_office_host.dart`). Only ONE path hands bytes to hermes: `applyMissionOfficeRealmMap` (`office/mission_office_map_apply.dart`), the map picker's "a realm's default workspace" target, through the argv bridge `sync/realm_level_bridge.dart`. "Apply to this workspace", the level editor's save and a link fork write locally only. Nothing reads a pulled level back into the launcher (`RealmLevelBridge.show` has no caller).
- Live store: no `levels/` directory exists — no workspace has ever handed hermes a level. The active realm (`test realm`) has `default_workspace_id: null`, so the one hermes-bound target refuses as not-addressable.

So the island the operator applied is in one machine's SharedPreferences and can never reach a realm. The transport is fine; the STORE is on the wrong side of the seam.

## 2. The ruling, as a design

**hermes is the store of a workspace's level, for every workspace, always.** The launcher's `SceneStore` for a `WorkspaceLevelRef` becomes an RPC-backed implementation over hermes; `LocalSceneStore` stops being the workspace arm (it keeps nothing else — voice channels are `DjangoSceneStore` by address and are untouched). A level then travels with the realm exactly like the office and the boards do: written through hermes, counted as drift, carried by the ordinary publish, three-way merged on pull, read back by the next office open. No hand-off stage, no second author, no local copy to diverge.

Standing rule applied (`feedback_rpc_route_first`): the store rides the hermes METHOD lane, not argv. The argv bridge is retired with its one caller.

## 3. The contract (hermes RPC, `TIER_CONSOLE`, `agent_runtime/serve_rpc.py`)

| method | params | result | errors |
|---|---|---|---|
| `runtime.level.get` | `workspace_id` | `{workspace_id, workspace_token, present, bytes, sha256, version, document}` — `document` is the stored bytes as a string, `null` when absent; `present:false` is an honest empty | `ERR_INVALID_PARAMS` (`workspace_id_required`); `ERR_NOT_FOUND` `workspace_not_found` for a workspace no record resolves (mirror `runtime.office.get`: never a blank for a typo) |
| `runtime.level.set` | `workspace_id`, `document` (string), `expect_sha256` (optional: hex of the bytes the caller read, or `null` meaning "must be absent"; omitted = unconditional) | `{workspace_id, sha256, bytes, version, changed}` | as above; `ERR_INVALID_PARAMS` with `data.reason = LevelDocumentError.code` for a refused document; `ERR_CONFLICT` with `{reason: "sha256_mismatch", current_sha256}` when `expect_sha256` does not match what is stored now |
| `runtime.level.clear` | `workspace_id`, `expect_sha256` (optional, same meaning) | `{workspace_id, cleared}` (`cleared:false` when nothing was stored) | as above |

Facts the lane keeps: the bytes are stored VERBATIM (`LevelStore.write` is the one door; `clear` is added to it beside `write`, deleting `level_path`); `sha256` is over the stored bytes (the same `sha256` `_level_row` prints — the launcher's compare-and-set token); the semantic hash realm sync merges on is unchanged. Every write logs a receipt through the same shape as `log_office_write` with `op` = the method name (observability is log receipts, never envelope keys). No new event contract. The three methods join the tier table in `tests/agent_runtime/test_peer_authorization.py`. The CLI grows the argv mirror only where it is free: `harness level set --expect-sha256` and `harness level clear` over the same `LevelStore` calls (so the CLI contract dump is re-run at the landing).

## 4. The launcher half

- **New** `lib/features/mission_control/data/rpc/mission_level_rpc.dart`: the typed read/write/clear legs over the same transport `mission_office_rpc_read.dart` uses, with a closed outcome family (answered / not found / refused-with-reason / conflict / transport failure / method unknown).
- **New** `HermesWorkspaceSceneStore implements SceneStore, LevelSlotWriter` (`lib/features/mission_control/office/mission_office_level_store.dart`), the adapter: `load` → `runtime.level.get`; `present:false` → `SceneLoadNotFound`; present → the SAME raw-bytes classification `LocalSceneStore.load` performs today (kind gate before version gate, `SceneLoadForeignDocument` for a link) — if that classifier is private to `LocalSceneStore`, it is lifted to a shared function in ONE MOVE commit first. `save` / `saveSlotDocument` → `runtime.level.set` with `expect_sha256` = the sha the adapter minted the caller's `expectedDocumentRevision` for (`null` revision ⇒ `expect_sha256: null`); `ERR_CONFLICT` → `SceneSaveConflict`; refused document → `SceneSaveValidationFailure` / `SceneSavePayloadTooLarge` by reason; transport or unknown method → `SceneSaveTransportFailure` with the "update Hermes" sentence the bridge used. `delete` → `runtime.level.clear`. The `int documentRevision` the `SceneStore` port speaks is the adapter's OWN token, minted per load and mapped to the sha256 it stands for; the sha is the truth.
- **Binding**: `mission_canvas_shell.dart`'s `officeHost(...)` passes `sceneStore:` and `slotWriter:` as one `HermesWorkspaceSceneStore` built from the runtime's RPC client. `MissionOfficeHost` stays provider-free and keeps its injected fields (every office widget test still pumps it with `office_scene_store_fake.dart`).
- **Delete**: `applyMissionOfficeRealmMap`'s hand-off stage and `RealmLevelBridge` (`sync/realm_level_bridge.dart`, its test, `realm_level_link_round_trip_test.dart`'s argv half). The realm-default target becomes save (now through hermes) + the existing publish. `MissionOfficeRealmMapApplyOutcome` loses `handoff`.
- **Publish**: level writes do NOT auto-publish. hermes already counts unpublished levels in realm status (`_level_status_row`); the ordinary publish carries them. The realm-default target keeps its explicit publish. If the sync sheet does not render the `levels` status row, that is a queue row, not this lane's work.
- **No migration** of levels already in SharedPreferences: they were never shared, and the office reads hermes from the landing on. Stated, not fixed.

## 5. Stages and lanes

| stage | repo | what | lane |
|---|---|---|---|
| H | hermes | §3: three methods, `LevelStore.clear`, CLI mirror, receipts, tier table | Opus, worktree `X:/Eternia/worktrees/hermes-level-rpc` |
| L | launcher | §4 against the §3 contract with a fake transport; integration against H after both land | Opus, worktree `X:/Eternia/worktrees/launcher-level-store` |

H and L run in parallel (the contract is fixed above). L's unit tests use a fake RPC transport; the one live proof — apply the island to `ws_testv4_afb811`, `hermes harness level show --workspace ws_testv4_afb811` reads it back, publish, `store/levels/` appears in the realm repo — is the operator's after both land.

## 6. Tests and controls

- H touched tests: `tests/agent_runtime/test_level_sync.py`, `test_harness_level_cli.py`, `test_realm_sync_level_artifact.py`, `test_peer_authorization.py`, `test_remote_cockpit_method_carriage.py`, plus a new `test_level_rpc.py` (get absent / get present / set unconditional / set with matching sha / set with stale sha → conflict / set null-expect over a present level → conflict / refused document → reason / clear present / clear absent / unknown workspace). Positive control: plant `expect_sha256` ignored in `runtime.level.set` on a throwaway copy — the conflict test reds; revert; paste in the CHANGE commit body.
- L touched tests: `test/features/mission_control/office/mission_office_realm_map_apply_test.dart`, `mission_office_level_link_test.dart`, `mission_office_level_session_test.dart`, `sync/realm_level_bridge_test.dart` (deleted with the bridge), `sync/realm_level_link_round_trip_test.dart`, `core/spatial/maps/workspace_level_slot_test.dart`, plus new `mission_office_level_store_test.dart` (the same ten cases against the fake transport, and the revision-token round trip: load → save with that revision → `expect_sha256` equals the loaded sha). Positive control: plant the adapter sending `expect_sha256` omitted on a non-null revision; the round-trip test reds; revert.
- Landing (hermes): validated suite once; `dump_cli_contract.py --check` (expected diff: `level clear`, `--expect-sha256`) regenerated after reading the diff; tooling gates. Landing (launcher): its own CLAUDE.md gates.
