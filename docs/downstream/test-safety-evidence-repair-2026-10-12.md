# Test attribution and original-attempt evidence repair

Scope: H02 and H13 from [the history-red triage](history-red-triage-2026-10-12.md).
Console history and production runtime behavior are unchanged. No upstream PR
is part of this repair.

## H02: correct ownership, preserve isolation

The triage reproduced a real gate failure but inferred the wrong cause. This
clone's `upstream/main` points at `ac0cfa7db9` from July. The integrated release
in `tests/fixtures/upstream_manifest.txt` is `818c13be1d` (v0.21.6), from October.
All twelve reported calls in seven files are upstream lines. The existing
`tests/_downstream/id_markers/hooks.py` collection hook marks these test bodies;
`tests/_downstream/conftest_plugin.py::pytest_pyfunc_call` restricts their undo to
body patches. No new sandbox leak was established by the structural red.

`tests/_fork_scope.py` now reads the release base through the existing
`scripts/upstream_footprint.py::read_manifest`, resolves it to a commit and
requires it to be an ancestor of HEAD. Missing, malformed, unavailable,
non-commit or non-ancestor bases still fail closed. No remote fetch is required
to attribute already-integrated source. The gate's AST scan, ban and fixture
tripwire remain intact; no inherited test is rewritten.

`tests/test_fork_scope_downstream.py` uses real scratch Git histories to prove
missing, stale and ahead-of-release remote refs cannot change attribution;
fork-added lines remain in scope. The new behavioral case in
`tests/test_conftest_pin_tripwire.py` drives the real collection and call hooks:
two body undos drop their stubs while keeping the home, credential blanking,
safety pin and teardown witness.

## H13: preserve the original attempt through the existing owner

`scripts/run_tests_bundled_plan.py::RunLedger` now retains one typed
`BundleDiagnostic` per abnormal bundle, before retry scheduling. It records
ordered members, process and recorded session statuses, whether the session
ended, its last observed member, failing node IDs and original output.
The existing `agent_runtime/redaction.py::scrub_secret_values` scrubs output
and node IDs before retention. Large output retains the first and last 32 Ki
characters and an explicit omitted-character count; no second redactor exists.

`scripts/run_tests_bundled_gate.py::GateRun.record` writes these records to the
existing clone-wide `runs.jsonl`, including runs with green-result caching off.
Scratch event files can still be removed. The terminal prints each original
bundle diagnostic once and explicitly labels summary counts as final attempts.
Final-red caching, retries, timeouts, exit policy and skip lists are unchanged.

`tests/scripts/test_run_tests_bundled_diagnostics_downstream.py` exercises failure,
process death, contradictory zero exit, missing session end, collection failure,
green retry, scratch cleanup, durable recording, redaction and truncation.
The cache/store integration test now uses the real ledger rather than a partial
stand-in. There is no parallel runner or receipt store.

## Verification

Source commit `db6ad5b124` records the killing mutations and their actual reds.
The nine focused files cover 127 passing tests after replacing one incomplete
test double with the real ledger. Removing original-attempt capture reddens
all five recovery cases; bypassing redaction reddens those cases and the bound
test; disabling scoped undo loses the fixture safety pin; using the stale
remote base misattributes upstream lines. The mutations ran in a disposable
checkout and are absent from the repair tree.

The real compression-worker/declared-scope pair reproduced its original
`'telegram' != 'override-src'` assertion, then passed alone (59 final passes,
exit 0). Both the terminal and the gate-store JSON retained original rc 1,
the failing node, ordered members and assertion while the final-red map was
empty. This proves H13 on the actual triaged leak, not only synthetic events.

The canonical `scripts/run_tests_bundled.sh tests` landing gate selected 1,026
fork files, with zero cached skips: **12,510 passed, 68 failed, one setup error,
49 skipped**, exit 1, 608.5 seconds. All **69** failing/error nodes match the
previous untouched-main inventory exactly; none is new. The baseline source
`5856b5d476` differs from this repair's parent `14c21555e4` only in documentation.
There were 63 bundles, 12 solos, 15 known-red runs, zero retries, zero process
deaths and zero final timeouts. The remaining reds are the recorded gateway/TLS
assertions and Python-version fixture error; this is not a green repository.
The [qualification record](test-safety-evidence-repair-2026-10-12.json) retains
the exact node set, source pins and log hashes.

The shared-undo gate, release-attribution cases, behavioral fixture proof and
all runner/cache tests passed in that broader run. The legibility floor,
duplicate-helper and upstream-footprint gates passed. The corrected attribution
also makes the existing source-grep and path-identity gates green; their
inherited source was not changed. Ruff, diff checks and the canonical citation
gate passed. Zero upstream-owned files changed.

The existing run-history file has no retention policy and its readers scan
the full file. That separate lifecycle finding is recorded in the fork-hygiene
queue; this repair bounds each diagnostic and preserves the existing history.

Remaining scope/backup leaks, Codex process death, TLS/environment failures and
Session API delivery stay in their existing queue rows. A recovered retry is
evidence to investigate, not proof that the original problem is fixed.
