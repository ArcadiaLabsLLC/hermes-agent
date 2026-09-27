# Native conversation lifecycle reuse audit

Status: findings reproduced; implementation not changed by this audit.
Baseline `5d00ba8388eebd5fa416a54f8f51bba0aaf875ad`; origin and
`nekwo/hermes-agent` main advertised the same SHA. Consumer evidence and full
acceptance matrix: `EterniaLauncher/docs/companion/planned/NATIVE_HERMES_LIFECYCLE_AUDIT_2026-09-26.md`.
This limits, rather than replaces, the earlier
[qualification](native-hermes-qualification-2026-09-26.md).

## Native-owner repairs

1. `ConversationService.open` returns projected events but discards the existing
   native live snapshot. Reuse `_live_session_payload`, SessionDB and
   `server_requests.open_requests`; establish a coherent recovery checkpoint and
   native replay cursor, not separate racing state/sequence reads. Remove the
   second history/replay authority from `agent_runtime/conversations/events.py`.
   A small aggregate-bounded delivery projection is disposable.
2. `ConversationService.stop` excludes unknown receipts. `LiveConversation` sends
   only a session ID to `session.interrupt`; `prompt.submit` receives no admitted
   turn identity. Persist the admitted-request/native-execution relation and
   cancellation intent; validate the exact execution in the native owner. Repeated
   Stop is idempotent; requested and stopped remain distinct. The checkout
   `execution_id` guard is installation evidence, not a per-turn execution fence.
3. `LiveConversation.answer` reports accepted after a pipe write. Existing native
   `request.answer` reports `ok`/`expired`; use it with session/execution ownership
   and reconcile a lost reply. Do not infer open permissions from old events.
4. Service maps retain settled sessions indefinitely; native TTL/LRU reapers already
   protect attached transports, so the permanent stdio peer prevents eligibility.
   Add logical observation/retirement at the native owner and reuse its eligibility
   recheck. Protect queued, active, pending, delegated and uncertain work; do not
   kill the profile worker to evict one conversation's cache.

## Native seam hazards

- `tui_gateway/event_replay.py::_stamp_event` deletes counters when a session ring
  is evicted. Real-module probe: seq 3 → evict with 64 other sessions → reinsert
  at seq 1, unchanged epoch. Preserve monotonic session identity or explicitly
  invalidate the old cursor; process epoch alone is insufficient.
- `_live_session_payload` and `session.events.since` do not currently provide one
  atomic checkpoint across history, in-flight state, requests and sequence. An
  adapter-side call sequence cannot prove that invariant; use a focused additive
  native seam, following the fork footprint policy, not another state manager.
- `session.resume` cold paths may schedule `_maybe_schedule_auto_continue`.
  Existing unsettled refusal prevents that route today. Recovery must be explicitly
  observation-only and respect the existing marker's `auto_continue` policy;
  never change Desktop's global defaults or silently replay an uncertain prompt.

## What to keep

The native worker starts the existing gateway, not a second agent engine.
`Workers` has no background restart loop. Profile ownership is distinct from
`HostSupervisor`'s compute isolation and different wire protocol. `spawn_server`
containment is already reused. Consolidate common mechanisms where semantics
match; do not replace this peer with the compute supervisor by name alone.

`ConversationStore` already uses `sqlite_util` transactions and protects scoped
payload fingerprints plus an atomic one-unsettled constraint. Generic
`RunIdempotencyStore` lacks that constraint and permits memory fallback; wholesale
replacement would weaken safety. Extend durable execution evidence, not transcript
storage. Discuss already has task/generation fencing and native journal recovery;
reuse its lessons without forcing operator and conversation sessions into one lane.

## Reproductions and limits

Local archive `lifecycle-audit/hermes-expanded-red.log`: **6 red, 3 green**.
Red: native snapshot discarded; unknown Stop emits nothing; replay overflow on
reopen; interrupt lacks execution identity; expired native answer status is not
consulted; real native ring sequence resets. Worker is doubled; production SQLite
and service run unchanged. Wire-fence and question tests show missing guarantees,
not a real-process delayed-interrupt or expiry-timer acceptance run.

Green controls preserve duplicate suppression/payload conflict/one-unsettled turn
and completed-before-Stop behavior. Retention probe after 20/40/80 completed
sessions: serialized projected buffers 1,345,399 / 2,690,919 / 5,381,959 bytes;
Python traced growth 1,501,066 / 3,026,862 / 6,078,378 bytes after GC. No unsettled
receipts. This is bounded synthetic measurement, not total RSS or a long soak.

Launcher probes add **4 red**: reconstructed adapter loses events and cannot Stop;
reconstructed engine cannot reconnect or Stop a persisted uncertain turn.
No real profiles, provider credentials, network turns or Mission Control processes
were used. No repairs, broad-suite green claim or native UI restart acceptance yet.
Permanent regressions and native UI qualification belong in the repair landing.
