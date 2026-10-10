# Busy chat root — accept and queue (2026-10-10)

Owner ruling 2026-10-10: busy is not a reason to refuse. An operator send to a chat
root whose lease another turn holds is persisted, answered "queued", and run after
that turn, in arrival order per root. Runtime-queue row "A message for a busy chat
root is accepted and queued…" (h-busy-queue).

## Why a new store, not an existing queue

- Upstream's gateway busy queue (`gateway/run_busy.py`) is in-memory per gateway
  runner, for messaging platforms; it does not survive a restart.
- `mission chat steer` injects into the RUNNING turn; a queued send is the next turn.
- `dispatch_store` is durable but its rows are agent dispatches with their own
  delivery semantics; an operator send is not a dispatch.
  Reused instead: the serve's delivery-drain shape (idle probe, the mission-chat
  door `run_mission_chat_turn`) and the settle outbox (`chat_turn_settles`).

The store is `agent_runtime/chat_root_send_queue.py`, one JSON file per entry under
`<store_root>/chat_root_send_queue/<root>/`, keyed by `client_message_id`. A serve
thread runs the head of each idle root through the door and records its settle.

## Who queues

Operator sends only: a send with no `requested_by_session` and no in-process `payload_sink`
(a door caller — a discussion member turn — takes its reply inside its own call and keeps
`chat_busy`). Agent relays
(`agent_chat_send` wait=true) and delivery forges (`dispatch_delivery`, which already
have a durable retry queue in `dispatch_store`) keep `chat_busy` — a different
meaning there: "retry from your own queue".

## The "queued" answer

```json
{"ok": true, "capability_id": "mission.chat.message", "execution_state": "accepted",
 "queued": true, "queue_position": 1, "client_message_id": "...", "turn_id": "...",
 "root_chat_session_id": "...", "session_id": "...", "queued_at": "...Z",
 "idempotent_replay": false, "next_expected": "..."}
```

Exit code 0. `queue_position` is 1-based among this root's waiting entries.
`idempotent_replay: true` when the same `client_message_id` was already queued. The
answer is not a settle: the serve records no settle for it; the turn's settle is
pushed when it runs (`turn_settled`, `request_id` `queued:<client_message_id>`).

## Drain

A queued turn running in the runner's pool counts as a chat turn in flight for the serve's
drain (`QueuedSendRunner.inflight_request_ids`, request id `queued:<client_message_id>`), so a
drain never completes, and the serve never exits, over one.

## Origin

Owner ruling 2026-10-10: a queued turn gets what a direct run of the same send gets. The
door persists the send's origin on the entry (`chat_root_send_queue.ORIGIN_ARG`,
`{"owner": <connection key> | "stdio" | null, "gateway": bool}`, from the serve request the
send arrived on; `owner` null for a send with no serve request). When the turn runs, the
stream (`hermes_cli/harness_parts/serve/queued_turn_origin.py::queued_turn_link`) binds the
app-function link `ArgvLanes._bind_launcher_link` would: the sender's own connection while
it is attached and answers `launcher.` requests (attached and not answering: no link, as
direct); a sender that is gone, or a paired device, takes the gateway rule — the stdio
starter, else the most recent local socket connection that declared it answers, else
none — and the tools are refreshed against that link, as a direct turn's are.
