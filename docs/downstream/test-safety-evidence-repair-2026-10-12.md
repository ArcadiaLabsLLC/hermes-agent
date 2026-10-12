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

Focused checks and mutation controls are recorded in the repair commit body.
Mutation runs use a disposable checkout; their defects are absent from the
repair tree. The completed whole-tree gate and any remaining baseline failures
are recorded below when qualification finishes.

Remaining scope/backup leaks, Codex process death, TLS/environment failures and
Session API delivery stay in their existing queue rows. A recovered retry is
evidence to investigate, not proof that the original problem is fixed.
