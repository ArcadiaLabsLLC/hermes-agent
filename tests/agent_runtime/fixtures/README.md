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
| Snapshot sha256 | `05edade189582f6f5781bc705a1628071a43c711f3a6c7a7394a4b29b4f1c291` |
| Snapshot taken | 2026-10-07, launcher `de077f4cb9f551090b24811e0edd6ad1962431e7` (`l-qa-brief`); 36-tool surface |
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

### Reviewed refresh: 2026-10-07

The exact Launcher source blob is `9a680dbff39da5faa91f201822ec823c03921aa0`.
Hermes adopts the reviewer's three added reads: `get_tool_manual` reads registered
manual/schema text without dispatching the described tool; `build_status` reads or
waits for an existing job without starting it; `get_render_profile` reads render
state. Names above use the `mcp_launcher_qa_` prefix. The seven newly explicit
warm-cache denials are `record_video`, `prebuild`, `dev_login`, `set_text`,
`resize_window`, `set_dpi`, and `pointer_drag`. All existing denials remain.
The resulting reviewer partition is 15 allowed and 21 denied tools. The full QA
profiles also document semantic-control scopes; those are fixture data, not new
Hermes MCP include entries. Unknown tool names remain denied by the positive list.
Alice/PM/reviewer can read the manual but cannot use it to execute a denied tool.
