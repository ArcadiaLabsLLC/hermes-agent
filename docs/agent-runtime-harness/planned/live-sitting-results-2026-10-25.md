# Live-proof sitting — results (2026-10-25, lane w1025a-hlive)

Status: **evidence note** (appended to, never worked from). The sitting the plan
`docs/agent-runtime-harness/planned/live-proof-sitting-2026-10-18.md` describes, run by an agent on
the owner's PC (owner ruling 2026-10-25). Queue rows point here; where a row and this note disagree,
this note wins.

Setup as found: no serve and no Launcher running (the orchestrator had ended the serve tree after the
live update). The lane started the owner serve itself, detached, the way the service template runs it:
`hermes --profile base harness serve --ndjson --service` (pid 29380, boot `3f9d35f2…`, code
`0841436e34`, namespace `acct-26858805fff7de3b`). The alice gateway was up throughout (scheduled task,
pinned `--namespace base`). Every `runtime.*` method below was called over the serve's loopback
socket as a `local_console` caller (a hello with the root's serve token, the same door the Launcher's
console uses); no store file was read or written by hand. Turns ran through
`hermes harness mission-chat message` (they run inside the live serve). Turn lines are in the
persona's profile log (`profiles/neko/logs/agent.log`), serve lines in `profiles/base/logs/agent.log`.

## RT-LENS-L1-LIVE-PROOF — DONE

- `runtime.lens.list`: plugin live, all five feed kinds `available`.
- Monitor `w1025a_l1`: `http_json` feed on `http://127.0.0.1:18765/cpu.json` (`{"cpu": 97}`,
  `python -m http.server`), threshold rule `cpu_hot` above 90, `level: notify`.
- First revision polled `private_address_refused` (gap rows, typed) — a loopback feed needs
  `allow_private_network: true` on the feed. Revision 2 with it: `preview` → `available 97.0 200`.
- Within one poll (5 s): Episode `25021709…` `active`, `turn_id: notified`; `runtime.lens.receipt`
  → `outcome: notified`, `tool_admission: none`.
- Stored evidence read back with `runtime.lens.range`: rows carry only
  `{sequence, observed_ms, value, gap, reason, http_status}` — no URL, no body, no header. Paused and
  retired after (data kept).

## RT-ETERNIA-LENS-L2-L4 — L2 and L3 DONE; L4 not run

- **L2 (W10-1):** monitor `w1025a_proof`, same feed, `automation.level: investigate`,
  `daily_turn_cap: 2`, `persona_id: qa`. Enabled 21:58:51; Episode `9798192c…` opened 21:58:56;
  receipt `outcome: forged`, `session_id: persona_chat_personainst_qa_6d0f33f106a1`,
  `tool_admission: read_only`, 10.9 s start→finish. The chat's first row is `kind: lens_episode`,
  text `[LENS EPISODE — w1025a_proof · cpu_hot · #1] …`; the second is the agent's finding. One turn.
  Paused after.
- **L3 (W10-2):** `push` monitor `w1025a_l3b` (`level: notify`), `runtime.lens.ingress.register
  {kind: alertmanager}` → `auth: hmac`, listener `127.0.0.1:47652`. A firing body signed
  `sha256=HMAC(secret, "<ts>:" + body)` with `X-Lens-Timestamp`: **202**, Episode `active`, receipt
  `notified`. The identical POST (same timestamp and signature) again: **409**. (A re-sign with a new
  timestamp is a new delivery and is accepted, by design.) Route revoked, monitor retired. The secret
  never left the script's memory.
- **L4 (W10-3):** not run — it needs a persona's profile `toolsets` changed to
  `[harness_core, lens]` (the owner's persistent config; `qa` today lists `hermes-cli` and the
  `lens` toolset sits in `undeclared_registered_toolsets`).
- Plan correction: W10-1's "serve `{"cpu": 97}` from `python -m http.server 8765`" also needs
  `allow_private_network: true`, and 8765 is the serve's gateway port on this box — use another.

## RT-W10-LIVE-CHECKS — DONE

- **W10-4 (209 chars):** read from live model-input receipts (`hermes harness prompt-context show`).
  Neko turns (holding `tool_describe`, `delegate_task`, `agent_chat_send`) carry the
  `## Plugin Context: eternia-harness.tool-guidance` block with the `DELEGATION_HANDOFF_GUIDANCE`
  line at **208** chars, joined by one newline: the without-`agent_chat_send` arm drops exactly
  **209**. The gate is `plugins/eternia-harness/__init__.py::_TOOL_GUIDANCE` (the line renders only
  when both tools are present); the forged `qa` lens turn's block (read-only admission) has no such
  line. No extra turn was spent.
