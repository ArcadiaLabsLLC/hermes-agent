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

## Batch C — `agent_runtime.mission_chat.lean_operative_rules` on (22:24–22:30)

Flag set in the namespace ROOT config with `hermes --profile default config set …` (the knob reads
the root config only), serve drained (`serve connect --drain` → `drain_complete`, old serve exited,
`29380.ended.json reason=drained`, inside 8 s of the request) and restarted (pid 34320); afterwards
`config unset` and the file is back to its bytes except `_config_version: 50 → 51`, which the `set`
verb bumped.

**R4 A/B (`RT-CHAT-TURN-22K-TOKENS`) — DONE.** Same persona, model and effort, first turn "hi":

| arm | system chars (foundation / Mission Control / volatile) | first-turn `in=` |
|---|---|---|
| OFF (A1) | 25,634 (4,856 / 11,626 / 9,154) | 17,388 |
| ON (C1) | 18,892 (4,853 / 4,881 / 9,154) | 15,293 |

ON cuts the Mission Control section by 6,745 chars and the first turn by 2,095 tokens (12%). Neko
kept the threading rules with the flag on: it answered both teammates in their threads and looked for
a `clarify_token` each time, without calling `tool_describe` on `agent_chat_send`.

**Clarify check (`RT-LEAN-OPERATIVE-RULES`) — could not pass, for a reason outside the flag.** Two
attempts (C2 → Launcher Dev, codex; C3 → Base, anthropic), each told to call its `clarify` tool.
`agent_chat_send` was promoted to a background dispatch both times. Dev asked in plain text. Base
DID call `clarify` (`tool clarify completed`, 22:29:01), but the `BACKGROUND DISPATCH COMPLETE`
delivery handed Neko only `--- THEIR REPLY --- Which colour should the throwaway test badge be: blue
or green?` — no `clarify_request`, no `clarify_token`, no choices. Neko answered "green" by thread,
as the rules say to when there is no token. The token never reached the asking agent: row
`RT-DISPATCH-DELIVERY-DROPS-CLARIFY`. Turns: 3 operator turns on chat `…8fc0db3c1397` plus 4 relay
deliveries to Neko and 4 teammate turns.

## RT-SEND-PREP-FIXES-LIVE-PROOF — part (a) read

On every warm CLI turn of the sitting the receipt reads `tool_form_receipt source=unchanged
publishes=0 pin_written=0 names=24 json_bytes=42172` and `turn_context_receipt … mcp_refresh_ms=0`.
Parts (b) and (c) are timing reads and wait for an idle box.

## RT-AUTH-JSON-TRANSIENT-READ — DONE (zero sightings)

