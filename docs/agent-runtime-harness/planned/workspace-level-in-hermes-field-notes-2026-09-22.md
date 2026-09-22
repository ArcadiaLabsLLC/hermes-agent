# Field notes — a workspace level lives in hermes (2026-09-22)

Running record for the plan [workspace-level-in-hermes.md](workspace-level-in-hermes.md). Each lane appends its own section: what the tree said that the plan did not, the positive control as run, and what it left for a row.

## Stage H — hermes (runtime.level.get / set / clear)

_not started_

## Stage L — launcher (HermesWorkspaceSceneStore)

Landed on `feat/level-store-hermes` in `EterniaLauncher`: MOVE `bdec1ef01`,
CHANGE `3e178ff70`, plus `f82bea085` re-vendoring the hermes CLI contract
fixture.

**What the tree said that the plan did not.**

- The plan puts the typed get/set/clear legs *and* the transport in
  `data/rpc/mission_level_rpc.dart`. The tree splits that everywhere else:
  `mission_scope_use_rpc.dart` / `mission_scope_use_client.dart`,
  `mission_office_rpc_read.dart` / `mission_office_rpc_reader.dart` — the pure
  leg under `data/rpc/`, the class holding a `MissionOfficeRpcCall` beside its
  consumer. Nothing under `data/rpc/` imports the serve session at all, and
  `MissionServeUnavailable` has no `toString`, so a leg that caught it there
  would have had to import the session to say anything useful. Followed the
  tree: builders, parsers and the sealed `MissionLevelRpcOutcome` family in the
  leg; the transport half in `HermesWorkspaceSceneStore`.
- The leg is deliberately NOT on the `mission_office_rpc.dart` barrel. It is a
  level leg with one caller; the barrel exists so the six office legs' shared
  callers keep one import.
- `LocalSceneStore.load`'s classifier was not private — `storedDocumentKind`
  was already shared — but the LADDER around it (kind gate, version gate,
  decode, the two decode-failure catches) was inline in `load`. Lifted whole as
  `classifyStoredLevelBytes` in the MOVE commit, taking a non-null
  `documentRevision` because `SceneLoadFound`'s is non-null.
- `SceneStore.delete` carries no compare-and-set token by contract, so `clear`
  is the one leg whose builder OMITS `expect_sha256` when it is null. Sending
  null there would mean "delete only if nothing is stored" and would refuse
  every delete that has anything to delete. The `set` builder does the
  opposite — it always sends the key, because this launcher never writes a
  level unconditionally, and the omitted (unconditional) state therefore has no
  producer and was not given one.
- The store is built once per container through a provider that WATCHES
  NOTHING; both doors are thunks read at call time. The sibling clients
  (`missionOfficeRpcWriterProvider` and friends) watch their door and are
  rebuilt with it, which for them costs nothing and here would drop the whole
  token table on every reconnect — every subsequent save would present a token
  the new instance never minted.
- The AIMED door (`missionAimedMethodLaneCallProvider`), not the refusing one:
  a workspace's level belongs to the machine that holds the workspace.
- `applyMissionOfficeRealmMap` has no production caller yet (the realm-target
  row is still open), so dropping its hand-off stage touched only that function,
  its message function and its test.

**Positive control, as run.** `expectSha256 = known;` → `expectSha256 = null;`
in `HermesWorkspaceSceneStore.saveSlotDocument`; two tests red, reverted, 18/18
green:

```
00:00 +15 -2: the revision token round trip the sha a load carried is the expect_sha256 the next save sends [E]
  Expected: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    Actual: <null>
     Which: not an <Instance of 'String'>
Failing tests:
  … save a stale sha is a conflict, and the current one comes back as a usable token
  … the revision token round trip the sha a load carried is the expect_sha256 the next save sends
EXIT=1
```

**Tests.** The 52 non-architecture launcher test files importing a touched
module, one run: 460 passing, exit 0. Plus the three that read the CLI contract
fixture over the re-vendored copy: 242 passing, exit 0.

**Left for a row.** Nothing new in code or design. Two standing facts this lane
did not change: `applyMissionOfficeRealmMap` is still unmounted (the realm
target needs the viewer's `ServerRealm` list and a verb probe), and levels
already in `SharedPreferences` are not migrated — they were never shared, and
the office reads hermes from the landing on.
