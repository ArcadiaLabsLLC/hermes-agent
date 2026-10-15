# Native discussion runtime — implementation checkpoint

2026-09-16. This checkpoint extends the reviewed definition/preset foundation.
It is feature-branch implementation, not a claim of Launcher or Stage C acceptance.

## Implemented

The existing serve owner binds the head-home definition/run/attempt stores. Additive
`runtime.discussion.*` methods use the existing authenticated method registry and
explicit console/read tiers; native peer permissions are unchanged. Start owns an
immutable configuration and durable table/instance claims. Definition writes share
the same immediate-transaction busy fence. Commands carry stable idempotency keys
and expected revisions. The public log remains upstream-owned.

`NativeSessionRPC` enters the canonical mission-chat handler under a trusted exact
auxiliary-chat scope. Opening, catalog repair, preparation and finalization do not
rewrite the operator's current instance row/default chat. Real native journal
commit evidence drives recovery, including clarification metadata. Exact attempt
interrupt scopes never select a newer operator turn. Unknown outcomes require
explicit recovery; cancellation acknowledgement waits for the owned turn to exit.

The existing HostedRoomRuntime remains the worker/scheduler. Native-only policy
limits admit 12 simultaneous instances (including a shared profile), up to three
rounds, and a 12KB member prompt. Stock profile/group limits stay unchanged. Native
policy checkpoint projection uses a larger bounded buffer for those rounds. End
pins the upstream transcript before disbanding; it does not erase meeting history.

## Local execution receipts

All commands below ran through `scripts/run_tests.sh` in an isolated source worktree.
This sandbox lacks pytest-timeout: the runs explicitly used
`-o "addopts=-m 'not integration'" --file-timeout 160` (180 for native-admission).
That is an environment qualification, not a repository configuration change.
Normal dependency/test options must be used in the local acceptance lane.

- Initial six-file run: 209 passed, one failed. The failed exact-End test exposed
  an interrupt guard that prevented sending cancellation to a still-live attempt.
  The guard now prevents only an unproved INACTIVE acknowledgement.
- Final `tests/agent_runtime/test_discussion_runtime.py`: 8 passed, 21.2s runner
  wall. Real SQLite/session/journal/room workers; deterministic provider boundary.
  Includes twelve distinct same-profile members, separate sessions, End/history,
  transactional Start replay/edit fences, competing table claims, commit-before-
  callback recovery, clarification continuation, exact End and wire validation.
- Initial native handler test found the handler's catalog-repair call still rewrote
  the instance display projection on auxiliary admission. Auxiliary admission now
  skips that writer, not just open/finalize. One test also corrected its assumption
  about the native journal's flattened metadata shape.
- Final `tests/agent_runtime/test_discussion_native_admission.py`: 7 passed, 2.8s.
  These run the REAL native handler with a deterministic provider. Success,
  failure, clarification and a concurrent operator row/thread change preserve the
  operator pointer/name. Scope reset and exact-pair checks pass.
- The initial six-file run's unchanged regressions passed: definition values 58,
  definition storage 20, dispatch policy 35, hosted discussion policy 45 and
  hosted driver 44. These are not a claim of a full repository suite.

## Still owed

Producer/consumer fixture, broader native/admission/authorization and crash-boundary
coverage, normal local dependency run, Launcher consumer/rendering implementation,
combined two-repository acceptance, actual live-provider smoke and stamped Stage C.
No test here establishes cross-install rooms or peer interoperability. New controls
must not advertise those features; capability reporting leaves them false.
