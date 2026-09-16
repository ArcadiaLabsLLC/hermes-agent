# Discussion Tables — runtime checkpoint handoff (2026-09-16)

Status: **checkpointed on `feat/discussion-tables-20260916`; do not merge to `main` yet.**

This note is the continuation point for the Discussion Tables program. Read the root `AGENTS.md`, applicable nested instructions, `docs/agent-runtime-harness/00-index.md`, the existing `upstream-bot-mode-peer-integration.md`, and `discussion-tables-local-handoff.md` before changing code.

## What is implemented in this branch

- strict table/preset definitions using exact durable instance addressing;
- capacities 2/4/6/8/10/12 and Auto, deterministic seats and explicit remap reporting;
- revisioned SQLite definition storage with tombstones and CAS semantics;
- durable discussion Start intent/run storage, current membership and instance/table presence fences;
- native instance-bound room sessions, including distinct instances that share one Hermes profile;
- auxiliary room-chat execution that preserves ordinary task-scoped/default chat ownership;
- reused hosted-room execution rather than a second model loop/scheduler;
- native room policy widened for the Mission Control 12-member use case without globally changing stock Bot Mode defaults;
- exact attempt identity, cancellation/recovery bookkeeping and commit-before-callback reconciliation;
- additive authenticated `runtime.discussion.*` JSON-RPC surface on the existing serve lane;
- producer-side wire descriptor/fixture coverage and focused recovery/ownership tests.

## Validation recorded before this handoff

The earlier foundation review passed the normal repository runner with **202/202** relevant cases (definition/store, dispatch-session, hosted-room discussion and driver).

The newer runtime checkpoint compiled successfully with `python -m compileall`. In the cloud sandbox the canonical runner could not start because `pytest-timeout` is absent; a fallback focused invocation without repository `addopts` passed **21 tests** covering runtime, native admission and wire behavior. Treat that as focused evidence, not the final repository gate.

## Remaining runtime verification

1. Rerun the changed discussion/native/hosted-room suites with the normal project environment and canonical `scripts/run_tests.sh`.
2. Run the broader affected regression population once at the feature-complete checkpoint.
3. Exercise a real serve child with the Launcher consumer, including restart boundaries and lost-ack recovery.
4. Prove: two same-profile instances remain distinct; 12-member execution; default-chat pointer unchanged on success/failure/clarification; stale Stop cannot kill a newer operator turn; commit-before-callback does not rerun; concurrent Start/edit conflicts are typed; End/remove do not release live work early.
5. Pin the final producer/consumer fixture against the Launcher branch after both tips are fixed.
6. Keep cross-install rooms, automatic failover and stock `hermes peer` interoperability separate unless explicitly added and tested; this checkpoint does not claim them.

## Landing rule

Do not merge this branch alone. The Launcher half must pass its compile/test gates and Stage C against the exact Hermes revision. Then rebase/resolve both feature branches against current `origin/main`, rerun affected gates, fast-forward/push without forcing `main`, and reconcile primary checkouts.