`hermes_cli.auth: could not read …auth.json` appears **0** times in every profile log of the live
namespace (2026-10-19 to 2026-10-25: eight serve boots, 41 persona turns, this sitting's 16 turns),
and the Launcher diag log carries no "needs attention" line in that window. `credential pool: no
available entries (all exhausted or empty)` does fire — twice, ~3 s after every serve boot (21:54:11,
22:25:21 today) — with no read failure beside it: it is the boot's probe of an empty pool, not the
2026-10-07 race.

## RT-REALM-SYNCED-LEVEL-REVERT and RT-REALM-SYNC-REVERT-TAKES — not run

`hermes harness realm sync status cf6d244d-…` ("test realm"): `last_pull: null`, `last_publish:
null`, `remote_check_error: sync_auth_failed`, and every store row reads `kind: added` — including
the new `level` family row (`level:ws_testv4_afb811:ws_testv4_afb811`, so S2's drift row does show).
With no pulled baseline a revert of that row would remove the owner's level rather than restore an
edit, and the remote cannot be reached without the operator's realm-sync sign-in. Both proofs need
the owner: sign in to realm sync and pull (or publish) a baseline, then edit a level and press Revert.

## RT-PIPER-FIRST-AUDIO-LATENCY — not run

No `openphonemizer*` or Piper pack anywhere under `X:\Eternia\.hermes` or the namespaces root. The
profile needs the speech pack installed first (a download the owner approves).

## RT-VERIFY-IMPROVE-FIRST-RESPONSE — sized, handed to the live phase

Its precondition has landed (launcher `469e500730` arm-B wording, `415215dbe4` catalog). The run is
two QA builds (arm A before `469e500730`, arm B at it) driven through `launcher_qa`
(`launcher.agent_chat.new/send`), 15 turns × 2 agents × every QA provider per arm
(`evals/genui_first_response_prompts.json`: 12 comparisons + 3 controls). That is a QA-launcher
sitting, which this wave runs one lane at a time in its live phase; it does not touch the owner's
serve.

## Timing batch (22:38–22:46, idle box)

The coordinator's tier ended 22:34; before each read there was no `flutter_tester`, `dart test`,
`pytest` or tier process and CPU sat at 4–14% (the only `dart` processes were the serve's own
`dart mcp-server` admission children). Fresh serve pid 28932 (boot `interpreter_ms=3482
main_import=298 dispatch=1642`), default flags. All turns are CLI turns (`mission-chat message`,
inside the serve); the Launcher was not running, so no `[MissionChatTiming]` span exists for them.
Spans below are `hermes harness observe turn-timing --check --last 10` and each turn's
`send_prep_receipt`.

| turn | what | anchor→request_sent | request_sent→headers | stream done→projected |
|---|---|---|---|---|
| P1 | Dev, sent while the boot build ran | **7,723** | 837 | 99 |
| N1 | Neko, first turn after boot (prewarmed chat, actor reused) | **356** | 1,827 | 42 |
| N2 | Neko, after 105 s idle | **258** | 1,784 | 43 |
| D1 | Dev 22-row chat, first on that actor | 688 | 1,070 | 127 |
| D2–D4 | Dev 22-row chat, warm | 305 / 317 / 308 | 720–1,287 | 107–132 |
| W1–W4 | Neko, warm (W2–W4 under `py-spy record`) | 344 / 552 / 297 / 286 | 1,304–2,201 | 45–61 |

**RT-FIRST-TURN-BOOT-LATENCY — DONE.** Boot leg 356 ms, idle leg 258 ms, against 770 / 441 ms on
the row and the 259.5 ms warm table. Against a warm Neko turn (W4 286): the boot leg's extra ~70 ms
is `observability_built` 75 vs 21 and `client_built` 58 vs 42 (`tls_done` 58 vs 64 — every Neko turn
handshakes, below). The idle leg is a warm turn. The time to text is the provider's (cache write of
24.8k tokens on N1: `request_sent→headers` 1,827 ms).

**RT-PREWARM-HOLDS-WORKDIR-LOCK — DONE (measured).** The actor prewarm's steps are now small
(`system_prompt_build_ms` 30–59, `construct_ms` 131–3,375 across five chats). P1, sent 4 s after
`ready`, did not land in an actor-prewarm step at all (the pass started at 22:38:33, after it): it
landed in the boot's prewarm SNAPSHOT build (22:38:24.8–31.0, 6,261 ms) and its send-prep read
7,723 ms (`cpu_ms` 7,390, `unattributed_ms` 4,671, `context_built_ms` 2,261) — the D1.04 number is
a 7.7 s first send behind a 6.3 s build, which is `RT-PREWARM-BUILD-AGENTS-READINESS-COLD`'s cost,
not a lock hold.

**RT-REMOVE-H-TURN1-A5 — go.** The A5 laps on N1 (first turn after boot): `lead_in 0, redecorate 1,
observe_tools 0, kwargs 3, preflight 0, middleware 5, hook 0` = 9 ms, the same as every warm Neko turn
(9–11 ms); Dev (codex) 41–46 ms (`kwargs` 36–39). The 0.57–2.3 s first-turn span the stamps were kept
for is gone: the 8 lines can return to upstream bytes.

**RT-ATTRIBUTE-RECORDED-FIRST-TURN — DONE: no local step delays first text.** On warm Neko turns
the local tail after the stream is 45–61 ms (`stream_done_to_projected`) and the response wait is the
provider's (`request_sent→headers` 1.3–2.2 s). `py-spy record --rate 200` over W2–W4 caught only
115–141 active samples in 14 s windows (~0.6 s of CPU across all threads), spread over skill
listing (`skill_resolution._listing`, `skills_resolver._walk_skill_catalog`), `serde.read_json`,
`git_cmd.run_git`, `provider_credentials.bound_provider_home` and the observability receipts — none
above 13 samples. Persistence, title and refresh do not show. No ablation was needed.

**RT-SEND-PREP-FIXES-LIVE-PROOF — DONE.** (a) above. (c) warm `send_prep_total`: Neko 258–344 ms,
Dev 305–317 ms — inside the 400 ms budget (the `--check` FAIL names D1, a first turn on that actor
grouped as warm, and W2, the first `py-spy` turn); warm median ~306 ms. (b) the 22-row Dev chat reads
`context_built_ms` 130–142 warm (D2–D4) against 197 on the actor's first turn; a matched BEFORE needs
the pre-`f7c61ff2ac` build and cannot be taken on the live serve, so (b) is recorded after-only.

**RT-WARM-MEDIAN-LIVE-PROOF — CLI route only.** Warm median on the CLI route ~306 ms (above). The
Launcher route needs the owner's Launcher open; none of these turns crossed it.

**RT-TURN1-WARM-CONNECTION — DONE: Neko's provider changed, so the warm connection does not
exist.** Neko now runs anthropic `claude-opus-5-5`. Its prewarm line reads `connect_ms=absent`
(Dev's, on openai-codex, reads `persona_chat_actor_prewarm_connect host=chatgpt.com status=404
kept=2`). Every Neko turn of the sitting builds its client (`client_built_ms` 41–58) and handshakes
(`tls_done_ms` 31–157); the check's `conn` line reads `new` on every Neko turn. Dev turns reuse
(`client_built_ms` 4, no `tls_done`). Rows `RT-ANTHROPIC-CONN-PER-TURN` and, for the receipts that
should have shown it per call, `RT-ANTHROPIC-STREAM-RECEIPT-ABANDONED` (all 87 anthropic
`send_window_receipt` lines on record read `end=abandoned first_event_ms=na`, logged when the NEXT
request begins).

**RT-LIVE-SERVE-AGENTS-READINESS — DONE (narrowed).** Three in-serve builds on the idle box
(22:44:37, 22:45:17, 22:45:58, `harness stream` hydrates): `walk_ms` 266 / 271 / 330,
`tool_visibility_ms` 47–52. The loaded figures were 651–1,595 (row) and, in today's log, p50 470 /
p90 972 over 60 warm walks; the first walk of every boot is 1.8–5.3 s. So the live serve's walk is
~2× the quiet 126–155 ms on an idle box: the 5–10× is load (turns, the Launcher hub, other lanes on
the box) plus the cold first walk, which `RT-PREWARM-BUILD-AGENTS-READINESS-COLD` carries.

**RT-BOARD-CARD-FOLD-RUNTIME — S0 measured: build S1–S4.** A hub subscriber (`{"op":"subscribe",
"lane":"stream"}` on its own connection) and a probe card on `board_default_ws_testv4_afb811`
(added, moved active → review → queued, archived): `runtime.board.card.move` acks in 10–12 ms, and
each move reaches the subscriber 2.0 / 2.3 / 2.4 s later as one `delta` frame
(`op: event.appended`) of ~668 KB — the demoted full core. That is far above any gesture tolerance
before the Launcher's repaint is even added (not measurable without the Launcher).

**RT-QUEUE-COMMIT-SERVE-RESTART — hermes half proven.** The vault-only fast-forward drew no serve
restart (above); both real restarts drained clean: `serve connect --drain` → `drain_complete`,
`29380.ended.json reason=drained` 7.3 s after the request was typed, and the same for 34320. The
`[MissionServe] drain` / `serve_drain proven=` lines are the Launcher's and need it open.

**RT-HARNESS-SERVE-COLD-BOOT — not run.** Three warm-disk boots today: `interpreter_ms` 4,967 /
6,750 / 3,482 (`interpreter_boot` 2,200 / 3,025 / 1,541, `main_import` 440 / 607 / 298, `dispatch`
2,326 / 3,116 / 1,642). The D1.06 protocol needs a disk-cold boot, i.e. a reboot.