- **W10-7 (bearer):** `ingress.register {kind: alertmanager, auth: bearer}` → route lists
  `auth: bearer`, `weaker: true`; `Authorization: Bearer <secret>` POST **202** + Episode +
  `notified` receipt; the same body again within 5 minutes **409**.

## RT-SETTLE-PUSH-LIVE-PROOF — DONE

- Six CLI turns' settles were pushed on the control channel to a listener socket that did not ack;
  after six attempts each went `undelivered` (`retry_budget_exhausted`), logged
  `serve_settle_undelivered` on the serve's stderr receipt.
- With an acking listener attached, `hermes harness serve settles rearm <settle_id>` at 22:15:19 →
  the `turn_settled` frame for `w1025a-A1` pushed (attempt 1) at 22:15:27, the listener sent
  `{"op":"settle_ack"}`, the serve answered `settle_acked`; the same for `w1025a-B1` and `-A2`.
  Outbox after: zero pending, zero undelivered for this lane's turns.
- Seen in passing: a CLI send's settle carries `turn_id: null`, and a `--new-session` send's also
  `session_id: null` (row `RT-SETTLE-CLI-SEND-NO-SESSION`).

## RT-ARGV-STREAM-READERS-LINGER — DONE

- Every `stream_attach op=harness_stream purpose=cli_stream` in the live namespace's `agent.log`
  from 2026-10-19 23:57 to 2026-10-25 19:25 (six serve boots, the owner's Launcher attached) has its
  `stream_detach`: **48 of 48** (35 `end=returned`, 13 `end=cancelled`). No reader lingered under
  the b931a2de996 lines. (`office_patch` subscribes log no detach line; their end is the
  connection close on the serve's stderr receipt.)
- Seen in passing: a standalone `hermes harness stream` falls back to an in-process build on this
  store, `stream_relay lane=in_process serve_fallback=transport_failed:_LineTooLong` (row
  `RT-STREAM-RELAY-LINE-BOUND`).

## RT-RESOLVE-TURN-TWO-CACHE — DONE

Two matched new Neko chats (`…c6368094ed9d` = A, `…b2defc584902` = B), three turns each, same
texts, anthropic `claude-opus-5-5`, effort medium (`chat_turn_effort … source=profile`). Tool form
identical on every turn: `tool_form_receipt source=unchanged publishes=0 pin_written=0 names=24
json_bytes=42172`. System prompts byte-identical between A1 and B1 (25,640 chars; sections Stable
Hermes foundation 4,856 / Mission Control context 11,626 / Volatile profile context 9,154).

| turn | A in / cached / written | B in / cached / written |
|---|---|---|
| 1 | 17,388 / 0 / 17,384 | 17,391 / 9,262 (53%) / 8,125 |
| 2 call 1 | 17,887 / 17,384 (97%) / 499 | 17,899 / 17,387 (97%) / 508 |
| 2 call 2 | 18,059 / 17,883 (99%) / 174 | 18,070 / 17,895 (99%) / 173 |
| 3 | 18,527 / 18,057 (97%) / 466 | 18,522 / 18,068 (98%) / 450 |

Turn two reads exactly what turn one wrote (17,384): **no prefix drift on turn two**. The only miss is
a FRESH chat's first turn (B1 53%): with identical tools and system bytes it can only be the cache
breakpoint layout — the shared prefix is cached at the breakpoint before the volatile section and
the per-chat user/runtime-context message, so a second chat's first turn re-writes ~8.1k tokens.
That is provider-side breakpoint placement, not drift. (Measured from provider-metered cache
tokens; the R034 hash capture was not needed to separate the two.)

## RT-CHAT-TURN-22K-TOKENS — S0 and `cache=` read (R4 rides batch C)

First Neko "hi" (A1): `API call #1 … in=17388 out=77 write=17384`. S0 per-part receipt
(`final_model_input.prompt_surface`): `tools=24 tool_chars=19493 system_chars=25634
skills_entries=13 listing_chars=0 promoted_mcp_chars=0 hud_chars=0 user_chars=1798 deferred=9
unavailable=12`; `tool_search activated (tier 1): 21 core/visible tools kept, 9 deferred (~3517
tokens)`. The 22k is now 17.4k, and the deferred listing is ~3.5k tokens, not ~20k. Second chat's
first turn `cache=9262/17391 (53%)` (above). The `prompt_surface` log line itself did not appear in
the profile log (the receipt on the context does carry it).

## RT-SNAPSHOT-BUILD-SLOW-AFTER-RESEED — DONE (measured)

The 6,327 ms build was the prewarm build of serve 25836's boot (2026-10-19 23:57:17):
`agents_readiness:4583` (walk 2,557 + tool_visibility 2,025), `prompt_observability:1114`,
`persona_chat:5`. It is not the 348-chat directory, and it is not the reseed: **every boot's first
build** since reads 5.0–13.3 s, agents_readiness 2.9–7.8 s of it (eight boots, 10-20 to 10-25,
including this lane's 9,005 ms at 21:54:08), while the next builds on the same serve read
0.8–1.5 s with agents_readiness 0.12–0.37 s. Row `RT-PREWARM-BUILD-AGENTS-READINESS-COLD` carries
the cut.

## RT-RETIRE-LEGACY-TOP-LEVEL — go

The owner runs the Launcher as a debug build of the primary checkout (all 13 diag-log sessions
2026-10-24/25 open with `debug=true`; `build/windows/x64/runner/Debug/eternia_launcher.exe` written
2026-10-25 07:42). `290449df44` (2026-10-03) is an ancestor of that checkout's `main`, so the
installed build writes the new keys: **go** for the retirement lane.

## RT-GATEWAY-START-MANAGED-PYTHON — not reproducible live

In the managed venv's interpreter `resolve_managed_python()` returns
`X:\Eternia\.hermes\venvs\hermes-agent\Scripts\python.exe` (`sys.prefix` is the venv) — the
2026-10-08 failure does not reproduce in-process. A live `gateway start` was not run: since the
namespace rule the service start fails first on `namespace_home_escape`
(`RT-GATEWAY-SERVICE-OUTSIDE-NAMESPACE`), and a second start beside the running gateway would put a
second poller on the owner's bot.

## RT-QUEUE-COMMIT-SERVE-RESTART — hermes half read

At 22:06:09 the live checkout fast-forwarded `0841436e34` → `4053e64a90`, three vault-only commits.
The serve did not drain or restart (pid 29380 kept serving; `serve connect --probe` reports its
`code_tree 638b865e…` under the rule that excludes `Harness_Brain/`). But the next CLI process logged
`_bytecode_sweep: Checkout changed since last launch … cleared 195 stale __pycache__` and
`home maintenance: code changed to 4053e64a90ec, running steps` — both keyed on the COMMIT (row
`RT-VAULT-COMMIT-HOME-MAINTENANCE`). The Launcher's `[MissionServe] drain` half needs the Launcher
open.

## RT-CORE-CACHE-WRITES-BUILD — DONE (families named)

Live namespace `agent.log` since the 2026-10-20 seed: 70 `snapshot_core_cache_write ok=true`
against 37 cache reads — **9 served from cache** (8 `stale=true` at boot, each followed by a rebuild,
and one fresh serve: 22:08:35 `core_source=cache caller=cli inputs=2536`), 28 `rebuilt`. So the cache
does serve now; the "never once" was the old base root. The reads happen at process boot, and the
misses are: `reason=build_stamp_mismatch` **29** (every code update — the stamp is the build, by
design) and `reason=fingerprint_mismatch` **7**, whose `diff=` paths group by family as
`chat_turn_reservations` 16, `work/ws_default` 6 and `work/ws_testv4_afb811` 3 (workspace git
internals such as `.git/FETCH_HEAD`), `chat_turn_settles` 4, `realm_sync_state` 1. Those turn- and
worker-written families are what breaks convergence between boots; whether a snapshot section reads
any of them is the follow-up's audit (row `RT-CORE-CACHE-INPUT-FAMILIES`).

## RT-WHETHER-UPSTREAM-POST-TURN — measured; owner rules

Receipt: upstream's `agent.background_review: Background review complete: thread=bg-review …` line,
one per spawn, in each persona's profile log. Over every persona turn in the live namespace since
2026-10-19 (the six turns of this sitting included): **41 turns** (neko 39, alice 1, launcher-qa 1),
**6 heavy** (≥ 10 tool iterations, all Neko), **2 spawns** — both skill reviews (`result=skill`),
after the 19- and 23-tool-turn Neko turns of 2026-10-22 10:25 and 2026-10-25 19:35; 3 calls each,
out 1,742 / 3,390 tokens, cache_read 215,089 / 148,098. Zero memory reviews. The sitting's six light
turns spawned none. That sample stands in for the plan's ten fresh turns (two heavy): it already
holds six heavy turns, so no extra credits were spent on it.

## RT-FULL-PERSONAASSIGNMENTSTORE — census

`hermes harness persona assignments --json` on the live namespace store: **0 rows**. The old base
root (`--namespace base`, read-only; Mission Control no longer reads it, only the alice gateway runs
there): 47 rows — 44 `completed`, 2 `cancelled`, **1 `queued`**. The 15 non-terminal rows of the
2026-09-04 census did not come across in the 2026-10-20 seed; nothing in the live store blocks the
retirement.
