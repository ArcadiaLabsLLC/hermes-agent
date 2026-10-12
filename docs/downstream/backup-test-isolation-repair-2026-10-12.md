# Backup collection-order isolation repair — 12 October 2026

H11 is a deterministic test-isolation defect. The apparent intermittent depends
on which files pytest imports during collection, including files that execute
after the backup tests. Source baseline: `ce10e2de15`.

## Cause and boundary

`tests/hermes_cli/test_backup_runtime_lock_downstream.py` imports
`hermes_cli.backup` during collection. Backup binds
`hermes_constants._get_platform_default_hermes_home` then. Later,
`tests/conftest.py::_hermetic_environment` patches the function on its defining
module, leaving backup's imported alias unchanged. `run_import` reaches that
alias while deciding whether to start the gateway after a restore. The
home-I/O guard refuses the resulting native-home metadata read.

The original three preceding files alone did not reproduce this because they
omit the collection-time importer. The original 20-file bundle reproduces all
19 backup failures. The minimal reproducer is just `test_backup.py` followed
by `test_backup_runtime_lock_downstream.py`; both modules are collected before
either body runs. This is independent of a provider or the operator's backups.

The repair extends the existing CLI isolation owner:
`tests/_downstream/hermes_cli_conftest/isolation.py::_backup_native_home_follows_test_home`.
After `_hermetic_environment`, it rebinds an already-loaded backup module to
delegate to the existing isolated resolver. Tests' explicit resolver overrides
still apply. The fixture does not import backup into other tests. The package
`__init__.py` registers it through the existing conftest seam.

No production restore change, new runner, unbundled-list entry, home-I/O
allowance, skipped assertion or upstream-file edit is part of this repair.

## Qualification

All runs use Windows / Python 3.13.15 and the canonical wrappers.

| Run | First attempt |
| --- | --- |
| Original 20-file bundle, unchanged baseline | 19 backup failures; isolated retry passes |
| Same bundle with the fixture | 204 passed, 10 skipped, 2 existing xfails; no rerun |
| Seven adjacent backup/isolation files | 69 passed, 4 existing skips |
| Killing control: remove only fixture registration; minimal two-file bundle | Same 19 backup failures; isolated retry passes |
| Restore registration; same minimal bundle | 84 passed, 10 skipped, 2 existing xfails; no rerun |

The killing control leaves the fixture implementation present but unreachable.
`TestImport::test_import_auto_installs_gateway_service` and the other 18 nodes
again fail at the native-home I/O guard. The runner's final zero after an
isolated retry is not treated as a clean first attempt; its retained original
diagnostics contain process/session exit 1 and all 19 failing IDs.

Minimal command:

```bash
bash scripts/run_tests_bundled.sh --no-cache --bundle-size 20 \
  --bundle-seconds 0 --solo-seconds 0 --file-timeout 120 --file-retries 0 -j 1 \
  tests/hermes_cli/test_backup.py \
  tests/hermes_cli/test_backup_runtime_lock_downstream.py
```

Ruff passes for the two changed modules. This is scoped qualification, not the
landing gate. `Harness_Brain/50 — Agent Handoffs/Running the tests.md` requires
session-chain changes to join a release-merge batch; this repair awaits that
batch's whole-tree qualification before landing. No full suite was run here.

The broader upstream fixture limitation remains: patching a defining module
does not update previously imported aliases. Backup is qualified and repaired
through the fork's existing test seam. Other consumers, including
`gateway.status`, need their own behavioral reproduction before extending the
fixture or proposing an upstream repair. No such submission is claimed.

## Retained receipts

Logs remain in the shared worktree parent. The queue points here; this note is
evidence, not another backlog.

| Log | SHA-256 |
| --- | --- |
| `triage-h11-whole-bundle.log` | `f72edabb7f2b77e22ece56a2491bba3f754aa56129a409874d9aef9e61f66999` |
| `triage-h11-whole-bundle-green.log` | `5f1b87797cd9762b4d523af357664d088ec16668d964df80554eb2817794bf7e` |
| `triage-h11-adjacent.log` | `89ba997d2be8e26fcbf60b5639435498f3ef3e56109f0777c729408ec361fc23` |
| `triage-h11-registration-red.log` | `88b0bc9afe378b9072f6b1dd5139fc1fe5984df496a1ea15a9cc004ae60c15bc` |
