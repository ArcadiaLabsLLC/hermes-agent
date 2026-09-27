# Native recovery repairs

Status: implementation in progress; not qualified or landed on main.

The owner approved the full [repair plan](native-hermes-lifecycle-audit-2026-09-26.md),
including compute-host answer acknowledgements. Stateful native RPC remains the
foundation. No Companion, real-profile or provider-credential changes.

## Native ownership

- Pending questions and bounded answer receipts belong to `server_requests`.
  The compute bridge returns the child's verdict, not a successful pipe write.
  Receipts contain an ephemeral keyed fingerprint, never the answer or a reusable
  secret hash. Retries address the exact session and question.
- Replay caches do not own sequence lifetime. Native session retirement releases
  sequence metadata; ring eviction preserves live numbering and its gap watermark.
- Route/admission records remain necessary for scope, fingerprint and one-unsettled
  admission. They must not become another transcript or pending-question store.

## Positive controls

- `test_native_answer_ack.py`: before repair, expired child answers and all three
  missing-ack cases incorrectly returned `ok` (4 failed, 1 passed). Seven focused
  cases now pass, including cross-session refusal and duplicate-answer receipts.
- `test_native_replay_recovery.py`: before repair, cache eviction changed the live
  session's latest sequence from 3 to 0; the repaired case passes.

These are unit controls, not end-to-end qualification. The audit's complete
reconstruction, cancellation, retirement, concurrent-surface and native UI matrix
remains required before closing its queue rows.

## 2026-09-27 branch checkpoint

Native execution identity reaches admission, events and interruption. An
acknowledged Stop remains a request, not a terminal verdict. Its durable intent
survives a missing reply; observation retries only that execution. Relayed child
events retain their original identity. Observation-only resume cannot schedule
auto-continue.

The outer event ring and question registry are removed. Reads translate native
epoch/sequence pages without retaining history. A read captures its dispatch
receipt before requesting events: the real-worker A/B/A test exposed the inverse
order returning completion ahead of its terminal event.

Measured focused checks:

- Answer owner: 7 cases; real child-process acknowledgement: 1, including a
  deliberately dropped reply, same-answer retry and cross-session refusal.
- Execution fences: 5; replay eviction sequence continuity: 1.
- Native recovery snapshot/prefix/history: 4; existing compute turn protocol: 10.
- Conversation service: 9; stateless event projection: 3; real native A/B/A: 1.
- Focused Ruff check passed. Generated gateway contracts refreshed.

Not complete: client/Compare restoration, native retirement, compressed-history
recovery, broader regression qualification and native UI acceptance. No main
landing or claim closure is justified by these focused results.

## Startup cancellation and native retirement boundary

Two added execution tests failed before the repair: cancellation during agent
startup left a running receipt, and a competing native admission replaced the
current execution. The fenced cases now pass (7 execution tests total).

`session.retire` reuses native reaper eligibility and teardown. It requires exact
settled execution evidence, refuses queued/pending/building/delegated work, checks
again after child retirement, and removes only disposable replay metadata. A
stale session reference cannot admit work after the native owner removes it.
Eleven focused cases pass; the stale-execution test also caught and corrected an
initial guard that accepted an older completed execution while a newer one existed.

The service's bounded open/facts reads pass its 9 focused cases. Generated
contracts and focused Ruff checks pass. **The retirement operation is not yet
wired to observation/retention policy.** Aggregate retention, real child retirement,
client reconstruction, compressed history and full acceptance remain unqualified.
