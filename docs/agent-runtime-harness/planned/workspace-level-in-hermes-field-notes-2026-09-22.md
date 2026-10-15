# Field notes — a workspace level lives in hermes (2026-09-22)

Running record for the plan [workspace-level-in-hermes.md](workspace-level-in-hermes.md). Each lane appends its own section: what the tree said that the plan did not, the positive control as run, and what it left for a row.

## Stage H — hermes (runtime.level.get / set / clear)

**Landed 2026-09-22**, branch `feat/level-rpc`. The three methods, `LevelStore.clear`, the argv mirror (`level set --expect-sha256`, `level clear`), the receipts and the tier rows.

### What the tree said that the plan did not

- **There is no tier TABLE in `tests/agent_runtime/test_peer_authorization.py`.** That suite is registry-driven by design ("loops, never literals") and asserts a property over every registered method, so a new verb is covered by it the moment it registers and there is nothing to add. The hand-written tier table the plan meant lives in `tests/agent_runtime/test_serve_rpc_method_tiers.py::test_level_mutations_are_console_and_reads_are_read`; the three rows went there.
- **`tests/agent_runtime/test_remote_cockpit_method_carriage.py` could not take the three rows yet, and it says why itself.** Its table is a claim about the OTHER repo — `test_remote_cockpit_method_carriage.py::test_the_table_is_the_launchers_refusal_set_and_not_a_sample` asserts `len(...) == 7` against the count `mission_method_lane_aim`'s own docstring records. Adding the level family made it 10 and red. The launcher does not bind these verbs yet (that is Stage L), so pinning them here would have been a false cross-repo claim in the one file whose job is to catch exactly that drift. The three rows belong in the SAME wave as Stage L's aim bindings, with the count moved to 10 in that commit. The hermes-side tier claim went to `test_serve_rpc_method_tiers.py` instead, which is the file that owns it.
- **The CLI already had a row builder the RPC needed.** `hermes_cli/harness_parts/level.py::_level_row` built the exact `{workspace_id, workspace_token, present, bytes, sha256, version, document}` shape §3 specifies for `runtime.level.get`. A second copy in `serve_rpc.py` would have been a duplicate-helper body AND a second authority for the launcher's compare-and-set token, so it was lifted to `level_sync.level_document_row` and the CLI helper now delegates to it. Same for the hash: `stored_level_sha256` is now a named function beside `level_document_hash`, because the whole family's defect surface is confusing the two.
- **`ERROR_EXIT_CODES` had no conflict code that fit.** `stale_revision` is the office's integer-revision guard and `sync_conflict` is realm sync's; spending either for a sha mismatch would have put two conditions under one word. A new row `level_sha256_mismatch: 4` landed with its comment, its hint (the default hint — "correct the request and retry" — is the one thing that cannot help here) and a literal producer, which is what `test_every_exit_code_has_a_producer` demands.
- **argv has no `null`.** The RPC's three-state `expect_sha256` (omitted / `null` / hex) needs a third spelling on the command line: `--expect-sha256 none` is "the workspace must have no level yet". `--expect-sha256` is checked on `--dry-run` too — a dry run that validated the document while ignoring the expectation would promise a write the real call refuses.
- **`runtime.level.get` is `console`, which the one-line tier rule does not say.** The rule ("a level MUTATION is console, everything else read") would make it `read`. It follows `runtime.media.get` instead: it hands back up to 1 MB of raw document bytes and the read tier is open to `unknown`. The cost is real — a `read`-tier viewer device cannot load the environment its office draws on — and is filed as a queue row rather than decided here.

### The positive control, as run

`level_expectation_matches(..., provided=expect_provided)` in `_runtime_level_set` changed to `provided=False` (the shape of "`expect_sha256` ignored"), then `tests/agent_runtime/test_level_rpc.py`:

```
_________ test_set_with_a_stale_sha_is_a_conflict_and_writes_nothing __________
E       KeyError: 'error'
_____ test_set_with_a_null_expectation_over_a_present_level_is_a_conflict _____
E       KeyError: 'error'
_ test_a_reserialised_document_is_a_conflict_even_though_the_merge_would_converge _
E       KeyError: 'error'
3 failed, 16 passed in 2.43s
```

Reverted. The three that red are the three arms of the compare-and-set and nothing else, which is the shape a control should have: the remaining sixteen cannot tell a guarded write from an unguarded one.

### Left for a row

- `runtime.level.get`'s tier (above): the launcher's adapter and any `read`-tier device.
- Stage L still owns the `SceneStore` adapter, the bridge deletion and the live proof; nothing here publishes, and nothing here migrates a level out of SharedPreferences.

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
