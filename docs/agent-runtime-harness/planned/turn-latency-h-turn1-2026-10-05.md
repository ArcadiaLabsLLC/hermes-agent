# Planned — turn latency, lane h-turn1 (2026-10-05): the four "turns still feel slow" rows

**Status:** DESIGN 2026-10-05 (Fable, read-only against the live store, the base serve log 14:14 / 14:48–14:54, the launcher diag log 18:47–18:54Z, and both trees). No production code was changed. **Rows:** the four `TAKEN … lane h-turn1` rows under `Harness_Brain/20 — Active Initiatives/runtime-queue.md` § "Filed on arrival — 2026-10-05 (owner live turns)", plus the `rt_provider_wait_ms` row as the beneficiary of lane C. **Owner doc:** [`../05-chat-turn-lane.md`](../05-chat-turn-lane.md) §4b (prewarm), [`../04-boot-and-lifecycle.md`](../04-boot-and-lifecycle.md) (drain, build identity). **Sibling:** `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` carries the launcher halves named below.

**One sentence per row.** (1) The cold Neko chat was not "outside the candidates" — it did not exist yet: the boot pass ran at 14:48:31, the operator dropped the agent at 14:50:56, and nothing on the create path or the Agent Console warms a freshly minted chat root. (4) A prewarmed actor is warm but its first turn still pays three first-turn-only costs the prewarm never reaches — the system prompt (upstream `_restore_or_build_system_prompt`), `build_api_request`, and the first provider connection — because `AgentRunExecution.run` returns before any conversation exists. (3) The per-turn core rebuild is NOT the core-cache fingerprint; it is the stream lane demoting every batch that carries `persona_chat.turn_started` / `turn_ended`, which are uncovered events, once per subscriber. (2) The launcher restarts on a vault-only commit because RS-6's rule keeps `Harness_Brain/`, and the old serve "never exits" because its drain waits on the launcher's own two standing stream requests, which the launcher holds until it gives up at 20 s.

---

## 0. Ground truth

### 0.1 The Neko control chat (`…07c76f93_749525d862b7`, three turns 18:51:02–18:51:42Z, `gpt-5.6-luna`)

Elapsed ms from `anchored_at` (ledger v3 `phases`); `profile_timing` keys named where they bite.

| turn | reused | `write_ahead` | `agent_ready` | `conversation_started` | `turn_context_built` | `preflight_done` | `request_built` | `client_built` | `tls_done` | `request_sent` | `response_headers` | `builds_overlapped` | `stream_done` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 `7920507f` | 0 | 570 | 964 | 1,072 | 2,422 | 2,428 | 3,074 | 3,109 | 3,371 | **3,393** | 6,272 | 1 | 9,105 |
| 2 `1b4597f1` | 1 | 399 | 448 | 476 | 565 | 567 | 663 | 667 | 690 | **737** | 1,418 | 2 | 2,803 |
| 3 `f2756d71` | 1 | 539 | 581 | 587 | 829 | 830 | 892 | 897 | 918 | **936** | 1,918 | 0 | 2,832 |

Turn 1's `profile_timing`: `agent_construct_ms=270`, `profile_conversation_turn_context_ms=1,349`, `profile_conversation_system_prompt_build_ms=1,273`, `runtime_resolve_ms=33` (`runtime_resolve_cached=0`), `registry_probe_rounds=1`. Turns 2–3 carry NO `system_prompt_build` key (the prompt is restored from the session row, `system_prompt_restore`) and `turn_context_ms` 88 / 241.

**So the cold construction the §4b prewarm exists to move is 270 ms.** The 2,650 ms turn 1 spends over turn 2 before `request_sent` is: `agent_ready − write_ahead` 394 vs 49 (the acquire, the one probe round, the runtime resolve); `conversation_started → request_built` 2,002 vs 187 (system prompt 1,273 + the rest of `turn_context` + `build_api_request` 646 vs 96); and `client_built → tls_done` 262 vs 23.

### 0.2 The Dev Agent first turns the row cites (`profile gpt-launcher`, `gpt-6-luna-900k`), same marks

