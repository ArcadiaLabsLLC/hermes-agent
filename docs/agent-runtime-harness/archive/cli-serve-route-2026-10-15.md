# One CLI-to-serve route for argv verbs that must run in the serve (design)

**Status, corrected 2026-10-16 on archiving: ~~PLAN — owner approval owed.~~ BUILT,
S1–S3, S4 in part** on branch `build/h3-runser` (lane h3-runser; owner approved
every recommendation 2026-10-15): S1 `c0ad5fa40ad` (`cli_route.py`; its recorded red
lists 2 failures, one of which was a test-side token patch since fixed — the
mutation's own red is the `argv_parse_failed` WRITE case), S2 `0c556a834ae`, S3
`542db47b97f`. Deviations, following the tree: (1) a third policy, `TURN_HANDOFF`,
keeps `mission-chat message`'s documented rule (local while nothing was sent) rather
than forcing it under WRITE; (2) no `--direct` flag on `settles rearm` — inside the
serve the request id is bound, so the CLI contract is unchanged; (3) `harness query`
keeps dialling a serve in its own process (`refuse_self_dial=False`). S4 live
(2026-10-16, a lane-owned temp root and serve): `harness serve settles rearm
runser-settle-1 --session-id … --json` against a live serve answered
`answered_by.lane = serve`, `rearmed: true`, the record back to `pending` and due.
The push half — "the serve's outbox pushes the settle" — needs an attached listener
(a launcher stream) to show a delivery; not exercised (row filed). Row: runtime-queue,
"No CLI-to-serve RPC client …" (deleted at this archiving).

## In plain English

Some `harness …` commands change state that a running serve also holds in
memory. Run from a terminal, they write the store from a separate process, and
the serve may not notice. The row says "there is no CLI-to-serve client". There
**are** two already — each hand-written: `harness query` and `mission-chat
send` dial the live serve over its local socket and ask it to run the command.
So the work is not a new transport: it is lifting those two copies into one
shared route, putting `settles rearm` on it, and writing down when a command
may fall back to running locally.

## Evidence (tree at `origin/main` 428e2b0dd09)

- Route 1: `agent_runtime/harness_query/serve_route.py::query_via_serve` —
  `resolve_socket_target(store_root)`, `serve_auth.read_token`,
  `ServeSocketClient.hello(token, client=…)`, sends `{"id", "argv": [... "--direct"]}`,
  reads frames to `exit`/`error`; every failure falls back with a named
  `serve_fallback` reason.
- Route 2: `hermes_cli/harness_parts/persona/chat_serve_route.py::relay_send_via_serve`
  — same dial/auth/hello, streams `line`/`stderr` frames, refuses when "this
  process is the serve".
- The verb: `hermes_cli/harness_parts/serve/settle_commands.py`
  (`_cmd_serve_settles_rearm` calls `rearm_settle` directly); method twin
  `agent_runtime/serve_rpc/settles.py` (`runtime.settles.rearm`, console tier).
- Design record: `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md`
  § D2.05.
- Transport pieces: `agent_runtime/serve_socket/` (`client.py`, `target.py`,
  `hello.py`), auth `agent_runtime/serve_auth.py`.

## Target shape

- `agent_runtime/serve_socket/cli_route.py`:
  `relay_argv(argv, *, client, write: bool, sink=None) -> RelayOutcome`, where
  `RelayOutcome` is typed: `served(code, lines)`, `no_serve(reason)`,
  `refused(reason)`. One dial/auth/hello/frame loop; the two existing routes
  become callers (their public behaviour unchanged).
- **Fallback rule, one place:**
  - read verbs: any failure → run locally, reply names `serve_fallback`.
  - write verbs: **no live serve** (no target, or this process is the serve) →
    run locally (the store's own lock guards it); **a live serve that refused,
    timed out or failed mid-request** → exit non-zero with the reason, never
    run locally (avoids a write the serve does not see, or a double write).
- `harness serve settles rearm` relays `serve settles rearm <id> --direct` and
  follows the write rule; `--direct` is the in-serve form, as for `query`.

## Owner decisions (recommendation first)

1. **Argv relay (recommended) vs a JSON-RPC method client.** The serve already
   runs argv requests from its local console, the CLI contract fixture already
   pins argv shapes, and two callers already work. A method-frame client is a
   second spelling of each verb's params; revisit only if a verb has no argv.
2. **Write fallback rule** as above. Recommend yes; it is the difference
   between "safe offline" and "split brain while online".
3. **Scope.** Recommend migrating only the two existing routes plus `settles
   rearm` now; other write verbs adopt the route when a row names them.

## Slices (build order)

- **S1 — `cli_route.py` + typed outcome**, unit-tested against an in-process
  fake socket server. Killing mutation: let a write verb fall back after a
  mid-request failure → the "live serve failed, write refused" test reds.
  Positive control: no target → local run.
- **S2 — port `query_via_serve` and `relay_send_via_serve`** onto it; their
  existing tests stay green unchanged (proof the behaviour held).
- **S3 — `settles rearm` relays.** Killing mutation: call `rearm_settle`
  directly while a fake serve is live → the test asserting the serve received
  the argv reds.
- **S4 — live proof:** with a serve running, `harness serve settles rearm <id>`
  shows `answered_by.lane = serve` and the serve's outbox pushes the settle.

## Blast radius

One new module; two route modules shrink; `settle_commands.py`; no new wire
contract, no new auth. CLI contract fixture unchanged (same argv).

## What it retires

Two copies of the dial/hello/frame loop, an undocumented per-caller fallback
policy, and the store-direct write path for `settles rearm` while a serve runs.
