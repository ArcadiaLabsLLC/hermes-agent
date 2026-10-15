# Chat-turn settle push — contract (2026-10-10)

Owner ruling 2026-10-09: hermes pushes every chat-turn settle and verifies the push
landed; the launcher never polls or re-probes. Runtime-queue row "Push every chat-turn
settle…" (h-settle-push).

## The settle frame

One frame per settled chat turn (`mission-chat message` / `mission-chat steer`), on
the serve's CONTROL channel, never the stream lane:

```json
{"event": "turn_settled", "lane": "settle", "settle_id": "<sha256>",
 "client_message_id": "...", "session_id": "..." | null, "turn_id": "..." | null,
 "request_id": "<serve rid>", "exit_code": 1, "refusal_class": "..." | null,
 "fix_hint": "..." | null, "summary": "..." | null, "settled_at": "...Z", "attempt": 1}
```

`refusal_class` / `fix_hint` / `summary` come from the turn's own last JSON result line
(`error_kind` | `error.code` | `code`; `fix_hint` | `error.hint` | `next_expected`;
`summary` | `error.message` | `error`). `settle_id` is the record key:
sha256(`session_id` NUL `client_message_id`), with `session_id` taken from argv
`--session-id`, else the result line. A turn with no client message id is not pushed
(nothing to correlate on). A serve-side duplicate refusal and a journal
`chat_turn_duplicate_in_flight` are not settles of the turn and are not recorded.

## Transport

The control channel the drain/shutdown announcements already use: the stdio frame
writer (when attached) plus `socket_server.broadcast` to every authenticated loopback
connection. Neither touches `StreamHub`, so a raising stream producer cannot block or
drop it. The gateway door is deliberately excluded (a paired device is not the
launcher), and `settle_ack` is denied there. One targeted exception (owner ruling
2026-10-10): a queued turn's frames and its `turn_settled` also go to the paired device
that sent the send, while that gateway connection is attached — the settle once, on its
first push, and not counted as a delivery attempt
(`hermes_cli/harness_parts/serve/queued_turn_origin.py`).

## Ack

`{"op": "settle_ack", "settle_id": "..."}` (or `client_message_id` + `session_id`),
answered `{"event": "settle_acked", "settle_id", "retired": bool}`. Idempotent: a
second ack, or an ack for an unknown id, answers `retired: false` and changes nothing.
The op is advertised in `ops_manifest` (stdio, socket), which is the launcher's
membership gate for "this runtime pushes settles".

## Durability, retry, undelivered

The record is written atomically under `<store_root>/chat_turn_settles/` BEFORE the
turn's `exit` frame, state `pending`. A pusher thread in every serve re-sends due
`pending` records with backoff 2, 4, 8, 16, 32 s; an attempt counts only when at least
one sink took the frame. A restarted serve resumes the pending set from disk.
`settle_ack` moves the record to `acked` (kept; idempotency). Past 6 counted attempts
(`retry_budget_exhausted`), or 1 h with no listener (`no_listener`), the record moves
to `undelivered` with that reason and one `serve_settle_undelivered` service-log line.
Operators read undelivered settles with
`agent_runtime.chat_turn_settles.list_settles(state="undelivered")` and in the
directory; each record carries the full frame, attempts and timestamps.

## Drop frame

`subscription_dropped` gains `refusal_class` and `fix_hint` keys ONLY when the producer
raised an exception that declares them (`code` / `fix_hint` attributes); every other
drop keeps its exact byte shape.