| root / turn | reused | `prewarm_overlapped` | `builds_overlapped` | sys prompt ms | `turn_context_ms` | `preflight_done → request_built` | `client_built → tls_done` | `request_sent` |
|---|---|---|---|---|---|---|---|---|
| `339c66e95690` t1 18:14:12 | **1** | 1 | 1 | 1,578 | 1,748 | 1,007 | **1,454** | 6,349 |
| `339c66e95690` t2 18:14:26 | 1 | — | 2 | — | 86 | 80 | 56 | 998 |
| `339c66e95690` t3 18:14:34 | 1 | — | 1 | — | 104 | 30 | (pooled, no handshake) | 1,160 |
| `5ee0073c9fe8` t1 17:05:14 | 0 | — | 1 | 1,555 | 1,643 | 2,311 | 1,195 | 5,173 |
| `5ee0073c9fe8` t2 17:05:53 | 1 | — | 4 | — | 332 | 48 | 22 | 1,151 |

Every first turn on record — warm or cold — pays the system prompt (1.1–1.6 s), a 0.65–2.3 s `build_api_request`, and a 0.26–1.45 s handshake; every later turn pays none of the first, ≤ 100 ms of the second, and 21–56 ms (or nothing) of the third. Every first turn on record also overlapped a core build, so the handshake's cold share and its GIL share cannot be separated from these records (§1 A4).

### 0.3 The boot pass, the drop, and the open (base `agent.log` local clock; diag log UTC = local + 4 h)

- 14:48:31.969 `persona_chat_actor_prewarm pass candidates=7 queued=7 skipped=0` — `max_hot_sessions: 8`, so the cap was not the limiter. `_boot_candidates` offers one root per instance (`default_chat_session_id`), most recent `updated_at` first.
- 18:50:56.186Z `[MissionAgentCreate] lane=rpc gesture=drop … instance=personainst_neko_supervisor_agent_07c76f93 phases=instance=110ms placement=22ms` — the instance, its chat root and its placement were minted here, by `runtime.agent.create` → `agent_runtime/agent_create/perform.py::perform_agent_create` (`_durable_chat_root`). The row's `updated_at` moved; nothing queued a chat-actor prewarm.
- 18:51:02.9Z turn 1 anchored: `resident_actor_reused=0`. No `[MissionOpenChat]` line between 18:14 and 18:54: the Agent Console opened the chat without `persona.instance.open_chat` (the only launcher caller of that capability is `lib/features/mission_control/state/cockpit/mission_chat_activation_lane.dart`; `lib/app/agent_console/*` never sends it).
- 14:54:30.048 the NEXT boot's pass (`candidates=8`) warmed the root in 212 ms.

### 0.4 What a turn does to the stream (14:14 window, pid 19012; 14:51 window, pid 28456)

