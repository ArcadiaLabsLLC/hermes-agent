# Planned — the launcher reads Lens-episode and agent-turn events after a cursor

**Status:** planned 2026-10-28 (lane w1028a-h-plan) for row `RT-LAUNCHER-EVENT-CURSOR`. Not built.
**Consumer:** the launcher's webhook source W4 (`DIST-WEBHOOK-LENS-SOURCE`,
`EterniaLauncher/docs/stages/installer-distribution/planned/HOST_OUTBOUND_WEBHOOKS_2026-10-27.md`
H5 and W4), which writes an event's outbox rows and its cursor in one transaction, so it needs a
cursor that names a durable position and a replay that is complete or says it is not.
**Owner doc:** [03 — Transport and wire](../03-transport-and-wire.md) (the method lane).

## 1. What the tree already has

The row asks for "a bounded durable journal". There is one already, and this plan uses it rather
than adding a second store:

- **The event log is the journal.** `agent_runtime/events.py::EventLog` appends every
  `lens.episode.changed` (`agent_runtime/lens/store.py`) and `persona_chat.turn_ended`
  (`agent_runtime/decision_contract_registry.py`) the runtime produces, whether or not a launcher
  is attached.
- **Its positions are durable and monotonic.** `agent_runtime/event_rotation.py` gives every line a
  LOGICAL offset that spans rotated slices; rotation seals a slice in place under
  `events_archive/` and never rewrites or deletes one, so a stored offset resolves to the same line
  forever (`EventLog.iter_from_offset`).
- **It already knows when a span can no longer be replayed.**
  `event_rotation.resume_floor_offset` answers the oldest offset from which every later slice is
  still on disk, and `agent_runtime/stream_resume.py` already refuses a resume below it
  (`journal_truncated`) rather than serving a span with a hole in it.

So no new file, no new retention rule, and no new writer: retention is the event log's
(archive-never-delete, a slice an operator removes by hand raises the floor), and "bounded" is a
property of each READ (§3), not of the store.

## 2. Decisions

1. **One read-tier RPC method, `runtime.events.after`** on the method lane, in a fork module
   `agent_runtime/serve_rpc/events_after.py`. Read tier, every transport: the events it returns are
   identity keys and states, never message text (§4), the same facts the stream lane already ships.
2. **The cursor is an opaque string** `"<journal_id>:<offset>"`. `offset` is the logical offset
   AFTER the last event the caller has committed. `journal_id` names the journal: a UUID minted
   once into `<store_root>/events_journal.json` (an additive path — a non-breaking
   `store_epoch.MIGRATION_REGISTRY` entry) the first time the method is asked. A cursor whose
   `journal_id` is not this store's (a reset store, another namespace) can never be read as an
   offset into this one.
3. **The event kinds are a closed allow-list in the method's module**
   (`WEBHOOK_EVENT_TYPES`): `lens.episode.changed`, `lens.receipt.changed` and
   `persona_chat.turn_ended`. A request may narrow it (`types`), never widen it; an unknown type is
   refused `unknown_event_type`. Adding a kind is a code change with its own test, because each one
   is a payload a third party's receiver will see.
4. **Each returned event carries a stable `event_id` = `"<journal_id>:<offset of its line>"`**, so the
   launcher's `UNIQUE(webhook_id, event_id)` makes a re-read a no-op and a receiver can de-duplicate
   (`HOST_OUTBOUND_WEBHOOKS` H5).
5. **A read is bounded twice:** at most `limit` events (default 200, max 500) and at most
   `SCAN_BUDGET_BYTES` (4 MiB) of journal scanned, whichever comes first. `next_cursor` always
   advances past every byte scanned, matched or not, so a page with zero matches still makes
   progress and a caller loops until `at_tail: true`.
6. **Refusals are typed and say where to go next, never silently empty:**
   - no `cursor` → no events, `next_cursor` = the tail (a new registration starts now; it does not
     replay history the user never subscribed to);
   - `journal_mismatch` → the cursor names another journal; the reply carries `tail_cursor`, and the
     launcher records the restart as a reason on its source before moving to it;
   - `journal_truncated` → the offset is below `resume_floor_offset()`; the reply carries
     `floor_cursor` and the byte span lost, and the launcher records the gap before continuing from
     the floor;
   - `cursor_ahead_of_journal` → an offset past the tail (the same evidence `stream_resume` reads as
     "not this runtime's baseline"), answered like `journal_mismatch`;
   - `journal_unreadable` → the tail cannot be stat'ed; the caller keeps its cursor and retries.
7. **The launcher stores the cursor only after its outbox commit** (its H5); hermes keeps no
   per-client position and so has nothing to lose or to garbage-collect.

## 3. The reply

```
runtime.events.after {cursor?: str, types?: [str], limit?: int}
  -> {events: [{event_id, type, at, payload}], next_cursor, at_tail: bool,
      refused?: {reason, tail_cursor?, floor_cursor?, lost_bytes?}}
```

`at` is the event's own `ts` (ISO-8601 UTC); `payload` is the event's payload as stored.

## 4. What a payload may carry

The three kinds' contracts (`decision_contract_registry.py`) are identity keys and states:
`monitor_id`, `episode_id`, `state`, `rule_id`, `ordinal`, `outcome`; `persona_instance_id`,
`root_chat_session_id`, `client_message_id`, `turn_id`, `state`. The method returns only the
contract's declared required and optional keys for each kind (a projection, not the raw dict), so a
field added to an event later does not reach a third-party receiver until this module names it.

## 5. Slices

- **E1 (hermes):** `agent_runtime/serve_rpc/events_after.py` (the method, the allow-list, the
  projection), the `journal_id` file and its `paths` builder plus the store-epoch entry,
  `serve_rpc_manifest.expected.json` regenerated (+1 method), doc 03's method list. Tests:
  `tests/agent_runtime/test_events_after.py`.
- **W4 (launcher):** `DIST-WEBHOOK-LENS-SOURCE`, which reads it on attach and on each
  `lens.episode.changed` / `persona_chat.turn_ended` it sees live (the live frame is only a nudge;
  the cursor read is the authority).

## 6. Test plan (each with its killing mutation)

- **Complete span:** events of the three kinds appended while "no launcher ran" are returned once,
  in offset order, and a second read from `next_cursor` returns none (positive control: a fourth
  event appended after is returned). *Mutation:* return `next_cursor` = the last matched event's
  offset instead of the end of its line → the second read returns it again → red.
- **Allow-list:** a `persona_chat.send_refused` and a `state.reconciled` in the span are never
  returned, and `types: ["state.reconciled"]` is refused `unknown_event_type`. *Mutation:* drop the
  type filter → red.
- **Projection:** an event whose payload carries an undeclared key returns without it.
  *Mutation:* return `event.payload` raw → red.
- **Progress on an empty page:** 5 MiB of other events then one episode → the first page is empty
  with `at_tail: false` and a moved cursor, the second returns the episode. *Mutation:* advance
  the cursor only past matches → the loop never ends (bounded test) → red.
- **Truncation is named:** a cursor below a removed sealed slice → `journal_truncated` with the
  floor. *Mutation:* read from the cursor anyway (`iter_from_offset` skips the missing slice) → an
  event list with a hole and no refusal → red.
- **Another journal:** a cursor with a different `journal_id` → `journal_mismatch`, no events.
  *Mutation:* ignore the id → events from offset N of this store → red.

## 7. Open questions

None blocking E1. The launcher decides its own nudge (whether a live `lens.episode.changed` frame
triggers an immediate read or the next poll) in W4.
