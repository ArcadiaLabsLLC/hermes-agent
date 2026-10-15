# Discussion definitions — foundation validation

Status: locally committed foundation, not wired to the live runtime, not on main.
Date: 2026-09-16. This evidence does not certify discussion execution or Launcher.

## Population and environment

Source archive: Hermes `fd13e82c94a9de0f950563b96637767c4691decd`.
The current-main comparison at audit time, `0a86b7e1374a3b7860cd37b8d89776ddc9255ea1`,
adds only an unrelated model-picker plan; no production source changed.
The archive excludes binary assets and original Git history. Work used an isolated
source-snapshot Git worktree; the exported patch must be applied to a real checkout,
not merged as unrelated history.

Interpreter: CPython 3.13.5 on Linux. pytest 9.0.2. Canonical runner:
`scripts/run_tests.sh`, with the existing sandbox virtualenv supplied through
`HERMES_TEST_VENV` and file retries disabled through `HERMES_TEST_FILE_RETRIES=0`.

The first ordinary runner invocation collected **zero tests** because this sandbox
lacks `pytest-timeout`: `unrecognized arguments: --timeout=30 --timeout-method=thread`.
That is an environmental failure, not a pass. The executable follow-up used the SAME
canonical runner/conftests with a command-line-only override:

```text
-o "addopts=-m 'not integration'" --file-timeout 30 -j 2
```

This preserves the integration exclusion, credential scrubbing, isolated home,
per-file subprocesses and outer file timeout. It omits the unavailable per-test
timeout plugin. No repository config, skip list or test gate was changed. The
local agent must rerun without this override in the normal project environment.
No claim of full dependency-pin or platform parity is made.

## Completed implementation

- `agent_runtime/discussions/definitions.py`: strict authoring values; explicit
  install/instance addresses; immutable copied data; six capacity variants and
  Auto; bounded finite transforms; moderator/seat membership validation;
  deterministic logical seats with explicit remap reporting.
- `agent_runtime/discussions/definition_store.py`: explicit absolute database
  binding; shared SQLite connection/transaction helpers; transactional schema
  initialization; workspace/kind/ID ownership; revision checks; tombstones;
  bounded keyset lists; copied preset provenance and Modified/Revert semantics.
- Neither module registers tools/RPC, starts workers, opens native chats, writes
  office actors, or treats syntactically valid references as authorized agents.

## Results

Final command (environment variables as described above):

```bash
bash scripts/run_tests.sh \
  tests/agent_runtime/test_discussion_definitions.py \
  tests/agent_runtime/test_discussion_definition_store.py \
  tests/agent_runtime/test_dispatch_session_policy.py \
  tests/gateway/test_hosted_room_discussion.py \
  tests/gateway/test_hosted_room_driver.py \
  -j 2 --file-timeout 30 -o "addopts=-m 'not integration'"
```

**202 passed, 0 failed, five files, 9.6 seconds runner wall** in this one sandbox
run. Not a performance target. New authoring tests: 58 value-policy cases plus
20 storage cases (78 total). Unmodified regression suites: 35 dispatch-session,
45 upstream discussion-policy and 44 upstream driver cases (124 total).

The first focused follow-up reported 77 passed / 1 failed: the new coexistence
fixture passed a string where the current `SessionDB` constructor expects a Path.
Corrected the fixture to `SessionDB(db_path=store.db_path)`; no production API was
changed or mocked. The corrected storage file passed all 20 cases, then all five
files passed in the final run above.

The storage tests use actual SQLite and an actual native SessionDB for coexistence.
A spawn-context two-process test gives two independent writers the same expected
revision; exactly one succeeds and the other receives `stale_revision`. A SQLite
abort trigger proves rollback preserves both document and revision, with a
successful same-revision retry after removing that injected trigger. Explicit
A/B/A ambient-home alternation does not redirect the explicitly bound DB.

## Killing mutations actually observed

Each mutation was applied in isolation after the slice was complete. The named
test failed, the original source was restored in a finally block, and the final
five-file run above passed on the restored source. No mutation survives the patch.

| Mutation | Named test which failed | Result |
| --- | --- | --- |
| In `capacity`, remove the exact-int requirement, accepting `6.0` | `test_capacity_types_are_not_coerced` | killed; exit 1 |
| In `_expect`, bypass the revision comparison | `test_create_update_cas_and_reopen_preserve_data` | killed; exit 1 |
| In `save_table`, discard the loaded preset baseline on edit | `test_preset_load_and_revert_are_revisioned_copies_not_live_links` | killed; exit 1 |
| In `_record`, bypass the deleted-row guard | `test_delete_tombstones_cannot_be_resurrected_by_old_clients` | killed; exit 1 |
| In `_schema_ready`, accept a different stored schema version | `test_shared_session_database_and_future_schema_are_preserved` | killed; exit 1 |
| In `plan_seats`, omit the remapped-participant report | `test_seat_preferences_reserve_valid_slots_and_report_geometry_remaps` | killed; exit 1 |

The delivery archive contains the actual stdout/stderr and mutation metadata under
`receipts/`. These are diagnostic receipts, not substitutes for local reruns.

## Still unproved / not implemented

No room-session adapter, twelve-member execution, atomic Start admission, run
presence, live-table mutation fence, runtime lifecycle, RPC, event publication,
Launcher product code, real-provider run, Windows/macOS test, or Stage C visual
proof is claimed. Allowing twelve authoring references does NOT lift upstream's
six-member execution policy. Constructor purity does not mean reads never perform
schema initialization: the first store operation initializes its namespace.
This is SQLite transaction/restart persistence, not a power-loss or distributed
exactly-once guarantee. Full-suite and real-serve cross-repository acceptance are
left to local integration.