- `snapshot_build reason=demote … caller=cli generation=2 build_ms=3713` (14:14:25.6) then `caller=hub generation=3 build_ms=6631` (14:14:33.2), `caller=cli generation=4 build_ms=9459` (14:14:43.0), `caller=hub generation=5 build_ms=5921`: two led cores per turn, one per subscriber. The launcher holds two standing `harness stream` requests per attachment (`session._busy_frame`'s `subscriptions`): the hub lane (`stream_attach op=subscribe purpose=stream_lane connection=conn-1`) and the argv lane's `harness stream` (`hermes_cli/harness_parts/runtime_commands.py`, `caller="cli"`).
- `reason=demote` is assigned in `agent_runtime/stream/build.py::_batch_frames_with_liveness`: `batch_required_fold_tokens` returns `None` because `persona_chat.turn_started` / `persona_chat.turn_ended` (`agent_runtime/chat_turn_presence.py`) are in neither `COVERED_DOMAIN_EVENT_TYPES` nor a `state.patched` pair (`agent_runtime/patch_coverage.py::event_is_patch_coverable`, last branch: "anything else is uncovered → the whole batch falls back to a full core").
- `demote_core_reuse.consult(floor=last_offset)` refuses a remembered core whose position is below the batch's last offset; the second subscriber's batch always closes later (debounce, the turn's trailing events), so the reuse that collapsed three builds on 2026-08-22 does not fire here (one `core_source=reused_same_offset` per window at most).
- `snapshot_core_cache_write … restat=refreshed self_perturbed_refreshed=4 foreign_moved=8` is the WRITE-BACK receipt of a rebuild already decided; the persisted-core lane is consulted at boot only (`core_cache/lane.py`: "the first consult always demotes, and the build that follows it disarms the lane"). The fingerprint never triggers a mid-session rebuild. The row's cause is wrong on this point; its effect and its cost are right.

### 0.5 The three restarts (hermes commits local time; diag log UTC)

| commit | files | launcher drain | serve end record | new serve's first core |
|---|---|---|---|---|
| `0ed627cea0` 14:20:29 (+ `fb5a186264` 14:19:28) | `Harness_Brain/20 — Active Initiatives/runtime-queue.md` only | — (`home maintenance: code changed to 0ed627cea08f` 14:20:47) | — | — |
| `16de000270` 14:44:06 (claim row) | the same file | 18:47:49.8 → `serve_drain proven=no probe=pid_present sidecar=absent polls=13 waited_ms=20503` at 18:48:10.294 | `28592.ended.json` reason=drained **18:48:10.372** | gen 1 `build_ms=11184` |
| `4adeb0f116` 14:52:54 | the same file | 18:53:40.1 → `proven=no … polls=14 waited_ms=20848` at 18:54:00.917; `serve_spawn_deferred reason=drain_in_flight waited_ms=19844/12563/3842` | `28456.ended.json` **18:54:01.080** | `snapshot_core_cache … reason=build_stamp_mismatch`, gen 1 `build_ms=15383`; `open_chat … answered=+26817 ms` |

- `agent_runtime/build_identity.py`: `NON_RUNTIME_PREFIXES = ("docs/", "tests/", ".github/")`, `NON_RUNTIME_ROOT_SUFFIXES = (".md",)`. `is_runtime_path("Harness_Brain/20 — Active Initiatives/runtime-queue.md")` is **True** (checked against the tree), so `build.code_tree` moved on each of these commits and the launcher's RS-6 rule (`mission_serve_build_behind.dart::recheckCheckout → _considerBuildBehindNow → decideMissionServeBuildBehind`) restarted on the digest exactly as designed. The Dart side applies the rule it is HANDED (`local_serve_attach.dart::MissionServeCodeTreeRule.fromRow`), so the prefix list is one hermes constant plus the shared parity fixture.
- `hermes_cli/boot_bootstrap.py` is not the restart door: `needs_bootstrap` compares git HEAD to the per-profile record and re-runs `post_update.BOOT_HOME_STEPS` on the NEW serve's boot. Its cost on a docs-only revision is not separable from the boot timeline in the log (`dispatch_ms=4448` spans it) — UNVERIFIED and not a stage.
- The drain, from the serve's own stderr (`serve_instances/28592.stderr.log`): `serve_socket_draining` → … → `serve_stream_worker_reclaimed connection=conn-2 request_ids=[req-1, req-2]` → `serve_socket_connection_close reason=client_disconnect` → `serve_instance_unregistered reason=drain`. `_cancel_standing_streams` is reached only from `_reclaim_abandoned_streams` (connection closed) and `_reclaim_stdio_streams` (stdio EOF) — never from `_request_drain`. `DrainLane._drain_monitor` waits for `self.inflight` to empty, and the two standing streams (`is_runtime_stream`) are in it. The launcher's `MissionServeDrainLane._drainService` sends `{"op":"drain","force":true}` with no `deadline_seconds` (serve default 30 s) and keeps the connection while it watches the pid for `drainDeadline` = 20 s; when it gives up it releases the connection, the serve reclaims the streams, `drain_complete` lands, and the end record is written 80–160 ms later. **The serve is held by the launcher's own patience, and the launcher's budget is shorter than the serve's.** The h-chatperf row "serve_drain never proves an exit … pid 31020" (same section, UNCLAIMED) is this defect; stage D2 closes both.

---

## 1. Lane A — the first turn of a chat (rows 1 and 4; one exec lane)

### A1 — the create path warms the chat root it mints (hermes)

- **Goal:** a dropped agent's first message finds a resident actor, as an opened chat's does.
- **Touches:** `agent_runtime/serve_rpc/agent.py::_runtime_agent_create` (the serve-side door; `perform_agent_create` runs with no serve and must stay a pure service). One call after the receipt is in hand and not an `idempotent_replay` refusal: `request_chat_actor_prewarm(receipt["default_chat_session_id"], launcher_link=current_launcher_link())` (`agent_runtime/persona_chat_actor_prewarm.py`, `agent_runtime/launcher_app_functions.current_launcher_link`). Inert without a registry, by the function's own contract. The rule `chat_open.py::_prewarm_chat_actor_for_open` states — "the operator's gesture, never the store method" — holds: a drop is a gesture.
- **Positive control:** test with a registry present and a stubbed `request_chat_actor_prewarm`: `runtime.agent.create` must call it once with the minted root; plant = delete the call → red.
- **Tests:** `tests/agent_runtime/test_serve_rpc_agent_create.py` (new case beside the create tests); `tests/agent_runtime/test_persona_chat_actor_prewarm.py` unchanged.
- **Saving:** `agent_ready − write_ahead` 394 → ~50 ms, `runtime_resolve` 33 → 0, `registry_probe_rounds` 1 → 0, `agent_construct_ms` 270 → 0: ~0.4–0.7 s on the first turn of every dropped agent (neko turn 1 vs turns 2–3, §0.1). The rest of row 1's 3,393 ms is A3/A4.

### A2 — the Agent Console open fires the open-chat capability (launcher)

- **Goal:** any surface that opens a chat warms it (row 1's last clause).
- **Touches:** `EterniaLauncher/lib/app/agent_console/agent_console_runtime_binding.dart` (the console's chat-open gesture) → the existing `persona.instance.open_chat` method lane the cockpit already uses (`mission_chat_activation_lane.dart`, `mission_open_chat_lane_client.dart`). Same intent, same decoder; no hermes change. File the row in `mission-control-queue.md` naming this plan.
- **Positive control:** launcher test — opening a chat from the console emits one `open_chat` intent for its root; plant = drop the dispatch → red. Live: a `[MissionOpenChat]` line precedes the console's first turn.
- **Saving:** same as A1 for a chat REOPENED after the boot's eight (the 9th-most-recent chat and older).

### A3 — the prewarm builds the system prompt and the first turn adopts it (hermes fork + ONE additive upstream seam)

- **Goal:** `profile_conversation_system_prompt_build_ms` absent on a prewarmed chat's first turn, as it is on turn 2.
- **Cause, exactly:** `AgentRunExecution.run` (`agent_runtime/profile_runner/execute.py`) returns at `if self.request.prewarm_only:` after `acquire_agent()`, before `bind_chat_root` and the conversation. The prompt is built inside the conversation by upstream `agent/conversation_loop.py::_restore_or_build_system_prompt`: with no `conversation_history` it does not even read the session row, so on a fresh chat it always reaches `agent._cached_system_prompt = agent._build_system_prompt(system_message)` (1.1–1.6 s here, §0.2). A warm actor carries no prompt because nothing ever built one on it.
- **Change, fork half:** in the prewarm branch, after `acquire_agent()`: build the prompt with the SAME `system_message` the turn would pass (the value `bind_chat_root`/`run_conversation` receive — resolve it through the same helper, never a copy) and store it as `agent._prewarmed_system_prompt = (prompt, signature)` where `signature` is the `persona_chat_runtime_signature` the actor was warmed under. `_finish_resident_persona_chat_agent` leaves it in place. Write the timing as `profile_timing["prewarm_system_prompt_build_ms"]` on the prewarm's own receipt line.
- **Change, upstream seam (ADDITIVE, `agent/conversation_loop.py::_restore_or_build_system_prompt`):** immediately before the final "first turn of a new session" build, one guarded block: if `not conversation_history` and `getattr(agent, "_prewarmed_system_prompt", None)` is set and `_stored_prompt_matches_runtime(agent, prompt)` → adopt it as `_cached_system_prompt`, clear the attribute, emit `_emit_conversation_timing(agent, "system_prompt_prewarmed", …)`, and fall through to the existing persist/switch-note tail. Anything else (attribute absent, runtime identity moved, queued skills pending for the root — the fork half clears the attribute when `build_mission_chat_turn_context` consumed a queued-skill list) rebuilds exactly as today and the fork stamps `system_prompt_prewarm_discarded=<reason>` on the turn record. Held PR row in `planned/upstream-footprint-ledger.md`; the block is one import-free `getattr` and ~8 lines.
- **OPEN RULING A3-r1 (recommended: the seam).** The alternative with no upstream edit — pre-seeding the session row's `system_prompt` at prewarm — does not work: the restore path reads the row only when `conversation_history` is non-empty, which a fresh chat's first turn never is. A fork-only variant that monkeypatches `_restore_or_build_system_prompt` is the shape ADR 0006 forbids.
- **Positive control:** (i) unit: `_restore_or_build_system_prompt` with the attribute set and a matching runtime adopts it and emits `system_prompt_prewarmed`; with a mismatched runtime it rebuilds; plant = remove the seam block → the adopt test reds. (ii) fork: `prewarm_chat_actor` leaves a non-empty `_prewarmed_system_prompt` on the resident agent keyed by the warmed signature; plant = skip the build → red. (iii) negative: a prompt stored under a different signature is never adopted.
- **Tests:** `tests/agent/test_system_prompt_restore.py` (extend, beside the restore cases), `tests/agent_runtime/test_persona_chat_actor_prewarm.py` (extend).
- **Saving:** 1.1–1.6 s on every first turn of a prewarmed chat (5 of the 6 first turns on record carry the key at 1,273–1,578 ms). Upstream-file edit: marked, additive, one block.

### A4 — the prewarm opens the provider connection once (hermes)

- **Goal:** the first turn's `client_built → tls_done` reads like a later turn's (21–56 ms), not 262–1,454 ms.
- **Cause, as far as the records go:** the OpenAI client is built at construction (`agent/agent_runtime_helpers.py` "OpenAI client created (agent_init, shared=True)") on a process-shared `httpx.HTTPTransport` with `keepalive_expiry=20.0` (`agent/process_bootstrap.py::build_keepalive_http_client`), so a chat's first turn — minutes after its prewarm — always opens a connection, and so does any turn more than 20 s after the last. The FIRST handshake in the process costs 262–1,454 ms, every later one 21–56 ms (§0.1, §0.2). What the first one pays that the later ones do not (resolver, first full handshake, certificate chain) versus what the overlapping core build charged it is **UNVERIFIED**: every first turn on record read `builds_overlapped ≥ 1`. The one live read that settles it: `tls_done − client_built` on a first turn with `builds_overlapped=0` (lane C makes those turns the norm).
- **Change:** in `prewarm_chat_actor`, after `runner.prewarm(request)` returns `warmed`, one fail-open `HEAD` (or `OPTIONS`) to the agent's `base_url` through the agent's own client transport (`agent.client._client` for the SDK client, the raw-httpx client otherwise), timeout 3 s, no body, no model call, logged as `persona_chat_actor_prewarm_connect root=… status=… elapsed_ms=…`. Nothing is kept open; the point is that the process's first resolve and first handshake happen on the prewarm thread. Skipped for `local_llama` and any provider whose profile declares `prewarm_connect: false`.
- **OPEN RULING A4-r1 (recommended: no).** Raising `keepalive_expiry` so the connection survives to the turn is an upstream file edit against a stated reason ("reaps idle connections before reverse proxies' 30–60 s timeouts"); not proposed.
- **Positive control:** test with a fake transport counting connects: after a prewarm the counter reads 1 and the first turn's connect does not pay the fake's 300 ms first-connect delay; plant = remove the pre-open → red. Live: the next prewarmed first turn's `tls_done − client_built`.
- **Tests:** `tests/agent_runtime/test_persona_chat_actor_prewarm.py` (extend with a transport double).
- **Saving:** bounded above by 0.24–1.4 s per first turn; honest expectation after lane C removes the overlap: 0.2–0.4 s. Re-estimate from the live read above before claiming more.

### A5 — the other first-turn cost, filed not fixed

`preflight_done → request_built` (`agent/turn_api_request.py::build_api_request`) reads 646 / 1,007 / 2,311 ms on first turns and 30–96 ms after (§0.1, §0.2). It is upstream code with no sub-timing; what it does once per agent is UNVERIFIED. File one row (fork / chat turn, evidence = these five records) asking for a `build_api_request` split on the conversation timing line before any fix; it is not part of this lane.

---

## 2. Lane C — a turn refreshes its section, not the core (row 3; one exec lane, hermes first)

### C1 — the turn's two events become coverable, carrying their own section rows (hermes)

- **Goal:** a subscriber that can fold them receives a patch for a turn; no `snapshot_build reason=demote` is led by a chat turn.
- **Touches:** `agent_runtime/chat_turn_presence.py` (`ChatTurnPresence.publish_started/publish_ended`), `agent_runtime/patch_coverage.py` (`COVERED_DOMAIN_EVENT_TYPES`, `TOKEN_GATED_DOMAIN_EVENT_TYPES`, a new fold token `persona_chat_turn`), `agent_runtime/stream/frames.py` (`running_work_frame` is the precedent and stays), the `persona_chat` section's builders `agent_runtime/persona_chat_history/summary.py::persona_chat_history_summary` and `agent_runtime/operator_channels/summary.py::operator_channel_summary` (a per-root entry point, same code, a one-instance list).
- **Change:** each presence publish appends, in the same batch, a `state.patched` upsert on entity `persona_chat` keyed by `root_chat_session_id` whose payload is what the core's `persona_chat` section would say for that ONE root after the event — the history recency row (`persona_chat_history[root]`) and the operator-channel row — computed by the section's own builders over a one-instance list (the section costs 394–981 ms for the whole roster; one root is tens of ms). `turn_started`/`turn_ended` join `COVERED_DOMAIN_EVENT_TYPES` gated on `persona_chat_turn` in `TOKEN_GATED_DOMAIN_EVENT_TYPES`, so a client that did not declare the token still demotes (today's wire, byte for byte) and a client that did gets `patch_batch_frame`. `running_work` keeps riding `running_work_frame` on `turn_ended`.
- **What is NOT refreshed by the patch, stated:** the `prompt_observability` row for the turn's new context record, and the `events` section. **OPEN RULING C1-r1 (recommended: wait).** The console reads context records on demand (`prompt_observability` get) and the events ride the delta frames themselves; the next uncovered event's full core carries both sections. If the owner wants the prompt-observability row on the patch, it is one more per-root builder call on the same patch.
- **Positive control:** (i) `event_is_patch_coverable(turn_ended, fold_entities={…, "persona_chat_turn"})` is True and False without the token; (ii) a stream golden: a turn's batch for a declaring subscriber yields one `patch` frame and no `snapshot_build_core role=led`; for a non-declaring subscriber it yields the demote core it yields today (the existing goldens pin this); (iii) the patch's `persona_chat` row equals the same root's row in a full core built at that offset (field-for-field, the core-cache equivalence test's shape). Plant = drop the event types from `COVERED_DOMAIN_EVENT_TYPES` → (ii) reds; plant = build the row from a stale instance list → (iii) reds.
- **Tests:** `tests/agent_runtime/test_scope_patch_coverage.py` (extend), `tests/agent_runtime/test_stream_turn_patch.py` (new golden), `tests/agent_runtime/test_serve_gateway_chat_reply_lanes.py::test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane` (update to the covered shape).
- **Saving:** two led cores per turn (3.7 + 6.6 s at 14:14; 3.0 + 2.9 s at 14:51; `agents_readiness` 0.5–5.8 s and `prompt_observability` 1.1–1.6 s of each) → zero on a turn for a declaring launcher. Second-order: `builds_overlapped` → 0 on ordinary turns, which is what makes `rt_provider_wait_ms` (the UNCLAIMED sibling row) readable without the CPU-share stamp it asks for, and removes the GIL share of A4's handshake.

### C2 — the launcher declares the token and folds the row (launcher)

- **Goal:** the console folds `persona_chat` rows and the `persona_chat_turn` token appears in its `fold_entities` declaration (today: `incident, office_actor, office_actor_lifecycle, office_conflict, office_surface, office_surface_fold, persona_instance, persona_instance_create, scope`).
- **Touches:** `EterniaLauncher/lib/features/mission_control/data/wire/mission_fold_declaration.dart` (the declaration), `mission_read_model_patch.dart` (the fold: replace the history row and the operator-channel row for that root in the held core), the stream goldens mirror (`test/fixtures/harness_stream/`, cross-stack landing by its own gate).
- **Positive control:** launcher fold test — a `persona_chat` upsert replaces exactly one root's rows and leaves every other root's bytes; plant = fold into the wrong key → red. Live: `[MissionFold] fold_applied … (persona_chat x1)` on a turn and no `[MissionBuild] snapshot_build state=busy` led by it.
- **Saving:** this is where C1's saving is realised; C1 alone changes nothing on the wire for the fielded launcher.

### C3 — not proposed: collapsing the two subscribers' builds

`demote_core_reuse.consult` already accepts a core at or ahead of the batch floor; the second build happens because the second subscriber's batch closes at a LATER offset than the first core's position. Widening reuse to "any core newer than the batch" is exactly the MCF-Q1 shape the W3-H2 note refuses (a core whose content the batch's events postdate is fine; one whose position is behind the frame's stamp is not — and here it is the frame that is behind). C1 removes both builds; C3 would buy half of one and a new invariant. Left as a note.

---

## 3. Lane D — a vault commit must not restart the serve, and a drain must end (row 2; hermes half first, one launcher fixture copy, one optional launcher stage)

### D1 — `Harness_Brain/` joins the non-runtime prefixes (hermes; launcher = fixture copy only)

- **Goal:** `build.code_tree` does not move on a vault-only commit.
- **Touches:** `agent_runtime/build_identity.py::NON_RUNTIME_PREFIXES` → `("docs/", "tests/", ".github/", "Harness_Brain/")`; the module doc's rule paragraph; `tests/fixtures/build_identity/code_tree_parity_tree.txt` (+ one `Harness_Brain/…` row and its expected digest) and its byte-equal copy `EterniaLauncher/test/fixtures/build_identity/`; `local_serve_attach.dart::MissionServeCodeTreeRule.defaultRule`'s comment (the Dart applies the handed rule, so the behaviour follows the next serve greeting with no Dart logic change). Re-vendor nothing else: the rule is published on the register row (`code_tree_rule`).
- **OPEN RULING D1-r1 (recommended: `Harness_Brain/` only).** Widening to every `*.md` outside the skills trees, or to `scripts/`, trades a known false restart for an unknown false "current": a skill's `SKILL.md` and a plugin's prompt files ARE loaded by a running serve. One vault prefix is the smallest change that covers all three of today's restarts.
- **Positive control:** `is_runtime_path("Harness_Brain/TODO.md") is False` and `is_runtime_path("docsite/x.py") is True`; the parity fixture's expected digest excludes the vault row; plant = drop the prefix → both red. Live: a queue-only commit on the primary checkout no longer produces a `[MissionServe] drain` line.
- **Tests:** `tests/agent_runtime/test_build_identity.py` (extend), the parity fixture in both repos.
- **Saving:** all three of today's restarts (§0.5) — each ~27 s of launcher stall (`serve_spawn_deferred` up to 19.8 s, `open_chat answered=+26817 ms`), plus the 11–15 s cold first core on each new serve, plus the warm registry lost with the old process.

### D2 — a forced drain cancels the requester's standing streams before it waits (hermes)

- **Goal:** `drain_complete` and the end record land within the launcher's 20 s whenever no chat turn or long run holds the drain — in practice within ~1 s.
- **Touches:** `hermes_cli/harness_parts/serve/handle_message.py::_request_drain` (socket lane, `force: true`): after the deadline is computed and before the monitor starts, call `self._cancel_standing_streams(self._owner_of(connection), connection)` — the same reclaim `_on_connection_closed` performs, moved to the moment the owner of those streams asked for the service to end. `hermes_cli/harness_parts/serve/drain.py::_drain_monitor` is unchanged: chat turns and long runs still hold. Stdio drains already reclaim (`_reclaim_stdio_streams`). Log the reclaim with the existing `serve_stream_worker_reclaimed` line (`connection=<owner>` names it).
- **Positive control:** `tests/hermes_cli/test_harness_serve_drain_order.py` (extend): a session with one `is_runtime_stream` request owned by the draining connection and nothing else — `{"op":"drain","force":true}` reaches `drain_complete` inside a 2 s test deadline with `requests_completed` counting the reclaimed stream; plant = remove the cancel → the monitor holds until the test's deadline → red. Live: `serve_drain proven=yes` and `<pid>.ended.json` inside `waited_ms` on the next restart.
- **Saving:** `serve_spawn_deferred … waited_ms` 19,223 / 19,844 / 12,563 → ≤ ~1,000; the restart's wall from drain to new socket ≈ boot alone. Also closes the h-chatperf row "serve_drain never proves an exit (pid 31020)".

### D3 — the launcher closes its streams before it drains (launcher, optional, belt-and-braces)

- **Goal:** the launcher's own watch does not depend on D2's serve build being the one it drains (an older serve is drained by a newer launcher once per upgrade).
- **Touches:** `mission_serve_drain_lane.dart::_drainService`: cancel the session's two standing stream requests (the hub subscribe and the argv `harness stream`) and THEN write the drain frame; the pid watch is unchanged. File in `mission-control-queue.md` naming D2.
- **Positive control:** launcher test — the drain frame is written only after both stream cancels were issued; plant = reorder → red.
- **Saving:** same as D2, for the one restart that drains a pre-D2 serve.

### D4 — the persisted core's build stamp keys on the code tree, not the commit (hermes)

- **Goal:** a docs-only revision (`docs/` today; the vault after D1) does not cost the next boot a cold core.
- **Evidence:** 14:54:13.669 `snapshot_core_cache core_source=rebuilt caller=prewarm reason=build_stamp_mismatch` on the serve that followed `4adeb0f116`, then gen 1 `build_ms=15383`.
- **Touches:** `agent_runtime/core_cache/fingerprint.py::build_stamp_token`: compose the token from `build_stamp()`'s `code_tree` when it is non-None (plus `dirty`), falling back to the commit when the digest could not be measured; `core_cache/read.py::_judge_persisted_pair` reads the same token, so the consult side follows. `DEMOTE_BUILD_STAMP_MISMATCH` keeps its name.
- **Positive control:** two stamps with different commits and the same `code_tree` yield one token; a different `code_tree` yields another; `dirty` still moves it; plant = key on the commit → the first case reds.
- **Tests:** `tests/agent_runtime/test_core_cache_demote_census.py` (extend, beside the `build_stamp_mismatch` cases) or a new `test_core_cache_build_stamp_token.py`.
- **Saving:** the 11–15 s cold core on a boot that follows a non-code revision (after D1 only `docs/`/`tests/`/`.github/` commits reach it, and any restart that was not code-driven).

---

## 4. Open rulings (recommended answer first)

| id | question | recommended |
|---|---|---|
| A3-r1 | Add the one additive block to upstream `agent/conversation_loop.py::_restore_or_build_system_prompt` (held PR row in the footprint ledger), or leave the first turn's system prompt as it is? | The seam. No fork-only door exists; the saving is 1.1–1.6 s on every first turn. |
| A4-r1 | Also raise `keepalive_expiry` (upstream `agent/process_bootstrap.py`)? | No; the file states why 20 s. Pre-open at prewarm only, then re-read. |
| C1-r1 | Must the turn patch also carry the `prompt_observability` row for the new context record? | Wait for the next full core; the console reads records on demand. |
| D1-r1 | `Harness_Brain/` only, or every non-skills `*.md` / `scripts/`? | `Harness_Brain/` only. |
| D3 | Build the launcher's own stream-close before drain? | Yes if cheap; D2 alone covers every post-D2 serve. |

## 5. Rows corrected

- **Row 1** ("outside the boot prewarm's candidates"): the chat did not exist at the pass; it was created by a drop 2.4 min later. The cap (8) was not the limiter (7 candidates). Estimate corrected: prewarm alone recovers ~0.4–0.7 s of the 3,393 ms (the construction is 270 ms); the rest is row 4's first-turn costs. Fix: A1 (create path) + A2 (console open), not a wider candidate list.
- **Row 3** (fingerprint moves → rebuild): the persisted-core lane is boot-only; `restat=refreshed … foreign_moved=8` is the write-back receipt, not the trigger. The trigger is the stream lane's demote of batches carrying `persona_chat.turn_started/ended`, once per subscriber (two). Cost and effect as filed. The "off-GIL DESIGN" row is the structural half of a different problem (builds that must happen); C1 makes the turn-driven ones not happen at all.
- **Row 2** ("the code identity should ignore commits that touch no shipped code"): the identity already does (RS-6) — it keeps the vault. `boot_bootstrap.py` is not the restart door. "The drain should end the old serve inside its budget": it does end — the instant the launcher releases the standing streams the serve is waiting on; the end records are 80–160 ms after `waited_ms`.
- **Row 4**: as filed, with the split: prompt (A3) + `build_api_request` (A5, UNVERIFIED) + handshake (A4, UNVERIFIED share). The TLS cost on a clean turn is not yet on any record.

## 6. Landing order and discipline

1. **D1 + D2 (+ D4)** first, one hermes lane: they stop the restarts that invalidate every other measurement. D1 lands with the fixture copy in the launcher the same wave (cross-stack fixture rule).
2. **A1 + A3 + A4** one hermes lane (A3's upstream block is its own CHANGE commit with the held-PR row); **A2** a launcher lane, independent.
3. **C1** hermes, then **C2** launcher; the goldens mirror lands in the C2 wave.
4. After C2: the owed clean-turn read — one prewarmed first turn and one warm turn with `builds_overlapped=0` — re-estimates A4 and A5 and closes the `rt_provider_wait_ms` row or re-arms it.

Every CHANGE commit carries its positive control in the body (the plant, the red, the revert). A lane runs only the test files that import a module it touched; the suite runs once at the landing.
