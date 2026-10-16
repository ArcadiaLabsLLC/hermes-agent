# One CLI-to-serve route for argv verbs that must run in the serve (design)

Status: PLAN — written 2026-10-15; owner approval owed. Row: runtime-queue,
"No CLI-to-serve RPC client: an argv write verb that should be RPC-first can
only read the store directly in its own process (`harness serve settles
rearm`)".

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
