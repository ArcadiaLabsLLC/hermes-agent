# Vendored cross-repo fixtures

Snapshots of files that live in ANOTHER repo and that a hermes test must be able
to check itself against **without that repo existing at runtime**. Each snapshot
is hash-pinned by the test that consumes it, so refreshing one is a deliberate,
reviewable act rather than something a `cp` can do silently.

## `launcher_qa_profile_allowlists.yaml`

| | |
| --- | --- |
| Source repo | `EterniaLauncher` |
| Source path | `docs/stages/qa-reboot/launcher_qa_profile_allowlists.yaml` |
| Snapshot sha256 | `4aad31d0467eaa807b2cf6295c25ec4645923d8495b88120dc4ecc63389591aa` |
| Snapshot taken | 2026-07-26, launcher `3e3feff0` (`feat(stagec-qa): run_actions — one MCP call, an ordered action list`); 26-tool surface |
| Consumed by | `tests/agent_runtime/test_mcp_admission_r2.py` (parity of `agent_runtime.mcp_admission.READ_ONLY_INCLUDED_TOOLS` / `READ_ONLY_EXCLUDED_TOOLS` against the YAML's `reviewer` row) |

Hermes **owns** the admission policy — design open question 6. This YAML is
documentation plus a CI parity fixture; it is never read at admission time, so a
missing launcher checkout or a deploy skew can never change what an agent may
call.

**This pin earned its keep within the hour.** The first snapshot taken (launcher
`a856f2b0`, 25 tools) was stale before R2 landed: the launcher shipped
`mcp_launcher_qa_run_actions` — a capability *multiplexer* that executes an
ordered list of other verbs in ONE call — and denied it to every restricted
profile precisely because a name-matching allowlist cannot see inside a batch.
Hermes adopted the denial. Note which direction the two shapes fail in: under a
positive include the new tool was denied by construction, and the pin only had to
tell us to *record* that; under an exclude list it would have been silently
admitted the day it shipped.

### Refreshing it

1. Copy the current source file over this one.
2. Re-run `sha256sum` on it and update **both** the table above and
   `_LAUNCHER_ALLOWLIST_SHA256` in `tests/agent_runtime/test_mcp_admission_r2.py`.
3. Re-run `pytest tests/agent_runtime/test_mcp_admission_r2.py`. If the parity
   assertions now fail, the launcher changed which tools a restricted profile may
   call: decide deliberately whether hermes adopts the change, then update
   `READ_ONLY_INCLUDED_TOOLS` / `READ_ONLY_EXCLUDED_TOOLS` in
   `agent_runtime/mcp_admission.py` **with a written security note**, or record
   the divergence in
   `docs/agent-runtime-harness/mission-chat-mcp-admission.md`. Never silently
   widen the include list to make a test pass.

## `round4_base_test_references.json`

| | |
| --- | --- |
| Source | this repo, pre-fold commit `4a21f0779` (absent from `main`'s history) |
| Snapshot sha256 | `7714caec75881a47ef52524f851d250e34eab8c03b4f99127048158e2da8b41c` |
| Snapshot taken | 2026-09-29, lane h10b-ci, after CI run 36621081725 failed `bad revision` on a fresh clone |
| Consumed by | `tests/agent_runtime/test_tombstone_registry.py` (`test_round4_deleted_tests_left_no_live_production_subject_uncovered`) |

Not cross-repo, but the same problem: the round-4 coverage audit's base is a
commit a fresh clone cannot resolve. The file freezes every top-level `test_*`
that existed at the base together with the `(module, symbol)` production
subjects it referenced; the audit reports any such test that no longer exists
whose live subject no current test references. The generator is
`_base_test_references` + `_serialise_base_test_references` in the consuming
test, and it needs a clone that still holds the pre-fold objects. The snapshot
is final — its base does not move — so a refresh should only ever fix a
generator defect, never absorb a coverage loss.
