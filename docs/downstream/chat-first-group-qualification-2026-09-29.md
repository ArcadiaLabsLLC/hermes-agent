# Chat-first group qualification

Scope: profile-backed groups and per-message Discuss, Compare and exact-member
reply. The existing Discussion service and native conversation owner remain
authoritative. This is automated qualification, not live-provider desktop acceptance.

## Population and receipts

The fork-owned population contained 623 files across `tests/agent_runtime`,
`tests/hermes_cli` and `tests/hermes_state`. Upstream-inherited files, including
the parked wrapper-publication investigation, were not included.

The first bundled run produced real outcomes for 422 files: 6,282 passes.
Nineteen other files had green labels but no test events; the recorder ended
with exit 2. They were not counted and were rerun individually. The remaining
201 files plus nine landing gates ran through the canonical per-file runner:
3,837 passed, 90 failed, five skipped, one collection error. One worker, no retries.

Nine failures belonged to this change: two imports still named the pre-split
native-turn owner, six manifest assertions omitted the two new console methods,
and one complexity exemption survived after its function was simplified.
The imports and manifest were corrected; the obsolete exemption was removed.
Two further failures were a missing `upstream/main` ref; fetching that ref
restored the gate's actual ownership input, without changing a baseline.
The correction run passed all 177 tests across eight files, including the
restored scope guard, method manifests, import boundary and footprint/legibility gates.

## Baseline comparison

The remaining 18 red files were rerun with the same Python 3.13.15 environment,
canonical isolation and one worker on clean primary `f2c8a2ef40`. All 79 failing
test identities and the collection error reproduced. Their implementation
paths were not changed by this group slice. This does not make them acceptable
or establish that the repository is wholly green.

| Existing failure class | Tests | Disposition |
|---|---:|---|
| TLS certificate/pin mismatch across ten gateway suites | 68 | Existing validated-suite residual row; still reproduces on this host despite another environment's green receipt. No TLS check weakened. |
| Chat-lane tests patch symbols moved into local imports | 5 | Follow-up in fork hygiene. |
| Duplicate-helper gate: unrelated `_model` names | 1 | Follow-up in fork hygiene. |
| Realm history ordering and publish staging | 3 | Follow-up in runtime queue. |
| Removed auth provider / missing root-observability envelope | 2 | Existing C2/C3 rows, already claimed by another lane. |
| Removed `hermes_cli.dep_ensure` test import | Collection error | Existing C2 row, already claimed. |

The TLS result differs from the Python 3.12 triage receipt in
[the earlier triage](triage-561-2026-09-29.md); neither result overrides the other.

## Isolation positive control

Removing `run.start_group` from the authenticated group-scope guard made
`test_open_is_idle_without_office_or_agent_creation_and_has_private_scope`
fail: expected `conversation owner changed`, received `workspace not found`.
The mutation was reverted. Lost/repeated request and answer acknowledgements,
exact Stop, independent failure and reconstruction have separate native tests.

Local logs under ignored `qa-artifacts/`: `chat-first-fork-landing.log`,
`chat-first-isolated-landing.log`, `chat-first-primary-baseline.log`,
`chat-first-scope-mutation.log`, and `chat-first-corrections.log`.
